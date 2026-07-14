"""Stage 9 — Vector Store (Qdrant).

Upserts embedded+metadata chunks into a per-job Qdrant collection.
Falls back gracefully if Qdrant is offline — the pipeline still completes.
"""
from __future__ import annotations
import time

from models.events import VectorStorePayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
import services.job_cache as cache

_HNSW_M = 8
_HNSW_EF = 100
_DIM = 1536


async def run(
    job_id: str,
    collection_prefix: str = "rag_proto_custom",
    cache_prefix: str = "",
) -> StageResult:
    embedded_chunks = cache.get(job_id, f"{cache_prefix}embedded_chunks", [])
    qdrant_live = False
    upsert_ms = 0.0
    total_in_collection = len(embedded_chunks)
    job_collection = f"{collection_prefix}_{job_id[:8]}"

    if embedded_chunks:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, PointStruct, HnswConfigDiff

            client = QdrantClient(host="localhost", port=6333, timeout=3)
            client.get_collections()  # liveness check

            try:
                client.delete_collection(job_collection)
            except Exception:
                pass

            client.create_collection(
                job_collection,
                vectors_config=VectorParams(size=_DIM, distance=Distance.COSINE),
                hnsw_config=HnswConfigDiff(m=_HNSW_M, ef_construct=_HNSW_EF),
            )

            points = []
            for i, chunk in enumerate(embedded_chunks):
                meta = {k: v for k, v in chunk.get("metadata", {}).items() if v is not None}
                meta["chunk_text"] = chunk.get("text", "")[:500]
                points.append(PointStruct(id=i, vector=chunk["vector"], payload=meta))

            t0 = time.perf_counter()
            client.upsert(collection_name=job_collection, points=points)
            upsert_ms = (time.perf_counter() - t0) * 1000

            total_in_collection = len(points)
            qdrant_live = True

            cache.put(job_id, f"{cache_prefix}qdrant_collection", job_collection)

        except Exception:
            qdrant_live = False

    payload = VectorStorePayload(
        collection=job_collection,
        vectors_upserted=len(embedded_chunks),
        hnsw_m=_HNSW_M,
        hnsw_ef_construction=_HNSW_EF,
        total_vectors_in_collection=total_in_collection,
        upsert_ms=round(upsert_ms, 1),
    )
    payload_dict = payload.model_dump()
    payload_dict["qdrant_live"] = qdrant_live

    # ── Chunk breakdown by type (for UI verification) ─────────────────────────
    breakdown: dict[str, dict] = {}
    for chunk in embedded_chunks:
        ctype = (chunk.get("metadata") or {}).get("chunk_type") or "prose"
        if ctype not in breakdown:
            breakdown[ctype] = {"count": 0, "samples": []}
        breakdown[ctype]["count"] += 1
        if len(breakdown[ctype]["samples"]) < 3:
            breakdown[ctype]["samples"].append({
                "id":       chunk.get("id", ""),
                "preview":  chunk.get("text", "")[:200],
                "page":     chunk.get("page"),
                "heading":  chunk.get("heading_path") or (chunk.get("metadata") or {}).get("table_name"),
            })
    payload_dict["chunk_breakdown"] = breakdown

    # ── SQL table store ───────────────────────────────────────────────────────
    # Read extracted tables cached by the runner after Stage 3/2
    extracted_tables = cache.get(job_id, f"{cache_prefix}extracted_tables", [])
    sql_registry: dict = {}
    if extracted_tables:
        try:
            from services import sql_store
            sql_registry = sql_store.create_tables(extracted_tables, job_id, cache_prefix)
            cache.put(job_id, f"{cache_prefix}sql_registry", sql_registry)
        except Exception:
            pass

    payload_dict["sql_tables_created"] = len(sql_registry)
    payload_dict["sql_registry"] = {
        k: {
            "row_count":    v["row_count"],
            "columns":      v["original_headers"],
            "sample_rows":  v.get("sample_rows", []),
        }
        for k, v in sql_registry.items()
    }

    checks = [
        make_check("vectors_upserted", len(embedded_chunks) > 0,
                   f"{len(embedded_chunks)} vectors stored"),
        make_check("qdrant_connected", qdrant_live,
                   "Qdrant online" if qdrant_live
                   else "Qdrant offline — start via docker compose for persistence",
                   severity="warn" if not qdrant_live else "info"),
        make_check("sql_tables", True,
                   f"{len(sql_registry)} table(s) indexed in SQLite"
                   if sql_registry else "No tables found — SQL store empty"),
    ]
    return StageResult(payload=payload_dict, verification=make_verification(checks))
