"""Verify the separation of concerns in the agent's tool catalog.

After the refactor that split `_caption_images` (which used to also do
tables) into two single-responsibility tools, we lock that in:

  • `describe_tables` exists in the catalog
  • `caption_images` exists in the catalog
  • Each is dispatched to its own executor
  • Each tool description says clearly what it does (and doesn't do)
  • `enrich_tables` and `process_images` are independently callable in
    stage_06_multimodal (without going through run())
"""
from __future__ import annotations

import inspect
import pytest

from agent.tools import TOOL_SCHEMAS, _TOOL_EXECUTORS
from pipelines.custom import stage_06_multimodal


pytestmark = pytest.mark.unit


def test_both_tools_in_catalog():
    """describe_tables and caption_images must both be exposed to the agent."""
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert "describe_tables" in names, "describe_tables tool missing from catalog"
    assert "caption_images" in names,  "caption_images tool missing from catalog"


def test_tools_have_distinct_executors():
    """Each tool must dispatch to its own implementation."""
    assert "describe_tables" in _TOOL_EXECUTORS
    assert "caption_images"  in _TOOL_EXECUTORS
    assert _TOOL_EXECUTORS["describe_tables"] is not _TOOL_EXECUTORS["caption_images"], (
        "describe_tables and caption_images must dispatch to different functions — "
        "the whole point of the split was separation of concerns"
    )


def test_describe_tables_description_mentions_tables_not_images():
    """Tool descriptions are how the LLM agent makes decisions. The
    describe_tables description must talk about tables, not generic content."""
    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "describe_tables")
    desc = schema["description"].lower()
    assert "table" in desc, "describe_tables description should mention tables"
    assert "summary" in desc or "summaries" in desc or "describ" in desc, (
        "describe_tables description should mention what it produces (summaries/descriptions)"
    )
    assert "mandatory" in desc or "always" in desc or "must" in desc, (
        "describe_tables description should emphasize it's not optional when tables exist"
    )


def test_caption_images_description_mentions_images_not_tables():
    """The caption_images description must NOT claim to do table work — the
    whole bug we fixed was that one tool did both."""
    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "caption_images")
    desc = schema["description"].lower()
    assert "image" in desc, "caption_images description should mention images"
    # If "table" appears it must be in a negative context ("does NOT touch tables")
    if "table" in desc:
        nearby = desc[max(0, desc.find("table") - 30): desc.find("table") + 50]
        assert "not" in nearby or "no " in nearby or "ocr" in nearby, (
            f"caption_images mentions tables but not in a 'does NOT' context: {nearby!r}"
        )


def test_stage_06_exposes_targeted_apis():
    """stage_06_multimodal must expose enrich_tables and process_images as
    independently-callable public coroutines (not just internal helpers)."""
    assert inspect.iscoroutinefunction(stage_06_multimodal.enrich_tables), (
        "enrich_tables must be a public async function"
    )
    assert inspect.iscoroutinefunction(stage_06_multimodal.process_images), (
        "process_images must be a public async function"
    )
    assert inspect.iscoroutinefunction(stage_06_multimodal.run), (
        "run must still exist for Mode A/B runners (composes both)"
    )


async def test_enrich_tables_returns_empty_for_no_tables():
    """Called on a payload with no tables, enrich_tables returns empty result —
    not a crash, not a Claude call. Cost should be 0."""
    result = await stage_06_multimodal.enrich_tables({"tables": []})
    assert result["tables_enriched"] == []
    assert result["llm_input_tokens"] == 0
    assert result["llm_output_tokens"] == 0
    assert result["llm_cost_usd"] == 0.0


async def test_process_images_returns_empty_for_no_images():
    """Symmetric: process_images on a payload with no images returns empty,
    makes no Claude calls."""
    result = await stage_06_multimodal.process_images({"images": []})
    assert result["captions"] == []
    assert result["ocr_chunks"] == []
    assert result["ocr_tables"] == []
    assert result["llm_input_tokens"] == 0
    assert result["llm_output_tokens"] == 0


async def test_describe_tables_tool_returns_zero_for_no_tables(clean_job_id):
    """The agent's describe_tables tool, when called on a doc with no tables,
    returns a clear 'no tables' signal — does NOT crash."""
    import services.job_cache as cache
    cache.put(clean_job_id, "parser_payload", {"tables": [], "text_blocks": []})
    from agent.tools import _describe_tables
    result = await _describe_tables(filepath=None, job_id=clean_job_id)
    assert result["tables_described"] == 0
    assert result["table_summary_chunks_added"] == 0


async def test_caption_images_tool_returns_zero_for_no_images(clean_job_id):
    """Symmetric for caption_images."""
    import services.job_cache as cache
    cache.put(clean_job_id, "parser_payload", {"tables": [], "images": []})
    from agent.tools import _caption_images
    result = await _caption_images(filepath=None, job_id=clean_job_id)
    assert result["images_captioned"] == 0
    assert result["ocr_pages"] == 0
