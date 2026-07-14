"""Mock pipeline for Layer 1 — emits fake stage events every 500ms."""
from __future__ import annotations
import asyncio
import time
from typing import Callable

_MOCK_SQL_COLS_ENDPOINT = ["arm", "n", "response_rate_pct", "p_value"]
_MOCK_SQL_ROWS_ENDPOINT = [
    ["treatment", 248, "99.2", "< 0.001"],
    ["placebo",   251, "12.4", "< 0.001"],
]

_MOCK_SQL_COLS_AE = ["adverse_event", "treatment_n", "placebo_n", "risk_difference"]
_MOCK_SQL_ROWS_AE = [
    ["Nausea",       34, 29, "2.0%"],
    ["Headache",     28, 31, "-1.2%"],
    ["Fatigue",      41, 22, "7.6%"],
]

_MOCK_LLM_ANSWER = {
    "answers": [
        {
            "index": 1, "route": "vector", "type": "conceptual", "difficulty": "easy",
            "sql_fallback": False, "sql_query": None, "sql_cols": None, "sql_rows": None,
            "question": "What are the main findings and conclusions of this study?",
            "context_chunks": 5,
            "answer": "The study demonstrated 99.2% efficacy for the primary endpoint with a statistically significant reduction in adverse events compared to placebo (p < 0.001). Secondary endpoints including quality-of-life scores and biomarker levels also showed meaningful improvement. The authors conclude that the intervention is both safe and effective for the target population.",
            "input_tokens": 1247, "output_tokens": 89, "latency_ms": 741.0,
            "confidence": 0.84, "confidence_label": "high",
        },
        {
            "index": 2, "route": "vector", "type": "methodological", "difficulty": "medium",
            "sql_fallback": False, "sql_query": None, "sql_cols": None, "sql_rows": None,
            "question": "What methodology was used for the clinical trial design and randomization?",
            "context_chunks": 5,
            "answer": "The study employed a double-blind, randomized, placebo-controlled Phase III design. Patients were stratified by disease severity and assigned 1:1 to treatment or placebo. The protocol included pre-specified interim analyses at 50% and 75% enrollment, with an independent data safety monitoring board overseeing the trial.",
            "input_tokens": 1188, "output_tokens": 76, "latency_ms": 694.0,
            "confidence": 0.79, "confidence_label": "high",
        },
        {
            "index": 3, "route": "kg", "type": "entity", "difficulty": "medium",
            "sql_fallback": False, "sql_query": None, "sql_cols": None, "sql_rows": None,
            "question": "What role does Dr. Smith play and what are they responsible for?",
            "context_chunks": 5,
            "answer": "Dr. Smith served as the principal investigator for the Phase III trial, responsible for the overall study design, site oversight, and final data interpretation. They led the clinical team at Clinical Corp and co-authored the interim and final study reports. The document notes Dr. Smith's specific contribution to the protocol amendments approved in Q2.",
            "input_tokens": 1389, "output_tokens": 82, "latency_ms": 712.0,
            "confidence": 0.68, "confidence_label": "medium",
        },
        {
            "index": 4, "route": "kg", "type": "entity", "difficulty": "hard",
            "sql_fallback": False, "sql_query": None, "sql_cols": None, "sql_rows": None,
            "question": "Which institutions or organizations collaborated on this research and what was their role?",
            "context_chunks": 5,
            "answer": "Clinical Corp served as the lead sponsor and contract research organization, managing site operations across 18 investigational sites. MedResearch Institute provided independent biostatistical analysis and the data safety monitoring board. Boston General Hospital contributed the largest patient cohort and hosted the principal investigator team.",
            "input_tokens": 1421, "output_tokens": 91, "latency_ms": 758.0,
            "confidence": 0.61, "confidence_label": "medium",
        },
        {
            "index": 5, "route": "sql", "type": "numerical", "difficulty": "hard",
            "sql_fallback": False,
            "sql_query": "SELECT arm, n, response_rate_pct, p_value FROM doc_table_1 ORDER BY arm",
            "sql_cols": _MOCK_SQL_COLS_ENDPOINT, "sql_rows": _MOCK_SQL_ROWS_ENDPOINT,
            "question": "What were the response rates and sample sizes across treatment and placebo arms?",
            "context_chunks": 5,
            "answer": "According to the SQL table result: the treatment arm enrolled 248 patients with a 99.2% response rate, while the placebo arm enrolled 251 patients with a 12.4% response rate. Both differences were statistically significant (p < 0.001), confirming the primary efficacy endpoint.",
            "input_tokens": 1534, "output_tokens": 78, "latency_ms": 831.0,
            "confidence": 0.91, "confidence_label": "high",
        },
        {
            "index": 6, "route": "sql", "type": "numerical", "difficulty": "hard",
            "sql_fallback": False,
            "sql_query": "SELECT adverse_event, treatment_n, placebo_n, risk_difference FROM doc_table_2",
            "sql_cols": _MOCK_SQL_COLS_AE, "sql_rows": _MOCK_SQL_ROWS_AE,
            "question": "What were the adverse event rates by type across treatment and placebo groups?",
            "context_chunks": 5,
            "answer": "From the adverse events table: fatigue showed the largest risk difference (+7.6%) with 41 treatment vs 22 placebo cases. Nausea was marginally higher in the treatment arm (+2.0%). Headache was slightly more common in placebo (−1.2% risk difference). No serious adverse events led to study discontinuation.",
            "input_tokens": 1612, "output_tokens": 95, "latency_ms": 879.0,
            "confidence": 0.89, "confidence_label": "high",
        },
        {
            "index": 7, "route": "sql+vec", "type": "comparative", "difficulty": "hard",
            "sql_fallback": False,
            "sql_query": "SELECT arm, response_rate_pct FROM doc_table_1",
            "sql_cols": ["arm", "response_rate_pct"], "sql_rows": [["treatment", "99.2"], ["placebo", "12.4"]],
            "question": "How does the treatment efficacy compare to placebo and what explains the large difference?",
            "context_chunks": 5,
            "answer": "The treatment arm achieved a 99.2% response rate versus 12.4% for placebo — a difference of 86.8 percentage points. Document context explains this large gap is attributable to the mechanism of action targeting the upstream pathway responsible for 90% of disease pathogenesis, combined with the highly selected patient population with confirmed biomarker positivity.",
            "input_tokens": 1689, "output_tokens": 102, "latency_ms": 917.0,
            "confidence": 0.93, "confidence_label": "high",
        },
        {
            "index": 8, "route": "vector", "type": "safety", "difficulty": "medium",
            "sql_fallback": False, "sql_query": None, "sql_cols": None, "sql_rows": None,
            "question": "What are the main safety findings and were there any serious adverse events?",
            "context_chunks": 5,
            "answer": "The safety profile was generally favourable. The most common treatment-related adverse events were fatigue (16.5%), nausea (13.7%), and headache (11.3%), all consistent with the known class effect. No grade 4 or 5 adverse events were attributed to the study drug. One serious adverse event occurred in the placebo arm unrelated to treatment.",
            "input_tokens": 1302, "output_tokens": 84, "latency_ms": 726.0,
            "confidence": 0.77, "confidence_label": "high",
        },
        {
            "index": 9, "route": "kg", "type": "relational", "difficulty": "hard",
            "sql_fallback": False, "sql_query": None, "sql_cols": None, "sql_rows": None,
            "question": "What is the relationship between the principal investigator, Clinical Corp, and the regulatory timeline?",
            "context_chunks": 5,
            "answer": "Dr. Smith (PI) holds a dual role as chief medical officer at Clinical Corp and serves as the academic lead for the independent investigator group. Clinical Corp submitted the IND in Q1, with Dr. Smith signing the protocol amendments. The regulatory timeline shows FDA breakthrough designation was granted based on Phase II results, accelerating the Phase III design.",
            "input_tokens": 1467, "output_tokens": 97, "latency_ms": 788.0,
            "confidence": 0.55, "confidence_label": "medium",
        },
        {
            "index": 10, "route": "sql+vec", "type": "statistical", "difficulty": "hard",
            "sql_fallback": False,
            "sql_query": "SELECT arm, n, response_rate_pct, p_value FROM doc_table_1",
            "sql_cols": _MOCK_SQL_COLS_ENDPOINT, "sql_rows": _MOCK_SQL_ROWS_ENDPOINT,
            "question": "What were the pre-specified statistical thresholds and which endpoints achieved significance?",
            "context_chunks": 5,
            "answer": "The pre-specified significance threshold was p < 0.05 for primary and p < 0.10 (Bonferroni-adjusted) for secondary endpoints. Per the SQL table, both arms show p < 0.001 for the primary response rate, exceeding the threshold by more than 2 orders of magnitude. Document context confirms all three secondary endpoints (biomarker normalisation, QoL improvement, event-free survival) also achieved significance after multiple-testing correction.",
            "input_tokens": 1721, "output_tokens": 108, "latency_ms": 944.0,
            "confidence": 0.88, "confidence_label": "high",
        },
    ],
    "total_input_tokens": 14570,
    "total_output_tokens": 902,
    "total_tokens": 15472,
    "total_llm_ms": 7990.0,
    "total_cost_usd": 0.015270,
    "model_used": "claude-haiku-4-5-20251001",
    "use_real_embeddings": False,
    "llm_input_tokens": 14570,
    "llm_output_tokens": 902,
    "llm_cost_usd": 0.015270,
}

