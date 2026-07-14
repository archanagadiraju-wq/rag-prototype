"""Stage 5 — Smart Chunking (Mode A).

Semantic chunking that respects heading boundaries from stage 3's text_blocks.
Target: ~300 tokens per chunk, ~50-token overlap between adjacent chunks.
Falls back to sliding-window chunking for table-only docs (XLSX).
"""
from __future__ import annotations
import uuid

from config import settings
from models.events import ChunkingPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult

_MAX_TOKENS     = settings.chunk_max_tokens      # 512 default, target 300 for demo
_OVERLAP_TOKENS = settings.chunk_overlap_tokens  # 64 default
_MIN_TOKENS     = settings.chunk_min_tokens      # 20 default
_TARGET_TOKENS  = 300


def _est(text: str) -> int:
    """Rough token estimate: words * 1.35."""
    return max(1, int(len(text.split()) * 1.35))


def _overlap_tail(texts: list[str], want_tokens: int) -> str:
    """Return the last `want_tokens` worth of text from a list of strings."""
    combined = " ".join(texts)
    words = combined.split()
    tail_words = int(want_tokens / 1.35)
    return " ".join(words[-tail_words:]) if tail_words < len(words) else combined


def _make_chunk(texts: list[str], heading_path: list[str], page: int | None, idx: int) -> dict:
    text = " ".join(t for t in texts if t).strip()
    return {
        "id": f"chunk_{idx:04d}",
        "text": text,
        "token_count": _est(text),
        "page": page,
        "heading_path": " > ".join(heading_path) if heading_path else None,
    }


