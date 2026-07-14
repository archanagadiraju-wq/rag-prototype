from pathlib import Path
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_prefix: str = "rag_proto"
    redis_url: str = "redis://localhost:6379"

    embedding_model: str = "text-embedding-3-large"
    embedding_batch_size: int = 100
    embedding_dim: int = 1536

    hnsw_m: int = 8
    hnsw_ef_construction: int = 100
    hnsw_ef_search: int = 100

    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 64
    chunk_min_tokens: int = 20

    docling_ocr_backend: str = "easyocr"
    docling_table_mode: str = "accurate"
    docling_cache_dir: str = "./.docling_cache"

    l2_verify_sample_chars: int = 800
    l2_verify_chunk_sample: int = 3
    ground_truth_dir: str = "./demo_docs"

    max_file_size_mb: int = 50
    max_pages: int = 200
    log_level: str = "INFO"

    # Persistent storage root — leave empty to auto-detect relative to backend/
    data_dir: str = ""

    # Route /ask questions through a Claude SQL-generator alongside the facts
    # pre-pass and vector retrieval. Enabled by default after the v2 router
    # rebuild: column descriptions injected, aggregates gated, fact-shaped
    # questions explicitly skipped, and a sanity check that rejects SQL
    # results whose magnitude doesn't match the retrieved chunks. To disable:
    # set ENABLE_SQL_ROUTING=false in .env.
    enable_sql_routing: bool = True

    # Listwise Claude reranker on top-15 RRF candidates → pick top-5 to feed
    # the answer LLM. Catches relevant chunks the RRF score missed (RRF is
    # bag-of-features; reranker reads the question and the chunk together).
    # Adds ~$0.005 + ~2s latency per /ask. Disable via ENABLE_RERANKER=false.
    enable_reranker: bool = True

    # Facts pre-pass: match question against facts.json labels by embedding
    # cosine and inject the matched fact (typed value + source quote) as
    # the top-of-context block. Disable to A/B test the system without the
    # facts layer (Vector+BM25+KG+reranker only).
    enable_facts_route: bool = True

    class Config:
        env_file = str(_ENV_FILE)
        extra = "ignore"


settings = Settings()