_MOCK_KG = {
    "entity_count": 15, "relationship_count": 28, "graph_nodes": 57,
    "unique_entity_types": ["PERSON", "ORG", "GPE"],
    "top_entities": [
        {"key": "ORG_clinical_corp", "text": "Clinical Corp", "label": "ORG", "mentions": 8},
        {"key": "PERSON_dr_smith",   "text": "Dr. Smith",     "label": "PERSON", "mentions": 5},
        {"key": "GPE_boston",        "text": "Boston",        "label": "GPE", "mentions": 4},
    ],
    "chunk_count": 42, "build_ms": 320.0,
}

_MOCK_RAG_READY = {
    "test_query": "What was the primary endpoint result?",
    "retrieval_results": [
        {"chunk_id": "c001", "text": "The primary endpoint showed 99.2% efficacy...", "dense_score": 0.91, "sparse_score": 0.78, "graph_score": 0.0, "rrf_score": 0.87, "rerank_score": 0.94, "final_rank": 1},
        {"chunk_id": "c007", "text": "Placebo-controlled arm showed no significant change...", "dense_score": 0.74, "sparse_score": 0.85, "graph_score": 0.0, "rrf_score": 0.81, "rerank_score": 0.88, "final_rank": 2},
    ],
    "hybrid_search_ms": 45, "rerank_ms": 0, "total_retrieval_ms": 165,
    "use_real_embeddings": False, "retrieval_mode": "dense + BM25 + knowledge graph (RRF)", "graph_active": True,
    "routing_summary": {
        "total_questions": 10,
        "vector_count": 3,
        "kg_count": 3,
        "sql_count": 2,
        "hybrid_count": 2,
        "sql_available": True,
        "tables_found": 2,
    },
    "query_showcase": [
        {
            "index": 1, "route": "vector", "type": "conceptual", "difficulty": "easy",
            "sql_fallback": False, "question": "What are the main findings and conclusions of this study?",
            "sql_query": None, "sql_cols": None, "sql_rows": None,
            "vector_results": [
                {"rank": 1, "chunk_id": "c001", "text": "The primary endpoint showed 99.2% efficacy with p < 0.001...", "dense_score": 0.91, "sparse_score": 0.72, "graph_score": 0.0, "rrf_score": 0.88},
                {"rank": 2, "chunk_id": "c015", "text": "Secondary endpoints including QoL scores also showed meaningful improvement...", "dense_score": 0.84, "sparse_score": 0.61, "graph_score": 0.0, "rrf_score": 0.79},
            ],
        },
        {
            "index": 2, "route": "vector", "type": "methodological", "difficulty": "medium",
            "sql_fallback": False, "question": "What methodology was used for the clinical trial design and randomization?",
            "sql_query": None, "sql_cols": None, "sql_rows": None,
            "vector_results": [
                {"rank": 1, "chunk_id": "c004", "text": "Double-blind, randomized, placebo-controlled Phase III design...", "dense_score": 0.87, "sparse_score": 0.68, "graph_score": 0.0, "rrf_score": 0.83},
            ],
        },
        {
            "index": 3, "route": "kg", "type": "entity", "difficulty": "medium",
            "sql_fallback": False, "question": "What role does Dr. Smith play and what are they responsible for?",
            "sql_query": None, "sql_cols": None, "sql_rows": None,
            "vector_results": [
                {"rank": 1, "chunk_id": "c003", "text": "Dr. Smith led the Phase III trial design as principal investigator...", "dense_score": 0.88, "sparse_score": 0.74, "graph_score": 0.75, "rrf_score": 0.86},
            ],
        },
        {
            "index": 4, "route": "kg", "type": "entity", "difficulty": "hard",
            "sql_fallback": False, "question": "Which institutions or organizations collaborated on this research?",
            "sql_query": None, "sql_cols": None, "sql_rows": None,
            "vector_results": [
                {"rank": 1, "chunk_id": "c008", "text": "Clinical Corp served as lead sponsor across 18 investigational sites...", "dense_score": 0.82, "sparse_score": 0.71, "graph_score": 0.62, "rrf_score": 0.81},
            ],
        },
        {
            "index": 5, "route": "sql", "type": "numerical", "difficulty": "hard",
            "sql_fallback": False,
            "question": "What were the response rates and sample sizes across treatment and placebo arms?",
            "sql_query": "SELECT arm, n, response_rate_pct, p_value FROM doc_table_1 ORDER BY arm",
            "sql_cols": _MOCK_SQL_COLS_ENDPOINT, "sql_rows": _MOCK_SQL_ROWS_ENDPOINT,
            "vector_results": [
                {"rank": 1, "chunk_id": "c001", "text": "Primary endpoint: 99.2% response in treatment arm...", "dense_score": 0.91, "sparse_score": 0.78, "graph_score": 0.0, "rrf_score": 0.87},
            ],
        },
        {
            "index": 6, "route": "sql", "type": "numerical", "difficulty": "hard",
            "sql_fallback": False,
            "question": "What were the adverse event rates by type across treatment and placebo groups?",
            "sql_query": "SELECT adverse_event, treatment_n, placebo_n, risk_difference FROM doc_table_2",
            "sql_cols": _MOCK_SQL_COLS_AE, "sql_rows": _MOCK_SQL_ROWS_AE,
            "vector_results": [
                {"rank": 1, "chunk_id": "c019", "text": "Safety profile was generally favourable; fatigue most common...", "dense_score": 0.79, "sparse_score": 0.65, "graph_score": 0.0, "rrf_score": 0.74},
            ],
        },
        {
            "index": 7, "route": "sql+vec", "type": "comparative", "difficulty": "hard",
            "sql_fallback": False,
            "question": "How does treatment efficacy compare to placebo and what explains the large difference?",
            "sql_query": "SELECT arm, response_rate_pct FROM doc_table_1",
            "sql_cols": ["arm", "response_rate_pct"], "sql_rows": [["treatment", "99.2"], ["placebo", "12.4"]],
            "vector_results": [
                {"rank": 1, "chunk_id": "c001", "text": "Primary endpoint showed 99.2% efficacy...", "dense_score": 0.91, "sparse_score": 0.72, "graph_score": 0.0, "rrf_score": 0.88},
                {"rank": 2, "chunk_id": "c012", "text": "Mechanism targets the upstream pathway responsible for 90% of pathogenesis...", "dense_score": 0.76, "sparse_score": 0.58, "graph_score": 0.0, "rrf_score": 0.71},
            ],
        },
        {
            "index": 8, "route": "vector", "type": "safety", "difficulty": "medium",
            "sql_fallback": False, "question": "What are the main safety findings and were there any serious adverse events?",
            "sql_query": None, "sql_cols": None, "sql_rows": None,
            "vector_results": [
                {"rank": 1, "chunk_id": "c019", "text": "No grade 4 or 5 adverse events attributed to study drug...", "dense_score": 0.83, "sparse_score": 0.69, "graph_score": 0.0, "rrf_score": 0.79},
            ],
        },
        {
            "index": 9, "route": "kg", "type": "relational", "difficulty": "hard",
            "sql_fallback": False, "question": "What is the relationship between the PI, Clinical Corp, and the regulatory timeline?",
            "sql_query": None, "sql_cols": None, "sql_rows": None,
            "vector_results": [
                {"rank": 1, "chunk_id": "c003", "text": "Dr. Smith holds dual role as CMO at Clinical Corp...", "dense_score": 0.79, "sparse_score": 0.61, "graph_score": 0.71, "rrf_score": 0.78},
            ],
        },
        {
            "index": 10, "route": "sql+vec", "type": "statistical", "difficulty": "hard",
            "sql_fallback": False,
            "question": "What were the pre-specified statistical thresholds and which endpoints achieved significance?",
            "sql_query": "SELECT arm, n, response_rate_pct, p_value FROM doc_table_1",
            "sql_cols": _MOCK_SQL_COLS_ENDPOINT, "sql_rows": _MOCK_SQL_ROWS_ENDPOINT,
            "vector_results": [
                {"rank": 1, "chunk_id": "c022", "text": "Pre-specified significance threshold: p < 0.05 primary, Bonferroni-adjusted p < 0.10 secondary...", "dense_score": 0.86, "sparse_score": 0.73, "graph_score": 0.0, "rrf_score": 0.83},
            ],
        },
    ],
}

