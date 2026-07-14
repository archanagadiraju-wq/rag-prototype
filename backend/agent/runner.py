"""Agentic ingestion runner.

A Claude haiku agent inspects a document and orchestrates the right ingestion
tools (parsers, OCR, captioning, embedding, KG, SQL store) without a
hardcoded sequence. Each tool call surfaces in the UI as a stage event via
the existing StageEmitter protocol, so the user sees the agent's plan unfold
live.

The agent loop:
  1. Send the agent the initial user message + tool schemas
  2. Claude responds with one or more tool_use blocks
  3. Execute each tool, append tool_result blocks to the message history
  4. Repeat until the agent calls `finalize` or hits MAX_ITERATIONS
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Callable

import anthropic

from config import settings
from pipelines.base import StageEmitter
from services.api_retry import with_retry_sync
import services.job_cache as cache

from .tools import TOOL_SCHEMAS, execute_tool

log = logging.getLogger(__name__)

_MODEL           = "claude-haiku-4-5-20251001"
_MAX_ITERATIONS  = 15
_MAX_TOKENS_TURN = 1024

_SYSTEM = """You are a document-ingestion agent for a RAG (Retrieval Augmented Generation)
retrieval system. Your single responsibility: take one document, decide what's
inside, and store it for later semantic + SQL retrieval. You drive a tool catalog
adaptively — there is no fixed pipeline. Be deliberate; you have a hard budget
of 15 tool calls total and most ingests should complete in 5–8 calls.

══════════════════════════════════════════════════════════════════════════
TOOL ORDERING RULES (HARD CONSTRAINTS — VIOLATING THESE PRODUCES EMPTY OUTPUT)
══════════════════════════════════════════════════════════════════════════
1. inspect_document MUST be your FIRST call. It populates the cache with
   format, page_count, ocr_fraction, has_images, has_tables — every downstream
   decision depends on this signal. Never skip it.
2. A parse_* tool MUST run before chunk_text. The chunker reads `text_blocks`
   from the parser's cached output; with no parser run, chunk_text emits 0
   chunks and the pipeline silently produces nothing usable.
3. chunk_text MUST run before embed_and_index. Embedding pulls from the
   `chunks` cache key the chunker writes.
4. store_tables_sql can run any time AFTER a parser populates the
   `extracted_tables` cache. It can be called before or after embed_and_index.
5. extract_entities reads from `chunks`, so it must run AFTER chunk_text.
6. caption_images reads `parser_payload.images`, so it must run AFTER a parser.
7. finalize MUST be the LAST call — it stops the agent loop.

══════════════════════════════════════════════════════════════════════════
PARSER SELECTION — THE MOST IMPORTANT DECISION
══════════════════════════════════════════════════════════════════════════
For PDFs, the critical signal is `ocr_fraction` (the fraction of pages with
effectively zero extractable text — those pages need OCR):
  • ocr_fraction ≤ 0.2  →  parse_pdf_native      (fast, pdfplumber, $0 LLM cost)
  • ocr_fraction > 0.2  →  parse_with_docling    (slow ~7s/page CPU, $0 LLM cost,
                                                  but handles OCR + complex
                                                  multi-page tables)
  • complex multi-page tables even when text-extractable → parse_with_docling
    (pdfplumber struggles with table continuations across pages; Docling's
    TableFormer model handles them natively)
  • FULLY scanned (ocr_fraction ≥ 0.6) AND page_count > 30, OR
    sample_text is filled with "(cid:N)" codes (broken font encoding),
    OR parse_with_docling returned word_count < 100 on a previous turn
      →  parse_with_vision_ocr   (Claude vision per page, ~$0.01-0.02/page,
                                  ~3-5s/page parallel — produces dramatically
                                  better English text than RapidOCR on
                                  Latin-alphabet documents)

For office formats:
  • DOCX, PPTX, XLSX, HTML  →  parse_office_document  (fast, $0)

