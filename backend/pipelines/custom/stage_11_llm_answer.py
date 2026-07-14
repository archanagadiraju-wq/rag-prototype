"""Stage 12 (Custom) / Stage 9 (Docling) — LLM Answer.

Answers the 10 showcase questions built in Stage 11 (RAG Ready) using
the appropriate storage mechanism for each:
  • vector  — top-5 chunks from full-hybrid retrieval
  • sql     — SQL result table injected as context
  • kg      — entity graph results surfaced via vector + graph bonus
  • hybrid  — both SQL result and top-k chunks combined

Records per-answer token usage, latency, and RAG confidence.
"""
from __future__ import annotations
import json
import math
import time
from typing import Any

import anthropic

from config import settings
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
import services.job_cache as cache
import services.sql_store as sql_store

from pipelines.custom.stage_10_rag_ready import (
    _retrieve,
    _build_keyword_query,
    _build_entity_query,
    _SEMANTIC_QUERIES,
    _DEFAULT_SEMANTIC,
)

_TOP_K            = 5    # chunks the answer LLM sees
_RETRIEVE_K       = 15   # candidate pool sent to the reranker (when enabled)
_RERANK_MAX_TOK   = 200  # output: just a JSON array of indices
_MAX_ANSWER_TOKENS = 400
_HAIKU            = "claude-haiku-4-5-20251001"
_COST_IN          = 0.80  / 1_000_000
_COST_OUT         = 4.00  / 1_000_000

# SQL routing: cap query rows + reject anything that isn't a single SELECT.
_SQL_MAX_ROWS         = 25
_SQL_ROUTER_MAX_TOK   = 500
_AGG_KEYWORDS = ("sum", "average", "avg", "total", "count", "minimum", "maximum",
                 "highest", "lowest", "compare", "across all", "how many")

# Rebuilt router prompt — three rules carry the load:
#   1. Stay out of fact-shaped questions (facts.json handles those)
#   2. Read column DESCRIPTIONS (not just names) — that's how the router knows
#      `capacity_tr@doc_table_3` is historical, not the current project
#   3. Aggregates (SUM/AVG/COUNT) only when the question explicitly asks
_SQL_ROUTER_SYSTEM = """You decide whether a user question about a document can
be answered by SQL over the document's extracted tables, and if so, generate
ONE SQLite SELECT statement.

Output ONLY valid JSON, no prose, no code fences:
{
  "use_sql": true|false,
  "sql":     "SELECT ..." | null,
  "reason":  "one short sentence"
}

WHEN TO USE SQL (use_sql=true) — VERY NARROW:
  - The question asks for a SPECIFIC NUMERIC value FROM A MULTI-ROW TABLE
    (e.g. "what is the labor cost for ductwork?", "what is the line-item
    total for general requirements?")
  - The question asks for a COMPARISON across rows ("which item costs the
    most?", "what's the total of all chilled water pipes?")
  - The question is about a SPECIFIC TABLE referenced by name

WHEN TO SKIP SQL (use_sql=false) — DEFAULT:
  - Document-level single-value PROPERTIES (capacity, budget, dates, approver,
    reference number, lot/floor area, contractors). These are handled by a
    separate fact-lookup layer; SQL would only get them wrong.
  - Narrative / qualitative / "what does the doc say about X" questions.
  - Questions about people, organizations, or entities (use the knowledge graph).
  - When you're unsure which table or column to query.
  - When column descriptions don't clearly indicate the right column.

AGGREGATE RULES (CRITICAL):
  - Use SUM / AVG / COUNT / MIN / MAX **only** when the question explicitly
    asks for an aggregate ACROSS MULTIPLE rows (e.g. "what's the total of all
    line items", "average cost across all bidders", "how many projects").
  - Specifically: if the question mentions a SPECIFIC NAMED ROW or category
    (e.g. "total cost for the Lower Ground Floor level", "budget for the
    Mechanical Equipment line item"), USE A WHERE FILTER ON THAT ROW — NOT
    A SUM. The value in the row is ALREADY a total for that category. SUM
    would aggregate across multiple rows incorrectly.
  - Heuristic: if you can identify exactly one row to query, do not use SUM.
  - Naive aggregates on the wrong table have been the #1 cause of wrong
    SQL answers. Default to specific WHERE-filter lookups.

SAFETY RULES:
  - The SQL MUST be a single SELECT statement.
  - Quote table + column names in double quotes (case-sensitive match required).
  - Always include LIMIT 25 to bound output.
  - No INSERT/UPDATE/DELETE/DROP/ALTER.

The schema below shows each table with column DESCRIPTIONS. Read the
descriptions, not just the column names. If a column description says
"for a historical project" or "for a specific bidder", that column is NOT
about the current document subject — pick a different one (or return
use_sql=false)."""

_SYSTEM = (
    "You are a precise document assistant. Answer using ONLY the provided "
    "context. Be concise (1-3 sentences). State the answer directly.\n\n"
    "Context blocks (in order of decreasing trust):\n"
    "  [Document Fact] — typed value extracted and quote-validated at ingest.\n"
    "  [Document Chunks] — verbatim text from the document.\n"
    "  [SQL Result] — generated query against extracted tables.\n\n"
    "Combining sources for compound questions — IMPORTANT:\n"
    "When the question asks for MULTIPLE pieces of information (e.g., "
    "'compare X and Y', 'which contractors have done X-scale projects', "
    "'how does X relate to Y'), use the BEST source for each piece and "
    "combine them. Different context blocks supply different pieces of the "
    "answer — they are not conflicts to choose between, they are sources to "
    "compose. Do NOT say 'the context does not contain X' when the SQL "
    "Result block clearly contains X.\n\n"
    "Example: if [Document Fact] gives a project budget and [SQL Result] "
    "lists historical contracts, a question 'compare current budget to "
    "historical contracts' uses BOTH — the budget from facts, the history "
    "from SQL.\n\n"
    "Reconciliation rules when blocks describe the SAME thing:\n"
    "  - If [Fact] and [SQL]/[Chunks] disagree on the SAME number, "
    "trust [Fact].\n"
    "  - If [SQL] and [Chunks] disagree, trust [Chunks].\n\n"
    "Do not explain the trust order or speculate about discrepancies. "
    "If the context is genuinely insufficient, say so in one sentence."
)