CUSTOM_STAGES = [
    (1,  "Intake",              {"filename": "demo.pdf", "size_bytes": 204800, "source_type": "upload", "sha256": "abc123"}),
    (2,  "Format Detection",    {"true_mime": "application/pdf", "encoding": "UTF-8", "sub_structure": "text-native-pdf", "is_scanned_pdf": False, "language": "en", "confidence": 0.99}),
    (3,  "Format Parser",       {"parser_used": "pdfplumber", "page_count": 20, "word_count": 8400, "table_count": 3, "image_count": 2, "raw_text_preview": "Abstract: This study investigates..."}),
    (4,  "Content Intelligence",{"doc_type": "research_paper", "doc_type_confidence": 0.94, "language": "en", "domain": "medical", "summary": "A clinical trial report.", "content_flags": ["contains_tables"], "entities": [], "key_dates": []}),
    (5,  "Smart Chunking",      {"strategy": "MarkdownHeaderTextSplitter", "chunk_count": 42, "avg_chunk_size_tokens": 387, "min_chunk_tokens": 24, "max_chunk_tokens": 512, "overlap_tokens": 64, "chunks": [], "size_distribution": [24, 387, 512]}),
    (6,  "Multi-Modal",         {"images_captioned": 2, "tables_serialised": 3, "captions": [], "model_used": "claude-3-5-sonnet"}),
    (7,  "Embedding",           {"model": "text-embedding-3-large", "vector_dim": 1536, "chunks_embedded": 42, "dense_sample": [0.12, -0.05, 0.33], "sparse_index_terms": 1847, "embedding_ms": 2340}),
    (8,  "Metadata",            {"sample_metadata": {"doc_id": "job_001", "chunk_type": "text", "pipeline": "custom"}, "total_metadata_keys": 12, "filterable_fields": ["doc_type", "domain", "page"]}),
    (9,  "Knowledge Graph",     _MOCK_KG),
    (10, "Vector Store",        {"collection": "rag_proto_custom", "vectors_upserted": 42, "hnsw_m": 8, "hnsw_ef_construction": 100, "total_vectors_in_collection": 42, "upsert_ms": 145, "qdrant_live": True,
                                "sql_tables_created": 2,
                                "sql_registry": {
                                    "doc_table_1": {"original_headers": ["arm", "n", "response_rate_pct", "p_value"], "columns": ["arm", "n", "response_rate_pct", "p_value"], "row_count": 2, "page": 5},
                                    "doc_table_2": {"original_headers": ["adverse_event", "treatment_n", "placebo_n", "risk_difference"], "columns": ["adverse_event", "treatment_n", "placebo_n", "risk_difference"], "row_count": 3, "page": 12},
                                }}),
    (11, "RAG Ready",           _MOCK_RAG_READY),
    (12, "LLM Answer",          _MOCK_LLM_ANSWER),
]

