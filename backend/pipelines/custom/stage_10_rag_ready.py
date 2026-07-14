"""Stage 11 — RAG Ready: 10-Question Multi-Storage Showcase.

Generates 10 document-specific questions that are routed to the most
appropriate storage mechanism:
  • vector   — HNSW + BM25 + KG hybrid (semantic / keyword / entity)
  • sql      — SQLite aggregation over extracted tables (numerical)
  • kg       — knowledge-graph traversal (entity relationships)
  • sql+vec  — SQL result injected as additional context for the LLM

Dynamically generated SQL questions replace the generic bank entries
when the document actually contains structured tables.
"""
from __future__ import annotations
import math
import time
from typing import Any

from models.events import RAGReadyPayload, RetrievalResult
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
import services.job_cache as cache
import services.sql_store as sql_store

_TOP_K    = 5
_COMP_K   = 3
_RRF_K    = 60
_GRAPH_W  = 0.25

# ── Question banks per document type (10 each) ────────────────────────────────

_Q_BANK: dict[str, list[dict]] = {
    "research_paper": [
        {"q": "What was the primary research hypothesis and what outcome was expected?",    "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What study design and methodology were used, and why?",                      "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What specific biomarkers, compounds, or named interventions appear?",        "route": "vector", "type": "keyword",   "difficulty": "medium"},
        {"q": "Who are the principal investigators and their institutional affiliations?",   "route": "kg",     "type": "entity",    "difficulty": "medium"},
        {"q": "Which funding bodies or industry partners are acknowledged?",                 "route": "kg",     "type": "entity",    "difficulty": "medium"},
        {"q": "What were the sample sizes and group allocations across all study arms?",     "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "What numerical outcome measures or p-values are reported in the results?",    "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "How do quantitative results compare across treatment and control groups?",    "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
        {"q": "What study limitations and threats to validity are explicitly acknowledged?", "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What evidence from the data directly supports the main conclusion?",          "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
    ],
    "financial_report": [
        {"q": "What is the company's overall strategic narrative and growth priorities?",   "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What specific financial metrics (EBITDA, FCF, ROE) are highlighted?",       "route": "vector", "type": "keyword",   "difficulty": "medium"},
        {"q": "Who are the key executives and board members mentioned?",                    "route": "kg",     "type": "entity",    "difficulty": "easy"},
        {"q": "What subsidiaries, JVs, or business segments are referenced?",              "route": "kg",     "type": "entity",    "difficulty": "medium"},
        {"q": "What were total revenues and year-over-year growth rates by segment?",      "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "What are the operating margins and largest cost categories?",               "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "How do reported financials compare to stated strategic targets?",           "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
        {"q": "What is the debt structure and current liquidity position?",               "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
        {"q": "What risks and regulatory uncertainties are disclosed?",                   "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What forward-looking guidance or targets are given for next period?",      "route": "vector", "type": "keyword",   "difficulty": "medium"},
    ],
    "contract": [
        {"q": "What are the core obligations of each contracting party?",                 "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What specific SLAs, KPIs, or performance thresholds are defined?",        "route": "vector", "type": "keyword",   "difficulty": "medium"},
        {"q": "Which legal entities, jurisdictions, or governing laws are named?",       "route": "kg",     "type": "entity",    "difficulty": "medium"},
        {"q": "Who are the authorised signatories and their designated roles?",          "route": "kg",     "type": "entity",    "difficulty": "easy"},
        {"q": "What payment amounts, schedules, or fee structures are specified?",       "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "What penalty amounts or liquidated damages are explicitly defined?",      "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "How do financial obligations relate to performance requirements?",         "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
        {"q": "What are the termination conditions and their contractual consequences?",  "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What IP ownership, data rights, or confidentiality clauses are included?","route": "vector", "type": "keyword",   "difficulty": "hard"},
        {"q": "How is dispute resolution structured and under which jurisdiction?",       "route": "vector", "type": "semantic",  "difficulty": "medium"},
    ],
    "technical_spec": [
        {"q": "What is the overall system architecture and principal components?",        "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What APIs, protocols, or integration standards are specified?",            "route": "vector", "type": "keyword",   "difficulty": "medium"},
        {"q": "What third-party libraries, vendors, or compliance frameworks are cited?", "route": "kg",     "type": "entity",    "difficulty": "medium"},
        {"q": "Which teams or owners are responsible for individual components?",         "route": "kg",     "type": "entity",    "difficulty": "easy"},
        {"q": "What performance benchmarks, rate limits, or throughput specs apply?",    "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "What capacity limits, storage quotas, or timeout values are defined?",    "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "How do performance requirements constrain the architectural choices?",    "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
        {"q": "What authentication, authorisation, or encryption requirements are stated?","route": "vector","type": "keyword",   "difficulty": "medium"},
        {"q": "What error handling, fallback, and recovery procedures are specified?",   "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What versioning, compatibility, and migration requirements exist?",       "route": "vector", "type": "semantic",  "difficulty": "medium"},
    ],
    "presentation": [
        {"q": "What is the core value proposition being pitched?",                       "route": "vector", "type": "semantic",  "difficulty": "easy"},
        {"q": "What specific product features or technical capabilities are highlighted?","route": "vector", "type": "keyword",   "difficulty": "medium"},
        {"q": "What partnerships, investors, or reference customers are mentioned?",     "route": "kg",     "type": "entity",    "difficulty": "medium"},
        {"q": "Who is the founding team and what credentials are stated?",               "route": "kg",     "type": "entity",    "difficulty": "easy"},
        {"q": "What TAM/SAM/SOM figures or market size estimates are cited?",            "route": "sql",    "type": "numerical", "difficulty": "hard"},
        {"q": "What revenue targets, unit economics, or financial projections are given?","route": "sql",   "type": "numerical", "difficulty": "hard"},
        {"q": "How do market figures support the stated funding ask?",                   "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
        {"q": "What competitive differentiation is claimed and on what basis?",          "route": "vector", "type": "semantic",  "difficulty": "medium"},
        {"q": "What technical moats or IP advantages are mentioned?",                    "route": "vector", "type": "keyword",   "difficulty": "medium"},
        {"q": "What is the go-to-market strategy and proposed timeline?",               "route": "vector", "type": "semantic",  "difficulty": "medium"},
    ],
}

_DEFAULT_QUESTIONS: list[dict] = [
    {"q": "What are the main themes and key conclusions of this document?",              "route": "vector", "type": "semantic",  "difficulty": "easy"},
    {"q": "What specific technical terms, acronyms, or domain jargon are used?",        "route": "vector", "type": "keyword",   "difficulty": "medium"},
    {"q": "Who are the key people, organisations, or entities mentioned?",              "route": "kg",     "type": "entity",    "difficulty": "medium"},
    {"q": "What numerical values, targets, or thresholds appear most significant?",     "route": "sql",    "type": "numerical", "difficulty": "hard"},
    {"q": "What is the document's primary objective or recommended action?",            "route": "vector", "type": "semantic",  "difficulty": "easy"},
    {"q": "What constraints, requirements, or mandatory conditions are stated?",        "route": "vector", "type": "keyword",   "difficulty": "medium"},
    {"q": "How do the named entities relate to each other and to the central topic?",   "route": "kg",     "type": "entity",    "difficulty": "hard"},
    {"q": "What measurable outcomes or performance metrics are tracked?",               "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
    {"q": "What risks, caveats, or exceptions are explicitly noted?",                   "route": "vector", "type": "semantic",  "difficulty": "medium"},
    {"q": "What quantitative evidence supports the document's main claims?",            "route": "sql+vec","type": "hybrid",    "difficulty": "hard"},
]


# ── SQL question generator ────────────────────────────────────────────────────

_NUMERIC_HINTS = {
    "amount","total","value","count","n","mean","avg","score","rate","pct",
    "%","$","revenue","cost","price","number","quantity","size","weight",
    "age","days","ratio","margin","growth","sales","profit","loss",
}
_CATEGORY_HINTS = {
    "group","type","category","segment","treatment","arm","product",
    "region","department","class","status","name","stage","quarter","year",
}


def _build_sql_questions(registry: dict, enriched_tables: list[dict]) -> list[dict]:
    """Generate SQL questions for every table in the registry.

    Uses Claude's description (from Stage 6) to write a meaningful question
    rather than a generic one. Covers ALL tables — no hard cap.
    """
    # Map table name → Claude description
    desc_map: dict[str, str] = {
        f"doc_table_{i + 1}": (tbl.get("description") or "").strip()
        for i, tbl in enumerate(enriched_tables)
    }

    questions: list[dict] = []

    for tname, info in registry.items():
        cols    = info["columns"]
        orig    = info["original_headers"]
        row_cnt = info["row_count"]
        if not cols or row_cnt == 0:
            continue

        desc     = desc_map.get(tname, "")
        context  = desc if desc else f"the data in {tname}"

        num_cols = [(c, h) for c, h in zip(cols, orig)
                    if any(kw in h.lower() for kw in _NUMERIC_HINTS)]
        cat_cols = [(c, h) for c, h in zip(cols, orig)
                    if any(kw in h.lower() for kw in _CATEGORY_HINTS)]

        if num_cols:
            nc, nh = num_cols[0]
            q_text = (
                f"From {context}: what are the maximum, minimum, and average "
                f"'{nh}' values across all {row_cnt} entries, and which row "
                f"has the highest value?"
            )
            sql = (
                f'SELECT '
                f'MAX(CAST(REPLACE(REPLACE("{nc}",",",""),"$","") AS REAL)) AS max_val, '
                f'MIN(CAST(REPLACE(REPLACE("{nc}",",",""),"$","") AS REAL)) AS min_val, '
                f'ROUND(AVG(CAST(REPLACE(REPLACE("{nc}",",",""),"$","") AS REAL)),2) AS avg_val '
                f'FROM {tname} '
                f'WHERE "{nc}" != "" AND "{nc}" IS NOT NULL'
            )
            questions.append({
                "q": q_text, "route": "sql", "type": "numerical",
                "difficulty": "hard", "sql": sql, "table": tname,
            })

        if cat_cols and num_cols:
            cc, ch = cat_cols[0]
            nc, nh = num_cols[0]
            q_text = (
                f"From {context}: breaking down by '{ch}', which category has "
                f"the highest average '{nh}' and how do all groups compare?"
            )
            sql = (
                f'SELECT "{cc}", COUNT(*) AS count, '
                f'ROUND(AVG(CAST(REPLACE(REPLACE("{nc}",",",""),"$","") AS REAL)),2) AS avg_val '
                f'FROM {tname} '
                f'WHERE "{nc}" != "" '
                f'GROUP BY "{cc}" ORDER BY avg_val DESC'
            )
            questions.append({
                "q": q_text, "route": "sql+vec", "type": "hybrid",
                "difficulty": "hard", "sql": sql, "table": tname,
            })

    return questions


# ── Retrieval helpers ─────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _qdrant_hnsw_search(
    job_id: str,
    query_vec: list[float],
    k: int,
    cache_prefix: str = "",
    ef_search: int | None = None,
) -> list[tuple[int, float]] | None:
    """Query Qdrant's HNSW index. Returns [(chunk_idx, score), …] or None on miss.

    Point IDs in the collection are integer chunk-list indices (assigned at
    upsert time in stage_09_vector_store), so the IDs map directly back to
    positions in the in-memory `embedded` list.

    Returns None (not raise) when:
      • Qdrant is offline / not reachable
      • The collection doesn't exist for this job
      • Any unexpected error
    Caller falls back to brute-force cosine when None.
    """
    collection = cache.get(job_id, f"{cache_prefix}qdrant_collection")
    if not collection:
        return None
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333, timeout=3)
        kwargs = {"collection_name": collection, "query": query_vec, "limit": k}
        if ef_search is not None:
            from qdrant_client.models import SearchParams
            kwargs["search_params"] = SearchParams(hnsw_ef=ef_search)
        response = client.query_points(**kwargs)
        return [(int(p.id), float(p.score)) for p in response.points]
    except Exception:
        return None


def _bm25_score(index: dict, tokens: list[str], doc_idx: int,
                k1: float = 1.5, b: float = 0.75) -> float:
    tf_doc = index["tf"][doc_idx]
    dl = sum(tf_doc.values())
    avgdl = index["avgdl"] or 1
    score = 0.0
    for t in tokens:
        if t not in index["idf"]:
            continue
        tf = tf_doc.get(t, 0)
        score += index["idf"][t] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
    return score


def _mock_vec(text: str, dim: int = 1536) -> list[float]:
    import hashlib
    seed = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    vec = []
    for _ in range(dim):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        val = ((seed >> 17) & 0xFFFF) / 32768.0 - 1.0
        vec.append(val)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _retrieve(
    embedded: list[dict],
    query_vec: list[float],
    bm25_idx: dict | None,
    qtokens: list[str],
    kg: Any | None,
    chunk_entity_map: dict[str, list[str]],
    mode: str,
    k: int = _COMP_K,
    job_id: str | None = None,
    cache_prefix: str = "",
) -> list[dict]:
    n = len(embedded)

    # Dense scoring: prefer Qdrant HNSW search (sub-linear, scales to large
    # collections) over the in-memory O(n) cosine sweep. Fall back to the
    # brute-force path when Qdrant is offline, the collection is missing,
    # or for very small N where the overhead isn't worth it.
    dense: list[tuple[int, float]] = []
    used_hnsw = False
    if job_id and n > 0:
        hnsw_hits = _qdrant_hnsw_search(job_id, query_vec, k=max(k * 4, 20), cache_prefix=cache_prefix)
        if hnsw_hits is not None:
            # Qdrant returns COSINE similarity in [-1, 1] (same metric as
            # _cosine on unit vectors), so scores are directly comparable.
            dense = hnsw_hits
            used_hnsw = True

    if not used_hnsw:
        dense = [(i, _cosine(query_vec, ch["vector"])) for i, ch in enumerate(embedded)]

    dense.sort(key=lambda x: -x[1])
    dense_rank = {idx: r + 1 for r, (idx, _) in enumerate(dense)}
    dense_map  = dict(dense)
    max_dense  = max((abs(s) for _, s in dense), default=1.0) or 1.0

    # When HNSW returns only the top-k chunks (not all n), the RRF loop below
    # iterates over every chunk index and will KeyError on chunks that didn't
    # make HNSW's cut. Backfill with a worst-case rank/score so those chunks
    # still get a (tiny) RRF contribution and can never be the top result on
    # dense alone — but at least the loop doesn't crash.
    if used_hnsw and len(dense) < n:
        worst_rank = len(dense) + 1
        for i in range(n):
            if i not in dense_rank:
                dense_rank[i] = worst_rank
                dense_map[i] = 0.0

    if mode == "hnsw":
        results = []
        for rank, (idx, score) in enumerate(dense[:k], 1):
            ch = embedded[idx]
            d_norm = round(max(0.0, min(1.0, (score + 1) / 2)), 4)
            results.append({
                "rank": rank, "idx": idx,
                "chunk_id": ch.get("metadata", {}).get("chunk_id", f"c{idx:04d}"),
                "text": ch.get("text", "")[:200],
                "dense_score": d_norm, "sparse_score": 0.0, "graph_score": 0.0,
                "final_score": d_norm,
            })
        return results

    if bm25_idx:
        sparse = [(i, _bm25_score(bm25_idx, qtokens, i)) for i in range(n)]
    else:
        sparse = [(i, 0.0) for i in range(n)]
    sparse.sort(key=lambda x: -x[1])
    sparse_rank = {idx: r + 1 for r, (idx, _) in enumerate(sparse)}
    sparse_map  = dict(sparse)
    max_sparse  = max((s for _, s in sparse), default=1.0) or 1.0

    rrf_list = sorted(
        [(i, 1.0 / (_RRF_K + dense_rank[i]) + 1.0 / (_RRF_K + sparse_rank[i]))
         for i in range(n)],
        key=lambda x: -x[1],
    )
    rrf_map = dict(rrf_list)

    if mode == "hybrid":
        results = []
        for rank, (idx, rrf_s) in enumerate(rrf_list[:k], 1):
            ch = embedded[idx]
            d_norm  = round(max(0.0, min(1.0, (dense_map[idx] + 1) / 2)), 4)
            sp_norm = round(max(0.0, min(1.0, sparse_map[idx] / max_sparse)), 4)
            results.append({
                "rank": rank, "idx": idx,
                "chunk_id": ch.get("metadata", {}).get("chunk_id", f"c{idx:04d}"),
                "text": ch.get("text", "")[:200],
                "dense_score": d_norm, "sparse_score": sp_norm, "graph_score": 0.0,
                "final_score": round(rrf_s, 6),
            })
        return results

    # full_hybrid
    graph_scores: dict[int, float] = {i: 0.0 for i in range(n)}
    if kg and chunk_entity_map:
        anchor_entities: set[str] = set()
        for idx, _ in rrf_list[:3]:
            chunk_id = embedded[idx].get("metadata", {}).get("chunk_id", "")
            for ent in chunk_entity_map.get(chunk_id, []):
                anchor_entities.add(ent)
        if anchor_entities:
            for i, ch in enumerate(embedded):
                chunk_id = ch.get("metadata", {}).get("chunk_id", "")
                shared = len(set(chunk_entity_map.get(chunk_id, [])) & anchor_entities)
                if shared:
                    graph_scores[i] = min(1.0, shared / len(anchor_entities))

    combined = sorted(
        [(i, rrf_map[i] + graph_scores[i] * _GRAPH_W) for i in range(n)],
        key=lambda x: -x[1],
    )
    results = []
    for rank, (idx, combined_s) in enumerate(combined[:k], 1):
        ch = embedded[idx]
        d_norm  = round(max(0.0, min(1.0, (dense_map[idx] + 1) / 2)), 4)
        sp_norm = round(max(0.0, min(1.0, sparse_map[idx] / max_sparse)), 4)
        g_norm  = round(graph_scores[idx], 4)
        results.append({
            "rank": rank, "idx": idx,
            "chunk_id": ch.get("metadata", {}).get("chunk_id", f"c{idx:04d}"),
            "text": ch.get("text", "")[:200],
            "dense_score": d_norm, "sparse_score": sp_norm, "graph_score": g_norm,
            "final_score": round(combined_s, 6),
        })
    return results


# ── Entity query builder (kept for primary result) ────────────────────────────

_STOPWORDS = {
    "the","a","an","is","in","of","to","and","or","for","this","that","with",
    "are","was","be","it","as","at","by","from","has","have","its","on","not",
    "but","if","so","we","our","their","they","will","can","may","also","been",
    "which","who","all","one","more","any","would","such","each","there","than",
    "into","other","about","when","up","out","no","two","time","new","use",
    "used","using","within","per","over","under",
}

_SEMANTIC_QUERIES: dict[str, str] = {
    "research_paper":   "What was the primary endpoint result and overall efficacy?",
    "financial_report": "What are the revenue projections and key growth metrics?",
    "contract":         "What are the payment terms and service level requirements?",
    "technical_spec":   "What are the API authentication and endpoint requirements?",
    "presentation":     "What is the funding ask and key business metrics?",
}
_DEFAULT_SEMANTIC = "What are the main findings, conclusions, and key takeaways?"


def _build_keyword_query(bm25_idx: dict | None) -> str:
    if not bm25_idx:
        return _DEFAULT_SEMANTIC
    idf = bm25_idx.get("idf", {})
    terms = sorted(
        [(t, s) for t, s in idf.items()
         if t not in _STOPWORDS and len(t) > 4 and t.isalpha()],
        key=lambda x: -x[1],
    )[:6]
    if not terms:
        return _DEFAULT_SEMANTIC
    term_str = " ".join(t for t, _ in terms[:4])
    return f"What information is provided about {term_str}?"


def _build_entity_query(kg: Any | None) -> tuple[str, str] | None:
    if not kg:
        return None
    try:
        _PREFERRED = {"PERSON": 0, "ORG": 1, "PRODUCT": 2, "LAW": 3, "FAC": 4}
        _GENERIC   = {
            "software","document","company","system","service","product",
            "report","data","information","management","development",
            "application","solution","process","support","team","group",
        }
        candidates = []
        for n, d in kg.nodes(data=True):
            if d.get("type") != "entity":
                continue
            label = d.get("label", "")
            text  = d.get("text", "").strip()
            if len(text) < 4 or text.lower() in _GENERIC:
                continue
            priority = _PREFERRED.get(label, 10)
            candidates.append((priority, -kg.degree(n), n, text, label))
        if not candidates:
            return None
        candidates.sort()
        _, _, _, top_text, top_label = candidates[0]
        if top_label == "PERSON":
            query = f"What role does {top_text} play and what are they responsible for?"
        elif top_label == "ORG":
            query = f"What is described about {top_text} and their involvement?"
        elif top_label == "PRODUCT":
            query = f"What details and specifications are given for {top_text}?"
        else:
            query = f"What information is provided about {top_text}?"
        return (query, top_text)
    except Exception:
        return None


# ── Question set composition ──────────────────────────────────────────────────

def _compose_questions(
    doc_type: str,
    sql_registry: dict,
    enriched_tables: list[dict],
) -> list[dict]:
    """Return exactly 10 questions with route annotations, customised to doc.

    SQL slots in the base question bank are filled with dynamically generated
    questions that cover ALL tables (not just the first 2), using Claude's
    description of each table to write a meaningful question.  If a document
    has more SQL questions than slots the extras are appended; the final list
    is always capped at 10.
    """
    base = [dict(q) for q in _Q_BANK.get(doc_type, _DEFAULT_QUESTIONS)]

    if sql_registry:
        dyn_sql  = _build_sql_questions(sql_registry, enriched_tables)
        sql_slots = [i for i, q in enumerate(base) if "sql" in q["route"]]

        # Fill existing SQL slots first
        for i, dq in enumerate(dyn_sql):
            if i < len(sql_slots):
                base[sql_slots[i]] = dq
            else:
                # Extra tables beyond the fixed slots: append before the cap
                base.append(dq)
    else:
        for q in base:
            if "sql" in q["route"]:
                q["route"] = "vector"
                q["sql_fallback"] = True

    return base[:10]


# ── Main run ──────────────────────────────────────────────────────────────────

async def run(job_id: str, doc_type: str = "", cache_prefix: str = "") -> StageResult:
    embedded         = cache.get(job_id, f"{cache_prefix}embedded_chunks", [])
    bm25_idx         = cache.get(job_id, f"{cache_prefix}bm25_index")
    kg               = cache.get(job_id, f"{cache_prefix}knowledge_graph")
    chunk_entity_map = cache.get(job_id, f"{cache_prefix}chunk_entity_map", {})
    sql_registry     = cache.get(job_id, f"{cache_prefix}sql_registry", {})
    enriched_tables  = cache.get(job_id, f"{cache_prefix}enriched_tables", [])

    semantic_query = _SEMANTIC_QUERIES.get(doc_type, _DEFAULT_SEMANTIC)
    entity_result  = _build_entity_query(kg)
    entity_subject = entity_result[1] if entity_result else None

    if not embedded:
        payload = RAGReadyPayload(
            test_query=semantic_query, retrieval_results=[],
            hybrid_search_ms=0, rerank_ms=0, total_retrieval_ms=0,
        )
        checks = [make_check("chunks_available", False, "No embedded chunks", severity="warn")]
        return StageResult(payload=payload.model_dump(), verification=make_verification(checks))

    t0 = time.perf_counter()

    # ── Compose 10 questions ─────────────────────────────────────────────────
    # In Compare mode (both pipelines run on the same job), the first pipeline
    # to reach this stage writes the question set to a *shared* (un-prefixed)
    # cache key; the second pipeline reuses it. This guarantees Mode A and
    # Mode B answer the IDENTICAL 10 questions for a fair side-by-side
    # comparison, even when their doc-type detection or table extraction would
    # otherwise produce slightly different banks.
    _SHARED_Q_KEY = "shared_questions"
    shared = cache.get(job_id, _SHARED_Q_KEY)
    if shared and shared.get("questions"):
        questions = [dict(q) for q in shared["questions"]]
    else:
        questions = _compose_questions(doc_type, sql_registry, enriched_tables)
        cache.put(job_id, _SHARED_Q_KEY, {
            "questions":   questions,
            "doc_type":    doc_type,
            "generated_by": cache_prefix or "custom",
        })

    # ── Embed all questions in one batch ─────────────────────────────────────
    q_texts = [q["q"] for q in questions]

    use_real = False
    query_vecs: list[list[float]] = []
    try:
        from config import settings
        if (settings.openai_api_key and len(settings.openai_api_key) > 20
                and not settings.openai_api_key.startswith("sk-...")):
            from openai import AsyncOpenAI
            from services.api_retry import with_retry_async
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await with_retry_async(
                client.embeddings.create,
                model="text-embedding-3-large",
                input=q_texts + [semantic_query],
                dimensions=1536,
                label="rag_ready.embed_questions",
            )
            query_vecs    = [item.embedding for item in resp.data[:-1]]
            sem_vec_final = resp.data[-1].embedding
            use_real      = True
    except Exception:
        pass

    if not query_vecs:
        query_vecs    = [_mock_vec(q) for q in q_texts]
        sem_vec_final = _mock_vec(semantic_query)

    embed_ms = (time.perf_counter() - t0) * 1000

    # ── Run retrieval for each question ───────────────────────────────────────
    showcase: list[dict] = []
    for q_info, q_vec in zip(questions, query_vecs):
        tr0 = time.perf_counter()
        route = q_info["route"]
        qtokens = q_info["q"].lower().split()

        # Vector retrieval (always run as baseline / primary for vector/kg/hybrid routes)
        vec_results = _retrieve(
            embedded, q_vec, bm25_idx, qtokens, kg, chunk_entity_map,
            "full_hybrid", k=_COMP_K,
            job_id=job_id, cache_prefix=cache_prefix,
        )

        # SQL retrieval
        sql_query = q_info.get("sql")
        sql_cols: list[str] | None  = None
        sql_rows: list[list] | None = None
        if "sql" in route and sql_query and sql_registry:
            try:
                sql_cols, sql_rows = sql_store.run_query(sql_query, job_id, cache_prefix)
                sql_rows = sql_rows[:8]
            except Exception as exc:
                sql_query = f"-- Error: {exc}"

        retrieval_ms = (time.perf_counter() - tr0) * 1000

        showcase.append({
            "index":       len(showcase) + 1,
            "question":    q_info["q"],
            "route":       route,
            "type":        q_info["type"],
            "difficulty":  q_info.get("difficulty", "medium"),
            "sql_fallback":q_info.get("sql_fallback", False),
            "table":       q_info.get("table"),
            "vector_results": [
                {"rank": r["rank"], "text": r["text"][:200], "chunk_id": r["chunk_id"],
                 "dense_score": r["dense_score"], "sparse_score": r["sparse_score"],
                 "graph_score": r["graph_score"]}
                for r in vec_results
            ],
            "sql_query":   sql_query,
            "sql_cols":    sql_cols,
            "sql_rows":    sql_rows,
            "retrieval_ms": round(retrieval_ms, 1),
        })

    # ── Cache for Stage 12 (LLM Answer) ──────────────────────────────────────
    cache.put(job_id, f"{cache_prefix}rag_queries", {
        "questions":       questions,
        "entity_subject":  entity_subject,
        "doc_type":        doc_type,
        # Legacy semantic / keyword for Stage 12 if it needs them
        "semantic":        semantic_query,
        "keyword":         _build_keyword_query(bm25_idx),
        "entity":          entity_result[0] if entity_result else None,
    })
    # Also cache showcase so Stage 12 can reuse SQL results
    cache.put(job_id, f"{cache_prefix}rag_showcase", showcase)

    # ── Primary semantic result (for Final Results tab) ───────────────────────
    primary = _retrieve(
        embedded, sem_vec_final, bm25_idx, semantic_query.lower().split(),
        kg, chunk_entity_map, "full_hybrid", k=_TOP_K,
        job_id=job_id, cache_prefix=cache_prefix,
    )
    primary_results = [
        RetrievalResult(
            chunk_id=r["chunk_id"], text=embedded[r["idx"]].get("text", "")[:400],
            dense_score=r["dense_score"], sparse_score=r["sparse_score"],
            graph_score=r["graph_score"],
            rrf_score=r["final_score"],
            rerank_score=round((r["dense_score"] + r["sparse_score"] + r["graph_score"]) / 3, 4),
            final_rank=r["rank"],
        )
        for r in primary
    ]

    total_ms = (time.perf_counter() - t0) * 1000

    # Summary stats
    routing_summary = {
        "total_questions": len(showcase),
        "vector_count":    sum(1 for q in showcase if q["route"] == "vector"),
        "kg_count":        sum(1 for q in showcase if q["route"] == "kg"),
        "sql_count":       sum(1 for q in showcase if q["route"] == "sql"),
        "hybrid_count":    sum(1 for q in showcase if "+" in q["route"]),
        "sql_available":   bool(sql_registry),
        "tables_found":    len(sql_registry),
    }

    graph_active  = bool(kg and chunk_entity_map)
    retrieval_mode = (
        "vector + BM25 + KG + SQL" if sql_registry and graph_active and bm25_idx
        else "vector + BM25 + KG" if graph_active and bm25_idx
        else "vector + BM25" if bm25_idx else "vector only"
    )

    payload = RAGReadyPayload(
        test_query=semantic_query,
        retrieval_results=[r.model_dump() for r in primary_results],
        hybrid_search_ms=round(embed_ms, 1),
        rerank_ms=0.0,
        total_retrieval_ms=round(total_ms, 1),
    )
    payload_dict = payload.model_dump()
    payload_dict["query_showcase"]    = showcase
    payload_dict["routing_summary"]   = routing_summary
    payload_dict["retrieval_mode"]    = retrieval_mode
    payload_dict["use_real_embeddings"] = use_real
    payload_dict["graph_active"]      = graph_active

    checks = [
        make_check("showcase_built", len(showcase) == 10,
                   f"{len(showcase)}/10 questions built"),
        make_check("sql_store", bool(sql_registry),
                   f"{len(sql_registry)} table(s) queryable via SQL"
                   if sql_registry else "No tables — SQL questions use vector fallback",
                   severity="info" if sql_registry else "warn"),
        make_check("hybrid_retrieval", bool(bm25_idx),
                   "Dense + BM25 + KG hybrid active"),
    ]
    return StageResult(payload=payload_dict, verification=make_verification(checks))