_JUDGE_SYSTEM = (
    "You are an answer-evaluation judge. Given a question, the retrieved "
    "context that was available, and an AI-generated answer, decide how well "
    "the answer addresses the question and how well it is supported by the "
    "context. Output ONLY valid JSON, no prose, no code fences:\n"
    '{"verdict":"correct|partial|unsupported|incorrect",'
    '"score":<0.0-1.0>,'
    '"rationale":"one short sentence"}\n\n'
    "Rubric:\n"
    "- correct      (0.85–1.00): fully answers the question; every factual claim is supported by the context.\n"
    "- partial      (0.50–0.84): addresses the question but misses detail, or adds minor unsupported framing.\n"
    "- unsupported  (0.20–0.49): makes claims not present in the context (hallucination), even if plausibly true.\n"
    "- incorrect    (0.00–0.19): wrong answer, or refuses without justification when the context contains the answer."
)
_JUDGE_MAX_TOKENS = 200


async def answer_one(question: str, job_id: str, cache_prefix: str = "") -> dict:
    """Answer a single ad-hoc question against an already-ingested job.

    Reuses retrieval + LLM + judge logic from the stage-11 loop but reads all
    its inputs from `job_cache` (which is disk-backed, so this works across
    restarts as long as the job's earlier stages completed). Returns a dict
    matching the per-question entries from the stage's `answers` list, plus
    the top-5 retrieved chunks for the requester to display.
    """
    import asyncio as _asyncio
    from services.api_retry import with_retry_sync

    embedded         = cache.get(job_id, f"{cache_prefix}embedded_chunks", [])
    bm25_idx         = cache.get(job_id, f"{cache_prefix}bm25_index")
    kg               = cache.get(job_id, f"{cache_prefix}knowledge_graph")
    chunk_entity_map = cache.get(job_id, f"{cache_prefix}chunk_entity_map", {})

    if not embedded:
        return {"error": "job not ingested (no embedded chunks)", "question": question}

    # ── Embed the question ────────────────────────────────────────────────────
    q_vec: list[float]
    if (settings.openai_api_key and len(settings.openai_api_key) > 20
            and not settings.openai_api_key.startswith("sk-...")):
        from openai import AsyncOpenAI
        from services.api_retry import with_retry_async
        oai = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await with_retry_async(
            oai.embeddings.create,
            model="text-embedding-3-large",
            input=[question],
            dimensions=1536,
            label="ask.embed_question",
        )
        q_vec = resp.data[0].embedding
    else:
        q_vec = _mock_vec(question)

    # ── Retrieval ─────────────────────────────────────────────────────────────
    # Fetch a wider candidate pool when the reranker is enabled, then narrow
    # to top-K via a listwise relevance pass. The RRF fuse is good at recall
    # (bag-of-features), but it can't read the question + chunk together to
    # judge "this chunk actually answers the question".
    qtokens = question.lower().split()
    use_reranker = bool(
        getattr(settings, "enable_reranker", False)
        and settings.anthropic_api_key
        and len(settings.anthropic_api_key) > 20
    )
    retrieve_k = _RETRIEVE_K if use_reranker else _TOP_K
    rrf_results = _retrieve(
        embedded, q_vec, bm25_idx, qtokens, kg, chunk_entity_map,
        "full_hybrid", k=retrieve_k,
        job_id=job_id, cache_prefix=cache_prefix,
    )

    # Reranker (when enabled): RRF top-15 → Claude listwise → top-5.
    # We delay reranking until AFTER the SQL route has decided so we can skip
    # reranking when SQL produced a confident result — the SQL context is
    # already authoritative; reordering the surrounding chunks would only
    # push out the table_summary that supports the SQL number.
    rerank_metrics: dict = {"reason": "disabled"}
    vec_results = rrf_results[:_TOP_K]  # provisional — may overwrite below

    vec_context = "\n\n---\n\n".join(
        f"[Chunk {i+1}]\n{embedded[r['idx']].get('text', '')}"
        for i, r in enumerate(vec_results)
    )

    # ── Document facts route (fast path for single-value lookups) ────────────
    # When the question matches a document fact key/label by embedding similarity,
    # we inject the typed value + source quote as the FIRST context block. The
    # answering LLM sees a directly cited, deterministic value before any
    # retrieved chunks, eliminating the "LLM picks the wrong number" failure
    # mode for fact-shaped questions.
    if getattr(settings, "enable_facts_route", True):
        facts_context_block, facts_match = _facts_route(question, q_vec, job_id, cache_prefix)
    else:
        facts_context_block, facts_match = "", None

    # ── SQL route (when applicable) ───────────────────────────────────────────
    # Run Claude as a SQL router: if the question is asking for an exact value
    # from a structured table, generate + execute a SELECT against the per-job
    # SQLite DB and prepend the result rows to the context. Falls back silently
    # to vector-only retrieval for narrative questions or on any failure.
    sql_result: dict | None = None
    sql_metrics: dict = {}
    use_llm = bool(settings.anthropic_api_key and len(settings.anthropic_api_key) > 20)
    if use_llm and getattr(settings, "enable_sql_routing", False):
        try:
            _router_llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            sql_result, sql_metrics = _try_sql_route(
                _router_llm, question, job_id, cache_prefix,
                facts_match=facts_match,
                vec_results=vec_results,
                embedded=embedded,
            )
        except Exception as exc:
            sql_metrics = {"router_in_tokens": 0, "router_out_tokens": 0,
                           "reason": f"sql_route_outer: {type(exc).__name__}"}
    else:
        sql_metrics = {"router_in_tokens": 0, "router_out_tokens": 0,
                       "reason": "sql_routing_disabled (set ENABLE_SQL_ROUTING=true to enable)"}

    sql_context_block = sql_result["context_block"] if (sql_result and "context_block" in sql_result) else ""
    sql_returned_rows = bool(sql_result and sql_result.get("row_count", 0) > 0)

    # Now decide on reranking. Skip when SQL returned a real result — the SQL
    # block is the authoritative source for that question and reranking would
    # likely push the supporting table_summary chunk out of the top-K.
    if use_reranker and len(rrf_results) > _TOP_K and not sql_returned_rows:
        try:
            _rerank_llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            vec_results, rerank_metrics = _rerank_chunks(
                _rerank_llm, question, rrf_results, embedded, top_k=_TOP_K,
            )
        except Exception as exc:
            rerank_metrics = {"reason": f"outer_failure: {type(exc).__name__}",
                              "rerank_in_tokens": 0, "rerank_out_tokens": 0,
                              "ms": 0.0, "kept_indices": None}
            # vec_results already set to RRF top-K above
    elif sql_returned_rows:
        rerank_metrics = {"reason": "skipped_sql_authoritative",
                          "rerank_in_tokens": 0, "rerank_out_tokens": 0,
                          "ms": 0.0, "kept_indices": None}

    # Rebuild vec_context now that vec_results may have changed
    vec_context = "\n\n---\n\n".join(
        f"[Chunk {i+1}]\n{embedded[r['idx']].get('text', '')}"
        for i, r in enumerate(vec_results)
    )

    # Compose full context: facts (most authoritative) → SQL → vector chunks.
    context_parts: list[str] = []
    if facts_context_block:
        context_parts.append(facts_context_block)
    if sql_context_block:
        context_parts.append(sql_context_block)
    context_parts.append(f"[Document Chunks]\n{vec_context}")
    full_context = "\n\n".join(context_parts)
    user_prompt = f"Context:\n{full_context}\n\nQuestion: {question}"

    # ── LLM call (with retry) ─────────────────────────────────────────────────
    answer = "[Mock — no Anthropic key]"
    in_tok = out_tok = 0
    latency_ms = 0.0
    judge: dict | None = None

    if use_llm:
        llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        t0 = time.perf_counter()
        try:
            msg = await _asyncio.to_thread(
                with_retry_sync,
                llm.messages.create,
                model=_HAIKU,
                max_tokens=_MAX_ANSWER_TOKENS,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
                label="ask.llm_answer",
            )
            answer  = msg.content[0].text.strip()
            in_tok  = msg.usage.input_tokens
            out_tok = msg.usage.output_tokens
        except Exception as exc:
            answer = f"LLM call failed: {exc}"
        latency_ms = (time.perf_counter() - t0) * 1000
        judge = _judge_answer(llm, question, full_context, answer)

    conf_score, conf_label = _rag_confidence(vec_results, False)
    # Cost includes the SQL router + reranker calls (each an extra Claude
    # haiku call) so the UI total stays accurate.
    router_in   = sql_metrics.get("router_in_tokens", 0) or 0
    router_out  = sql_metrics.get("router_out_tokens", 0) or 0
    rerank_in   = rerank_metrics.get("rerank_in_tokens", 0) or 0
    rerank_out  = rerank_metrics.get("rerank_out_tokens", 0) or 0
    cost_usd = round(
        (in_tok + router_in + rerank_in) * _COST_IN
        + (out_tok + router_out + rerank_out) * _COST_OUT,
        6,
    )

    return {
        "question":         question,
        "answer":           answer,
        "input_tokens":     in_tok + router_in + rerank_in,
        "output_tokens":    out_tok + router_out + rerank_out,
        "cost_usd":         cost_usd,
        "latency_ms":       round(latency_ms, 1),
        "confidence":       conf_score,
        "confidence_label": conf_label,
        "context_chunks":   len(vec_results),
        "retrieved": [
            {
                "chunk_id":   embedded[r["idx"]].get("id"),
                "text":       embedded[r["idx"]].get("text", "")[:400],
                "score":      r.get("dense_score", 0),
                "page":       embedded[r["idx"]].get("page"),
                "heading":    embedded[r["idx"]].get("heading_path"),
            }
            for r in vec_results
        ],
        "system_prompt":    _SYSTEM,
        "user_prompt":      user_prompt,
        # Document-facts routing trace — null when no fact matched.
        "fact_used":        facts_match is not None,
        "fact_match":       facts_match,
        # Reranker trace — null when disabled or too few candidates.
        "rerank_used":      use_reranker and len(rrf_results) > _TOP_K,
        "rerank_candidates": len(rrf_results),
        "rerank_kept":      rerank_metrics.get("kept_indices"),
        "rerank_ms":        rerank_metrics.get("ms", 0.0),
        "rerank_reason":    rerank_metrics.get("reason"),
        # SQL routing trace — null when not used, populated when SQL was tried.
        "sql_used":         bool(sql_result and sql_result.get("row_count", 0) > 0),
        "sql_query":        (sql_result or {}).get("sql"),
        "sql_columns":      (sql_result or {}).get("columns") or [],
        "sql_rows":         (sql_result or {}).get("rows") or [],
        "sql_row_count":    (sql_result or {}).get("row_count", 0),
        "sql_router_reason": sql_metrics.get("reason"),
        "judge_score":      judge["score"]     if judge else None,
        "judge_verdict":    judge["verdict"]   if judge else None,
        "judge_rationale":  judge["rationale"] if judge else None,
    }


