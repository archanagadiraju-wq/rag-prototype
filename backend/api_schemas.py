"""Pydantic schemas powering the OpenAPI / Swagger documentation.

Every public API endpoint has a request and/or response model defined here.
Field-level `description=` and `examples=` populate the Swagger UI directly,
so the auto-generated docs at /docs and /redoc are accurate without manual
markdown maintenance.

Models are imported by main.py and used via FastAPI's `response_model=`
and request-body annotations.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# ── Common types ──────────────────────────────────────────────────────────────


PipelineMode = Literal["custom", "docling", "compare", "agent"]


class ErrorResponse(BaseModel):
    """Standard error body returned by FastAPI for HTTPException."""
    detail: str = Field(
        ...,
        description="Human-readable error message.",
        examples=["Job not found"],
    )


# ── /api/jobs ─────────────────────────────────────────────────────────────────


class JobCreateResponse(BaseModel):
    """Returned when a new ingestion job is created."""
    job_id: str = Field(
        ...,
        description="UUID v4 identifier. Used in all subsequent endpoints "
                    "(`GET /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/ask`, "
                    "and the WebSocket `/ws/{job_id}`).",
        examples=["873141fe-1c5c-4ad3-b279-5b7ad9cf3296"],
    )
    created_at: str = Field(
        ...,
        description="ISO-8601 UTC timestamp the job was queued.",
        examples=["2026-05-21T10:30:00Z"],
    )


class JobStatusResponse(BaseModel):
    """Current state of an existing job."""
    job_id: str = Field(..., examples=["873141fe-1c5c-4ad3-b279-5b7ad9cf3296"])
    pipeline: str = Field(
        ...,
        description="Which mode this job was created with.",
        examples=["custom", "docling", "compare", "agent"],
    )
    status: Literal["queued", "running", "completed", "error", "cancelled"] = Field(
        ...,
        description="High-level job state. Stage-level events arrive via the WebSocket. "
                    "`cancelled` indicates the user issued DELETE /api/jobs/{id} while the job was in flight.",
        examples=["completed"],
    )
    filename: str | None = Field(
        None,
        description="Original filename (if uploaded) or demo doc name.",
        examples=["02_financial_model.xlsx"],
    )
    created_at: str = Field(..., examples=["2026-05-21T10:30:00Z"])
    completed_at: str | None = Field(
        None,
        description="ISO-8601 UTC timestamp the pipeline finished. Null while running.",
        examples=["2026-05-21T10:30:18Z"],
    )
    error: str | None = Field(
        None,
        description="Pipeline-level failure message (set when status='error').",
    )


# ── /api/jobs/{job_id}/ask ────────────────────────────────────────────────────


class AskRequest(BaseModel):
    """Body for the ad-hoc Q&A endpoint."""
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The natural-language question to ask of the ingested document. "
                    "Empty or whitespace-only strings return HTTP 400.",
        examples=["What is the projected ARR for end of year 2026?"],
    )
    pipeline: PipelineMode = Field(
        "custom",
        description="Which pipeline's index to query. Use `custom` for Mode A or "
                    "Mode D (agent — they share the same cache prefix). Use `docling` "
                    "for Mode B. Other values fall back to `custom`.",
        examples=["custom"],
    )


class RetrievedChunk(BaseModel):
    """A single chunk returned by the hybrid retriever (dense + BM25 + KG)."""
    chunk_id: str | None = Field(None, examples=["chunk_0002"])
    text: str = Field(
        ...,
        description="First ~400 chars of the chunk; full chunk text is in storage.",
        examples=["Q3 2026 Net New MRR ranged from $1.06M (Jul) to $1.54M (Sep)..."],
    )
    score: float = Field(
        ...,
        description="Dense (cosine) similarity score for this chunk against the question. "
                    "Higher = more relevant.",
        examples=[0.836],
    )
    page: int | None = Field(None, examples=[12])
    heading: str | None = Field(
        None,
        description="Heading-path breadcrumb if the chunker preserved it.",
        examples=["Revenue > Forecasts > FY 2026"],
    )


class AskResponse(BaseModel):
    """Response to a single Q&A request — fully audit-able."""
    question: str = Field(..., examples=["What is Q3 Net New MRR?"])
    answer: str = Field(
        ...,
        description="Claude haiku's grounded answer. The model is instructed to only "
                    "use the retrieved chunks; if they don't contain the answer, the "
                    "response will say so explicitly rather than hallucinate.",
    )

    # Cost & latency
    input_tokens: int = Field(..., description="Input tokens consumed by the answer call.", examples=[1546])
    output_tokens: int = Field(..., description="Output tokens generated.", examples=[89])
    cost_usd: float = Field(..., description="Total cost of this Q&A in USD (embed + answer + judge).", examples=[0.00189])
    latency_ms: float = Field(..., description="Answer-call latency (does not include embed or judge).", examples=[1842.0])

    # Confidence — two independent signals
    confidence: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Retrieval-signal confidence (heuristic from dense/BM25/KG quality). "
                    "Compare with `judge_score` for true correctness.",
        examples=[0.81],
    )
    confidence_label: str = Field(..., examples=["high"])

    context_chunks: int = Field(..., description="Number of chunks retrieved and fed to the answer call.", examples=[5])
    retrieved: list[RetrievedChunk] = Field(
        ...,
        description="The chunks fed to the LLM, in rank order. Use these to verify "
                    "the answer's grounding.",
    )

    # Full prompts for audit / debugging
    system_prompt: str = Field(
        ...,
        description="The exact system prompt sent to Claude. Identical across calls.",
    )
    user_prompt: str = Field(
        ...,
        description="The exact user message: `Context:\\n[chunks]\\n\\nQuestion: ...`",
    )

    # LLM-as-judge fields (second Claude pass)
    judge_score: float | None = Field(
        None,
        ge=0.0, le=1.0,
        description="Independent judge's 0–1 score for whether the answer is "
                    "grounded in the retrieved context. Null if judge unavailable.",
        examples=[0.95],
    )
    judge_verdict: Literal["correct", "partial", "unsupported", "incorrect"] | None = Field(
        None,
        description="4-tier verdict from the judge LLM. `correct` = fully grounded, "
                    "`partial` = some claims unsupported, `unsupported` = significant "
                    "hallucination, `incorrect` = wrong answer.",
        examples=["correct"],
    )
    judge_rationale: str | None = Field(
        None,
        description="One-sentence justification from the judge.",
        examples=["The answer correctly identifies $74M base case ARR from the forecast table."],
    )

    # Reranker trace — listwise Claude pass that re-ordered the RRF top-15.
    rerank_used: bool = Field(
        False,
        description="True when a Claude listwise reranker re-ordered the "
                    "retrieval candidates before answering.",
    )
    rerank_candidates: int = Field(0, description="How many candidates the reranker saw.")
    rerank_kept: list[int] | None = Field(
        None,
        description="Indices (into the RRF candidate list) that the reranker kept, "
                    "ordered by relevance. Null when reranking was skipped.",
    )
    rerank_ms: float = Field(0.0, description="Reranker call latency in milliseconds.")
    rerank_reason: str | None = Field(
        None,
        description="Why reranking ran (or didn't). "
                    "Examples: 'ok (5 kept)', 'skip_too_few_candidates', 'disabled'.",
    )

    # Document-facts routing trace — null when no extracted fact matched.
    fact_used: bool = Field(
        False,
        description="True when the answer was anchored to an extracted document "
                    "fact (facts.json) injected as the highest-priority context block.",
    )
    fact_match: dict[str, Any] | None = Field(
        None,
        description="The matched fact record (key, label, value, unit, source, "
                    "match_score). Null when no fact matched.",
    )

    # SQL routing trace — null when the question wasn't routed through SQL.
    sql_used: bool = Field(
        False,
        description="True when the SQL router generated a SELECT, executed it, "
                    "and at least one row was returned (i.e. the answer LLM saw "
                    "structured SQL context, not just retrieved chunks).",
    )
    sql_query: str | None = Field(
        None,
        description="The SELECT statement the router ran. Null if SQL was not used.",
        examples=["SELECT * FROM \"doc_table_1\" WHERE bidder='HYPER-AIRE' LIMIT 25"],
    )
    sql_columns: list[str] = Field(
        default_factory=list,
        description="Column names returned by the SELECT.",
    )
    sql_rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Row data returned by the SELECT (capped at 25).",
    )
    sql_row_count: int = Field(0, description="Number of rows the SQL query returned.")
    sql_router_reason: str | None = Field(
        None,
        description="Why SQL routing was used or skipped — useful for debugging "
                    "wrong routing decisions. Examples: 'ok (3 rows)', "
                    "'router_skipped: question is narrative', 'no_sql_registry'.",
    )


# ── /api/demo-docs ────────────────────────────────────────────────────────────


class DemoDocInfo(BaseModel):
    """Catalog entry for a bundled demo document."""
    id: str = Field(..., examples=["02"])
    filename: str = Field(..., examples=["02_financial_model.xlsx"])
    doc_type: str = Field(..., examples=["financial_report"])
    domain: str = Field(..., examples=["financial"])
    description: str = Field(..., examples=["6-sheet SaaS financial model with cross-sheet formulas"])
    has_ground_truth: bool = Field(..., description="Whether ground-truth Q&A exists for L3 evaluation.")


class DemoDocList(BaseModel):
    docs: list[DemoDocInfo]


# ── WebSocket events (StageEvent — for docs only, not validated) ─────────────


class StorageQdrant(BaseModel):
    collection: str | None = Field(None, examples=["rag_proto_agent_abc12345"])
    vectors: int = Field(..., examples=[8])
    dimensions: int = Field(..., examples=[1536])
    live: bool = Field(..., description="Whether Qdrant is currently reachable.", examples=[True])
    distance: str = Field("COSINE", description="Distance metric used by the index.", examples=["COSINE"])
    hnsw_m: int = Field(8, description="HNSW graph connectivity (neighbours per node).", examples=[8])
    hnsw_ef_construct: int = Field(100, description="HNSW build-time accuracy parameter.", examples=[100])
    embedding_model: str = Field("text-embedding-3-large", examples=["text-embedding-3-large"])
    sample_vector: list[float] = Field(
        default_factory=list,
        description="First 8 components of one stored vector (for sanity-checking that real embeddings landed).",
        examples=[[-0.0126, -0.0027, 0.0345, 0.0091, -0.0212, 0.0033, 0.0156, -0.0089]],
    )


class StorageSqliteTable(BaseModel):
    name: str = Field(..., examples=["doc_table_1"])
    rows: int = Field(..., examples=[24])
    columns: list[str] = Field(..., examples=[["Month", "New MRR ($)", "Expansion MRR ($)"]])


class StorageSqlite(BaseModel):
    file: str | None = Field(None, description="SQLite filename (if a SQL store exists).", examples=["tables.db"])
    size_bytes: int = Field(0)
    tables: list[StorageSqliteTable] = Field(default_factory=list)


class StorageBm25(BaseModel):
    unique_terms: int = Field(..., examples=[475])
    doc_count: int = Field(..., examples=[8])
    avg_doc_len: float = Field(..., examples=[146.1])


class StorageKnowledgeGraph(BaseModel):
    nodes: int = Field(..., examples=[59])
    edges: int = Field(..., examples=[234])
    entity_types: list[str] = Field(..., examples=[["ORG", "PERSON", "DATE", "MONEY"]])


class StorageDiskFile(BaseModel):
    name: str = Field(..., examples=["embedded_chunks.json"])
    size_bytes: int = Field(..., examples=[247808])


class StorageDisk(BaseModel):
    path: str = Field(..., examples=["backend/data/jobs/<job_id>/"])
    total_bytes: int = Field(..., examples=[350000])
    file_count: int = Field(..., examples=[17])
    files: list[StorageDiskFile] = Field(default_factory=list)


class StorageInMemory(BaseModel):
    key_count: int = Field(..., examples=[9])
    keys: list[str] = Field(default_factory=list)


class StorageFacts(BaseModel):
    """Document-level facts layer — single-valued properties extracted at ingest."""
    extracted: bool = Field(..., description="True if facts.json exists for this job.")
    fact_count: int = Field(..., examples=[14])
    by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count of facts grouped by type (number, currency, date, person, ...).",
        examples=[{"number": 4, "currency": 1, "date": 2, "person": 1, "list": 1}],
    )
    extractor_version: str | None = Field(None, examples=["1.0"])
    extracted_at: str | None = Field(None, examples=["2026-05-22T14:30:00Z"])
    stats: dict[str, Any] = Field(default_factory=dict, description="Extraction telemetry (tokens, ms, rejected).")
    error: str | None = Field(None, description="If extraction failed, the reason.")


class StorageSummary(BaseModel):
    """Consolidated view of every storage sink used by one ingestion job."""
    job_id: str
    exists: bool = Field(..., description="True if any storage state was found for this job.")
    qdrant: StorageQdrant
    sqlite: StorageSqlite
    bm25:   StorageBm25
    kg:     StorageKnowledgeGraph
    facts:  StorageFacts
    disk:   StorageDisk
    cache:  StorageInMemory


class JobSummaryAnthropic(BaseModel):
    input_tokens: int = Field(..., examples=[21900])
    output_tokens: int = Field(..., examples=[580])
    cache_create_tokens: int = Field(..., examples=[68])
    cache_read_tokens: int = Field(..., examples=[4200])
    cost_usd: float = Field(..., examples=[0.0202])
    no_cache_baseline_usd: float = Field(..., description="What this would have cost without prompt caching.", examples=[0.0235])
    saved_usd: float = Field(..., examples=[0.0033])
    saved_pct: float = Field(..., examples=[14.0])


class JobSummaryOpenAI(BaseModel):
    embedding_tokens: int = Field(..., examples=[1574])
    cost_usd: float = Field(..., examples=[0.0002])


class JobSummaryStage(BaseModel):
    stage_id: int
    name: str
    duration_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


class JobSummary(BaseModel):
    """Consolidated cost/token/time totals for one ingestion job."""
    job_id: str
    pipeline: str | None = Field(None, examples=["agent"])
    filename: str | None = Field(None, examples=["02_financial_model.xlsx"])
    status: str = Field(..., examples=["completed"])
    wall_time_s: float = Field(..., description="Total elapsed time in seconds.", examples=[11.2])
    iterations: int | None = Field(None, description="Agent turns (Mode D only).", examples=[5])

    anthropic: JobSummaryAnthropic
    openai: JobSummaryOpenAI

    total_cost_usd: float = Field(..., description="Anthropic + OpenAI combined.", examples=[0.0204])
    total_tokens: int = Field(..., description="All input + output tokens summed across both providers.", examples=[22480])

    stages: list[JobSummaryStage] = Field(..., description="Per-stage breakdown in order.")


# ── Inspect endpoints — full storage drill-down ──────────────────────────────


class InspectChunkItem(BaseModel):
    chunk_id: str = Field(..., examples=["873141fe_custom_c0042"])
    text: str = Field(..., description="Full chunk text.")
    token_count: int | None = Field(None, examples=[412])
    page: int | None = Field(None, examples=[3])
    heading_path: str | None = Field(None, examples=["Section 2 · Revenue"])
    chunk_type: str | None = Field(None, examples=["prose", "table_summary", "ocr_prose"])
    table_name: str | None = Field(None, examples=["doc_table_3"])
    doc_id: str | None = Field(None)
    vector_preview: list[float] = Field(
        default_factory=list,
        description="First 8 dims of the stored vector — sanity check that embeddings landed.",
    )
    has_vector: bool = Field(..., description="Whether a real 1536-d vector is attached.")


class InspectChunksResponse(BaseModel):
    job_id: str
    total: int = Field(..., description="Total chunks matching the filter (across all pages).")
    offset: int
    limit: int
    chunk_types: list[str] = Field(default_factory=list, description="All distinct chunk_type values present.")
    items: list[InspectChunkItem]


class InspectSqlRow(BaseModel):
    row_index: int = Field(..., description="0-based row index within the table.")
    cells: dict[str, Any] = Field(..., description="Column-name → cell value map.")


class InspectSqlResponse(BaseModel):
    job_id: str
    table_name: str
    columns: list[str]
    total: int
    offset: int
    limit: int
    rows: list[InspectSqlRow]


class InspectKgNode(BaseModel):
    key: str = Field(..., description="The node key as stored in NetworkX.", examples=["Table:doc_table_3"])
    type: str = Field(..., description="Node type: document, table, chunk, or entity.", examples=["table"])
    label: str | None = Field(None, description="For entity nodes — the entity LABEL (PERSON, ORG, …).")
    text: str | None = Field(None, description="Display text — entity text, chunk_id, table_name, etc.")
    attrs: dict[str, Any] = Field(default_factory=dict, description="All other NetworkX node attributes.")
    degree: int = Field(..., description="Number of edges touching this node.")


class InspectKgEdge(BaseModel):
    source: str
    target: str
    weight: float | int = Field(1)
    rel: str | None = Field(None, description="Relationship label if set (contains, mentions, co-occurrence, summarized_by).")


class InspectKgNodeDetail(BaseModel):
    node: InspectKgNode
    neighbours: list[InspectKgNode] = Field(default_factory=list)
    edges: list[InspectKgEdge] = Field(default_factory=list)


class InspectKgResponse(BaseModel):
    job_id: str
    total_nodes: int
    total_edges: int
    node_types: dict[str, int] = Field(..., description="Count of nodes by type — {document: 1, table: 6, chunk: 27, entity: 41}.")
    offset: int
    limit: int
    items: list[InspectKgNode]
    detail: InspectKgNodeDetail | None = Field(None, description="Set when ?focus=<node_key> is passed.")


class StageEventDoc(BaseModel):
    """Schema of WebSocket events streamed over /ws/{job_id}.

    NOT used for request/response validation — documents the message shape
    that frontend clients should expect on the WS channel.
    """
    job_id: str = Field(..., examples=["873141fe-1c5c-4ad3-b279-5b7ad9cf3296"])
    pipeline: Literal["custom", "docling", "agent"] = Field(..., examples=["custom"])
    stage_id: int = Field(
        ...,
        description="Stage number within the pipeline. Mode A: 1–12, Mode B: 1–9, "
                    "Mode D (agent): dynamic.",
        examples=[7],
    )
    stage_name: str = Field(..., examples=["Embedding"])
    status: Literal["started", "running", "completed", "error"] = Field(..., examples=["completed"])
    timestamp_ms: float = Field(..., description="Unix timestamp in milliseconds.", examples=[1747800600000.0])
    duration_ms: float | None = Field(None, description="Stage duration; null while running.", examples=[1843.0])
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Stage-specific output. Schema varies by stage. For agent stages, "
                    "includes `tool`, `tool_input`, `tool_result`, `reasoning`. For "
                    "heartbeats, includes `_heartbeat: true` and `elapsed_ms`.",
    )
    verification: dict[str, Any] | None = Field(
        None,
        description="L1 verification snapshot — pass/fail per stage check.",
    )
