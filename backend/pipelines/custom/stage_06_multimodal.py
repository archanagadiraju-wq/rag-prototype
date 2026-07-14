"""Stage 6 — Multi-Modal Enrichment (Mode A).

For each table from stage 3: calls Claude haiku to add a 1-sentence description
that is prepended to the markdown — improving retrieval quality in stage 7.

For images with base64 data: calls Claude haiku vision to generate a caption.

All tables are batched into a single Claude call to keep latency low.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re

import anthropic

from config import settings
from models.events import MultiModalPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
from services.api_retry import with_retry_sync

log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
# Pricing: $0.80/M input, $4.00/M output
_COST_IN  = 0.80  / 1_000_000
_COST_OUT = 4.00  / 1_000_000

_MAX_TABLE_CHARS = 1500   # chars of markdown sent to Claude per table
_MAX_TABLES_BATCH = 10    # max tables in one Claude call
_MAX_TABLE_ROWS  = 25     # rows kept per table for as_markdown / as_json

# Bounded concurrency for per-image Claude vision calls. 4 keeps wall-clock
# tolerable on long docs without hitting Anthropic rate limits.
_IMAGE_CONCURRENCY = 4


def _to_markdown(headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return ""
    sep = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows[:_MAX_TABLE_ROWS]:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        lines.append("| " + " | ".join(str(c) for c in padded[: len(headers)]) + " |")
    return "\n".join(lines)


def _truncate_md(md: str, max_chars: int = _MAX_TABLE_CHARS) -> str:
    if len(md) <= max_chars:
        return md
    return md[:max_chars] + "\n…(truncated)"


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    return re.sub(r"\n?```$", "", text).strip()


async def _describe_tables(tables: list[dict], client: anthropic.Anthropic) -> tuple[list[str], int, int]:
    """Returns (descriptions, input_tokens, output_tokens)."""
    if not tables:
        return [], 0, 0

    batch = tables[:_MAX_TABLES_BATCH]
    parts = []
    for i, tbl in enumerate(batch):
        md = tbl.get("as_markdown") or ""
        if not md and tbl.get("headers"):
            # Reconstruct minimal markdown if as_markdown is empty
            header_row = " | ".join(str(h) for h in tbl["headers"])
            sep = " | ".join("---" for _ in tbl["headers"])
            rows = "\n".join(
                " | ".join(str(c) for c in row)
                for row in (tbl.get("rows") or [])[:5]
            )
            md = f"| {header_row} |\n| {sep} |\n{rows}"
        parts.append(f"TABLE {i+1}:\n{_truncate_md(md)}")

    prompt = (
        "For each table below, write exactly one concise sentence describing what "
        "the table contains and its purpose. Return a JSON array of strings, one per table, "
        "in the same order.\n\n"
        + "\n\n".join(parts)
        + "\n\nReturn ONLY a JSON array of strings. No markdown, no explanation."
    )

    response = await asyncio.to_thread(
        with_retry_sync,
        client.messages.create,
        model=_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        label="describe_tables",
    )
    try:
        descriptions = json.loads(_strip_fences(response.content[0].text))
        if not isinstance(descriptions, list):
            descriptions = [str(descriptions)]
    except Exception:
        descriptions = ["Table data"] * len(batch)

    # Pad if Claude returned fewer items than tables
    while len(descriptions) < len(batch):
        descriptions.append("Table data")

    return descriptions, response.usage.input_tokens, response.usage.output_tokens


def _media_type(fmt: str) -> str:
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(fmt.lower(), "image/png")


async def _caption_image(img: dict, client: anthropic.Anthropic) -> tuple[str, int, int]:
    """Returns (caption, input_tokens, output_tokens)."""
    b64 = img.get("bytes_b64", "")
    response = await asyncio.to_thread(
        with_retry_sync,
        client.messages.create,
        model=_MODEL,
        max_tokens=128,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": _media_type(img.get("format", "png")), "data": b64}},
                {"type": "text", "text": "Describe this image in one sentence for a document retrieval system."},
            ],
        }],
        label=f"caption_image[{img.get('id', '?')}]",
    )
    caption = response.content[0].text.strip()
    return caption, response.usage.input_tokens, response.usage.output_tokens


_STRUCTURED_OCR_PROMPT = """You are extracting content from a scanned document page.
Return ONLY valid JSON matching this exact schema:

{
  "prose_text": "all non-table prose with paragraph breaks. Empty string if none.",
  "tables": [
    {
      "description": "one sentence describing what this table contains and its purpose",
      "headers": ["column1", "column2", ...],
      "rows": [["a", "b", ...], ["c", "d", ...], ...]
    }
  ]
}