# Lowered from 0.55 — the previous threshold missed fact-shaped questions
# whose label phrasing only loosely matched the user's wording. The judge LLM
# corrects for false positives anyway, and we'd rather inject a fact + quote
# (provenance preserved) than fall through to vector retrieval and risk
# the LLM picking the wrong number from a chunk.
_FACT_MATCH_THRESHOLD = 0.45


_RERANKER_SYSTEM = """You are a relevance reranker. Given a question and a
list of candidate document chunks, identify the TOP {top_k} chunks that
contain information needed to answer the question.

Score each candidate on these criteria, in order:
  1. Does it directly answer the question? (highest weight)
  2. Does it contain a specific number, name, date, or quote that the question
     asks about?
  3. Does it provide context that helps verify a direct answer in another chunk?

Output ONLY a JSON array of chunk indices (0-based, integer), sorted by
relevance (most relevant first):
  [3, 7, 1, 12, 0]

If fewer than {top_k} chunks are relevant, return fewer indices.
Do not include explanations, prose, or code fences. Just the JSON array."""


def _rerank_chunks(
    llm,
    question: str,
    candidates: list[dict],
    embedded: list[dict],
    top_k: int = _TOP_K,
) -> tuple[list[dict], dict]:
    """Listwise reranker — Claude reads (question, candidates) and returns the
    top-k most relevant indices. Falls back to the original RRF order on any
    failure (parse error, invalid indices, LLM error).

    Returns (reordered_subset, metrics_dict).
    """
    from services.api_retry import with_retry_sync

    metrics: dict = {
        "candidate_count": len(candidates),
        "kept_indices":    None,        # filled below
        "rerank_in_tokens":  0,
        "rerank_out_tokens": 0,
        "ms":              0.0,
        "reason":          "skipped",
    }
    if not candidates:
        return [], metrics
    if len(candidates) <= top_k:
        # Nothing to rerank — return as-is
        metrics["reason"] = "skip_too_few_candidates"
        metrics["kept_indices"] = list(range(len(candidates)))
        return candidates, metrics

    # Build compact candidate block: index + truncated text per candidate.
    # Truncate to 400 chars each — enough for the reranker to judge relevance
    # without blowing token budget. Full chunk text is restored downstream.
    lines: list[str] = []
    for i, r in enumerate(candidates):
        ch = embedded[r["idx"]]
        text = (ch.get("text") or "").replace("\n", " ").strip()
        if len(text) > 400:
            text = text[:400] + "…"
        meta = ch.get("metadata") or {}
        hint = []
        if meta.get("chunk_type") and meta.get("chunk_type") != "prose":
            hint.append(meta["chunk_type"])
        if meta.get("table_name"):
            hint.append(meta["table_name"])
        if meta.get("page") is not None:
            hint.append(f"p{meta['page']}")
        hint_str = f" [{' · '.join(hint)}]" if hint else ""
        lines.append(f"[{i}]{hint_str} {text}")

    user_msg = (
        f"Question:\n{question}\n\n"
        f"Candidates:\n" + "\n\n".join(lines)
    )
    system = _RERANKER_SYSTEM.format(top_k=top_k)

    t0 = time.perf_counter()
    try:
        msg = with_retry_sync(
            llm.messages.create,
            model=_HAIKU,
            max_tokens=_RERANK_MAX_TOK,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            label="ask.reranker",
        )
        metrics["rerank_in_tokens"]  = msg.usage.input_tokens
        metrics["rerank_out_tokens"] = msg.usage.output_tokens
    except Exception as exc:
        metrics["reason"] = f"llm_failed: {type(exc).__name__}"
        metrics["kept_indices"] = list(range(top_k))
        return candidates[:top_k], metrics
    finally:
        metrics["ms"] = round((time.perf_counter() - t0) * 1000, 1)

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        order = json.loads(raw)
        if not isinstance(order, list):
            raise ValueError("Expected a JSON array")
        # Validate: dedupe, keep only valid indices into `candidates`
        seen: set[int] = set()
        valid: list[int] = []
        for i in order:
            i = int(i)
            if 0 <= i < len(candidates) and i not in seen:
                valid.append(i)
                seen.add(i)
            if len(valid) >= top_k:
                break
        if not valid:
            raise ValueError("No valid indices")
    except Exception as exc:
        metrics["reason"] = f"parse_failed: {type(exc).__name__}: {str(exc)[:80]}"
        metrics["kept_indices"] = list(range(top_k))
        return candidates[:top_k], metrics

    metrics["reason"] = f"ok ({len(valid)} kept)"
    metrics["kept_indices"] = valid
    reordered = [candidates[i] for i in valid]
    return reordered, metrics


