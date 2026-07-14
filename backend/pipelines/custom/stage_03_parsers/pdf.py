"""PDF parser — pdfplumber for text/tables, PyMuPDF for image extraction.

Pages get re-routed to Claude vision OCR when:
  • pdfplumber returns no text (scanned / image-only page)
  • OR pdfplumber returns text dominated by (cid:N) artifacts — a sign the PDF
    uses custom fonts without a ToUnicode CMap, so the glyph→Unicode mapping is
    broken. Common in academic, pharma, and legal PDFs.

For those pages the full page is rendered as a PNG at 150 DPI and tagged
needs_ocr=True. Stage 6 (Multi-Modal) then runs Claude vision on them.

Embedded images smaller than _MIN_IMAGE_PX² are skipped (logos, bullets, etc.).
Total images extracted is capped at _MAX_IMAGES to stay within Claude's 20-image limit.
"""
from __future__ import annotations
import base64
import re
from pathlib import Path

from models.events import ExtractedTable, TextBlock
from pipelines.base import StageResult

_MAX_TABLE_ROWS    = 25
_MIN_IMAGE_PX      = 5_000   # minimum pixel area (e.g. 70×70) — skip decorative images
_MAX_OCR_PAGES     = 40      # cap on full-page OCR renders (each is a separate Claude call)
_MAX_EMBEDDED_IMGS = 10      # cap on decorative embedded images we caption
_RENDER_DPI        = 150     # DPI for full-page renders of scanned pages

_CID_PATTERN       = re.compile(r"\(cid:\d+\)")
_LONG_RUN_PATTERN  = re.compile(r"(.)\1{4,}")     # any char repeated 5+ times in a row
_CID_RATIO_CUTOFF  = 0.20    # >20% of chars inside (cid:N) markers → broken
_CID_MIN_CHARS     = 30
_GIBBERISH_MIN_CHARS = 80    # need enough text to compute stable stats


def _is_cid_garbage(text: str) -> tuple[bool, int, float]:
    """Detect text dominated by (cid:N) artifacts (one specific kind of broken font)."""
    if len(text) < _CID_MIN_CHARS:
        return False, 0, 0.0
    cid_matches = _CID_PATTERN.findall(text)
    cid_chars = sum(len(m) for m in cid_matches)
    ratio = cid_chars / len(text)
    return ratio > _CID_RATIO_CUTOFF, len(cid_matches), ratio


def _is_gibberish(text: str) -> tuple[bool, dict]:
    """Detect text where the PDF's font subset maps glyphs to meaningless ASCII.

    Different from the (cid:N) case — the characters look 'normal' but spell nothing.
    Three independent signals; we flag if any two fire:

      1. Long character runs (KKKKKKKKKK) — real text rarely has 5+ identical chars
      2. Vowel deficit             — English letters are ~38% vowels; <15% is suspect
      3. Symbol/digit-heavy        — broken fonts often map to !"#$%&* and digits

    Returns (is_garbage, metrics).
    """
    if len(text) < _GIBBERISH_MIN_CHARS:
        return False, {}

    # 1. Long-run density: runs of 5+ same char per 100 chars of text
    long_runs = len(_LONG_RUN_PATTERN.findall(text))
    long_run_density = long_runs / (len(text) / 100)

    # 2. Vowel ratio over alphabetic chars
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return True, {"reason": "no_letters"}
    vowels = sum(1 for c in letters if c in "aeiou")
    vowel_ratio = vowels / len(letters)

    # 3. Symbol/digit ratio over non-whitespace chars
    non_space = [c for c in text if not c.isspace()]
    sym_or_digit = sum(1 for c in non_space if not c.isalpha())
    sym_ratio = sym_or_digit / max(1, len(non_space))

    metrics = {
        "long_run_density": round(long_run_density, 2),
        "vowel_ratio":      round(vowel_ratio, 3),
        "sym_ratio":        round(sym_ratio, 3),
    }

    # Score each signal as "suspicious" — flag if 2 or more fire
    signals = [
        long_run_density > 1.5,   # >1.5 long runs per 100 chars
        vowel_ratio      < 0.15,  # <15% vowels (English ~38%)
        sym_ratio        > 0.45,  # >45% non-letter chars
    ]
    return sum(signals) >= 2, metrics


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