def _chunk_blocks(text_blocks: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    heading_path: list[str] = []
    current: list[str] = []
    current_tokens = 0
    current_page: int | None = None

    def flush(keep_overlap: bool = True):
        nonlocal current, current_tokens
        if current and current_tokens >= _MIN_TOKENS:
            chunks.append(_make_chunk(current, list(heading_path), current_page, len(chunks)))
        if keep_overlap and current:
            tail = _overlap_tail(current, _OVERLAP_TOKENS)
            current = [tail] if tail else []
            current_tokens = _est(tail) if tail else 0
        else:
            current = []
            current_tokens = 0

    for block in text_blocks:
        level = block.get("heading_level", 0)
        text  = (block.get("text") or "").strip()
        page  = block.get("page")

        if not text:
            continue

        if level and level > 0:
            # Save any sub-threshold content so it isn't silently dropped
            carry = list(current) if current and current_tokens < _MIN_TOKENS else []
            flush(keep_overlap=False)
            # Update heading breadcrumb: trim to current depth
            heading_path = heading_path[:level - 1] + [text]
            # Prepend any carried content so nothing is lost
            current = carry + [text]
            current_tokens = sum(_est(t) for t in carry) + _est(text)
            current_page = page
        else:
            block_tokens = _est(text)
            if current_tokens + block_tokens > _TARGET_TOKENS and current:
                flush(keep_overlap=True)
                if page is not None:
                    current_page = page
            current.append(text)
            current_tokens += block_tokens
            if page is not None:
                current_page = page

    flush(keep_overlap=False)

    # Safety net: if every accumulator landed below _MIN_TOKENS the loop above
    # emits zero chunks even when the document had real text. That cascades —
    # embedding / metadata / KG / RAG-ready all "complete" with empty payloads
    # because they have nothing to chunk over.
    #
    # Cap each fallback chunk at _FALLBACK_MAX_TOKENS (well below OpenAI's
    # 8191-token embedding limit) so we never emit a single mega-chunk that
    # the embedder would reject. Sliding-window split with overlap if the
    # joined text exceeds the cap.
    if not chunks:
        chunks = _fallback_window_chunks(text_blocks)

    return _merge_small(chunks)


# Sliding-window fallback configuration. 6000 tokens leaves comfortable headroom
# under text-embedding-3-large's 8191-token max-input ceiling.
_FALLBACK_MAX_TOKENS = 6000
_FALLBACK_OVERLAP_TOKENS = 200


def _fallback_window_chunks(text_blocks: list[dict]) -> list[dict]:
    """Emit at least one chunk per non-empty document, capped at 6K tokens each.

    Used only when the normal heading-aware chunker produces zero chunks
    (e.g. every paragraph below _MIN_TOKENS). Joins all non-empty blocks
    and either returns one chunk (if small) or sliding-window-splits with
    overlap (if large).
    """
    non_empty = [b for b in text_blocks if (b.get("text") or "").strip()]
    if not non_empty:
        return []

    joined = "\n\n".join((b.get("text") or "").strip() for b in non_empty)
    first_page = non_empty[0].get("page")

    if _est(joined) <= _FALLBACK_MAX_TOKENS:
        return [{
            "id": "chunk_0000",
            "text": joined,
            "token_count": _est(joined),
            "page": first_page,
            "heading_path": None,
        }]

    # Sliding window in word-space — tokens-per-word ≈ 1.35 from _est()
    words = joined.split()
    words_per_window = max(1, int(_FALLBACK_MAX_TOKENS / 1.35))
    overlap_words    = max(0, int(_FALLBACK_OVERLAP_TOKENS / 1.35))
    step             = max(1, words_per_window - overlap_words)

    out: list[dict] = []
    i = 0
    while i < len(words):
        window = words[i:i + words_per_window]
        if not window:
            break
        text = " ".join(window)
        out.append({
            "id": f"chunk_{len(out):04d}",
            "text": text,
            "token_count": _est(text),
            "page": first_page,
            "heading_path": None,
        })
        if i + words_per_window >= len(words):
            break
        i += step
    return out


def _merge_small(chunks: list[dict]) -> list[dict]:
    """Merge chunks below _MIN_TOKENS into their following neighbour (or previous if last)."""
    if not chunks:
        return chunks
    merged: list[dict] = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if chunk["token_count"] < _MIN_TOKENS and len(chunks) > 1:
            # Absorb into next chunk if available, else into previous
            if i + 1 < len(chunks):
                next_c = chunks[i + 1]
                combined = (chunk["text"] + " " + next_c["text"]).strip()
                chunks[i + 1] = {
                    **next_c,
                    "text": combined,
                    "token_count": _est(combined),
                    "heading_path": chunk["heading_path"] or next_c["heading_path"],
                    "page": chunk["page"] if chunk["page"] is not None else next_c["page"],
                }
                i += 1
                continue
            elif merged:
                prev = merged[-1]
                combined = (prev["text"] + " " + chunk["text"]).strip()
                merged[-1] = {**prev, "text": combined, "token_count": _est(combined)}
                i += 1
                continue
        merged.append(chunk)
        i += 1
    # Re-index IDs
    for j, c in enumerate(merged):
        c["id"] = f"chunk_{j:04d}"
    return merged


def _chunk_tables(tables: list[dict]) -> list[dict]:
    """Sliding-window chunker for table rows (XLSX fallback)."""
    chunks: list[dict] = []
    for tbl in tables:
        headers = tbl.get("headers") or []
        rows    = tbl.get("rows") or []
        header_str = " | ".join(str(h) for h in headers)

        batch: list[str] = [header_str] if header_str else []
        batch_tokens = _est(header_str)

        for row in rows:
            row_str = " | ".join(str(c) for c in row)
            row_tokens = _est(row_str)
            if batch_tokens + row_tokens > _TARGET_TOKENS and batch:
                text = "\n".join(batch)
                chunks.append({
                    "id": f"chunk_{len(chunks):04d}",
                    "text": text,
                    "token_count": _est(text),
                    "page": None,
                    "heading_path": tbl.get("id"),
                })
                batch = [header_str] if header_str else []
                batch_tokens = _est(header_str)
            batch.append(row_str)
            batch_tokens += row_tokens

        if batch:
            text = "\n".join(batch)
            if _est(text) >= _MIN_TOKENS:
                chunks.append({
                    "id": f"chunk_{len(chunks):04d}",
                    "text": text,
                    "token_count": _est(text),
                    "page": None,
                    "heading_path": tbl.get("id"),
                })
    return chunks


async def run(parser_payload: dict) -> StageResult:
    text_blocks = parser_payload.get("text_blocks") or []
    tables      = parser_payload.get("tables") or []

    if text_blocks:
        chunks   = _chunk_blocks(text_blocks)
        strategy = "heading-aware"
    elif tables:
        chunks   = _chunk_tables(tables)
        strategy = "table-row-window"
    else:
        chunks   = []
        strategy = "none"

    token_counts       = [c["token_count"] for c in chunks] if chunks else [0]
    chunk_count        = len(chunks)
    avg_tokens         = sum(token_counts) / chunk_count if chunk_count else 0.0
    min_tokens         = min(token_counts) if token_counts else 0
    max_tokens         = max(token_counts) if token_counts else 0
    total_chunk_tokens = sum(token_counts)

    # Coverage: compare against tokens in the actual text_blocks/tables fed to the chunker
    # (not raw word_count which may include text the parser discarded)
    if text_blocks:
        source_words = sum(len((b.get("text") or "").split()) for b in text_blocks)
    else:
        source_words = sum(
            len(" ".join(str(c) for row in (t.get("rows") or []) for c in row).split())
            for t in tables
        )
    doc_tokens_est = int(source_words * 1.35)
    coverage_pct   = min(100.0, total_chunk_tokens * 100 / max(1, doc_tokens_est))

    # Size distribution: bucket into 10 equal-width bins
    if chunks:
        bucket_size = max(1, (max_tokens - min_tokens + 1) // 10)
        distribution = [0] * 10
        for tc in token_counts:
            bucket = min(9, (tc - min_tokens) // bucket_size)
            distribution[bucket] += 1
    else:
        distribution = [0] * 10

    payload = ChunkingPayload(
        strategy=strategy,
        chunk_count=chunk_count,
        avg_chunk_size_tokens=round(avg_tokens, 1),
        min_chunk_tokens=min_tokens,
        max_chunk_tokens=max_tokens,
        overlap_tokens=_OVERLAP_TOKENS,
        total_chunk_tokens=total_chunk_tokens,
        doc_tokens_est=doc_tokens_est,
        coverage_pct=round(coverage_pct, 1),
        chunks=chunks,
        size_distribution=distribution,
    )

    checks = [
        make_check(
            "chunks_created",
            chunk_count > 0,
            f"{chunk_count} chunk{'s' if chunk_count != 1 else ''}",
        ),
        make_check(
            "avg_tokens_in_range",
            30 <= avg_tokens <= 600,
            f"avg {avg_tokens:.0f} tokens (target 30–600)",
            severity="warn",
        ),
        make_check(
            "no_empty_chunks",
            all(c["token_count"] >= _MIN_TOKENS for c in chunks),
            f"min chunk {min_tokens} tokens",
        ),
        make_check(
            "coverage",
            coverage_pct >= 90.0,
            f"{coverage_pct:.0f}% of doc tokens covered",
        ),
    ]

    return StageResult(payload=payload.model_dump(), verification=make_verification(checks))
