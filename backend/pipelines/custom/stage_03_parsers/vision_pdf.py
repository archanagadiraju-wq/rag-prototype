"""Vision-OCR PDF parser — last resort for scanned / CID-broken PDFs.

When Docling times out AND pdfplumber/pymupdf can't extract usable text
(scanned bitmaps, custom-font PDFs without ToUnicode CMaps, etc.), render
every page to a PNG via PyMuPDF and have Claude vision transcribe it.

Cost: ~$0.005–0.02 per page (Haiku 4.5 vision in+out). For a 48-page doc,
that's ~$0.25–1.00. Slower per call than RapidOCR but parallelisable, and
the English text quality is dramatically better than RapidOCR's Chinese-
optimised models on a Latin-alphabet document.

Returns a `parser_payload`-shaped dict so downstream chunker / embedding
stages can consume it without any special-casing.
"""
from __future__ import annotations
import asyncio
import base64
import logging
import time
from pathlib import Path

import anthropic

from config import settings
from pipelines.custom.stage_06_multimodal import _ocr_page_structured

log = logging.getLogger(__name__)

# Cap concurrent vision calls — Anthropic's per-org RPM is generous but each
# call sends a ~150 KB image, so blasting 50 at once burns the rate limit fast.
_MAX_CONCURRENT = 4
# DPI for page rasterisation. 150 is the sweet spot — lower hurts OCR quality
# on small text, higher inflates image bytes (and cost) without meaningful gain.
_PAGE_DPI = 150
# Defensive ceiling. 200 pages × ~$0.015 ≈ $3 worst case; beyond that the user
# should be cancelling and reconsidering their ingest strategy.
_MAX_PAGES = 200


def _render_page_png_b64(pdf_path: Path, page_idx: int, dpi: int) -> str:
    """Render one PDF page → base64-encoded PNG. CPU-bound; call via to_thread."""
    import fitz  # PyMuPDF
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_idx]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _count_pages(pdf_path: Path) -> int:
    import fitz
    doc = fitz.open(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


async def vision_ocr_full_pdf(filepath: Path) -> dict:
    """OCR an entire PDF via Claude vision.

    Returns a `parser_payload`-compatible dict:
      {parser_used, page_count, ocr_used, ocr_pages, ocr_pages_count,
       word_count, text_blocks, tables, raw_text_preview,
       vision_input_tokens, vision_output_tokens, vision_elapsed_s}
    """
    if not (settings.anthropic_api_key and len(settings.anthropic_api_key) > 20):
        return {
            "parser_used": "vision_ocr",
            "page_count": 0, "word_count": 0,
            "text_blocks": [], "tables": [], "images": [],
            "ocr_used": True, "ocr_pages": [], "ocr_pages_count": 0,
            "raw_text_preview": "",
            "error": "anthropic_api_key not configured",
        }

    page_count = _count_pages(filepath)
    if page_count == 0:
        return {
            "parser_used": "vision_ocr",
            "page_count": 0, "word_count": 0,
            "text_blocks": [], "tables": [], "images": [],
            "ocr_used": True, "ocr_pages": [], "ocr_pages_count": 0,
            "raw_text_preview": "",
        }

    pages_to_process = min(page_count, _MAX_PAGES)
    if pages_to_process < page_count:
        log.warning(
            "vision-OCR truncating %d-page doc to first %d pages (cost ceiling)",
            page_count, pages_to_process,
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    t0 = time.perf_counter()

    # Render all pages in parallel threads — fast (~50ms/page on modern hardware).
    log.info("vision-OCR rendering %d pages at %d DPI", pages_to_process, _PAGE_DPI)
    rendered = await asyncio.gather(*[
        asyncio.to_thread(_render_page_png_b64, filepath, i, _PAGE_DPI)
        for i in range(pages_to_process)
    ])

    # OCR each page (bounded concurrency).
    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async def _ocr_one(idx: int, b64: str):
        async with sem:
            img_stub = {"id": f"page_{idx + 1}", "format": "png", "bytes_b64": b64}
            try:
                prose, tables, in_tok, out_tok = await _ocr_page_structured(img_stub, client)
                return idx, prose, tables, in_tok, out_tok, None
            except Exception as exc:
                return idx, "", [], 0, 0, f"{type(exc).__name__}: {exc}"

    log.info("vision-OCR calling Claude on %d pages (concurrency=%d)",
             pages_to_process, _MAX_CONCURRENT)
    results = await asyncio.gather(*[_ocr_one(i, b64) for i, b64 in enumerate(rendered)])

    # Aggregate.
    text_blocks: list[dict] = []
    tables: list[dict] = []
    total_in = total_out = 0
    full_text_parts: list[str] = []
    failed_pages: list[int] = []

    for idx, prose, page_tables, in_tok, out_tok, err in results:
        page_no = idx + 1
        total_in += in_tok
        total_out += out_tok
        if err:
            failed_pages.append(page_no)
            continue
        if prose:
            text_blocks.append({
                "id": f"vocr_p{page_no}",
                "text": prose,
                "page": page_no,
                "heading_level": 0,
            })
            full_text_parts.append(prose)
        for j, t in enumerate(page_tables):
            tables.append({
                "id": f"vocr_p{page_no}_t{j + 1}",
                "page": page_no,
                "description": t.get("description", ""),
                "headers": t.get("headers", []),
                "rows": t.get("rows", []),
                "as_json": [dict(zip(t.get("headers", []), row)) for row in t.get("rows", [])],
            })

    joined = "\n\n".join(full_text_parts)
    elapsed_s = time.perf_counter() - t0
    log.info(
        "vision-OCR done: %d pages, %d words, %d tables, %d failed, %.1fs, %d in / %d out tokens",
        pages_to_process, len(joined.split()), len(tables), len(failed_pages),
        elapsed_s, total_in, total_out,
    )

    return {
        "parser_used": "vision_ocr",
        "page_count": page_count,
        "ocr_used": True,
        "ocr_pages": list(range(1, pages_to_process + 1)),
        "ocr_pages_count": pages_to_process,
        "word_count": len(joined.split()),
        "text_blocks": text_blocks,
        "tables": tables,
        "images": [],
        "raw_text_preview": joined[:400],
        "vision_input_tokens": total_in,
        "vision_output_tokens": total_out,
        "vision_elapsed_s": round(elapsed_s, 1),
        "vision_failed_pages": failed_pages,
        "vision_pages_processed": pages_to_process,
        "vision_pages_truncated": page_count - pages_to_process,
    }
