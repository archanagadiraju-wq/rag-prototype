from __future__ import annotations
from pathlib import Path

import magic
import chardet

from models.events import FormatDetectPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult

try:
    from langdetect import detect, LangDetectException
    _LANGDETECT = True
except ImportError:
    _LANGDETECT = False

_HEAD_BYTES = 65536  # 64 KB sample for MIME / encoding detection


def _classify(mime: str, head: bytes) -> tuple[str, bool]:
    """Returns (sub_structure_label, is_scanned_pdf)."""
    if mime == "application/pdf":
        # Text-native PDFs embed font references; scanned ones typically lack them.
        is_scanned = b"/Font" not in head
        return ("scanned-pdf" if is_scanned else "text-native-pdf", is_scanned)
    if "spreadsheetml" in mime or mime == "application/vnd.ms-excel":
        return "spreadsheet-xlsx", False
    if "wordprocessingml" in mime or mime == "application/msword":
        return "docx-document", False
    if "presentationml" in mime:
        return "pptx-presentation", False
    if mime == "text/html":
        return "html-document", False
    if mime.startswith("text/"):
        return "plain-text", False
    return "unknown", False


async def run(filepath: Path) -> StageResult:
    raw = filepath.read_bytes()
    head = raw[:_HEAD_BYTES]

    # MIME — from_file reads the full file (needed for OOXML ZIP detection)
    mime = magic.from_file(str(filepath), mime=True)

    # Encoding — chardet can't decode binary containers; use known values for those formats.
    enc = chardet.detect(head)
    encoding: str = enc.get("encoding") or "binary"
    enc_confidence: float = float(enc.get("confidence") or 0.0)
    if encoding == "binary":
        if "openxmlformats" in mime:
            encoding = "UTF-8"       # OOXML XML entries are always UTF-8
            enc_confidence = 1.0
        elif mime == "application/pdf":
            encoding = "PDF-internal"  # text encoding is embedded in PDF streams
            enc_confidence = 1.0

    # Sub-structure
    sub_structure, is_scanned = _classify(mime, head)

    # Language (best-effort)
    language = "unknown"
    if _LANGDETECT:
        try:
            sample = raw[:8192].decode("utf-8", errors="ignore").strip()
            if len(sample) > 50:
                language = detect(sample)
        except Exception:
            pass

    checks = [
        make_check("mime_resolved", mime != "application/octet-stream", f"MIME: {mime}"),
        make_check(
            "encoding_detected",
            encoding not in ("binary", "unknown"),
            f"{encoding} ({enc_confidence:.0%} confidence)",
        ),
    ]
    # scanned-PDF check is only meaningful for PDFs
    if mime == "application/pdf":
        checks.append(make_check(
            "not_scanned_pdf",
            not is_scanned,
            "Text-native PDF" if not is_scanned else "Scanned PDF — OCR required",
            severity="warn",
        ))
    checks.append(make_check(
        "sub_structure_classified",
        sub_structure != "unknown",
        f"Structure: {sub_structure}",
    ))

    payload = FormatDetectPayload(
        true_mime=mime,
        encoding=encoding,
        is_scanned_pdf=is_scanned,
        sub_structure=sub_structure,
        language=language,
        confidence=enc_confidence,
    )

    return StageResult(payload=payload.model_dump(), verification=make_verification(checks))