def _facts_route(
    question: str,
    q_vec: list[float],
    job_id: str,
    cache_prefix: str = "",
) -> tuple[str, dict | None]:
    """Match a question against this job's facts.json by label-vector similarity.

    Returns (context_block, matched_fact_record). When no fact matches above
    threshold, returns ("", None) and the caller skips this path.

    Why label-only matching (not the value)? The user's question phrases the
    PROPERTY they want ("what's the capacity?"), not the answer. The fact's
    `label` field is what we should compare against. We compute label
    embeddings on the fly — extracting facts is rare enough that caching the
    label vectors per job would be premature optimisation.
    """
    try:
        from services.fact_extractor import load_facts
        payload = load_facts(job_id, cache_prefix=cache_prefix)
        if payload is None or not payload.get("facts"):
            return "", None
    except Exception:
        return "", None

    facts = payload["facts"]

    # Embed every label in one batch — cheap (text-embedding-3-large, small input)
    labels = [f.get("label") or f.get("key") or "" for f in facts]
    if not any(labels):
        return "", None

    label_vecs: list[list[float]] = []
    try:
        if (settings.openai_api_key and len(settings.openai_api_key) > 20
                and not settings.openai_api_key.startswith("sk-...")):
            from openai import OpenAI
            from services.api_retry import with_retry_sync
            oai = OpenAI(api_key=settings.openai_api_key)
            resp = with_retry_sync(
                oai.embeddings.create,
                model="text-embedding-3-large",
                input=labels,
                dimensions=1536,
                label="facts.embed_labels",
            )
            label_vecs = [item.embedding for item in resp.data]
        else:
            label_vecs = [_mock_vec(l) for l in labels]
    except Exception:
        return "", None

    # Pick the best-matching fact above threshold
    from pipelines.custom.stage_10_rag_ready import _cosine
    best_idx = -1
    best_score = -1.0
    for i, lv in enumerate(label_vecs):
        s = _cosine(q_vec, lv)
        if s > best_score:
            best_score, best_idx = s, i

    if best_score < _FACT_MATCH_THRESHOLD or best_idx < 0:
        return "", None

    f = facts[best_idx]
    src = f.get("source") or {}

    # Render the matched fact as a high-authority context block. The format
    # puts the typed value first (so the LLM doesn't drift to a different
    # number from the prose) and the verbatim quote second (for citation).
    val = f.get("value")
    unit = f.get("unit")
    val_str = _format_fact_value(val, f.get("type"), unit)
    label = f.get("label") or f.get("key")

    lines = [
        "[Document Fact — extracted at ingest, typed and cited]",
        f"  {label}: {val_str}",
        f"  Source: page {src.get('page', '?')}",
    ]
    if src.get("table_name"):
        lines.append(f"  From SQL table: {src['table_name']}")
    if src.get("quote"):
        lines.append(f'  Verbatim quote: "{src["quote"]}"')

    block = "\n".join(lines)
    matched_record = {
        "key":           f.get("key"),
        "label":         label,
        "value":         val,
        "unit":          unit,
        "type":          f.get("type"),
        "match_score":   round(best_score, 4),
        "source":        src,
    }
    return block, matched_record