def _extract_images(fitz_doc, ocr_pages: list[int]) -> list[dict]:
    """Extract images for Stage 6. Two separate caps:

      • OCR page renders (needs_ocr=True) — capped at _MAX_OCR_PAGES. These are
        the important ones; without them, content from broken-font/scanned pages
        is unrecoverable. Prioritised first.
      • Decorative embedded images (needs_ocr=False) — capped at _MAX_EMBEDDED_IMGS.
        Used for captioning only; nice-to-have. Skipped on pages already routed
        to OCR (the full-page render covers them).
    """
    images: list[dict] = []
    ocr_set = set(ocr_pages)

    # 1. OCR page renders FIRST — these are the load-bearing ones.
    for pg in ocr_pages[:_MAX_OCR_PAGES]:
        page = fitz_doc[pg - 1]
        mat = page.get_pixmap(dpi=_RENDER_DPI)
        b64 = base64.b64encode(mat.tobytes("png")).decode()
        images.append({
            "id":        f"p{pg}_scan",
            "page":      pg,
            "width":     mat.width,
            "height":    mat.height,
            "format":    "png",
            "bytes_b64": b64,
            "needs_ocr": True,
        })

    # 2. Decorative embedded images on pages whose text layer worked.
    embedded_count = 0
    for page_num in range(len(fitz_doc)):
        if embedded_count >= _MAX_EMBEDDED_IMGS:
            break
        if (page_num + 1) in ocr_set:
            continue   # full-page render already covers this page
        page = fitz_doc[page_num]
        for img_info in page.get_images(full=False):
            if embedded_count >= _MAX_EMBEDDED_IMGS:
                break
            xref = img_info[0]
            try:
                img_data = fitz_doc.extract_image(xref)
            except Exception:
                continue
            w, h = img_data.get("width", 0), img_data.get("height", 0)
            if w * h < _MIN_IMAGE_PX:
                continue
            b64 = base64.b64encode(img_data["image"]).decode()
            images.append({
                "id":        f"p{page_num + 1}_img{embedded_count + 1}",
                "page":      page_num + 1,
                "width":     w,
                "height":    h,
                "format":    img_data.get("ext", "png"),
                "bytes_b64": b64,
                "needs_ocr": False,
            })
            embedded_count += 1

    return images


async def parse(filepath: Path, mime: str, result_fn) -> StageResult:
    import pdfplumber
    import fitz  # PyMuPDF

    text_blocks: list[TextBlock] = []
    tables: list[ExtractedTable] = []
    scanned_pages: list[int] = []
    cid_garbled_pages: list[int] = []
    gibberish_pages: list[int] = []
    word_count = 0

    with pdfplumber.open(str(filepath)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            pg = page.page_number

            # Decide first whether the page's text layer is usable — extract
            # text BEFORE tables so we can skip table extraction on broken pages.
            # pdfplumber happily "finds" dozens of fake tables in CID-glyph clusters,
            # which then poison Stages 4–6 with garbage.
            text = (page.extract_text(x_tolerance=3, y_tolerance=3) or "").strip()

            if not text:
                scanned_pages.append(pg)
                continue

            cid_bad, _cid_n, _cid_ratio = _is_cid_garbage(text)
            if cid_bad:
                cid_garbled_pages.append(pg)
                continue

            gib_bad, _metrics = _is_gibberish(text)
            if gib_bad:
                # Broken font subset — glyphs map to junk ASCII. OCR will recover it.
                gibberish_pages.append(pg)
                continue

            # Page text layer is trustworthy — extract tables and text normally.
            for j, tbl in enumerate(page.extract_tables() or []):
                if not tbl:
                    continue
                headers = [str(c or "").strip() for c in tbl[0]]
                rows = [[str(c or "").strip() for c in row] for row in tbl[1:]]
                # Defensive: also skip individual tables whose cells are CID garbage
                # (happens when body text is OK but a table uses a different font).
                joined = " ".join(headers + [c for r in rows for c in r])
                tbl_bad, _, _ = _is_cid_garbage(joined)
                if tbl_bad:
                    continue
                tables.append(ExtractedTable(
                    id=f"p{pg}_t{j + 1}",
                    page=pg,
                    headers=headers,
                    rows=rows,
                    as_markdown=_to_markdown(headers, rows),
                    as_json=[dict(zip(headers, row)) for row in rows[:_MAX_TABLE_ROWS]],
                ))

            # Strip any residual stray (cid:N) tokens before keeping the text
            clean_text = _CID_PATTERN.sub("", text).strip()
            if clean_text:
                word_count += len(clean_text.split())
                text_blocks.append(TextBlock(id=f"p{pg}", text=clean_text[:2000], page=pg))

    # All pages that need vision OCR: scanned + CID-garbled + gibberish
    pages_for_ocr = sorted(set(scanned_pages) | set(cid_garbled_pages) | set(gibberish_pages))

    fitz_doc = fitz.open(str(filepath))
    images = _extract_images(fitz_doc, pages_for_ocr)
    fitz_doc.close()

    raw_preview = text_blocks[0].text[:500] if text_blocks else ""
    result = result_fn(
        "pdfplumber+pymupdf", mime,
        text_blocks, tables, word_count, page_count,
        len(images), raw_preview,
    )
    result.payload["images"] = list(images)
    result.payload["scanned_page_count"] = len(scanned_pages)
    result.payload["cid_garbled_page_count"] = len(cid_garbled_pages)
    result.payload["cid_garbled_pages"] = cid_garbled_pages
    result.payload["gibberish_page_count"] = len(gibberish_pages)
    result.payload["gibberish_pages"] = gibberish_pages
    return result
