"""Pre-embedding oversize-chunk splitter — unit tests.

Bug class this guards against: a single jumbo chunk exceeds OpenAI's 8191-token
input limit, the embedding API rejects the whole batch, the stage errors,
cascade ensues. The splitter pre-emptively splits anything over 7500 tokens
into sliding-window sub-chunks.
"""
from __future__ import annotations

import pytest
from pipelines.custom.stage_07_embedding import (
    _split_oversize,
    _est_tokens,
    _MAX_TOKENS_PER_INPUT,
)

pytestmark = pytest.mark.unit


def test_small_chunks_pass_through_unchanged():
    """Chunks below the cap should not be modified."""
    chunks = [
        {"id": "c0", "text": "short text", "token_count": 2},
        {"id": "c1", "text": "another short one", "token_count": 4},
    ]
    out = _split_oversize(chunks)
    assert out == chunks, "Sub-cap chunks must pass through unchanged"


def test_oversize_chunk_splits_into_multiple():
    """A 12K-token chunk must be split into multiple sub-chunks under the cap."""
    big_text = " ".join(["word"] * 9000)  # ~9000 words * 1.35 = ~12K tokens
    chunks = [
        {"id": "normal", "text": "small chunk", "token_count": 2},
        {"id": "huge",   "text": big_text,       "token_count": 12000},
    ]
    out = _split_oversize(chunks)
    assert len(out) > len(chunks), "Oversize chunk must be split"
    # All output chunks fit under the cap
    for c in out:
        assert _est_tokens(c["text"]) <= _MAX_TOKENS_PER_INPUT, (
            f"Output chunk {_est_tokens(c['text'])} tokens exceeds cap "
            f"{_MAX_TOKENS_PER_INPUT}"
        )


def test_split_preserves_parent_metadata():
    """Split sub-chunks should track their parent via metadata."""
    big_text = " ".join(["word"] * 10000)
    chunks = [{"id": "parent_chunk", "text": big_text, "token_count": 13500,
               "page": 42, "heading_path": "Section X"}]
    out = _split_oversize(chunks)
    assert len(out) >= 2
    for sub in out:
        meta = sub.get("metadata", {})
        assert meta.get("split_from") == "parent_chunk"
        assert "split_index" in meta
        assert sub["page"] == 42, "Parent page must be inherited"
        assert sub["heading_path"] == "Section X", "Parent heading must be inherited"


def test_split_ids_are_unique():
    """No two sub-chunks should share an id."""
    big_text = " ".join(["w"] * 20000)
    chunks = [{"id": "big", "text": big_text, "token_count": 27000}]
    out = _split_oversize(chunks)
    ids = [c["id"] for c in out]
    assert len(ids) == len(set(ids)), "Split chunk ids must be unique"
