from __future__ import annotations
import hashlib
from pathlib import Path

from models.events import IntakePayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult


async def run(filepath: Path, source_type: str) -> StageResult:
    raw = filepath.read_bytes()
    size_bytes = len(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    extension = filepath.suffix.lower().lstrip(".")

    checks = [
        make_check("file_exists", True, f"Found: {filepath.name}"),
        make_check("size_nonzero", size_bytes > 0, f"{size_bytes:,} bytes"),
        make_check("extension_present", bool(extension), f".{extension}" if extension else "No extension"),
        make_check("sha256_computed", len(sha256) == 64, f"{sha256[:16]}…"),
    ]

    payload = IntakePayload(
        filename=filepath.name,
        size_bytes=size_bytes,
        source_type=source_type,
        sha256=sha256,
    )

    return StageResult(payload=payload.model_dump(), verification=make_verification(checks))
