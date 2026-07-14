"""Document-level fact extraction.

Runs once at ingest time (or on demand) and produces a typed JSON store at
`data/jobs/{job_id}/facts.json` containing single-valued document properties:
capacity, budget, dates, approver, reference number, etc.

Why JSON not SQL: document-level facts are flat key-value data, not relational
rows. Forcing them into SQL caused systematic router failures (see
qa_eval_report.md — the SQL router can't distinguish "this project's capacity"
from "a historical project's capacity in some unrelated row").

Every fact carries provenance — chunk_id, table_name, page, verbatim quote —
so consumers can verify, cite, and resolve cross-store linkage.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import anthropic
import structlog

from config import settings
import services.job_cache as cache

log = structlog.get_logger()

_HAIKU = "claude-haiku-4-5-20251001"
_EXTRACTION_VERSION = "1.0"
_MAX_CONTEXT_CHARS = 80_000
_MAX_OUTPUT_TOKENS = 4096

_EXTRACTION_SYSTEM = """You extract structured document-level facts from a corporate document.

Output ONLY a JSON array of fact objects. No prose, no code fences. Each fact MUST:
- Be a SINGLE-VALUED property of the WHOLE document — not a derived calculation,
  not a per-row line item, not a value that varies by bidder/category/scope
- Use snake_case for keys
- Include a verbatim `source.quote` from one of the provided chunks
- Use typed values: numbers as numbers (strip currency/commas), dates as YYYY-MM-DD, lists as JSON arrays
- Include `source.chunk_id` matching one of the chunk_ids provided

