"""Docling pipeline (Mode B) orchestrator — 9 stages."""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from pipelines.base import StageEmitter, StageResult
from pipelines.custom import stage_01_intake
from pipelines.docling import stage_02_unified_parse
from pipelines.custom import (
    stage_06_multimodal,
    stage_07_embedding,
    stage_08_metadata,
    stage_09_knowledge_graph,
    stage_09_vector_store,
    stage_10_rag_ready,
    stage_11_llm_answer,
)
from pipelines.custom.runner import _table_summary_chunks
import services.job_cache as cache

_CACHE_PFX  = "d_"
_COLLECTION = "rag_proto_docling"

# Heuristic: born-digital pages ~3-5s/page, OCR-required pages ~10-15s/page.
# Use 7s as a middle estimate — close enough for "still working, ~50% done"
# style progress hints without being misleading on either extreme.
_DOCLING_SECONDS_PER_PAGE = 7.0


def _quick_pdf_page_count(filepath) -> int | None:
    """Return PDF page count via pdfplumber (cheap, ~50ms), else None for non-PDFs."""
    if filepath.suffix.lower() != ".pdf":
        return None
    try:
        import pdfplumber
        with pdfplumber.open(str(filepath)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def _make_docling_progress(total_pages: int):
    """Build a `(elapsed_ms) -> progress_dict` closure for StageEmitter heartbeat.

    Page count comes from pdfplumber pre-scan, expected per-page time is a
    fixed estimate (Docling doesn't expose true per-page callbacks). The
    pct is capped at 95 so we don't hit 100% before the stage actually
    finishes — the completed event will flip it to 100.
    """
    expected_total_s = total_pages * _DOCLING_SECONDS_PER_PAGE

    def _progress(elapsed_ms: float) -> dict:
        elapsed_s = elapsed_ms / 1000.0
        pct = min(95.0, (elapsed_s / expected_total_s) * 100) if expected_total_s > 0 else 0
        est_page = min(total_pages, int(elapsed_s / _DOCLING_SECONDS_PER_PAGE))
        return {
            "progress_page_estimate": est_page,
            "total_pages":            total_pages,
            "progress_pct":           round(pct, 1),
        }
    return _progress


async def run_docling_pipeline(
    job_id: str,
    filepath: Path | None,
    source_type: str,
    publish: Callable,
) -> None:
    emitter = StageEmitter(job_id, "docling", publish)

    if filepath and filepath.exists():
        # Stage 1 — Intake
        result1: StageResult = await emitter.run_stage(
            1, "Intake", stage_01_intake.run(filepath, source_type)
        )
        intake_payload: dict = (result1.payload or {}) if result1 else {}

        # Stage 2 — Docling Unified Parse
        # Build a progress estimator so the heartbeat can emit
        # "page ~X / N (~Y%)" while PyTorch/OCR are grinding inside to_thread.
        page_count = _quick_pdf_page_count(filepath)
        progress_fn = _make_docling_progress(page_count) if page_count else None
        result2: StageResult = await emitter.run_stage(
            2, "Docling Unified Parse",
            stage_02_unified_parse.run(filepath, job_id),
            heartbeat_interval=10.0,        # tighter heartbeat for the slow stage
            progress_info=progress_fn,
        )
        unified = result2.payload or {} if result2 else {}

        chunks: list[dict] = cache.get(job_id, "d_chunks", [])
        _dp = cache.get(job_id, "d_parser_payload", {})
        cache.put(job_id, "d_extracted_tables", _dp.get("tables", []))
        parser_payload: dict = cache.get(job_id, "d_parser_payload", {})
        intel_payload: dict  = cache.get(job_id, "d_intel_payload", {})

        # Stage 3 — Multi-Modal enrichment (capture for table summary chunks)
        result3: StageResult = await emitter.run_stage(
            3, "Multi-Modal", stage_06_multimodal.run(parser_payload)
        )
        mm_payload: dict = (result3.payload or {}) if result3 else {}
        tables_enriched: list[dict] = mm_payload.get("tables_enriched", [])
        ocr_chunks:      list[dict] = mm_payload.get("ocr_chunks", [])
        ocr_tables:      list[dict] = mm_payload.get("ocr_tables", [])

        if ocr_tables:
            existing = cache.get(job_id, f"{_CACHE_PFX}extracted_tables", []) or []
            cache.put(job_id, f"{_CACHE_PFX}extracted_tables", existing + ocr_tables)

        if tables_enriched:
            cache.put(job_id, f"{_CACHE_PFX}enriched_tables", tables_enriched)

        all_chunks = chunks + _table_summary_chunks(tables_enriched) + ocr_chunks

        # Stage 4 — Embedding
        await emitter.run_stage(
            4, "Embedding",
            stage_07_embedding.run(all_chunks, job_id, cache_prefix=_CACHE_PFX)
        )

        # Stage 5 — Metadata
        await emitter.run_stage(
            5, "Metadata",
            stage_08_metadata.run(
                job_id, intel_payload, intake_payload,
                pipeline="docling", cache_prefix=_CACHE_PFX
            )
        )

        # Stage 6 — Knowledge Graph
        await emitter.run_stage(
            6, "Knowledge Graph",
            stage_09_knowledge_graph.run(job_id, cache_prefix=_CACHE_PFX)
        )

        # Stage 7 — Vector Store
        await emitter.run_stage(
            7, "Vector Store",
            stage_09_vector_store.run(job_id, collection_prefix=_COLLECTION, cache_prefix=_CACHE_PFX)
        )

        # Stage 8 — RAG Ready
        doc_type = unified.get("doc_type", intel_payload.get("doc_type", ""))
        await emitter.run_stage(
            8, "RAG Ready",
            stage_10_rag_ready.run(job_id, doc_type, cache_prefix=_CACHE_PFX)
        )

        # Stage 9 — LLM Answer
        await emitter.run_stage(
            9, "LLM Answer",
            stage_11_llm_answer.run(job_id, doc_type, cache_prefix=_CACHE_PFX)
        )

    else:
        from pipelines.mock import DOCLING_STAGES, _emit_stages
        await _emit_stages(job_id, "docling", DOCLING_STAGES, publish)
