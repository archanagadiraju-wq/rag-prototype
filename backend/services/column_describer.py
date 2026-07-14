"""Generate semantic column descriptions for SQL tables at ingest.

For each table in sql_registry, runs one Claude call that reads the table's
sample rows and writes a one-line description per column. These descriptions
go into the SQL router's prompt so it can disambiguate columns with similar
names across tables (e.g. `capacity_tr` exists in both `doc_table_3` historical
contracts and other contexts).

Without this, the router has only the raw column name to go on, which is the
root cause of the SQL-routing regression measured in the 25-question eval.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import anthropic
import structlog

from config import settings
import services.job_cache as cache

log = structlog.get_logger()

_HAIKU = "claude-haiku-4-5-20251001"
_MAX_TOK = 1500
_MAX_TABLES_PER_BATCH = 1  # one table at a time keeps output focused + cheap

_SYSTEM = """You generate semantic column descriptions for an extracted document table.

You are given:
  - The table name (e.g. doc_table_3)
  - Column names
  - Up to 5 sample rows
  - A short context phrase if the table_summary chunk already had one

For each column, write a ONE-LINE description that:
  - Tells what the column actually contains, not just restates the name
  - Indicates SCOPE when it matters ("for this project" vs "for a historical project"
    vs "for a specific bidder")
  - Identifies UNIT if the values are numeric ("Philippine pesos", "tons of
    refrigeration", "square meters")
  - States the column is a label/key when it's a vertical-table layout
    (e.g. `col` with values like "CAPACITY (TR):", "Start Date:")

Output ONLY valid JSON:
{
  "table_summary":  "one-sentence semantic description of the table as a whole",
  "scope":          "this_project | reference_data | bidder_<name> | mixed | unknown",
  "columns": {
    "col_name_1": "one-line semantic description",
    "col_name_2": "one-line semantic description",
    ...
  }
}

Be brief — every column description should be a single sentence, max ~150 chars."""


async def describe_columns(job_id: str, cache_prefix: str = "") -> dict:
    """Generate descriptions for every table in the per-job SQL registry.

    Reads `sql_registry` (with `columns`, `sample_rows`) and `enriched_tables`
    (for the existing Claude-generated table summary, if any). Writes the
    descriptions back into the same registry entries so downstream consumers
    (the SQL router, the inspector UI) see them.

    Returns a small report: {tables_described, total_columns, ms, tokens}.
    """
    registry = cache.get(job_id, f"{cache_prefix}sql_registry") or {}
    if not registry:
        return {"tables_described": 0, "error": "no_sql_registry"}

    if not (settings.anthropic_api_key and len(settings.anthropic_api_key) > 20):
        return {"tables_described": 0, "error": "no_anthropic_key"}

    enriched = cache.get(job_id, f"{cache_prefix}enriched_tables", []) or []
    desc_by_table_idx = {
        f"doc_table_{i + 1}": (t.get("description") or "").strip()
        for i, t in enumerate(enriched)
    }

    from services.api_retry import with_retry_sync
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    t0 = time.perf_counter()
    in_tok_total = 0
    out_tok_total = 0
    described = 0
    failed = 0
    total_columns = 0

    for tname, meta in registry.items():
        cols = meta.get("columns") or []
        sample = meta.get("sample_rows") or []
        if not cols:
            continue

        # Build a compact prompt: just headers + first 5 rows
        sample_block = " | ".join(cols) + "\n"
        for row in sample[:5]:
            cells = [str(c) if c is not None else "" for c in row]
            sample_block += " | ".join(cells) + "\n"

        existing_summary = desc_by_table_idx.get(tname, "")
        ctx_block = (
            f"Existing table summary: {existing_summary}\n\n"
            if existing_summary else ""
        )
        user_msg = (
            f"Table name: {tname}\n"
            f"{ctx_block}"
            f"Columns + sample rows:\n{sample_block}"
        )

        try:
            msg = await asyncio.to_thread(
                with_retry_sync,
                client.messages.create,
                model=_HAIKU,
                max_tokens=_MAX_TOK,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                label=f"describe_columns.{tname}",
            )
            in_tok_total += msg.usage.input_tokens
            out_tok_total += msg.usage.output_tokens
        except Exception as exc:
            log.warning("column_describer_llm_failed", table=tname, error=str(exc))
            failed += 1
            continue

        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        try:
            decision = json.loads(raw)
        except Exception as exc:
            log.warning("column_describer_parse_failed", table=tname, error=str(exc))
            failed += 1
            continue

        col_descriptions = decision.get("columns") or {}
        # Validate: only keep keys that are actual columns
        col_descriptions = {
            c: str(d)[:300]
            for c, d in col_descriptions.items()
            if c in cols and isinstance(d, str) and d.strip()
        }
        if not col_descriptions:
            failed += 1
            continue

        # Patch the registry in place
        meta["column_descriptions"] = col_descriptions
        meta["table_summary"] = decision.get("table_summary", "")[:400]
        meta["scope"] = decision.get("scope", "unknown")[:40]
        described += 1
        total_columns += len(col_descriptions)

    # Persist the updated registry back to cache + disk
    cache.put(job_id, f"{cache_prefix}sql_registry", registry)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    report = {
        "tables_described": described,
        "tables_failed":    failed,
        "total_columns":    total_columns,
        "elapsed_ms":       round(elapsed_ms, 1),
        "input_tokens":     in_tok_total,
        "output_tokens":    out_tok_total,
    }
    log.info("column_describer_completed", **report)
    return report