Rules:
- Preserve numbers, currency, dates, and identifiers EXACTLY as shown — do not round or rephrase.
- Distinguish tables from prose by visual structure (aligned columns, row separators, borders).
- If no tables on this page, return "tables": [].
- If the page is blank or illegible, return "prose_text": "" and "tables": [].
- Do not invent any content not visible in the image.
- Output ONLY the JSON — no markdown fences, no commentary."""


async def _ocr_page_structured(
    img: dict, client: anthropic.Anthropic
) -> tuple[str, list[dict], int, int]:
    """Vision OCR that also recovers table structure.

    Returns (prose_text, tables_list, input_tokens, output_tokens).
    Each table dict: {description, headers, rows}.
    """
    b64 = img.get("bytes_b64", "")
    response = await asyncio.to_thread(
        with_retry_sync,
        client.messages.create,
        model=_MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": _media_type(img.get("format", "png")), "data": b64}},
                {"type": "text", "text": _STRUCTURED_OCR_PROMPT},
            ],
        }],
        label=f"ocr_page[{img.get('id', '?')}]",
    )
    raw = _strip_fences(response.content[0].text)

    prose: str = ""
    tables: list[dict] = []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            prose = str(data.get("prose_text", "")).strip()
            raw_tables = data.get("tables", [])
            if isinstance(raw_tables, list):
                for tbl in raw_tables:
                    if not isinstance(tbl, dict):
                        continue
                    headers = [str(h) for h in (tbl.get("headers") or [])]
                    rows = [
                        [str(c) for c in (row or [])]
                        for row in (tbl.get("rows") or [])
                        if isinstance(row, list)
                    ]
                    if not headers or not rows:
                        continue
                    tables.append({
                        "description": str(tbl.get("description", "")).strip(),
                        "headers": headers,
                        "rows": rows,
                    })
    except Exception:
        # Model returned non-JSON — treat the whole response as prose
        prose = raw

    return prose, tables, response.usage.input_tokens, response.usage.output_tokens


# ── Public sub-stage APIs ─────────────────────────────────────────────────────
# Two targeted functions that callers (the agent's tools, in particular) can
# invoke independently when they only care about one concern. The full run()
# below still composes both for the Mode A/B runners.


async def enrich_tables(parser_payload: dict) -> dict:
    """Describe structured tables only — Claude haiku batched description per table.

    Returns a dict with `tables_enriched` (the input tables with `description`
    and prefixed-markdown added) plus token + cost accounting. Pure side-effect-
    free; caller decides what to do with the result.
    """
    tables = parser_payload.get("tables") or []
    if not tables:
        return {
            "tables_enriched": [], "tables_described": 0,
            "llm_input_tokens": 0, "llm_output_tokens": 0, "llm_cost_usd": 0.0,
        }

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    descriptions, in_tok, out_tok = await _describe_tables(tables, client)

    enriched: list[dict] = []
    for tbl, desc in zip(tables, descriptions):
        e = dict(tbl)
        e["description"] = desc
        existing_md = tbl.get("as_markdown") or ""
        e["as_markdown"] = f"> {desc}\n\n{existing_md}".strip()
        enriched.append(e)

    return {
        "tables_enriched":   enriched,
        "tables_described":  len(descriptions),
        "llm_input_tokens":  in_tok,
        "llm_output_tokens": out_tok,
        "llm_cost_usd":      round(in_tok * _COST_IN + out_tok * _COST_OUT, 6),
    }


async def process_images(parser_payload: dict) -> dict:
    """Image captioning + structured OCR of scanned pages.

    Distinct from enrich_tables — this function ONLY handles `parser_payload.images`.
    Returns captions, ocr_chunks (text from scanned pages), and ocr_tables
    (tables extracted from scanned pages). Caller is responsible for routing
    these into the chunks / extracted_tables caches.
    """
    all_images = [img for img in (parser_payload.get("images") or []) if img.get("bytes_b64")]
    regular_images = [img for img in all_images if not img.get("needs_ocr")]
    scanned_images = [img for img in all_images if img.get("needs_ocr")]

    if not all_images:
        return {
            "captions": [], "captions_failed": 0,
            "ocr_chunks": [], "ocr_tables": [],
            "ocr_pages_count": 0, "ocr_pages_failed": 0,
            "llm_input_tokens": 0, "llm_output_tokens": 0, "llm_cost_usd": 0.0,
        }

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    total_in = total_out = 0
    sem = asyncio.Semaphore(_IMAGE_CONCURRENCY)

    # ── Embedded-image captioning ────────────────────────────────────────
    captions: list[dict] = []
    failed_captions = 0

    async def _caption_task(img):
        async with sem:
            try:
                return await _caption_image(img, client)
            except Exception as exc:
                log.warning("caption_image failed for %s after retries: %s", img.get("id"), exc)
                return None

    caption_results = await asyncio.gather(*[_caption_task(img) for img in regular_images])
    for img, result in zip(regular_images, caption_results):
        if result is None:
            failed_captions += 1
            continue
        caption, tin, tout = result
        total_in += tin; total_out += tout
        captions.append({"id": img.get("id"), "caption": caption,
                         "page": img.get("page"), "width": img.get("width"), "height": img.get("height")})

    # ── Structured OCR of scanned pages ──────────────────────────────────
    ocr_chunks: list[dict] = []
    ocr_tables: list[dict] = []
    failed_ocr = 0

    async def _ocr_task(img):
        async with sem:
            try:
                return await _ocr_page_structured(img, client)
            except Exception as exc:
                log.warning("ocr_page failed for %s after retries: %s", img.get("id"), exc)
                return None

    ocr_results = await asyncio.gather(*[_ocr_task(img) for img in scanned_images])
    for img, result in zip(scanned_images, ocr_results):
        if result is None:
            failed_ocr += 1
            continue
        prose, page_tables, tin, tout = result
        total_in += tin; total_out += tout
        pg = img.get("page")

        if prose:
            ocr_chunks.append({
                "id":           f"ocr_p{pg}",
                "text":         prose,
                "token_count":  max(1, int(len(prose.split()) * 1.35)),
                "page":         pg,
                "heading_path": f"Scanned Page {pg}",
                "metadata":     {"chunk_type": "ocr_page", "page": pg},
            })

        for j, tbl in enumerate(page_tables):
            headers = tbl["headers"]; rows = tbl["rows"]
            ocr_tables.append({
                "id":          f"ocr_p{pg}_t{j + 1}",
                "page":        pg,
                "headers":     headers,
                "rows":        rows,
                "as_markdown": _to_markdown(headers, rows),
                "as_json":     [dict(zip(headers, row)) for row in rows[:25]],
                "description": tbl.get("description", ""),
                "_from_ocr":   True,
            })

    return {
        "captions":          captions,
        "captions_failed":   failed_captions,
        "ocr_chunks":        ocr_chunks,
        "ocr_tables":        ocr_tables,
        "ocr_pages_count":   len(scanned_images),
        "ocr_pages_failed":  failed_ocr,
        "llm_input_tokens":  total_in,
        "llm_output_tokens": total_out,
        "llm_cost_usd":      round(total_in * _COST_IN + total_out * _COST_OUT, 6),
    }


async def run(parser_payload: dict) -> StageResult:
    """Full multi-modal enrichment: tables + images + scanned-page OCR.

    Composed from `enrich_tables` and `process_images` so the Mode A/B runners
    can do everything in one call while the agent can invoke them individually.
    """
    # 1. Describe tables (parser-extracted structured tables)
    tables_result = await enrich_tables(parser_payload)
    tables_enriched: list[dict] = tables_result["tables_enriched"]

    # 2. Process images (captions + OCR of scanned pages)
    images_result = await process_images(parser_payload)
    captions    = images_result["captions"]
    ocr_chunks  = images_result["ocr_chunks"]
    ocr_tables  = images_result["ocr_tables"]

    # OCR'd tables join the enriched-table list so they flow into SQL store +
    # summary chunks downstream. Their description came from the OCR call,
    # so we skip the table-description Claude call.
    for tbl in ocr_tables:
        enriched = dict(tbl)
        existing_md = tbl.get("as_markdown") or ""
        desc = tbl.get("description") or ""
        enriched["as_markdown"] = f"> {desc}\n\n{existing_md}".strip() if desc else existing_md
        tables_enriched.append(enriched)

    total_in  = tables_result["llm_input_tokens"]  + images_result["llm_input_tokens"]
    total_out = tables_result["llm_output_tokens"] + images_result["llm_output_tokens"]
    failed_captions = images_result["captions_failed"]
    failed_ocr      = images_result["ocr_pages_failed"]
    scanned_images_count = images_result["ocr_pages_count"]
    cost = round((total_in * _COST_IN) + (total_out * _COST_OUT), 6)

    tables_in_input = parser_payload.get("tables") or []
    images_in_input = [img for img in (parser_payload.get("images") or []) if img.get("bytes_b64")]
    has_tables = len(tables_in_input) > 0
    has_images = len(images_in_input) > 0

    payload = MultiModalPayload(
        images_captioned=len(captions),
        tables_serialised=len(tables_enriched),
        tables_enriched=tables_enriched,
        captions=captions,
        model_used=_MODEL if (has_tables or has_images) else "",
        llm_input_tokens=total_in,
        llm_output_tokens=total_out,
        llm_cost_usd=cost,
    )
    result = StageResult(payload=payload.model_dump(), verification=None)
    result.payload["ocr_chunks"] = ocr_chunks
    result.payload["ocr_pages_count"] = scanned_images_count
    result.payload["ocr_tables"] = ocr_tables   # for runner → extracted_tables cache → SQL store
    result.payload["ocr_tables_count"] = len(ocr_tables)
    result.payload["captions_failed"] = failed_captions
    result.payload["ocr_pages_failed"] = failed_ocr

    checks = [
        make_check(
            "tables_processed",
            not has_tables or len(tables_enriched) >= len(tables_in_input),
            f"{len(tables_enriched)} table{'s' if len(tables_enriched) != 1 else ''} enriched"
            if has_tables else "no tables in document",
        ),
        make_check(
            "images_processed",
            not has_images or (len(captions) + len(ocr_chunks)) == len(images_in_input),
            (f"{len(captions)} image(s) captioned, {len(ocr_chunks)} page(s) OCR'd")
            if has_images else "no images in document",
            severity="warn",
        ),
        make_check(
            "llm_responded",
            not (has_tables or has_images) or total_in > 0,
            f"{total_in:,} tokens in / {total_out:,} out"
            if total_in else "skipped — no tables or images",
        ),
    ]

    result.verification = make_verification(checks)
    return result