CRITICAL RULES — when to SKIP rather than guess:

  1. Same-property MULTIPLE VALUES.
     If you see two or more candidate values for the same conceptual property
     in different contexts (e.g., a "project capacity" mentioned in both a
     parametric cost calculation AND a project-facts table; or a "cost per
     TR" with bidder-specific values), DO NOT extract the property. Multiple
     values means the property is scope-ambiguous, and extracting one value
     will mislead downstream consumers.

  2. Derived from CALCULATION not stated as a fact.
     "Budget is derived from 36,000/TR × 2,000 TR = 108,000,000" — the
     ENDS-with value (108,000,000) is a stated budget fact. The 2,000 inside
     the calculation is NOT a project capacity fact — it's an intermediate
     calculation step. If the actual project capacity is stated separately
     (e.g., in a "CAPACITY (TR): 3,000" project-facts row), prefer THAT
     value and skip the calculation-internal number.

  3. Per-bidder / per-row / per-category values.
     If a value belongs to a specific bidder ("Hyper-Aire's cost per TR"),
     a specific row ("General Requirements total"), or a specific category
     ("Lower Ground Floor cost"), DO NOT extract it as a document fact.
     Those live in SQL tables, not facts.

  4. The fact must answer "what is the X OF THIS DOCUMENT" without
     qualification. If you need to say "for which X?" or "of which bidder/
     category/scope?", skip it.

Schema (every field required unless marked optional):
[
  {
    "key":   "snake_case identifier, e.g. project_capacity, project_budget_php",
    "label": "Human-readable label",
    "value": <number | string | date-string | list>,
    "type":  "number | currency | date | text | person | org | list",
    "unit":  "PHP | tons_refrigeration | sqm | ... (optional, only if meaningful)",
    "source": {
      "page":       <int | null>,
      "chunk_id":   "the exact chunk_id from the context where this fact appears",
      "table_name": "doc_table_N if from a table, else null",
      "quote":      "verbatim text from the chunk that supports the fact"
    },
    "confidence": "high | medium | low"
  }
]

Common fact keys (extract when scope is unambiguous, skip when not):
  project_capacity, project_budget_<currency>, project_start_date,
  project_finish_date, project_location, lot_area_sqm, gross_floor_area_sqm,
  recommended_contractors (list), approver (person), preparer (org),
  document_date, reference_number, project_name, project_subject.

Extract any other property that meets the rules above. When in doubt, skip.
A missing fact is harmless — downstream retrieval still works. A wrong
fact with a confident quote is harmful because it overrides correct data."""


# ── Public API ────────────────────────────────────────────────────────────────


async def extract_facts(job_id: str, cache_prefix: str = "") -> dict:
    """Extract single-valued document properties to facts.json.

    Reads embedded_chunks from job_cache, builds an extraction prompt context,
    runs Claude once, validates each returned fact's source.quote against the
    actual chunk text, and persists the validated subset.

    Returns the same dict that's written to disk.
    """
    chunks = cache.get(job_id, f"{cache_prefix}embedded_chunks", []) or []
    base_result: dict[str, Any] = {
        "doc_id": job_id,
        "facts": [],
        "extractor_version": _EXTRACTION_VERSION,
        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if not chunks:
        base_result["error"] = "no_chunks"
        _persist(job_id, cache_prefix, base_result)
        return base_result

    if not (settings.anthropic_api_key and len(settings.anthropic_api_key) > 20):
        base_result["error"] = "no_anthropic_key"
        _persist(job_id, cache_prefix, base_result)
        return base_result

    # Build context: chunk_id-annotated text the model can quote from
    chunk_text_by_id, context_text = _build_extraction_context(chunks)

    t0 = time.perf_counter()
    raw_facts, in_tok, out_tok = await _call_llm(context_text)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Validate and stamp doc_id on every fact
    validated, rejected = _validate_facts(raw_facts, chunk_text_by_id, job_id)

    result: dict[str, Any] = {
        **base_result,
        "facts": validated,
        "stats": {
            "extracted":       len(raw_facts),
            "validated":       len(validated),
            "rejected":        rejected,
            "extraction_ms":   round(elapsed_ms, 1),
            "input_tokens":    in_tok,
            "output_tokens":   out_tok,
            "context_chars":   len(context_text),
        },
    }
    _persist(job_id, cache_prefix, result)
    log.info(
        "fact_extraction_completed",
        job_id=job_id[:8], validated=len(validated), rejected=rejected,
        ms=round(elapsed_ms, 0), in_tok=in_tok, out_tok=out_tok,
    )
    return result


def load_facts(job_id: str, cache_prefix: str = "") -> dict | None:
    """Return the cached/persisted facts payload for a job, or None."""
    cached = cache.get(job_id, f"{cache_prefix}facts")
    if cached:
        return cached
    path = _facts_path(job_id, cache_prefix)
    if not path.exists():
        return None
    try:
        result = json.loads(path.read_text())
        cache.put(job_id, f"{cache_prefix}facts", result)
        return result
    except Exception as exc:
        log.warning("facts_load_failed", job_id=job_id[:8], error=str(exc))
        return None


# ── Internals ─────────────────────────────────────────────────────────────────


def _build_extraction_context(chunks: list[dict]) -> tuple[dict[str, str], str]:
    """Return (chunk_id -> text map, formatted-context-string).

    The map is used later to verify that each fact's `source.quote` actually
    appears in the named chunk. The context string is what the LLM reads.
    """
    chunk_text_by_id: dict[str, str] = {}
    lines: list[str] = []
    total = 0
    for c in chunks:
        meta = c.get("metadata") or {}
        cid = meta.get("chunk_id") or c.get("id") or f"c{c.get('chunk_idx', 0):04d}"
        text = c.get("text", "") or ""
        chunk_text_by_id[cid] = text
        page = meta.get("page")
        ctype = meta.get("chunk_type", "prose")
        block = f"[chunk_id={cid} page={page if page is not None else '?'} type={ctype}]\n{text}\n"
        lines.append(block)
        total += len(block)
        # Stop adding chunks if we would exceed the budget — the LLM can still
        # extract from earlier chunks; this prevents oversized prompts.
        if total > _MAX_CONTEXT_CHARS:
            lines.append(f"[... {len(chunks) - len(lines)} more chunks truncated for context length]")
            break
    return chunk_text_by_id, "\n---\n".join(lines)


async def _call_llm(context_text: str) -> tuple[list[dict], int, int]:
    """Run the extraction call, parse JSON, return (raw_facts, in_tokens, out_tokens)."""
    from services.api_retry import with_retry_sync
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        msg = await asyncio.to_thread(
            with_retry_sync,
            client.messages.create,
            model=_HAIKU,
            max_tokens=_MAX_OUTPUT_TOKENS,
            system=_EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Document content (chunked, with chunk_id annotations):\n\n{context_text}",
            }],
            label="fact_extractor",
        )
    except Exception as exc:
        log.warning("fact_extraction_llm_failed", error=str(exc))
        return [], 0, 0

    in_tok = msg.usage.input_tokens
    out_tok = msg.usage.output_tokens
    raw = msg.content[0].text.strip()
    # Strip optional ```json fences in case the model ignores instructions
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
        return data, in_tok, out_tok
    except Exception as exc:
        log.warning("fact_extraction_parse_failed", error=str(exc), preview=raw[:200])
        return [], in_tok, out_tok


_REQUIRED_FIELDS = ("key", "label", "value", "type", "source")


def _validate_facts(
    raw_facts: list[dict],
    chunk_text_by_id: dict[str, str],
    job_id: str,
) -> tuple[list[dict], int]:
    """Drop facts that fail validation. Return (kept, rejected_count).

    Rejection rules (designed to suppress hallucination):
      1. Required fields missing → reject
      2. source.chunk_id not in our chunk map → reject
      3. source.quote does not appear (case- and whitespace-tolerant) in the
         named chunk → reject (LLM made it up or cited the wrong chunk)
    """
    kept: list[dict] = []
    rejected = 0
    for f in raw_facts:
        if not isinstance(f, dict) or not all(k in f for k in _REQUIRED_FIELDS):
            rejected += 1
            continue

        src = f.get("source") or {}
        cid = src.get("chunk_id")
        quote = (src.get("quote") or "").strip()
        if not cid or not quote:
            rejected += 1
            continue

        chunk_text = chunk_text_by_id.get(cid, "")
        if not chunk_text:
            # The LLM cited a chunk_id we never produced — drop
            rejected += 1
            continue

        if not _quote_in_text(quote, chunk_text):
            rejected += 1
            continue

        # Stamp the doc_id (the LLM may not have set it on every source block)
        src["doc_id"] = job_id
        f["source"] = src
        # Default confidence if the model didn't supply one
        f.setdefault("confidence", "medium")
        kept.append(f)
    return kept, rejected


def _quote_in_text(quote: str, text: str) -> bool:
    """Whitespace-tolerant substring match.

    Allows trivial formatting differences between the LLM's quote and the
    chunk text without enabling hallucinations of substantive content.
    """
    norm = lambda s: re.sub(r"\s+", " ", s.lower()).strip()
    return norm(quote) in norm(text)


def _facts_path(job_id: str, cache_prefix: str) -> Path:
    base = Path(__file__).resolve().parent.parent / "data" / "jobs" / job_id
    suffix = f"_{cache_prefix.rstrip('_')}" if cache_prefix else ""
    return base / f"facts{suffix}.json"


def _persist(job_id: str, cache_prefix: str, result: dict) -> None:
    """Write facts.json atomically + populate the in-memory cache."""
    path = _facts_path(job_id, cache_prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2, default=str))
    tmp.replace(path)
    cache.put(job_id, f"{cache_prefix}facts", result)
