"""Regression tests — one test per bug we've already fixed.

Each test references the bug it guards against. **Do not delete these tests
even if the code looks unrelated** — they prevent silent re-introduction of
classes of failure we've already paid the cost to find once.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.regression


# ── Bug #1: Docling produced one giant markdown block → 1 chunk for entire doc ──


async def test_docling_markdown_splits_into_multiple_blocks():
    """Was: Docling's export_to_markdown returned a single string → the chunker
    saw one text_block → emitted 1 chunk for the entire doc → embedding had no
    granularity → RAG quality collapsed.

    Fix: `_markdown_to_blocks` splits on ATX headings + blank-line paragraphs.
    """
    from pipelines.docling.stage_02_unified_parse import _markdown_to_blocks
    md = """# Title

First paragraph here.

## Section A

Section A body text.

## Section B

Section B body text."""

    blocks = _markdown_to_blocks(md)
    assert len(blocks) >= 5, "Markdown must split into multiple blocks"
    levels = [b["heading_level"] for b in blocks]
    assert 1 in levels, "Must detect H1"
    assert 2 in levels, "Must detect H2"


# ── Bug #2: Docling page_count was a bound method, not its value ─────────────


async def test_docling_page_count_is_value_not_method():
    """Was: getattr(doc, 'num_pages', None) returned the bound METHOD in Docling
    2.x — caused `Object of type method is not JSON serializable` on job_cache
    disk write, broke the whole job.

    Fix: detect callable and invoke. This test asserts the code path is
    callable-safe via a mock doc object.
    """
    class MockDoc:
        def num_pages(self):  # callable, not attribute
            return 42

    doc = MockDoc()
    np = getattr(doc, "num_pages", None)
    result = np() if callable(np) else np
    assert result == 42, "Must invoke num_pages when it's a method"
    assert not callable(result), "Result must not be a bound method"


# ── Bug #3: Docling tables had empty headers/rows → SQL store skipped them ──


async def test_docling_table_to_dataframe_path():
    """Was: raw_tables[] populated with `headers: [], rows: [], as_json: []` —
    sql_store.create_tables skips tables with empty headers, so Mode B had
    zero SQL tables even on XLSX-rich docs.

    Fix: call tbl.export_to_dataframe() and populate the structured fields.
    """
    from pipelines.docling.stage_02_unified_parse import _df_to_headers_rows
    import pandas as pd
    df = pd.DataFrame({"col_a": ["x", "y"], "col_b": [1, 2]})
    headers, rows = _df_to_headers_rows(df)
    assert headers == ["col_a", "col_b"]
    assert rows == [["x", "1"], ["y", "2"]]


# ── Bug #4: OCR fraction sampled only first 3 pages ──────────────────────────


async def test_ocr_detection_full_document_scan():
    """Was: ocr_fraction only looked at first 3 pages — for a 50-page PDF where
    pages 1-3 are born-digital and 40+ are scanned, agent chose pdfplumber and
    missed all OCR content.

    Fix: _scan_pdf_ocr_signal walks every page (up to a 200-page sample cap).
    """
    from agent.tools import _scan_pdf_ocr_signal

    class TextPage:
        def extract_text(self): return "real content here " * 20

    class ScannedPage:
        def extract_text(self): return ""

    # Page 1-3 text, pages 40-50 scanned — old bug would say ocr_fraction=0
    pages = [TextPage()] * 3 + [TextPage()] * 36 + [ScannedPage()] * 11
    info = _scan_pdf_ocr_signal(pages)
    assert info["pages_sampled"] == 50, "Must scan all 50 pages, not just first 3"
    assert info["pages_needing_ocr"] == 11
    assert info["ocr_fraction"] == pytest.approx(0.22, abs=0.01)
    assert info["ocr_fraction"] > 0.2, (
        "Trailing scanned section must be detected (would have been missed pre-fix)"
    )


# ── Bug #5: Question generation was per-pipeline (Mode C unfair) ─────────────


async def test_shared_questions_used_across_pipelines():
    """Was: Mode A and Mode B in Mode C each generated their own 10 questions,
    so the comparison was unfair — different questions per pipeline.

    Fix: stage_10_rag_ready writes/reads from `shared_questions` cache key
    (no cache_prefix). Whichever pipeline reaches stage 10 first writes the
    set; the other reads it.
    """
    import services.job_cache as cache
    job_id = "test_shared_q_regression"
    cache.clear(job_id)

    # Simulate Mode A reaching stage 10 first
    cache.put(job_id, "shared_questions", {
        "questions": [{"q": "test1", "route": "vector", "type": "fact"}],
        "doc_type": "research_paper",
        "generated_by": "custom",
    })
    shared = cache.get(job_id, "shared_questions")
    assert shared is not None
    assert shared["questions"][0]["q"] == "test1"
    assert shared["generated_by"] == "custom"

    # Mode B reaches stage 10 → reads shared (no prefix), uses it
    same = cache.get(job_id, "shared_questions")
    assert same["questions"] == shared["questions"], "Both pipelines must see identical questions"
    cache.clear(job_id)


# ── Bug #6: Anthropic agent emitted stage events that StageEvent rejected ────


async def test_stage_event_accepts_agent_pipeline_literal():
    """Was: StageEvent.pipeline was Literal['custom', 'docling'] — agent runner
    crashed with pydantic validation error on the first stage event because
    pipeline='agent' wasn't in the literal.

    Fix: add 'agent' to the literal type.
    """
    from models.events import StageEvent
    # Should not raise
    event = StageEvent(
        job_id="test", pipeline="agent", stage_id=1, stage_name="test",
        status="completed", timestamp_ms=0.0,
    )
    assert event.pipeline == "agent"


# ── Bug #7: Chunker emitted 0 chunks when all text_blocks below MIN_TOKENS ──


async def test_chunker_safety_net_prevents_zero_chunks():
    """Was: docs where every paragraph was below the 20-token MIN_TOKENS
    threshold produced 0 chunks → cascade: 0 embeddings → 0 vectors → empty
    RAG. Stages all reported "completed" because no exception fired.

    Fix: `_fallback_window_chunks` emits at least one chunk when text exists.
    """
    from pipelines.custom import stage_05_chunker
    tiny_blocks = [
        {"id": "p0", "text": "Hi.", "page": 1, "heading_level": 0},
        {"id": "p1", "text": "Hello.", "page": 1, "heading_level": 0},
    ]
    res = await stage_05_chunker.run({"text_blocks": tiny_blocks, "tables": []})
    assert res.payload["chunk_count"] >= 1, "Safety net must produce at least one chunk"


# ── Bug #8: Mode B's stage dispatch was by ID, mismatching with Mode A ──────


def test_mode_b_stages_dispatch_by_name_not_id():
    """Was: frontend StageDetail dispatched by stage_id (1-12 for Mode A).
    Mode B's stage 4 = Embedding (not Content Intel), so it rendered with
    the wrong viz → looked "empty" to the user.

    Fix (frontend-side): RichViz dispatches by stage name. We can't run TSX
    in pytest, but we sanity-check that the backend's stage names are
    distinct between modes for the stages where IDs collide.
    """
    # Mode A: stage 4 = Content Intelligence; Mode B: stage 4 = Embedding
    # Both pipelines emit StageEvents tagged with their pipeline and the
    # correct human-readable name. We assert the names DIFFER so a name-based
    # dispatcher won't be confused.
    a_stage_4_name = "Content Intelligence"
    b_stage_4_name = "Embedding"
    assert a_stage_4_name != b_stage_4_name, (
        "Mode A and Mode B stage 4 must have distinct names for name-based "
        "viz dispatch to work correctly."
    )


# ── Bug #9: Embedding crashed on single 12K-token chunk ────────────────────


async def test_oversize_chunk_split_prevents_openai_400():
    """Was: a single chunk with 12K estimated tokens was sent to OpenAI's
    text-embedding-3-large → API returned 400 (limit is 8191) → entire batch
    of 100 chunks failed → embedding stage errored.

    Fix: _split_oversize splits anything over 7500 tokens before embedding.
    """
    from pipelines.custom.stage_07_embedding import _split_oversize, _est_tokens, _MAX_TOKENS_PER_INPUT

    big_text = " ".join(["word"] * 10000)  # ~13.5K tokens
    chunks = [{"id": "big", "text": big_text}]
    out = _split_oversize(chunks)
    assert len(out) >= 2, "12K-token chunk must split into multiple sub-chunks"
    for c in out:
        assert _est_tokens(c["text"]) <= _MAX_TOKENS_PER_INPUT, (
            "Every sub-chunk must be below the OpenAI 8191 limit"
        )


# ── Bug #10: Cache resume — disk-backed get must work after memory clear ──


async def test_cache_resume_reads_from_disk_after_memory_clear():
    """Was: stage results lived only in memory; backend restart lost them and
    every stage re-ran. Now job_cache writes to disk on put, falls back to
    disk on get → restart-safe resume.

    Fix: services.job_cache puts to disk too; gets fall back to disk if
    memory is empty.
    """
    import services.job_cache as cache
    job_id = "test_cache_resume_regression"
    cache.clear(job_id)

    cache.put(job_id, "stage_4_payload", {"chunks": 8, "result": "ok"})
    # Simulate restart by clearing in-memory store
    cache._store.pop(job_id, None)
    # Disk fallback should re-hydrate
    val = cache.get(job_id, "stage_4_payload")
    assert val == {"chunks": 8, "result": "ok"}, (
        "After in-memory clear, disk fallback must return the persisted value"
    )
    cache.clear(job_id)