def _format_fact_value(value, type_hint: str | None, unit: str | None) -> str:
    """Render a typed fact value back as a readable string for prompt context."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, (int, float)) and unit:
        return f"{value:,} {unit}" if isinstance(value, int) else f"{value:,.2f} {unit}"
    if isinstance(value, (int, float)):
        return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
    return str(value)


def _find_sql_db(job_id: str, cache_prefix: str = "") -> str | None:
    """Locate the per-job SQLite file. Returns absolute path or None."""
    from pathlib import Path
    job_dir = Path(__file__).resolve().parents[2] / "data" / "jobs" / job_id
    for candidate in (f"tables_{cache_prefix}.db", "tables.db", "tables_d_.db"):
        p = job_dir / candidate
        if p.exists():
            return str(p)
    return None


def _build_sql_schema_block(registry: dict, enriched_tables: list[dict]) -> str:
    """Render the available SQL tables for the router prompt.

    Includes the COLUMN DESCRIPTIONS (from services.column_describer) so the
    router can disambiguate columns with similar names across tables. The
    descriptions are the load-bearing piece — without them the router falls
    back to guessing from column names alone, which caused the regression we
    measured.
    """
    desc_by_id: dict[str, str] = {}
    for i, t in enumerate(enriched_tables or []):
        desc_by_id[f"doc_table_{i + 1}"] = (t.get("description") or "").strip()

    lines: list[str] = []
    for tname, info in (registry or {}).items():
        cols = info.get("columns") or []
        col_types = info.get("column_types") or ["TEXT"] * len(cols)
        col_descriptions = info.get("column_descriptions") or {}
        rows = info.get("row_count", 0)
        scope = info.get("scope") or "unknown"
        table_summary = (info.get("table_summary") or desc_by_id.get(tname, "")).strip()

        lines.append(f'TABLE "{tname}"  ({rows} rows, scope={scope})')
        if table_summary:
            lines.append(f"  about:   {table_summary}")
        # Per-column block: name + type + description
        lines.append("  columns:")
        for c, t in zip(cols, col_types):
            d = col_descriptions.get(c, "").strip()
            line = f'    "{c}" ({t})'
            if d:
                line += f"  — {d}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


def _question_asks_for_aggregate(question: str) -> bool:
    """Heuristic: does the question explicitly ask for SUM/AVG/COUNT semantics?

    Used to gate the SQL router from generating naive aggregates when the user
    just wants a specific cell value.
    """
    q = question.lower()
    return any(kw in q for kw in _AGG_KEYWORDS)


def _check_facts_sql_overlap(facts_match: dict, rows: list[dict], col_names: list[str]) -> str | None:
    """Decide whether SQL is redundantly answering the same property as facts.

    Returns a short reason string when SQL should be suppressed, None to keep
    SQL.

    Logic:
      - Look at the first numeric value in SQL output.
      - Compare its magnitude to the facts.value.
      - If they're identical (within 1%) → SQL is redundant; drop it (facts
        is more authoritative).
      - If same order of magnitude but different values → SQL is competing
        about the same property; drop (facts wins).
      - If wildly different magnitudes → different properties; keep SQL.
      - If facts.value isn't numeric → keep SQL (no overlap test possible).
    """
    fact_value = facts_match.get("value")
    if not isinstance(fact_value, (int, float)) or fact_value == 0:
        return None

    # First numeric value in SQL output
    sql_value: float | None = None
    for r in rows[:5]:
        for c in col_names:
            v = r.get(c)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                sql_value = float(v)
                break
        if sql_value is not None:
            break
    if sql_value is None or sql_value == 0:
        return None

    fv = float(fact_value)
    ratio = abs(sql_value / fv) if fv else float("inf")

    # Identical → SQL is redundant noise
    if abs(sql_value - fv) / abs(fv) < 0.01:
        return f"identical_to_fact ({sql_value} ≈ {fv})"

    # Same order of magnitude (within 10×) → competing values for the same
    # property. Facts wins; drop SQL.
    if 0.1 < ratio < 10:
        return f"same_magnitude_different_value (sql={sql_value} vs fact={fv})"

    # Different magnitude → almost certainly a different property; keep SQL.
    return None


def _sql_result_is_sane(rows: list, columns: list[str], question: str, vec_results: list, embedded: list) -> tuple[bool, str]:
    """Reject SQL output that looks numerically nonsensical vs what the vector
    chunks show. Heuristic, not perfect — designed to catch the obvious
    "SUM returned 7.0 but the doc says 3,000" failure mode.
    """
    if not rows:
        return True, "ok"  # No rows = no harm done
    if len(rows) > 5:
        return True, "ok"  # Multi-row queries less suspicious

    # Single-row aggregate-shaped result with one numeric column → high risk
    if len(rows) == 1 and len(columns) == 1:
        val = list(rows[0].values())[0]
        if isinstance(val, (int, float)):
            # Check whether this number, or its rough magnitude, appears in
            # any retrieved chunk. If not, the SQL output is likely an
            # aggregate over the wrong table.
            magnitudes = []
            for r in vec_results[:5]:
                text = embedded[r["idx"]].get("text", "") if r.get("idx") is not None else ""
                # Pull plausible numbers from chunk text
                import re
                for m in re.finditer(r"\d[\d,]*\.?\d*", text):
                    try:
                        magnitudes.append(float(m.group().replace(",", "")))
                    except ValueError:
                        pass
            if magnitudes:
                vmag = abs(val) if val != 0 else 1.0
                ratios = [abs(m / vmag) if vmag > 0 else float("inf") for m in magnitudes]
                # If the closest chunk-mentioned number is >100× off, very suspicious
                closest = min(ratios, key=lambda r: abs(r - 1.0)) if ratios else 1.0
                if closest > 100 or closest < 0.01:
                    return False, f"sql_result_magnitude_off (closest ratio {closest:.1f}× vs chunk values)"
    return True, "ok"


def _sql_is_safe(sql: str) -> bool:
    """Reject anything that isn't a single SELECT. Defence in depth — the
    per-job DB is sandbox-isolated, but no point letting a router hallucinate
    DDL/DML when there's no use case for it."""
    if not sql or not isinstance(sql, str):
        return False
    s = sql.strip().rstrip(";").strip().lower()
    if not s.startswith("select"):
        return False
    # Block multi-statement chains and common DDL/DML keywords
    forbidden = (
        ";", " insert ", " update ", " delete ", " drop ", " alter ",
        " create ", " attach ", " replace ", " pragma ",
    )
    return not any(k in f" {s} " for k in forbidden)


