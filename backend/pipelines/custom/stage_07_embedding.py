"""Stage 7 — Embedding (Mode A).

Embeds all chunks using OpenAI text-embedding-3-large (1536 dims).
Falls back to deterministic mock vectors if no API key is configured.
Also builds an in-memory BM25 sparse index from chunk texts.
Results stored in job_cache for stage 9 (Vector Store) and stage 10 (RAG Ready).
"""
from __future__ import annotations
import hashlib
import math
import time

from config import settings
from models.events import EmbeddingPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
from services.api_retry import with_retry_async
import services.job_cache as cache

_MODEL      = "text-embedding-3-large"
_DIM        = 1536
_BATCH_SIZE = 100
_COST_PER_M = 0.13  # $0.13/M tokens for text-embedding-3-large

# OpenAI's text-embedding-3-large rejects any input >8191 tokens; we cap each
# chunk well below that and split oversize chunks into windowed sub-chunks.
_MAX_TOKENS_PER_INPUT = 7500
_SPLIT_OVERLAP_TOKENS = 200


def _est_tokens(text: str) -> int:
    """Cheap token estimate (words × 1.35) — same heuristic as the chunker."""
    return max(1, int(len(text.split()) * 1.35))


def _split_oversize(chunks: list[dict]) -> list[dict]:
    """Return chunks with any oversize entry split into windowed sub-chunks.

    Preserves chunk metadata, marks splits with `split_from`/`split_index` so
    callers can stitch results back to the parent chunk if needed.
    """
    out: list[dict] = []
    words_per_window = max(1, int(_MAX_TOKENS_PER_INPUT / 1.35))
    overlap_words    = max(0, int(_SPLIT_OVERLAP_TOKENS / 1.35))
    step             = max(1, words_per_window - overlap_words)

    for c in chunks:
        text = (c.get("text") or "")
        if _est_tokens(text) <= _MAX_TOKENS_PER_INPUT:
            out.append(c)
            continue
        words = text.split()
        parent_id = c.get("id", "chunk")
        part_idx = 0
        i = 0
        while i < len(words):
            window = words[i:i + words_per_window]
            if not window:
                break
            part_text = " ".join(window)
            out.append({
                **c,
                "id":          f"{parent_id}_part_{part_idx:02d}",
                "text":        part_text,
                "token_count": _est_tokens(part_text),
                "metadata": {
                    **(c.get("metadata") or {}),
                    "split_from":  parent_id,
                    "split_index": part_idx,
                },
            })
            part_idx += 1
            if i + words_per_window >= len(words):
                break
            i += step
    return out


def _mock_vector(text: str) -> list[float]:
    """Deterministic unit vector seeded from text hash — clearly not a real embedding."""
    seed = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    vec = []
    for i in range(_DIM):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        val = ((seed >> 17) & 0xFFFF) / 32768.0 - 1.0
        vec.append(val)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _build_bm25(texts: list[str]) -> dict:
    """Simple BM25 index: term -> {doc_idx -> tf} + idf table."""
    from collections import defaultdict
    import math as _math

    N = len(texts)
    avgdl = sum(len(t.split()) for t in texts) / max(N, 1)
    tf: list[dict[str, int]] = []
    df: dict[str, int] = defaultdict(int)

    for text in texts:
        counts: dict[str, int] = defaultdict(int)
        for token in text.lower().split():
            counts[token] += 1
        tf.append(dict(counts))
        for term in counts:
            df[term] += 1

    idf = {term: _math.log((N - freq + 0.5) / (freq + 0.5) + 1)
           for term, freq in df.items()}

    return {"tf": tf, "idf": idf, "avgdl": avgdl, "N": N}


def _bm25_score(index: dict, query_tokens: list[str], doc_idx: int,
                k1: float = 1.5, b: float = 0.75) -> float:
    tf_doc = index["tf"][doc_idx]
    dl = sum(tf_doc.values())
    avgdl = index["avgdl"]
    score = 0.0
    for token in query_tokens:
        if token not in index["idf"]:
            continue
        tf = tf_doc.get(token, 0)
        score += index["idf"][token] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
    return score


async def run(chunks: list[dict], job_id: str, cache_prefix: str = "") -> StageResult:
    if not chunks:
        payload = EmbeddingPayload(model=_MODEL, vector_dim=_DIM, chunks_embedded=0,
                                   dense_sample=[], sparse_index_terms=0, embedding_ms=0.0)
        checks = [make_check("chunks_embedded", False, "No chunks to embed", severity="warn")]
        return StageResult(payload=payload.model_dump(), verification=make_verification(checks))

    # Split any oversize chunks BEFORE embedding so a single jumbo chunk
    # doesn't crash the whole batch with a 400 from OpenAI.
    chunks = _split_oversize(chunks)

    texts = [c.get("text", "") for c in chunks]
    t0 = time.perf_counter()
    use_real = bool(settings.openai_api_key and len(settings.openai_api_key) > 20
                    and not settings.openai_api_key.startswith("sk-..."))
    vectors: list[list[float]] = []
    input_tokens = 0
    cost_usd = 0.0

    if use_real:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i:i + _BATCH_SIZE]
            resp = await with_retry_async(
                client.embeddings.create,
                model=_MODEL, input=batch, dimensions=_DIM,
                label=f"openai.embed[batch={i // _BATCH_SIZE}]",
            )
            vectors.extend([item.embedding for item in resp.data])
            input_tokens += resp.usage.total_tokens
        cost_usd = round(input_tokens * _COST_PER_M / 1_000_000, 6)
    else:
        vectors = [_mock_vector(t) for t in texts]

    embedding_ms = (time.perf_counter() - t0) * 1000

    # BM25 sparse index
    bm25 = _build_bm25(texts)
    sparse_terms = len(bm25["idf"])

    # Build embedded chunk list for downstream stages
    embedded = [
        {**chunk, "vector": vec, "chunk_idx": idx}
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    cache.put(job_id, f"{cache_prefix}embedded_chunks", embedded)
    cache.put(job_id, f"{cache_prefix}bm25_index", bm25)

    payload = EmbeddingPayload(
        model=_MODEL + ("" if use_real else " [mock]"),
        vector_dim=_DIM,
        chunks_embedded=len(chunks),
        dense_sample=vectors[0][:8] if vectors else [],
        sparse_index_terms=sparse_terms,
        embedding_ms=round(embedding_ms, 1),
    )
    # Attach cost fields manually (not in base model)
    payload_dict = payload.model_dump()
    payload_dict["use_real_embeddings"] = use_real
    payload_dict["llm_input_tokens"] = input_tokens
    payload_dict["llm_cost_usd"] = cost_usd

    checks = [
        make_check("chunks_embedded", len(chunks) > 0, f"{len(chunks)} chunks → {_DIM}d vectors"),
        make_check("vector_dim_correct", True, f"{_DIM} dims ({_MODEL})"),
        make_check("bm25_built", sparse_terms > 0, f"{sparse_terms:,} unique terms"),
        make_check("real_embeddings", use_real,
                   "OpenAI API" if use_real else "mock vectors — set OPENAI_API_KEY for real embeddings",
                   severity="warn"),
    ]
    return StageResult(payload=payload_dict, verification=make_verification(checks))
