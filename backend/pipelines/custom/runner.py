"""Custom pipeline (Mode A) orchestrator — all 12 stages real."""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from pipelines.base import StageEmitter, StageResult
import services.job_cache as cache
from pipelines.custom import (
    stage_01_intake,
    stage_02_format_detect,
    stage_03_parser,
    stage_04_content_intel,
    stage_05_chunker,
    stage_06_multimodal,
    stage_07_embedding,
    stage_08_metadata,
    stage_09_knowledge_graph,
    stage_09_vector_store,
    stage_10_rag_ready,
    stage_11_llm_answer,
)


def _table_summary_chunks(tables_enriched: list[dict]) -> list[dict]:
    """One embeddable chunk per table: description + columns + sample rows.

    These chunks go into the vector store so retrieval can surface which
    table is relevant to a question — keyed by chunk_type='table_summary'
    and table_name='doc_table_N' in their metadata.
    """
    chunks = []
    for i, tbl in enumerate(tables_enriched):
        tname   = f"doc_table_{i + 1}"
        desc    = tbl.get("description", "")
        headers = tbl.get("headers") or []
        rows    = tbl.get("rows") or []

        parts = []
        if desc:
            parts.append(f"Table summary: {desc}")
        if headers:
            parts.append(f"Columns: {', '.join(str(h) for h in headers)}")
        if rows:
            sample_lines = [
                "  " + " | ".join(str(c) for c in row)
                for row in rows[:3]
            ]
            parts.append("Sample data:\n" + "\n".join(sample_lines))

        if not parts:
            continue

        text = "\n".join(parts)
        chunks.append({
            "id":           f"table_summary_{tname}",
            "text":         text,
            "token_count":  max(1, int(len(text.split()) * 1.35)),
            "page":         tbl.get("page"),
            "heading_path": f"Table {i + 1}",
            "metadata": {
                "chunk_type": "table_summary",
                "table_name": tname,
            },
        })
    return chunks


async def run_custom_pipeline(
    job_id: str,
    filepath: Path | None,
    source_type: str,
    publish: Callable,
) -> None:
    emitter = StageEmitter(job_id, "custom", publish)

    if filepath and filepath.exists():
        # Stage 1 — Intake
        result1: StageResult = await emitter.run_stage(
            1, "Intake", stage_01_intake.run(filepath, source_type)
        )
        intake_payload: dict = (result1.payload or {}) if result1 else {}

        # Stage 2 — Format Detection
        result2: StageResult = await emitter.run_stage(
            2, "Format Detection", stage_02_format_detect.run(filepath)
        )
        mime: str = (result2.payload or {}).get("true_mime", "") if result2 else ""

        # Stage 3 — Format Parser
        result3: StageResult = await emitter.run_stage(
            3, "Format Parser", stage_03_parser.run(filepath, mime)
        )
        parser_payload: dict = (result3.payload or {}) if result3 else {}
        cache.put(job_id, "extracted_tables", parser_payload.get("tables", []))

        # Stage 4 — Content Intelligence
        result4: StageResult = await emitter.run_stage(
            4, "Content Intelligence", stage_04_content_intel.run(parser_payload, mime)
        )
        intel_payload: dict = (result4.payload or {}) if result4 else {}

        # Stage 5 — Smart Chunking
        result5: StageResult = await emitter.run_stage(
            5, "Smart Chunking", stage_05_chunker.run(parser_payload)
        )
        prose_chunks: list[dict] = (result5.payload or {}).get("chunks", []) if result5 else []

        # Stage 6 — Multi-Modal enrichment
        # Capture result so we can build table-summary chunks for embedding
        result6: StageResult = await emitter.run_stage(
            6, "Multi-Modal", stage_06_multimodal.run(parser_payload)
        )
        mm_payload: dict = (result6.payload or {}) if result6 else {}
        tables_enriched: list[dict] = mm_payload.get("tables_enriched", [])
        ocr_chunks:      list[dict] = mm_payload.get("ocr_chunks", [])
        ocr_tables:      list[dict] = mm_payload.get("ocr_tables", [])

        # OCR'd tables → SQL store (Stage 10 reads from extracted_tables cache)
        if ocr_tables:
            existing = cache.get(job_id, "extracted_tables", []) or []
            cache.put(job_id, "extracted_tables", existing + ocr_tables)

        if tables_enriched:
            cache.put(job_id, "enriched_tables", tables_enriched)

        all_chunks = prose_chunks + _table_summary_chunks(tables_enriched) + ocr_chunks

        # Stage 7 — Embedding (dense + BM25 sparse)
        await emitter.run_stage(
            7, "Embedding", stage_07_embedding.run(all_chunks, job_id)
        )

        # Stage 8 — Metadata (merges into existing chunk metadata, preserving chunk_type)
        await emitter.run_stage(
            8, "Metadata", stage_08_metadata.run(job_id, intel_payload, intake_payload)
        )

        # Stage 9 — Knowledge Graph
        await emitter.run_stage(
            9, "Knowledge Graph", stage_09_knowledge_graph.run(job_id)
        )

        # Stage 10 — Vector Store
        await emitter.run_stage(
            10, "Vector Store", stage_09_vector_store.run(job_id)
        )

        # Stage 11 — RAG Ready
        doc_type = intel_payload.get("doc_type", "")
        await emitter.run_stage(
            11, "RAG Ready", stage_10_rag_ready.run(job_id, doc_type)
        )

        # Stage 12 — LLM Answer
        await emitter.run_stage(
            12, "LLM Answer", stage_11_llm_answer.run(job_id, doc_type)
        )

    else:
        from pipelines.mock import CUSTOM_STAGES, _emit_stages
        await _emit_stages(job_id, "custom", CUSTOM_STAGES, publish)