def _try_sql_route(
    llm,
    question: str,
    job_id: str,
    cache_prefix: str,
    facts_match: dict | None = None,
    vec_results: list | None = None,
    embedded: list | None = None,
) -> tuple[dict | None, dict]:
    """Decide-then-execute: ask Claude whether the question is SQL-routable,
    generate a SELECT, run it on the per-job DB, return formatted rows.

    Returns (result_dict | None, metrics_dict). `result_dict` is None when
    SQL routing is skipped or fails; the caller then falls back to vector-only
    context. `metrics_dict` always carries router_in/out_tokens (for cost
    accounting) and a `reason` field for debugging.
    """
    import sqlite3
    from services.api_retry import with_retry_sync

    metrics = {"router_in_tokens": 0, "router_out_tokens": 0, "reason": "skipped"}

    # NOTE: We used to skip SQL when facts_match.score >= 0.65 on the theory
    # that facts is more authoritative for single-value properties. That
    # heuristic *over*-suppressed SQL for compound questions like
    # "compare the project budget to the floor-level breakdown" — facts
    # supplied the budget, but the floor breakdown lives in SQL and we
    # dropped it. Now we always run SQL (subject to the aggregate gate +
    # sanity check below), and the post-execution suppressor decides
    # whether to actually inject SQL context.

    registry = cache.get(job_id, f"{cache_prefix}sql_registry") or {}
    if not registry:
        metrics["reason"] = "no_sql_registry"
        return None, metrics
    db_path = _find_sql_db(job_id, cache_prefix)
    if not db_path:
        metrics["reason"] = "no_sqlite_file"
        return None, metrics

    enriched_tables = cache.get(job_id, f"{cache_prefix}enriched_tables", []) or []
    schema_block = _build_sql_schema_block(registry, enriched_tables)
    if not schema_block:
        metrics["reason"] = "empty_schema"
        return None, metrics

    # Step 1: ask Claude — use_sql? generate SQL?
    try:
        router_msg = with_retry_sync(
            llm.messages.create,
            model=_HAIKU,
            max_tokens=_SQL_ROUTER_MAX_TOK,
            system=_SQL_ROUTER_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Question:\n{question}\n\nAvailable tables:\n{schema_block}",
            }],
            label="ask.sql_router",
        )
        metrics["router_in_tokens"] = router_msg.usage.input_tokens
        metrics["router_out_tokens"] = router_msg.usage.output_tokens
        raw = router_msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        decision = json.loads(raw)
    except Exception as exc:
        metrics["reason"] = f"router_failed: {type(exc).__name__}"
        return None, metrics

    if not decision.get("use_sql"):
        metrics["reason"] = f"router_skipped: {decision.get('reason', '')[:120]}"
        return None, metrics

    sql = (decision.get("sql") or "").strip()
    if not _sql_is_safe(sql):
        metrics["reason"] = "unsafe_sql_rejected"
        return None, metrics

    # Aggregate gate: if the question doesn't explicitly ask for an aggregate
    # but the router generated one anyway, reject. Naive SUM/AVG over the
    # wrong table is the #1 SQL failure mode.
    sql_lower = sql.lower()
    has_aggregate = any(fn in sql_lower for fn in ("sum(", "avg(", "count(", "max(", "min("))
    if has_aggregate and not _question_asks_for_aggregate(question):
        metrics["reason"] = f"aggregate_rejected (sql='{sql[:80]}', question has no aggregate intent)"
        return None, metrics

    # Step 2: execute. Read-only mode + per-query timeout via interrupt would be
    # ideal, but a 5s connection timeout is enough for our table sizes.
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = cur.fetchmany(_SQL_MAX_ROWS)
        col_names = [d[0] for d in (cur.description or [])]
        conn.close()
    except sqlite3.Error as exc:
        metrics["reason"] = f"execute_error: {exc}"
        return {
            "sql": sql, "error": str(exc),
            "rows": [], "columns": [], "row_count": 0,
        }, metrics

    if not rows:
        metrics["reason"] = "zero_rows"
        return None, metrics  # don't pollute context with "no rows matched"

    row_dicts = [{c: r[c] for c in col_names} for r in rows]

    # Sanity check: if the SQL result is numerically incompatible with what
    # the retrieved chunks suggest, drop it. Better to lose a possibly-right
    # answer than confuse the LLM with a confidently-wrong one.
    if vec_results is not None and embedded is not None:
        is_sane, sanity_reason = _sql_result_is_sane(row_dicts, col_names, question, vec_results, embedded)
        if not is_sane:
            metrics["reason"] = sanity_reason
            return None, metrics

    # Same-property suppressor: when facts already answered this question AND
    # SQL appears to be asking about the same property, drop SQL.
    # Heuristic: if the only numeric SQL output is the same number (or wildly
    # different but same magnitude) as the matched fact's value, SQL is
    # redundant (same number → noise) or competing (different number same
    # magnitude → almost certainly wrong about the same thing).
    # If SQL value is a different magnitude entirely, treat it as a different
    # property and keep both.
    if facts_match:
        suppression = _check_facts_sql_overlap(facts_match, row_dicts, col_names)
        if suppression:
            metrics["reason"] = f"suppressed_overlap_with_fact ({suppression})"
            return None, metrics

    # Format as a compact context block. Headers + pipe-delimited rows is the
    # densest representation Claude reads well.
    out_lines = [f"[SQL Query]\n{sql}", "", "[SQL Result]"]
    out_lines.append(" | ".join(col_names))
    for r in rows:
        out_lines.append(" | ".join("" if r[c] is None else str(r[c]) for c in col_names))
    context_block = "\n".join(out_lines)

    metrics["reason"] = f"ok ({len(rows)} rows)"
    return {
        "sql": sql,
        "rows": [{c: r[c] for c in col_names} for r in rows],
        "columns": col_names,
        "row_count": len(rows),
        "context_block": context_block,
    }, metrics


