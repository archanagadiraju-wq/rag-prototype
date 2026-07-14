"""Stage 8 — Metadata Enrichment.

Attaches per-chunk metadata fields needed for Qdrant payload filtering:
doc_id, chunk_id, chunk_idx, page, heading_path, pipeline, doc_type, domain, source_filename.
"""
from __future__ import annotations

from models.events import MetadataPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
import services.job_cache as cache

_FILTERABLE_FIELDS = [
    "doc_type", "domain", "page", "pipeline",
    "source_filename", "chunk_idx", "heading_path",
]
_REQUIRED_KEYS = ["doc_id", "chunk_id", "doc_type", "pipeline"]


async def run(
    job_id: str,
    content_intel: dict,
    intake: dict,
    pipeline: str = "custom",
    cache_prefix: str = "",
) -> StageResult:
    embedded_chunks = cache.get(job_id, f"{cache_prefix}embedded_chunks", [])

    if not embedded_chunks:
        payload = MetadataPayload(
            sample_metadata={}, total_metadata_keys=0, filterable_fields=_FILTERABLE_FIELDS
        )
        checks = [make_check("metadata_attached", False, "No embedded chunks to enrich", severity="warn")]
        return StageResult(payload=payload.model_dump(), verification=make_verification(checks))

    doc_type = content_intel.get("doc_type", "unknown")
    domain = content_intel.get("domain", "unknown")
    source_filename = intake.get("filename", "unknown")

    for i, chunk in enumerate(embedded_chunks):
        existing = chunk.get("metadata", {})
        chunk["metadata"] = {
            **existing,                               # preserve chunk_type, table_name, etc.
            "doc_id": job_id,
            "chunk_id": f"{job_id[:8]}_{pipeline}_c{i:04d}",
            "chunk_idx": i,
            "page": chunk.get("page"),
            "heading_path": chunk.get("heading_path", ""),
            "pipeline": pipeline,
            "doc_type": doc_type,
            "domain": domain,
            "source_filename": source_filename,
        }

    cache.put(job_id, f"{cache_prefix}embedded_chunks", embedded_chunks)

    sample = embedded_chunks[0]["metadata"] if embedded_chunks else {}
    all_keys: set[str] = set()
    for chunk in embedded_chunks:
        all_keys.update(chunk.get("metadata", {}).keys())

    payload = MetadataPayload(
        sample_metadata=sample,
        total_metadata_keys=len(all_keys),
        filterable_fields=_FILTERABLE_FIELDS,
    )

    missing = [k for k in _REQUIRED_KEYS if k not in all_keys]
    checks = [
        make_check("metadata_attached", len(embedded_chunks) > 0,
                   f"{len(embedded_chunks)} chunks enriched"),
        make_check("required_fields_present", not missing,
                   "All required fields present" if not missing else f"Missing: {missing}"),
        make_check("filterable_fields", len(_FILTERABLE_FIELDS) >= 5,
                   f"{len(_FILTERABLE_FIELDS)} filterable fields"),
    ]
    return StageResult(payload=payload.model_dump(), verification=make_verification(checks))