# Docling replaces stages 2-5 with a single unified parse stage (stage_id 2)
DOCLING_STAGES = [
    (1, "Intake",              {"filename": "demo.pdf", "size_bytes": 204800, "source_type": "upload", "sha256": "abc123"}),
    (2, "Docling Unified Parse", {"parser": "docling-2.x", "page_count": 20, "word_count": 8720, "table_count": 3, "image_count": 2,
                                  "doc_type": "research_paper", "doc_type_confidence": 0.96, "language": "en", "domain": "medical",
                                  "strategy": "HierarchicalChunker", "chunk_count": 38, "avg_chunk_size_tokens": 401,
                                  "summary": "A clinical trial report.", "content_flags": ["contains_tables", "bounding_box_provenance"],
                                  "entities": [], "key_dates": [],
                                  "note": "Stages 2-5 unified: format detect + parse + content intel + chunking"}),
    (3, "Multi-Modal",         {"images_captioned": 2, "tables_serialised": 3, "captions": [], "model_used": "claude-3-5-sonnet"}),
    (4, "Embedding",           {"model": "text-embedding-3-large", "vector_dim": 1536, "chunks_embedded": 38, "dense_sample": [0.09, -0.08, 0.41], "sparse_index_terms": 1621, "embedding_ms": 2110}),
    (5, "Metadata",            {"sample_metadata": {"doc_id": "job_001", "chunk_type": "text", "pipeline": "docling"}, "total_metadata_keys": 14, "filterable_fields": ["doc_type", "domain", "page", "bounding_box"]}),
    (6, "Knowledge Graph",     {**_MOCK_KG, "chunk_count": 38}),
    (7, "Vector Store",        {"collection": "rag_proto_docling", "vectors_upserted": 38, "hnsw_m": 8, "hnsw_ef_construction": 100, "total_vectors_in_collection": 38, "upsert_ms": 131, "qdrant_live": True,
                                "sql_tables_created": 2,
                                "sql_registry": {
                                    "doc_table_1": {"original_headers": ["arm", "n", "response_rate_pct", "p_value"], "columns": ["arm", "n", "response_rate_pct", "p_value"], "row_count": 2, "page": 5},
                                    "doc_table_2": {"original_headers": ["adverse_event", "treatment_n", "placebo_n", "risk_difference"], "columns": ["adverse_event", "treatment_n", "placebo_n", "risk_difference"], "row_count": 3, "page": 12},
                                }}),
    (8, "RAG Ready",           _MOCK_RAG_READY),
    (9, "LLM Answer",          _MOCK_LLM_ANSWER),
]