def _judge_answer(llm, question: str, context: str, answer: str) -> dict | None:
    """Run a separate Claude pass to evaluate (question, context, answer).

    Returns {verdict, score, rationale, input_tokens, output_tokens} or None
    if the LLM is unavailable or the response can't be parsed as JSON.
    """
    if llm is None:
        return None
    from services.api_retry import with_retry_sync
    try:
        msg = with_retry_sync(
            llm.messages.create,
            model=_HAIKU,
            max_tokens=_JUDGE_MAX_TOKENS,
            system=_JUDGE_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Retrieved context:\n{context}\n\n"
                    f"AI answer:\n{answer}"
                ),
            }],
            label="judge_answer",
        )
        raw = msg.content[0].text.strip()
        # Strip optional ```json fences in case the model ignores instructions
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        return {
            "verdict":       str(data.get("verdict", "unknown")),
            "score":         score,
            "rationale":     str(data.get("rationale", ""))[:300],
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
    except Exception:
        return None


def _mock_vec(text: str, dim: int = 1536) -> list[float]:
    import hashlib
    seed = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    vec = []
    for _ in range(dim):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        val = ((seed >> 17) & 0xFFFF) / 32768.0 - 1.0
        vec.append(val)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _fmt_sql_table(cols: list[str] | None, rows: list[list] | None) -> str:
    if not cols or not rows:
        return ""
    header = " | ".join(str(c) for c in cols)
    sep    = " | ".join(["---"] * len(cols))
    lines  = [header, sep]
    for r in rows[:8]:
        lines.append(" | ".join(str(v) for v in r))
    return "\n".join(lines)


def _rag_confidence(results: list[dict], has_sql: bool = False) -> tuple[float, str]:
    if not results:
        return (0.55, "medium") if has_sql else (0.0, "low")
    dense = [r["dense_score"] for r in results]
    avg_dense  = sum(dense) / len(dense)
    multi      = sum(1 for r in results if r["sparse_score"] > 0.05 or r["graph_score"] > 0.0)
    multi_ratio= multi / len(results)
    high_q     = sum(1 for d in dense if d > 0.55) / len(dense)
    sql_bonus  = 0.08 if has_sql else 0.0
    score = round(min(1.0, avg_dense * 0.5 + multi_ratio * 0.28 + high_q * 0.14 + sql_bonus), 3)
    label = "high" if score >= 0.70 else "medium" if score >= 0.45 else "low"
    return score, label


async def run(job_id: str, doc_type: str = "", cache_prefix: str = "") -> StageResult:
    embedded         = cache.get(job_id, f"{cache_prefix}embedded_chunks", [])
    bm25_idx         = cache.get(job_id, f"{cache_prefix}bm25_index")
    kg               = cache.get(job_id, f"{cache_prefix}knowledge_graph")
    chunk_entity_map = cache.get(job_id, f"{cache_prefix}chunk_entity_map", {})
    sql_registry     = cache.get(job_id, f"{cache_prefix}sql_registry", {})
    rag_data: dict   = cache.get(job_id, f"{cache_prefix}rag_queries", {})
    showcase: list   = cache.get(job_id, f"{cache_prefix}rag_showcase", [])

    questions: list[dict] = rag_data.get("questions", [])

    if not embedded or not questions:
        payload = {
            "answers": [], "total_input_tokens": 0, "total_output_tokens": 0,
            "total_tokens": 0, "total_llm_ms": 0.0, "total_cost_usd": 0.0,
            "model_used": "none", "llm_input_tokens": 0, "llm_output_tokens": 0,
            "llm_cost_usd": 0.0,
        }
        checks = [make_check("data_available", False, "No questions or chunks", severity="warn")]
        return StageResult(payload=payload, verification=make_verification(checks))

    # ── Embed all questions in one batch ─────────────────────────────────────
    q_texts = [q["q"] for q in questions]
    query_vecs: list[list[float]] = []
    use_real_embeddings = False
    try:
        if (settings.openai_api_key and len(settings.openai_api_key) > 20
                and not settings.openai_api_key.startswith("sk-...")):
            from openai import AsyncOpenAI
            from services.api_retry import with_retry_async
            oai = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await with_retry_async(
                oai.embeddings.create,
                model="text-embedding-3-large",
                input=q_texts,
                dimensions=1536,
                label="llm_answer.embed_questions",
            )
            query_vecs = [item.embedding for item in resp.data]
            use_real_embeddings = True
    except Exception:
        pass
    if not query_vecs:
        query_vecs = [_mock_vec(q) for q in q_texts]

    # ── LLM client ───────────────────────────────────────────────────────────
    use_llm = bool(settings.anthropic_api_key and len(settings.anthropic_api_key) > 20)
    llm     = anthropic.Anthropic(api_key=settings.anthropic_api_key) if use_llm else None
    model_used = _HAIKU if use_llm else "mock"

    # ── Answer each question ──────────────────────────────────────────────────
    answers: list[dict] = []
    total_in = total_out = 0
    judge_total_in = judge_total_out = 0

    for idx, (q_info, q_vec) in enumerate(zip(questions, query_vecs)):
        route = q_info["route"]
        q_text = q_info["q"]
        qtokens = q_text.lower().split()

        # Vector context (always retrieved as grounding) — uses Qdrant HNSW
        # when available, falls back to in-memory cosine if Qdrant is offline.
        vec_results = _retrieve(
            embedded, q_vec, bm25_idx, qtokens, kg, chunk_entity_map,
            "full_hybrid", k=_TOP_K,
            job_id=job_id, cache_prefix=cache_prefix,
        )
        vec_context = "\n\n---\n\n".join(
            f"[Chunk {i+1}]\n{embedded[r['idx']].get('text', '')}"
            for i, r in enumerate(vec_results)
        )

        # SQL context (reuse from showcase cache if available, else re-run)
        sql_query: str | None = q_info.get("sql")
        sql_cols:  list[str] | None  = None
        sql_rows:  list[list] | None = None
        sql_context = ""
        if "sql" in route and sql_query and sql_registry:
            # Check showcase cache first
            if idx < len(showcase) and showcase[idx].get("sql_cols"):
                sql_cols = showcase[idx]["sql_cols"]
                sql_rows = showcase[idx]["sql_rows"]
            else:
                try:
                    sql_cols, sql_rows = sql_store.run_query(sql_query, job_id, cache_prefix)
                    sql_rows = sql_rows[:8]
                except Exception:
                    pass
            if sql_cols and sql_rows is not None:
                sql_context = f"[SQL Table Result]\n{_fmt_sql_table(sql_cols, sql_rows)}"

        # Combine context sources
        context_parts = []
        if sql_context and "sql" in route:
            context_parts.append(sql_context)
        context_parts.append(f"[Document Chunks]\n{vec_context}")
        full_context = "\n\n".join(context_parts)

        # Build the exact prompts that go to the model — also stored on the
        # answer record so the UI can show them in a popup for comparison.
        user_prompt = f"Context:\n{full_context}\n\nQuestion: {q_text}"

        # ── LLM call ─────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        if llm:
            try:
                from services.api_retry import with_retry_sync
                import asyncio as _asyncio
                msg = await _asyncio.to_thread(
                    with_retry_sync,
                    llm.messages.create,
                    model=_HAIKU,
                    max_tokens=_MAX_ANSWER_TOKENS,
                    system=_SYSTEM,
                    messages=[{"role": "user", "content": user_prompt}],
                    label=f"llm_answer[q{idx + 1}]",
                )
                answer  = msg.content[0].text.strip()
                in_tok  = msg.usage.input_tokens
                out_tok = msg.usage.output_tokens
            except Exception as exc:
                answer  = f"LLM call failed: {exc}"
                in_tok  = 0
                out_tok = 0
        else:
            preview = " … ".join(
                ch.get("text", "")[:50].strip()
                for ch in [embedded[r["idx"]] for r in vec_results[:2]]
            )
            sql_note = f" SQL result: {sql_cols[0]}={sql_rows[0][0]}." if (sql_cols and sql_rows) else ""
            answer  = (
                f"[Mock — no Anthropic key] Based on {len(vec_results)} retrieved chunks: "
                f"{preview}…{sql_note}"
            )
            in_tok  = len(full_context.split()) + len(q_text.split())
            out_tok = 64

        latency_ms = (time.perf_counter() - t0) * 1000
        total_in  += in_tok
        total_out += out_tok

        conf_score, conf_label = _rag_confidence(vec_results, bool(sql_rows))

        # ── LLM-as-judge pass (separate Claude call) ─────────────────────────
        judge = _judge_answer(llm, q_text, full_context, answer)
        if judge:
            judge_total_in  += judge.get("input_tokens", 0)
            judge_total_out += judge.get("output_tokens", 0)

        answers.append({
            "index":            idx + 1,
            "question":         q_text,
            "route":            route,
            "type":             q_info["type"],
            "difficulty":       q_info.get("difficulty", "medium"),
            "sql_fallback":     q_info.get("sql_fallback", False),
            "answer":           answer,
            "input_tokens":     in_tok,
            "output_tokens":    out_tok,
            "latency_ms":       round(latency_ms, 1),
            "confidence":       conf_score,
            "confidence_label": conf_label,
            "sql_query":        sql_query if "sql" in route else None,
            "sql_cols":         sql_cols,
            "sql_rows":         sql_rows[:5] if sql_rows else None,
            "context_chunks":   len(vec_results),
            "system_prompt":    _SYSTEM,
            "user_prompt":      user_prompt,
            "judge_score":      judge["score"]     if judge else None,
            "judge_verdict":    judge["verdict"]   if judge else None,
            "judge_rationale":  judge["rationale"] if judge else None,
        })

    # Roll judge tokens into the stage's overall LLM totals — the judge runs
    # as a separate Claude call per answer, so its tokens belong to this stage.
    total_in    += judge_total_in
    total_out   += judge_total_out
    total_tokens = total_in + total_out
    total_cost   = round(total_in * _COST_IN + total_out * _COST_OUT, 6)
    total_llm_ms = round(sum(a["latency_ms"] for a in answers), 1)

    # Aggregate judge stats for the payload
    judged = [a for a in answers if a.get("judge_score") is not None]
    avg_judge = sum(a["judge_score"] for a in judged) / len(judged) if judged else 0.0
    verdict_counts: dict[str, int] = {}
    for a in judged:
        v = a.get("judge_verdict") or "unknown"
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    checks = [
        make_check("answers_generated", len(answers) == len(questions),
                   f"{len(answers)}/10 questions answered"),
        make_check("llm_available", use_llm,
                   f"Claude {_HAIKU}" if use_llm
                   else "Mock answers (set ANTHROPIC_API_KEY for real answers)",
                   severity="info" if use_llm else "warn"),
        make_check("token_budget", total_tokens < 50_000,
                   f"{total_tokens:,} tokens · ${total_cost:.4f}"),
    ]

    payload = {
        "answers":             answers,
        "total_input_tokens":  total_in,
        "total_output_tokens": total_out,
        "total_tokens":        total_tokens,
        "total_llm_ms":        total_llm_ms,
        "total_cost_usd":      total_cost,
        "model_used":          model_used,
        "use_real_embeddings": use_real_embeddings,
        # Judge aggregates
        "judge_avg_score":     round(avg_judge, 3),
        "judge_verdict_counts": verdict_counts,
        "judge_input_tokens":  judge_total_in,
        "judge_output_tokens": judge_total_out,
        # LLMUsageSummary sidebar keys
        "llm_input_tokens":    total_in,
        "llm_output_tokens":   total_out,
        "llm_cost_usd":        total_cost,
    }
    return StageResult(payload=payload, verification=make_verification(checks))