⚠ CRITICAL: `ocr_fraction` comes from a full-document scan. The `sample_text`
in inspection is ONLY from the first 3 pages and can look fine even when
pages 40+ are scanned. ALWAYS trust ocr_fraction over sample_text for the
parse decision.

══════════════════════════════════════════════════════════════════════════
TYPICAL TOOL SEQUENCES BY DOC TYPE (use these as starting plans)
══════════════════════════════════════════════════════════════════════════
Born-digital PDF (text-heavy report, research paper, contract):
  inspect → parse_pdf_native → chunk_text → describe_tables (if has_tables)
        → embed_and_index → extract_entities → finalize

Scanned PDF (ocr_fraction > 0.5) OR mixed-content PDF (ocr_fraction > 0.2):
  inspect → parse_with_docling → chunk_text → caption_images (if informative)
        → describe_tables (always — covers parser tables AND OCR'd page tables)
        → store_tables_sql → embed_and_index → extract_entities → finalize

Fully-scanned PDF (ocr_fraction ≥ 0.6 AND >30 pages) OR broken-font PDF
(sample_text full of "(cid:N)" codes):
  inspect → parse_with_vision_ocr → chunk_text → describe_tables (if any tables
        recovered) → store_tables_sql (if any tables) → embed_and_index
        → extract_entities → finalize
  Vision OCR is the only path that consistently succeeds on these — Docling
  often times out and pdfplumber returns garbage. Skip caption_images: vision
  OCR already extracted page content.

XLSX spreadsheet (almost always tables-heavy):
  inspect → parse_office_document → chunk_text → describe_tables
        → store_tables_sql → embed_and_index → extract_entities → finalize

DOCX prose document (contract, brief, letter):
  inspect → parse_office_document → chunk_text
        → describe_tables (if has_tables; usually no for legal docs)
        → embed_and_index → extract_entities → finalize
  (skip caption_images — DOCX usually has only logos/page furniture)

PPTX slide deck (usually has charts, diagrams, screenshots):
  inspect → parse_office_document → chunk_text → caption_images
        → describe_tables (if has_tables)
        → embed_and_index → finalize
  (extract_entities optional — slide decks have sparse prose)

HTML technical doc (API spec, manual, wiki page):
  inspect → parse_office_document → chunk_text
        → describe_tables (if has_tables) → store_tables_sql (if has_tables)
        → embed_and_index → extract_entities → finalize

══════════════════════════════════════════════════════════════════════════
describe_tables — MANDATORY when has_tables=true (cost: very low)
══════════════════════════════════════════════════════════════════════════
This is NOT optional when the parser extracted tables. One batched Claude
call describes every table and pushes table_summary chunks (description +
columns + sample rows) into the embedding queue. Without this, the vector
DB only has raw row text — questions like "what does the revenue table
show" or "which table covers headcount" can't be answered.

Call describe_tables whenever has_tables=true OR after caption_images
extracted any OCR'd page-tables. Skip only when the doc truly has no tables.

══════════════════════════════════════════════════════════════════════════
caption_images — WHEN TO CALL vs SKIP (cost: ~$0.005 per image)
══════════════════════════════════════════════════════════════════════════
Image work ONLY (does NOT touch parser-extracted tables — that's
describe_tables). Does two things: one-sentence captions for embedded
images + structured OCR of scanned/image-only pages.

Call caption_images when has_images=true AND the doc is one of:
  • slide deck / presentation — almost always informative visuals
  • research paper / technical paper — figures, plots, schematics
  • marketing report — infographics, branded illustrations
  • engineering doc — architecture diagrams, flowcharts, UML
  • product catalogue — product photos
  • scanned PDF — OCR'd page images become text via vision

Skip caption_images when images are likely decorative:
  • contract / legal document — typically only logos & signatures
  • code listing / thesis — usually only headers/footers
  • plain text report — page numbers, watermarks
  • when uncertain — prefer skip; cost compounds (4-concurrent, 3-5s each)

If caption_images ran and discovered OCR'd page-tables, call
describe_tables AFTER it so those new tables get summary chunks too.

══════════════════════════════════════════════════════════════════════════
extract_entities — WHEN TO CALL vs SKIP (cost: $0, spaCy local NER)
══════════════════════════════════════════════════════════════════════════
Call extract_entities when the doc has ≥500 words of natural prose — spaCy
needs human-language text to find PERSON / ORG / GPE / DATE / MONEY / LAW
entities. Good fits: research papers, news, reports, contracts, technical
specs with substantive narration.

Skip extract_entities when the doc is mostly:
  • numeric tables (XLSX with only numbers and short labels)
  • bullet-point slides (PowerPoint with sparse, fragmentary text)
  • image-only or visual-heavy with minimal text

══════════════════════════════════════════════════════════════════════════
COST GUIDANCE PER TOOL
══════════════════════════════════════════════════════════════════════════
Free (no LLM calls):
  • inspect_document, parse_pdf_native, parse_office_document
  • chunk_text, store_tables_sql, extract_entities, finalize
Cheap (~$0.0001/chunk):
  • embed_and_index — OpenAI text-embedding-3-large
Moderate (~$0.005/image, batched 4-concurrent):
  • caption_images — Claude haiku vision per image
Slow but $0 at the API level (CPU-bound, ~7s/page):
  • parse_with_docling — PyTorch TableFormer + RapidOCR locally

══════════════════════════════════════════════════════════════════════════
EDGE CASES TO HANDLE
══════════════════════════════════════════════════════════════════════════
• Mixed-content PDF (pages 1-3 born-digital, pages 40+ scanned): trust
  ocr_fraction, NOT sample_text. Pick parse_with_docling.
• Image-only PDF (every page scanned, no text layer): ocr_fraction will be
  near 1.0. Pick parse_with_docling.
• Encrypted/locked PDF: inspect_document may report inspect_error. Stop and
  finalize with an error note — you cannot parse what you cannot read.
• Very long doc (>200 pages): same flow, just expect parser to take longer.
  Heartbeat events flow during long parses; don't retry.
• Empty doc / scan failed: if chunk_count would be 0 after all reasonable
  attempts, still call embed_and_index (creates an empty collection so the
  job_id is queryable), then finalize with a note.

══════════════════════════════════════════════════════════════════════════
FINALIZATION
══════════════════════════════════════════════════════════════════════════
Call finalize with a 1-2 sentence summary stating:
  (a) what you ingested (chunk count, table count, entity count)
  (b) what you deliberately skipped and why

Good example: "Ingested 4-page financial report PDF (Q3 2024) with 8 chunks
across revenue + opex tables; OCR'd page 3 via Docling; skipped extract_entities
because doc is mostly numeric tables."

══════════════════════════════════════════════════════════════════════════
FINAL REMINDERS
══════════════════════════════════════════════════════════════════════════
• Exactly ONE parser tool per document — pick based on inspect, don't run multiple.
• Don't call Docling on born-digital PDFs — wastes 10-15 minutes for no quality gain.
• Don't run OCR on text-extractable PDFs.
• Skip discretionary tools when they don't apply — your budget is 15 calls.
• Match the tool order rules above strictly; the cache pipeline is sequential."""


async def run_agent_pipeline(
    job_id: str,
    filepath: Path | None,
    source_type: str,
    publish: Callable,
    *,
    trace_callback: Callable[[dict], None] | None = None,
) -> None:
    """Drive a Claude-haiku agent to ingest one document.

    Mirrors the contract of run_custom_pipeline / run_docling_pipeline:
    emits StageEvents via `publish` so the existing WS infrastructure shows
    progress in the UI.
    """
    emitter = StageEmitter(job_id, "agent", publish)

    if not filepath or not filepath.exists():
        await emitter.run_stage(0, "Agent (no file)", _empty_stage())
        return

    # Validate API key — no key, no agent. Fall back to a clean error stage.
    if not (settings.anthropic_api_key and len(settings.anthropic_api_key) > 20):
        await emitter.run_stage(
            0, "Agent unavailable",
            _error_stage("ANTHROPIC_API_KEY not configured — agent mode needs Claude haiku"),
        )
        return

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    messages: list[dict] = [{
        "role": "user",
        "content": (
            f"Ingest the document at path: {filepath.name}\n"
            f"File size: {filepath.stat().st_size:,} bytes\n"
            f"Source: {source_type}\n\n"
            "Use the tools to inspect it, pick the right parsers, and "
            "store it for retrieval. Start with inspect_document."
        ),
    }]

    # Build cache-enabled system + tools ONCE per job. Anthropic prompt caching:
    # `cache_control: ephemeral` marks the cache boundary. The first turn
    # creates the cache (~30s TTL), every subsequent turn reads from it —
    # paying 0.1× the input cost on cached tokens (~90% cheaper) and shaving
    # ~40% off latency once the cache is hot. System prompt + tool schemas
    # are identical across turns within a single ingest, so caching them is
    # pure win.
    cached_system = [
        {"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}},
    ]
    # cache_control on the LAST tool caches all tools up to and including it
    cached_tools = [
        *TOOL_SCHEMAS[:-1],
        {**TOOL_SCHEMAS[-1], "cache_control": {"type": "ephemeral"}},
    ]

    # Per-job rolling counters for the UI
    total_input        = 0
    total_output       = 0
    total_cache_create = 0  # tokens written to the cache (first turn)
    total_cache_read   = 0  # tokens served from the cache (subsequent turns)
    stage_id           = 0
    finalized          = False

    for iteration in range(1, _MAX_ITERATIONS + 1):
        # Cooperative cancel check — DELETE /api/jobs/{id} sets a flag main.py
        # exposes. We poll between turns so user cancels surface fast even when
        # we're not awaiting in-network. Importing lazily avoids a circular
        # import (main.py → agent.runner).
        try:
            from main import is_cancelled  # noqa: PLC0415
            if is_cancelled(job_id):
                raise asyncio.CancelledError()
        except ImportError:
            pass

        # ── Ask the agent what to do next ──────────────────────────────────
        try:
            resp = await asyncio.to_thread(
                with_retry_sync,
                client.messages.create,
                model=_MODEL,
                max_tokens=_MAX_TOKENS_TURN,
                system=cached_system,
                tools=cached_tools,
                messages=messages,
                label=f"agent_turn_{iteration}",
            )
        except asyncio.CancelledError:
            # Re-raise so _run_pipeline's CancelledError handler marks the
            # job 'cancelled' and emits the UI event.
            raise
        except Exception as exc:
            stage_id += 1
            await emitter.run_stage(
                stage_id, f"Agent error (turn {iteration})",
                _error_stage(f"{type(exc).__name__}: {exc}"),
            )
            return

        turn_in           = resp.usage.input_tokens
        turn_out          = resp.usage.output_tokens
        turn_cache_create = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
        turn_cache_read   = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        total_input       += turn_in
        total_output      += turn_out
        total_cache_create += turn_cache_create
        total_cache_read   += turn_cache_read

        # Per-turn cost using Haiku 4.5 pricing
        # input: $0.80/M, cache_write: $1.00/M, cache_read: $0.08/M, output: $4.00/M
        turn_cost = (
            turn_in            * 0.80 / 1_000_000
            + turn_cache_create * 1.00 / 1_000_000
            + turn_cache_read   * 0.08 / 1_000_000
            + turn_out          * 4.00 / 1_000_000
        )

        # Fire trace callback BEFORE the assistant message is appended below
        # so we capture the input context as it was when Claude saw it.
        if trace_callback is not None:
            try:
                trace_callback({
                    "kind":            "agent_turn",
                    "iteration":       iteration,
                    "messages_sent":   _snapshot_messages(messages),
                    "system_prompt":   _SYSTEM,
                    "tool_catalog":    [t["name"] for t in cached_tools],
                    "response_text":   "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text"),
                    "tool_calls":      [
                        {"id": b.id, "name": b.name, "input": dict(b.input or {})}
                        for b in resp.content if getattr(b, "type", None) == "tool_use"
                    ],
                    "usage": {
                        "input_tokens":               turn_in,
                        "output_tokens":              turn_out,
                        "cache_creation_input_tokens": turn_cache_create,
                        "cache_read_input_tokens":    turn_cache_read,
                    },
                    "cost_usd":        round(turn_cost, 6),
                    "stop_reason":     resp.stop_reason,
                })
            except Exception:
                pass

        # ── Extract the agent's text reasoning + tool calls ────────────────
        text_blocks: list[str] = []
        tool_calls:  list[dict] = []
        for block in resp.content:
            if block.type == "text":
                text_blocks.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id":    block.id,
                    "name":  block.name,
                    "input": dict(block.input or {}),
                })

        reasoning = "\n".join(text_blocks).strip()
        messages_at_turn_start = len(messages)

        # Per-turn instrumentation that ships in EVERY tool-call stage event
        # for this iteration. Lets the UI render the same trace the CLI
        # /tmp/agent_trace.py shows — INPUT CONTEXT / AGENT RESPONSE /
        # METRICS THIS TURN / TOOL EXECUTION.
        turn_trace = {
            "turn_input_tokens":          turn_in,
            "turn_output_tokens":         turn_out,
            "turn_cache_read_tokens":     turn_cache_read,
            "turn_cache_create_tokens":   turn_cache_create,
            "turn_cost_usd":              round(turn_cost, 6),
            "cumulative_input_tokens":    total_input,
            "cumulative_output_tokens":   total_output,
            "cumulative_cache_read":      total_cache_read,
            "cumulative_cache_create":    total_cache_create,
            "stop_reason":                resp.stop_reason,
            # Full system prompt + tool schemas — same across all turns of one
            # job (that's why Anthropic caches the prefix). Shipped on every
            # stage event so the UI can show what was actually sent to Claude.
            "system_prompt":              _SYSTEM,
            "system_prompt_chars":        len(_SYSTEM),
            "tools_available":            [t["name"] for t in cached_tools],
            "tool_schemas":               [
                {"name": t["name"], "description": t.get("description", "")}
                for t in cached_tools
            ],
            "messages_count":             messages_at_turn_start,
            "messages_preview":           _summarize_messages(messages[:messages_at_turn_start]),
        }

        # If the agent stopped without calling a tool, emit and break.
        # CRITICAL: include the full `turn` payload here so per-stage sums see
        # this turn's tokens. Without this, no-tool "end_turn" responses
        # leak from any accumulator that walks stage events.
        if not tool_calls:
            stage_id += 1
            await emitter.run_stage(
                stage_id, f"Agent: {(reasoning[:50] + '…') if reasoning else 'end turn'}",
                _info_stage({
                    "reasoning":     reasoning,
                    "stop_reason":   resp.stop_reason,
                    "tokens_total":  total_input + total_output,
                    "turn":          turn_trace,
                }),
            )
            break

        # ── Execute each tool call (sequential — agent expects ordered results)
        # Update message history with the assistant's turn first
        messages.append({"role": "assistant", "content": resp.content})

        # ── Avoid double-counting tokens when Claude calls multiple tools in
        #    ONE turn. The turn's input/output/cache tokens come from a SINGLE
        #    Claude API call; if N tools were emitted we'd previously stamp the
        #    same turn metrics on N stage events → per-stage summation
        #    multiplied them by N. Attribute the real metrics to the FIRST tool
        #    only; subsequent tools in the same turn get a "shared" marker with
        #    zeroed counters so any sum-over-stages math stays correct.
        turn_trace_shared = {
            **{k: v for k, v in turn_trace.items() if k in (
                "system_prompt", "system_prompt_chars",
                "tools_available", "tool_schemas",
                "messages_count", "messages_preview",
                "stop_reason",
                "cumulative_input_tokens", "cumulative_output_tokens",
                "cumulative_cache_read", "cumulative_cache_create",
            )},
            "turn_input_tokens":          0,
            "turn_output_tokens":         0,
            "turn_cache_read_tokens":     0,
            "turn_cache_create_tokens":   0,
            "turn_cost_usd":              0.0,
            "_metrics_shared_with_first_tool_of_turn": True,
        }

        tool_results: list[dict] = []
        for tc_idx, call in enumerate(tool_calls):
            stage_id += 1
            is_first_of_turn = tc_idx == 0
            payload_preview = {
                "reasoning":  reasoning,
                "tool":       call["name"],
                "tool_input": call["input"],
                "iteration":  iteration,
                "turn":       turn_trace if is_first_of_turn else turn_trace_shared,
            }
            # Run the tool inside the StageEmitter wrapper so the UI shows
            # a started/heartbeat/completed lifecycle per tool call.
            async def _run_tool(call=call):
                result = await execute_tool(call["name"], call["input"], filepath, job_id)
                return _SimpleResult(payload={
                    **payload_preview,
                    "tool_result": result,
                })

            try:
                stage_result = await emitter.run_stage(
                    stage_id, f"agent.{call['name']}", _run_tool(),
                )
                tool_result_payload = (stage_result.payload or {}).get("tool_result") or {}
            except Exception as exc:
                tool_result_payload = {"error": str(exc)}

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": call["id"],
                "content":     json.dumps(tool_result_payload)[:8000],
                "is_error":    "error" in tool_result_payload,
            })

            if trace_callback is not None:
                try:
                    trace_callback({
                        "kind":        "tool_execution",
                        "iteration":   iteration,
                        "stage_id":    stage_id,
                        "tool_name":   call["name"],
                        "tool_input":  call["input"],
                        "tool_result": tool_result_payload,
                        "is_error":    "error" in tool_result_payload,
                    })
                except Exception:
                    pass

            if call["name"] == "finalize":
                finalized = True

        messages.append({"role": "user", "content": tool_results})

        if finalized:
            break

    # ── Post-ingest enforcement (invariants) ───────────────────────────────
    # No matter what the agent decided, the final ingestion state MUST include:
    #   1. table_summary chunks in the vector DB (if the doc had tables)
    #   2. a non-empty knowledge graph (if any prose chunks exist)
    # These run as `auto.*` stages so they're visible in the UI as automatic
    # cleanup, not as agent decisions.
    stage_id = await _enforce_ingest_invariants(
        emitter=emitter,
        job_id=job_id,
        filepath=filepath,
        stage_id=stage_id,
    )

    # Final summary event
    stage_id += 1
    cache_hit_ratio = (
        total_cache_read / (total_cache_read + total_input)
        if (total_cache_read + total_input) > 0 else 0.0
    )
    await emitter.run_stage(
        stage_id, "Agent finished",
        _info_stage({
            "iterations":           iteration,
            "tool_calls":           stage_id - 1,
            "total_input_tokens":   total_input,
            "total_output_tokens":  total_output,
            "cache_create_tokens":  total_cache_create,
            "cache_read_tokens":    total_cache_read,
            "cache_hit_ratio":      round(cache_hit_ratio, 3),
            "finalized":            finalized,
            "agent_model":          _MODEL,
        }),
    )


# ── Post-ingest invariant enforcement ─────────────────────────────────────────


async def _enforce_ingest_invariants(
    *,
    emitter: StageEmitter,
    job_id: str,
    filepath: Path,
    stage_id: int,
) -> int:
    """Guarantee two invariants regardless of what the agent did:

    1. If the document had tables, the vector DB has table_summary chunks
       (Claude-written description + columns + sample rows).
    2. If the document has any chunks, the knowledge graph is non-empty
       (or, at minimum, extract_entities ran on the chunks).

    Each missing piece is filled via an `auto.*` stage event so the user
    sees the system completing the work.

    Returns the updated stage_id.
    """
    import services.job_cache as cache
    from pipelines.custom.runner import _table_summary_chunks

    chunks = cache.get(job_id, "chunks", []) or []
    enriched = cache.get(job_id, "enriched_tables", []) or []
    extracted_tables = cache.get(job_id, "extracted_tables", []) or []

    # Count existing summary chunks (per-table, not globally) so we know if
    # ANY table is missing its summary — covers the case where parser tables
    # got summaries but OCR'd tables (added by caption_images) didn't.
    existing_summary_count = sum(
        1 for c in chunks
        if (c.get("metadata") or {}).get("chunk_type") == "table_summary"
    )
    needs_more_summaries = (
        len(extracted_tables) > 0
        and existing_summary_count < len(extracted_tables)
    )

    # ── Invariant 1: table_summary chunks in vector DB ─────────────────
    if needs_more_summaries:
        # Use extracted_tables (which already includes OCR'd tables added by
        # caption_images) as the source of truth. For each table missing a
        # description, run Claude haiku enrichment; tables that already have
        # a description (OCR tables) skip the Claude call.
        existing_enriched_ids = {t.get("id") for t in enriched}
        tables_needing_description = [
            t for t in extracted_tables
            if t.get("id") not in existing_enriched_ids and not t.get("description")
        ]

        if tables_needing_description:
            stage_id += 1
            try:
                from pipelines.custom import stage_06_multimodal

                async def _enrich_only():
                    result = await stage_06_multimodal.enrich_tables(
                        {"tables": tables_needing_description}
                    )
                    return _SimpleResult(payload=result)

                stage_result = await emitter.run_stage(
                    stage_id, "auto.describe_tables", _enrich_only(),
                )
                new_descriptions = (stage_result.payload or {}).get("tables_enriched", [])
                enriched = enriched + new_descriptions
            except Exception as exc:
                log.warning("auto.describe_tables failed: %s", exc)

        # OCR tables (already have descriptions) — add them to enriched if not present
        for tbl in extracted_tables:
            if tbl.get("id") not in {t.get("id") for t in enriched} and tbl.get("description"):
                enriched.append(tbl)

        if enriched:
            cache.put(job_id, "enriched_tables", enriched)
            # Reorder to match extracted_tables sequence (so doc_table_N
            # numbering aligns with SQL store table ordering)
            id_to_enriched = {t.get("id"): t for t in enriched}
            ordered_enriched = [id_to_enriched[t.get("id")] for t in extracted_tables
                                if t.get("id") in id_to_enriched]
            summary_chunks = _table_summary_chunks(ordered_enriched)
            if summary_chunks:
                existing = cache.get(job_id, "chunks", []) or []
                existing_ids = {c.get("id") for c in existing}
                new_summary = [c for c in summary_chunks if c.get("id") not in existing_ids]
                if new_summary:
                    chunks = existing + new_summary
                    cache.put(job_id, "chunks", chunks)
                    # Re-embed and re-upsert so the new chunks land in Qdrant
                    stage_id += 1
                    try:
                        from pipelines.custom import stage_07_embedding, stage_09_vector_store
                        async def _re_embed():
                            return await stage_07_embedding.run(chunks, job_id)
                        await emitter.run_stage(
                            stage_id, "auto.re_embed_with_table_summaries", _re_embed(),
                        )
                        stage_id += 1
                        async def _re_upsert():
                            return await stage_09_vector_store.run(
                                job_id,
                                collection_prefix="rag_proto_agent",
                                cache_prefix="",
                            )
                        await emitter.run_stage(
                            stage_id, "auto.refresh_vector_store", _re_upsert(),
                        )
                    except Exception as exc:
                        log.warning("auto re-embed failed: %s", exc)

    # ── Invariant 2: non-empty knowledge graph ──────────────────────────
    chunks = cache.get(job_id, "chunks", []) or []
    if chunks:
        kg = cache.get(job_id, "knowledge_graph")
        kg_empty = (
            kg is None
            or (hasattr(kg, "number_of_nodes") and kg.number_of_nodes() == 0)
        )
        if kg_empty:
            stage_id += 1
            try:
                from pipelines.custom import stage_09_knowledge_graph
                async def _build_kg():
                    return await stage_09_knowledge_graph.run(job_id, cache_prefix="")
                await emitter.run_stage(
                    stage_id, "auto.build_knowledge_graph", _build_kg(),
                )
            except Exception as exc:
                log.warning("auto.build_knowledge_graph failed: %s", exc)

    return stage_id


# ── Small helpers ──────────────────────────────────────────────────────────────


class _SimpleResult:
    def __init__(self, payload: dict, verification=None):
        self.payload = payload
        self.verification = verification


async def _empty_stage():
    return _SimpleResult(payload={"note": "no file provided"})


async def _error_stage(msg: str):
    return _SimpleResult(payload={"error": msg})


async def _info_stage(payload: dict):
    return _SimpleResult(payload=payload)


def _summarize_messages(messages: list[dict]) -> list[dict]:
    """Compact per-message preview for the UI — role + content type + short text.

    Avoids shipping every full message body (tool_result blocks can be 8KB+).
    Each entry: {role, kinds: [text|tool_use|tool_result], preview}.
    """
    out: list[dict] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str):
            out.append({
                "role": role,
                "kinds": ["text"],
                "preview": content[:120] + ("…" if len(content) > 120 else ""),
            })
            continue
        kinds: list[str] = []
        preview_bits: list[str] = []
        for b in content or []:
            if isinstance(b, dict):
                t = b.get("type", "?")
            else:
                t = getattr(b, "type", "?")
            kinds.append(t)
            if t == "text":
                txt = b.get("text") if isinstance(b, dict) else getattr(b, "text", "")
                preview_bits.append((txt or "")[:80])
            elif t == "tool_use":
                name = b.get("name") if isinstance(b, dict) else getattr(b, "name", "")
                preview_bits.append(f"→ {name}()")
            elif t == "tool_result":
                content_val = b.get("content") if isinstance(b, dict) else getattr(b, "content", "")
                preview_bits.append(f"← {str(content_val)[:60]}")
        out.append({
            "role": role,
            "kinds": kinds,
            "preview": " | ".join(preview_bits)[:200],
        })
    return out


def _snapshot_messages(messages: list[dict]) -> list[dict]:
    """Return a JSON-safe shallow copy of the message history for tracing.

    Anthropic SDK content blocks aren't plain dicts — convert tool_use /
    tool_result blocks into something we can json.dumps and inspect.
    """
    snap: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            snap.append({"role": role, "content": content})
            continue
        # content is a list of blocks (mix of objects and dicts)
        blocks: list[dict] = []
        for b in content or []:
            if isinstance(b, dict):
                blocks.append(b)
            else:
                # SDK object — pull the relevant fields by attribute
                btype = getattr(b, "type", None)
                if btype == "text":
                    blocks.append({"type": "text", "text": getattr(b, "text", "")})
                elif btype == "tool_use":
                    blocks.append({
                        "type":  "tool_use",
                        "id":    getattr(b, "id", ""),
                        "name":  getattr(b, "name", ""),
                        "input": dict(getattr(b, "input", {}) or {}),
                    })
                elif btype == "tool_result":
                    blocks.append({
                        "type":        "tool_result",
                        "tool_use_id": getattr(b, "tool_use_id", ""),
                        "content":     getattr(b, "content", ""),
                    })
                else:
                    blocks.append({"type": btype or "unknown"})
        snap.append({"role": role, "content": blocks})
    return snap