def _l1(passed: bool = True, name: str = "mock_check", detail: str = "Passed"):
    return {"name": name, "passed": passed, "severity": "info" if passed else "warn", "detail": detail}


async def _emit_stages(job_id: str, pipeline: str, stages: list, publish: Callable, delay: float = 0.0):
    if delay:
        await asyncio.sleep(delay)
    for stage_id, stage_name, payload in stages:
        await publish({
            "job_id": job_id, "pipeline": pipeline, "stage_id": stage_id,
            "stage_name": stage_name, "status": "started",
            "timestamp_ms": time.time() * 1000, "payload": {},
        })
        await asyncio.sleep(0.3)
        await publish({
            "job_id": job_id, "pipeline": pipeline, "stage_id": stage_id,
            "stage_name": stage_name, "status": "completed",
            "timestamp_ms": time.time() * 1000, "duration_ms": 280 + stage_id * 20,
            "payload": payload,
            "verification": {"l1_checks": [_l1()], "l1_pass_rate": 1.0},
        })
        await asyncio.sleep(0.2)


async def run_mock_pipeline(job_id: str, pipeline: str, publish: Callable):
    if pipeline == "custom":
        await _emit_stages(job_id, "custom", CUSTOM_STAGES, publish)
    elif pipeline == "docling":
        await _emit_stages(job_id, "docling", DOCLING_STAGES, publish)
    elif pipeline == "compare":
        # Both pipelines run concurrently
        await asyncio.gather(
            _emit_stages(job_id, "custom",  CUSTOM_STAGES,  publish, delay=0.0),
            _emit_stages(job_id, "docling", DOCLING_STAGES, publish, delay=0.15),
        )
