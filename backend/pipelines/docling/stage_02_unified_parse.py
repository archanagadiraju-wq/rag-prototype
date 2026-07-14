"""Docling Unified Parse — Stage 2 of Mode B.

In production: IBM Docling runs format detection + parsing + content intelligence
+ chunking in a single ML-driven pass with bounding-box provenance.

Fallback (Docling not installed): chains Mode A stages 2-5 internally and presents
the result as a unified payload. The pipeline is still fully functional — only the
bounding_box_provenance flag and docling-specific layout metadata are absent.
"""
from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
from pipelines.custom import (
    stage_02_format_detect,
    stage_03_parser,
    stage_04_content_intel,
    stage_05_chunker,
)
import services.job_cache as cache

# Cache the heavy Docling converter at module scope — RapidOCR's PyTorch weights
# load once instead of every job. None until first successful import.
_DOCLING_CONVERTER = None


def _detect_ocr_pages(filepath: Path) -> list[int]:
    """Identify PDF pages with effectively no extractable text.

    Docling 2.x doesn't expose an explicit "this was OCRed" flag per page.
    Heuristic: if pdfplumber returns <30 chars for a page, the page is
    image-only / scanned and Docling's OCR pass is what produced its text.
    Returns [] for non-PDFs or when pdfplumber import/extract fails.
    """
    if filepath.suffix.lower() != ".pdf":
        return []
    try:
        import pdfplumber
        ocr_pages: list[int] = []
        with pdfplumber.open(str(filepath)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                txt = (page.extract_text() or "").strip()
                if len(txt) < 30:
                    ocr_pages.append(i)
        return ocr_pages
    except Exception:
        return []


def _df_to_headers_rows(df) -> tuple[list[str], list[list[str]]]:
    """Convert a Docling-exported pandas DataFrame to plain headers+rows lists."""
    headers = [str(c) for c in df.columns]
    rows: list[list[str]] = []
    for row in df.values.tolist():
        rows.append(["" if v is None else str(v) for v in row])
    return headers, rows


def _markdown_to_blocks(md_text: str) -> list[dict]:
    """Split a markdown document into heading + paragraph blocks for the chunker.

    Emits one block per ATX heading line (with `heading_level` = number of #),
    and one block per blank-line-separated paragraph in between (heading_level=0).
    The chunker uses heading_level > 0 to start new chunks and pack body blocks
    to the target chunk size.
    """
    blocks: list[dict] = []
    para_lines: list[str] = []

    def flush_para() -> None:
        if not para_lines:
            return
        text = "\n".join(para_lines).strip()
        para_lines.clear()
        if text:
            blocks.append({
                "id": f"docling_block_{len(blocks)}",
                "text": text,
                "page": None,
                "heading_level": 0,
            })

    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            rest   = stripped[hashes:].lstrip()
            if 1 <= hashes <= 6 and rest and stripped[hashes:hashes+1] in (" ", "\t"):
                flush_para()
                blocks.append({
                    "id": f"docling_block_{len(blocks)}",
                    "text": rest,
                    "page": None,
                    "heading_level": hashes,
                })
                continue
        if not stripped:
            flush_para()
        else:
            para_lines.append(line)
    flush_para()

    # Guard against an empty doc / heading-less doc: always return at least one block
    if not blocks and md_text.strip():
        blocks.append({
            "id": "docling_block_0",
            "text": md_text.strip(),
            "page": None,
            "heading_level": 0,
        })
    return blocks


def _pick_accelerator():
    """Pick the fastest accelerator for Docling's models on this host.

    Empirical finding: on Apple Silicon (MPS), Docling's TableFormer +
    RapidOCR models are small enough that GPU dispatch overhead dominates
    and MPS actually runs ~25% SLOWER than CPU. CUDA on real NVIDIA GPUs
    is still a clear win.

    Order of preference:
      1. CUDA  — large speedup, NVIDIA GPU
      2. CPU   — fast on Apple Silicon's ARM cores (NEON SIMD)
      3. MPS   — only as a fallback if explicitly requested via env

    Override with DOCLING_ACCELERATOR={cpu,cuda,mps,auto} to force.
    """
    import os
    from docling.datamodel.pipeline_options import AcceleratorOptions, AcceleratorDevice
    override = (os.environ.get("DOCLING_ACCELERATOR") or "").lower().strip()

    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        mps_ok  = torch.backends.mps.is_available() and torch.backends.mps.is_built()
    except Exception:
        cuda_ok = mps_ok = False

    if override == "cuda" and cuda_ok:
        device, label = AcceleratorDevice.CUDA, "CUDA (override)"
    elif override == "mps" and mps_ok:
        device, label = AcceleratorDevice.MPS, "MPS (override — note: ~25% slower than CPU on Apple Silicon)"
    elif override == "cpu":
        device, label = AcceleratorDevice.CPU, "CPU (override)"
    elif cuda_ok:
        device, label = AcceleratorDevice.CUDA, "CUDA"
    else:
        # Default: CPU on macOS/Linux without NVIDIA. Faster than MPS for
        # Docling's small models.
        device, label = AcceleratorDevice.CPU, "CPU"

    log.info("docling accelerator: %s (cuda_avail=%s, mps_avail=%s)", label, cuda_ok, mps_ok)
    return AcceleratorOptions(device=device, num_threads=4)


def _get_docling_converter():
    """Lazily build a DocumentConverter; reuse across jobs. Returns None if import fails."""
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is not None:
        return _DOCLING_CONVERTER
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    pdf_opts = PdfPipelineOptions()
    pdf_opts.do_ocr = True
    pdf_opts.generate_picture_images = True
    pdf_opts.accelerator_options = _pick_accelerator()
    _DOCLING_CONVERTER = DocumentConverter(
        format_options={"pdf": PdfFormatOption(pipeline_options=pdf_opts)}
    )
    return _DOCLING_CONVERTER


def _docling_parse_sync(filepath: Path) -> dict:
    """Run Docling synchronously and return a parser_payload dict.

    Runs in a worker thread so it doesn't block the FastAPI event loop.
    """
    import base64, io as _io
    converter = _get_docling_converter()
    result = converter.convert(str(filepath))
    doc = result.document

    md_text = doc.export_to_markdown()
    text_blocks = _markdown_to_blocks(md_text)

    raw_tables = []
    try:
        for tbl in doc.tables:
            md = tbl.export_to_markdown() if hasattr(tbl, "export_to_markdown") else ""
            headers: list[str] = []
            rows: list[list[str]] = []
            as_json: list[dict] = []
            # Populate structured cells via Docling's DataFrame export — this
            # is what unlocks SQL storage downstream (sql_store.create_tables
            # skips tables with empty headers/rows).
            try:
                if hasattr(tbl, "export_to_dataframe"):
                    df = tbl.export_to_dataframe()
                    if df is not None and not df.empty:
                        headers, rows = _df_to_headers_rows(df)
                        as_json = [dict(zip(headers, row)) for row in rows]
            except Exception:
                pass
            raw_tables.append({
                "id": f"tbl_{len(raw_tables)}",
                "as_markdown": md,
                "headers": headers,
                "rows": rows,
                "as_json": as_json,
            })
    except Exception:
        pass

    images = []
    try:
        for i, pic in enumerate(doc.pictures):
            pil_img = pic.get_image(doc)
            if not pil_img:
                continue
            prov = pic.prov[0] if pic.prov else None
            page_no = prov.page_no if prov else None
            buf = _io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            images.append({
                "id":        f"docling_pic_{i}",
                "page":      page_no,
                "width":     pil_img.width,
                "height":    pil_img.height,
                "format":    "png",
                "bytes_b64": b64,
                "needs_ocr": False,
            })
    except Exception:
        pass

    # Docling 2.x: num_pages is a method, not an attribute
    _np = getattr(doc, "num_pages", None)
    page_count = _np() if callable(_np) else _np

    ocr_pages = _detect_ocr_pages(filepath)

    return {
        "parser_used": "docling-2.x",
        "page_count": page_count,
        "ocr_used": len(ocr_pages) > 0,
        "ocr_pages": ocr_pages,
        "word_count": len(md_text.split()),
        "table_count": len(raw_tables),
        "image_count": len(images),
        "text_blocks": text_blocks,
        "tables": raw_tables,
        "images": images,
        "raw_text_preview": md_text[:400],
    }


async def run(filepath: Path, job_id: str) -> StageResult:
    t0 = time.perf_counter()
    using_docling = False
    parser_payload: dict = {}
    intel_payload: dict = {}
    chunks: list[dict] = []
    mime = ""

    # ── Attempt real Docling — runs in a worker thread so the event loop
    #    keeps shipping WebSocket events while PyTorch/OCR grinds. ───────────
    # Hard cap at 30 min: Docling sometimes wedges on pathological pages (torch
    # dispatch deadlocks, RapidOCR infinite loops). 30 min covers most legitimate
    # 50–100 page scanned PDFs on CPU (~20s/page). If Docling AND the Mode A
    # fallback both produce empty text, we chain to vision-OCR via Claude as a
    # last resort — much better than failing silently.
    try:
        parser_payload = await asyncio.wait_for(
            asyncio.to_thread(_docling_parse_sync, filepath),
            timeout=1800.0,
        )
        using_docling = True
    except asyncio.TimeoutError:
        log.warning("docling parse exceeded 30 min — falling back to Mode A parser")
        r2 = await stage_02_format_detect.run(filepath)
        mime = (r2.payload or {}).get("true_mime", "")
        r3 = await stage_03_parser.run(filepath, mime)
        parser_payload = r3.payload or {}
        parser_payload["docling_timeout"] = True
    except Exception as exc:
        log.warning(f"docling parse raised {type(exc).__name__}: {exc} — falling back to Mode A")
        # ── Fallback: chain Mode A stages 2-5 ────────────────────────────────
        r2 = await stage_02_format_detect.run(filepath)
        mime = (r2.payload or {}).get("true_mime", "")
        r3 = await stage_03_parser.run(filepath, mime)
        parser_payload = r3.payload or {}
        parser_payload["docling_error"] = f"{type(exc).__name__}: {exc}"

    # ── Last-resort: vision OCR via Claude ────────────────────────────────
    # If both Docling and the Mode A pdfplumber fallback returned essentially
    # nothing (CID-encoded PDFs, fully-scanned scans where pdfplumber sees only
    # image data), render every page to a PNG and have Claude transcribe it.
    # Slow per-page but parallelisable; ~$0.01-0.02/page for Haiku.
    if filepath.suffix.lower() == ".pdf" and not using_docling:
        word_count = parser_payload.get("word_count", 0)
        if word_count < 100:
            try:
                from pipelines.custom.stage_03_parsers import vision_pdf
                log.info("triggering vision-OCR rescue (mode A fallback returned %d words)", word_count)
                vision_payload = await vision_pdf.vision_ocr_full_pdf(filepath)
                if vision_payload.get("word_count", 0) > word_count:
                    parser_payload = {**parser_payload, **vision_payload}
                    parser_payload["used_vision_ocr_rescue"] = True
            except Exception as exc:
                log.warning(f"vision-OCR rescue failed: {type(exc).__name__}: {exc}")

    # Content Intelligence + Chunking (same for both paths)
    r4 = await stage_04_content_intel.run(parser_payload, mime)
    intel_payload = r4.payload or {}

    r5 = await stage_05_chunker.run(parser_payload)
    chunk_info = r5.payload or {}
    chunks = chunk_info.get("chunks", [])

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Store in cache for downstream stages (d_ prefix avoids collisions in compare mode)
    cache.put(job_id, "d_chunks", chunks)
    cache.put(job_id, "d_parser_payload", parser_payload)
    cache.put(job_id, "d_intel_payload", intel_payload)

    flags = intel_payload.get("content_flags", [])
    if using_docling:
        flags = list(flags) + ["bounding_box_provenance"]
    if parser_payload.get("ocr_used"):
        flags = list(flags) + ["used_ocr"]

    payload = {
        "parser": "docling-2.x" if using_docling
                  else f"mode-a-fallback ({parser_payload.get('parser_used', 'unknown')})",
        "page_count": parser_payload.get("page_count"),
        "word_count": parser_payload.get("word_count", 0),
        "table_count": parser_payload.get("table_count", 0),
        "image_count": parser_payload.get("image_count", 0),
        "doc_type": intel_payload.get("doc_type", "unknown"),
        "doc_type_confidence": intel_payload.get("doc_type_confidence", 0.0),
        "language": intel_payload.get("language", "en"),
        "domain": intel_payload.get("domain", "unknown"),
        "strategy": chunk_info.get("strategy", "heading_aware"),
        "chunk_count": len(chunks),
        "avg_chunk_size_tokens": chunk_info.get("avg_chunk_size_tokens", 0),
        "min_chunk_tokens": chunk_info.get("min_chunk_tokens", 0),
        "max_chunk_tokens": chunk_info.get("max_chunk_tokens", 0),
        "overlap_tokens": chunk_info.get("overlap_tokens", 0),
        "total_chunk_tokens": chunk_info.get("total_chunk_tokens", 0),
        "doc_tokens_est": chunk_info.get("doc_tokens_est", 0),
        "size_distribution": chunk_info.get("size_distribution", []),
        "chunks": chunks,
        "coverage_pct": chunk_info.get("coverage_pct", 0),
        "summary": intel_payload.get("summary", ""),
        "content_flags": flags,
        "entities": intel_payload.get("entities", []),
        "key_dates": intel_payload.get("key_dates", []),
        "note": ("Docling 2.x unified parse" if using_docling
                 else "Mode A fallback — install docling for real Mode B"),
        "elapsed_ms": round(elapsed_ms, 1),
        "ocr_used": parser_payload.get("ocr_used", False),
        "ocr_pages_count": len(parser_payload.get("ocr_pages") or []),
        "llm_input_tokens": intel_payload.get("llm_input_tokens", 0),
        "llm_output_tokens": intel_payload.get("llm_output_tokens", 0),
        "llm_cost_usd": intel_payload.get("llm_cost_usd", 0.0),
    }

    checks = [
        make_check("parse_completed", len(chunks) > 0,
                   f"{len(chunks)} chunks from unified parse"),
        make_check("docling_used", using_docling,
                   "Docling 2.x" if using_docling
                   else "Mode A fallback (pip install docling for real Mode B)",
                   severity="warn" if not using_docling else "info"),
        make_check("content_classified", intel_payload.get("doc_type", "unknown") != "unknown",
                   f"{intel_payload.get('doc_type')} / {intel_payload.get('domain')}"),
    ]
    return StageResult(payload=payload, verification=make_verification(checks))
