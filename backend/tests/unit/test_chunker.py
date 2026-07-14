"""Smart chunker — unit tests.

The chunker is the load-bearing piece between parsing and embedding. Bugs
here cascade into 0 chunks → 0 vectors → empty RAG pipeline. We test:

  - Normal heading-aware chunking (target ~300 tokens)
  - The "safety net" fallback when every block lands below _MIN_TOKENS
  - The sliding-window cap (chunks must stay below the embedder's 8K-token limit)
  - Coverage % is reasonable for normal docs
  - Empty / whitespace-only docs don't crash
"""
from __future__ import annotations

import pytest
from pipelines.custom import stage_05_chunker
from pipelines.custom.stage_05_chunker import (
    _FALLBACK_MAX_TOKENS,
    _fallback_window_chunks,
)


pytestmark = pytest.mark.unit


# ── Normal path ───────────────────────────────────────────────────────────────


async def test_normal_chunking_produces_reasonable_chunks():
    """A typical doc with heading + paragraphs should chunk into ~300-token chunks."""
    blocks = [
        {"id": "h1", "text": "Introduction", "page": 1, "heading_level": 1},
        {"id": "p1", "text": "Lorem ipsum " * 100, "page": 1, "heading_level": 0},
        {"id": "h2", "text": "Methods", "page": 2, "heading_level": 1},
        {"id": "p2", "text": "Dolor sit amet " * 100, "page": 2, "heading_level": 0},
    ]
    res = await stage_05_chunker.run({"text_blocks": blocks, "tables": []})
    p = res.payload
    assert p["chunk_count"] > 0
    assert p["strategy"] == "heading-aware"
    assert p["coverage_pct"] >= 90.0
    # No chunk should exceed the fallback cap (8K limit margin)
    assert all(c["token_count"] < _FALLBACK_MAX_TOKENS for c in p["chunks"])


# ── Safety net: tiny docs ─────────────────────────────────────────────────────


async def test_safety_net_kicks_in_for_tiny_doc():
    """Pre-fix bug: a doc with all blocks below MIN_TOKENS produced 0 chunks.

    Now the fallback safety net should emit at least one chunk so the pipeline
    doesn't silently collapse downstream.
    """
    blocks = [
        {"id": "p0", "text": "Hi.", "page": 1, "heading_level": 0},
        {"id": "p1", "text": "Hello.", "page": 1, "heading_level": 0},
    ]
    res = await stage_05_chunker.run({"text_blocks": blocks, "tables": []})
    chunks = res.payload["chunks"]
    assert len(chunks) >= 1, "Safety net must emit at least one chunk for any non-empty doc"
    assert chunks[0]["text"].strip(), "Fallback chunk must have non-empty text"


async def test_safety_net_caps_giant_combined_text():
    """A giant doc routed through the safety net must produce multiple chunks,
    each under the OpenAI embedding limit."""
    # 25K words ≈ 33K tokens — way over the 8191 OpenAI cap
    blocks = [
        {"id": f"p{i}", "text": "word " * 5000, "page": 1, "heading_level": 0}
        for i in range(5)
    ]
    chunks = _fallback_window_chunks(blocks)
    assert len(chunks) >= 2, "Giant doc should produce multiple windowed chunks"
    for c in chunks:
        assert c["token_count"] <= _FALLBACK_MAX_TOKENS + 100, (
            f"Chunk token_count {c['token_count']} exceeds fallback cap "
            f"{_FALLBACK_MAX_TOKENS} — would exceed OpenAI's 8191 limit"
        )


async def test_empty_input_does_not_crash():
    """Edge: completely empty input should return zero chunks, not error."""
    res = await stage_05_chunker.run({"text_blocks": [], "tables": []})
    assert res.payload["chunk_count"] == 0
    assert res.payload["chunks"] == []
