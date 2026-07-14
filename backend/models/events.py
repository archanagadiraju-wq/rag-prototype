from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel


class CheckResult(BaseModel):
    name: str
    passed: bool
    severity: Literal["info", "warn", "fail"]
    detail: str
    value: Any = None
    threshold: Any = None


class VerificationSnapshot(BaseModel):
    l1_checks: list[CheckResult] = []
    l1_pass_rate: float = 0.0
    l2_score: Optional[float] = None
    l3_report: Optional[dict] = None


# ── Stage payloads ─────────────────────────────────────────────────────────────

class IntakePayload(BaseModel):
    filename: str
    size_bytes: int
    source_type: str
    sha256: str


class FormatDetectPayload(BaseModel):
    true_mime: str
    encoding: str
    is_scanned_pdf: bool = False
    sub_structure: str
    language: str = "unknown"
    confidence: float = 0.0


class TextBlock(BaseModel):
    id: str
    text: str
    page: Optional[int] = None
    heading_level: int = 0
    confidence: Optional[float] = None


class ExtractedTable(BaseModel):
    id: str
    page: Optional[int] = None
    rows: list[list[str]] = []
    headers: list[str] = []
    as_markdown: str = ""
    as_json: list[dict] = []
    bounding_box: Optional[dict] = None


class ExtractedImage(BaseModel):
    id: str
    page: Optional[int] = None
    width: int = 0
    height: int = 0
    format: str = "png"
    bytes_b64: str = ""
    caption: Optional[str] = None


class ParserPayload(BaseModel):
    parser_used: str
    page_count: Optional[int] = None
    word_count: int
    table_count: int
    image_count: int
    text_blocks: list[TextBlock] = []
    tables: list[ExtractedTable] = []
    images: list[ExtractedImage] = []
    raw_text_preview: str = ""


class ContentIntelPayload(BaseModel):
    doc_type: str
    doc_type_confidence: float
    language: str
    domain: str
    entities: list[dict] = []
    key_dates: list[str] = []
    summary: str
    content_flags: list[str] = []
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_usd: float = 0.0


class ChunkingPayload(BaseModel):
    strategy: str
    chunk_count: int
    avg_chunk_size_tokens: float
    min_chunk_tokens: int
    max_chunk_tokens: int
    overlap_tokens: int
    total_chunk_tokens: int = 0
    doc_tokens_est: int = 0
    coverage_pct: float = 0.0
    chunks: list[dict] = []
    size_distribution: list[int] = []


class MultiModalPayload(BaseModel):
    images_captioned: int = 0
    tables_serialised: int = 0
    tables_enriched: list[dict] = []
    captions: list[dict] = []
    model_used: str = ""
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_usd: float = 0.0


class EmbeddingPayload(BaseModel):
    model: str
    vector_dim: int
    chunks_embedded: int
    dense_sample: list[float] = []
    sparse_index_terms: int = 0
    embedding_ms: float = 0.0


class MetadataPayload(BaseModel):
    sample_metadata: dict = {}
    total_metadata_keys: int = 0
    filterable_fields: list[str] = []


class VectorStorePayload(BaseModel):
    collection: str
    vectors_upserted: int
    hnsw_m: int
    hnsw_ef_construction: int
    total_vectors_in_collection: int
    upsert_ms: float


class KnowledgeGraphPayload(BaseModel):
    entity_count: int
    relationship_count: int
    unique_entity_types: list[str]
    top_entities: list[dict]
    chunk_count: int


class RetrievalResult(BaseModel):
    chunk_id: str
    text: str
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rrf_score: float = 0.0
    graph_score: float = 0.0
    rerank_score: float = 0.0
    final_rank: int = 0


class RAGReadyPayload(BaseModel):
    test_query: str
    retrieval_results: list[RetrievalResult] = []
    hybrid_search_ms: float = 0.0
    rerank_ms: float = 0.0
    total_retrieval_ms: float = 0.0


class LLMAnswerItem(BaseModel):
    query_type: str
    label: str
    query: str
    entity_subject: Optional[str] = None
    context_chunks: int = 0
    answer: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class LLMAnswerPayload(BaseModel):
    answers: list[LLMAnswerItem] = []
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_llm_ms: float = 0.0
    total_cost_usd: float = 0.0
    model_used: str = ""
    use_real_embeddings: bool = False


StagePayload = (
    IntakePayload
    | FormatDetectPayload
    | ParserPayload
    | ContentIntelPayload
    | ChunkingPayload
    | MultiModalPayload
    | EmbeddingPayload
    | MetadataPayload
    | VectorStorePayload
    | RAGReadyPayload
    | dict
)


class StageEvent(BaseModel):
    job_id: str
    pipeline: Literal["custom", "docling", "agent"]
    stage_id: int
    stage_name: str
    status: Literal["started", "running", "completed", "error"]
    timestamp_ms: float
    duration_ms: Optional[float] = None
    progress: Optional[float] = None
    payload: Any = {}
    verification: Optional[VerificationSnapshot] = None
