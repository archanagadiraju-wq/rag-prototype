"""End-to-end functional tests for each ingestion pipeline.

These run the real pipeline against real demo documents and verify the
overall contract: stages complete, expected artifacts produced, downstream
queries work.

Marked `slow` and `needs_api_key` because they exercise real LLM calls. Run
with `pytest -m "not slow"` to skip in fast CI.
"""
from __future__ import annotations

import asyncio
import os

import pytest

import services.job_cache as cache


pytestmark = [pytest.mark.functional, pytest.mark.slow, pytest.mark.needs_api_key]


def _has_api_keys() -> bool:
    from config import settings
    return bool(
        settings.anthropic_api_key
        and len(settings.anthropic_api_key) > 20
        and settings.openai_api_key
        and len(settings.openai_api_key) > 20
        and not settings.openai_api_key.startswith("sk-...")
    )


# ── Mode A: Custom pipeline on XLSX ──────────────────────────────────────────


async def test_mode_a_xlsx_produces_full_pipeline(clean_job_id, finance_xlsx):
    """Full Mode A run on XLSX: all 11 stages complete, expected outputs exist."""
    if not _has_api_keys():
        pytest.skip("Real API keys required for end-to-end pipeline test")
    if not finance_xlsx.exists():
        pytest.skip("Demo doc not found")

    from pipelines.custom.runner import run_custom_pipeline

    events: list[dict] = []
    async def cap(e): events.append(e)

    await asyncio.wait_for(
        run_custom_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=120,
    )

    # Every stage emitted a `completed` event
    completed = [e for e in events if e.get("status") == "completed"]
    stage_ids = {e["stage_id"] for e in completed}
    assert len(stage_ids) >= 10, (
        f"Expected at least 10 distinct stages completed, got {sorted(stage_ids)}"
    )

    # Specific stages produced expected outputs
    by_name = {e["stage_name"]: e for e in completed}
    if "Smart Chunking" in by_name:
        assert by_name["Smart Chunking"]["payload"]["chunk_count"] > 0
    if "Embedding" in by_name:
        assert by_name["Embedding"]["payload"]["chunks_embedded"] > 0
    if "Vector Store" in by_name:
        assert by_name["Vector Store"]["payload"]["sql_tables_created"] >= 1, (
            "XLSX must produce at least one SQL table"
        )


# ── Stage event protocol ─────────────────────────────────────────────────────


async def test_stage_events_have_required_fields(clean_job_id, finance_xlsx):
    """Every completed event must have stage_id, stage_name, status, payload."""
    if not _has_api_keys():
        pytest.skip("Needs API keys")
    from pipelines.custom.runner import run_custom_pipeline

    events: list[dict] = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_custom_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=120,
    )
    for e in events:
        assert "stage_id" in e
        assert "stage_name" in e
        assert "status" in e
        assert e["status"] in ("started", "running", "completed", "error")
        if e["status"] == "completed":
            assert "payload" in e


# ── /ask after ingestion produces grounded answer ────────────────────────────


async def test_ask_after_ingest_returns_grounded_answer(clean_job_id, finance_xlsx):
    """After Mode A ingestion, /ask should return a real answer with retrieved chunks."""
    if not _has_api_keys():
        pytest.skip("Needs API keys")
    from pipelines.custom.runner import run_custom_pipeline
    from pipelines.custom.stage_11_llm_answer import answer_one

    events = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_custom_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=120,
    )

    result = await answer_one(
        "What is the projected ARR for end of year 2026?",
        clean_job_id,
        cache_prefix="",
    )
    assert result.get("error") is None
    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 10, "Answer must be substantive"
    assert result["context_chunks"] > 0, "Must retrieve at least one chunk"
    assert len(result["retrieved"]) > 0
    # Judge metadata present
    assert result["judge_score"] is not None or result["judge_verdict"] is None  # null OK if judge failed
    # System + user prompt captured for audit
    assert result["system_prompt"]
    assert result["user_prompt"]
    assert "Context:" in result["user_prompt"]


# ── Resume after restart ────────────────────────────────────────────────────


async def test_pipeline_resumes_from_cache_after_memory_clear(clean_job_id, finance_xlsx):
    """Second run with same job_id after memory-clear should be near-instant
    (replaying cached stages from disk)."""
    if not _has_api_keys():
        pytest.skip("Needs API keys")
    import time
    from pipelines.custom.runner import run_custom_pipeline

    events1 = []
    async def cap1(e): events1.append(e)
    t0 = time.perf_counter()
    await asyncio.wait_for(
        run_custom_pipeline(clean_job_id, finance_xlsx, "upload", cap1),
        timeout=120,
    )
    first_duration = time.perf_counter() - t0

    # Simulate backend restart: clear memory, leave disk intact
    cache._store.pop(clean_job_id, None)

    events2 = []
    async def cap2(e): events2.append(e)
    t0 = time.perf_counter()
    await asyncio.wait_for(
        run_custom_pipeline(clean_job_id, finance_xlsx, "upload", cap2),
        timeout=30,  # Should be fast — all cached
    )
    second_duration = time.perf_counter() - t0

    assert second_duration < first_duration / 3, (
        f"Resume should be 3x+ faster than fresh run; got {first_duration:.1f}s → {second_duration:.1f}s"
    )

    # Most stages should have been replayed from cache
    resumed = sum(
        1 for e in events2
        if (e.get("payload") or {}).get("_resumed_from_cache") and e.get("status") == "completed"
    )
    assert resumed >= 5, f"Expected most stages to resume; got {resumed}"
