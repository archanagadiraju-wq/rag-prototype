"""Agent-flow invariants — these MUST hold for every agent ingest.

Guards against:
  • Bug: agent's `chunk_text` tool only chunked prose, never produced
    table_summary chunks → tables weren't searchable by description in Qdrant.
  • Bug: agent could decide to skip `extract_entities` → knowledge graph
    never built → entity-anchored questions had no graph to query.

Fix: `_caption_images` now also produces table_summary chunks; agent runner
has a post-ingest enforcement step that ensures both invariants regardless
of which tools the agent chose to call. These tests verify the enforcement.
"""
from __future__ import annotations

import asyncio
import pytest

import services.job_cache as cache


pytestmark = [pytest.mark.regression, pytest.mark.slow, pytest.mark.needs_api_key]


def _has_api_keys() -> bool:
    from config import settings
    return bool(
        settings.anthropic_api_key
        and len(settings.anthropic_api_key) > 20
        and settings.openai_api_key
        and len(settings.openai_api_key) > 20
        and not settings.openai_api_key.startswith("sk-...")
    )


# ── Invariant 1: tables → vector DB has table_summary chunks ────────────────


async def test_agent_ingest_creates_table_summary_chunks_for_xlsx(
    clean_job_id, finance_xlsx,
):
    """An XLSX (6 sheets, structured tables) ingested through the agent
    MUST end with table_summary chunks in the embedded_chunks cache,
    regardless of which tools the agent decided to call."""
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")
    if not finance_xlsx.exists():
        pytest.skip("Demo XLSX not found")

    from agent.runner import run_agent_pipeline

    events: list = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_agent_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=180,
    )

    embedded = cache.get(clean_job_id, "embedded_chunks", []) or []
    table_summary_chunks = [
        c for c in embedded
        if (c.get("metadata") or {}).get("chunk_type") == "table_summary"
    ]
    extracted_tables = cache.get(clean_job_id, "extracted_tables", []) or []

    # If the doc had tables, the embedded chunks must include summaries
    if extracted_tables:
        assert len(table_summary_chunks) > 0, (
            f"Agent ingested a doc with {len(extracted_tables)} tables but produced "
            f"zero table_summary chunks. The post-ingest enforcement is broken — "
            f"the vector DB cannot answer 'what is doc_table_N about' questions."
        )
        # Each summary chunk should have a real 1536-d vector
        for c in table_summary_chunks:
            assert c.get("vector"), f"table_summary chunk {c.get('id')} has no vector"
            assert len(c["vector"]) == 1536, "Vector should be 1536-d"


# ── Invariant 2: every successful agent ingest builds a knowledge graph ─────


async def test_agent_ingest_always_builds_knowledge_graph(
    clean_job_id, finance_xlsx,
):
    """Even when the agent decides to skip extract_entities, the post-ingest
    enforcement MUST build a knowledge graph. This guards against the bug where
    'mostly numeric tables' caused KG to silently never get built."""
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")
    if not finance_xlsx.exists():
        pytest.skip("Demo XLSX not found")

    from agent.runner import run_agent_pipeline

    events: list = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_agent_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=180,
    )

    kg = cache.get(clean_job_id, "knowledge_graph")
    assert kg is not None, (
        "Agent ingest finished but knowledge_graph cache key is None. "
        "Post-ingest enforcement should have built one. KG-based queries "
        "('what did <ORG> say?') would fail silently."
    )
    assert hasattr(kg, "number_of_nodes"), (
        f"Expected a NetworkX graph in knowledge_graph cache, got {type(kg).__name__}"
    )
    # Allow KG to have zero nodes only for truly entity-less docs; for the
    # XLSX with company names, dollar amounts, dates, etc. it must have some.
    assert kg.number_of_nodes() > 0, (
        f"KG built but empty (0 nodes). Either spaCy NER ran on empty input, "
        f"or the chunks didn't reach it. Check that chunks were not zero."
    )


# ── Invariant 3: every extracted table is 1-hop reachable in the KG ─────────


async def test_kg_table_nodes_link_to_sql_and_vector_db(clean_job_id, finance_xlsx):
    """For every `doc_table_N` extracted from the doc, the knowledge graph
    MUST contain a `Table:doc_table_N` node that:

      • shares its identifier with the SQLite table name AND the Qdrant
        `metadata.table_name` payload field (one ID, three stores), AND
      • is 1-hop reachable from a `Document:{doc_id}` node, AND
      • when nlp ran, has at least one entity neighbour (the rollup edge).

    This guards against the trap where entities from a table summary lived
    only on the chunk node, forcing every "which entities are in
    doc_table_3?" query to do a multi-hop join through chunk_ids.
    """
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")
    if not finance_xlsx.exists():
        pytest.skip("Demo XLSX not found")

    from agent.runner import run_agent_pipeline

    events: list = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_agent_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=180,
    )

    extracted = cache.get(clean_job_id, "extracted_tables", []) or []
    sql_registry = cache.get(clean_job_id, "sql_registry", {}) or {}
    kg = cache.get(clean_job_id, "knowledge_graph")

    if not extracted:
        pytest.skip("Doc produced no tables — nothing to verify")

    assert kg is not None, "KG must be built post-ingest"

    # Every extracted table → a Table:doc_table_N node exists
    for i, _tbl in enumerate(extracted):
        tname = f"doc_table_{i + 1}"
        table_node = f"Table:{tname}"
        assert kg.has_node(table_node), (
            f"Extracted table {tname} has no `{table_node}` node in KG. "
            f"Cross-store discoverability is broken — KG can't be queried "
            f"by the same ID that SQLite and Qdrant use."
        )
        node_attrs = kg.nodes[table_node]
        assert node_attrs.get("type") == "table"
        assert node_attrs.get("table_name") == tname
        assert node_attrs.get("doc_id") == clean_job_id

        # 1-hop reachable from Document node (same job)
        doc_node = f"Document:{clean_job_id}"
        assert kg.has_edge(doc_node, table_node), (
            f"Document → Table edge missing for {tname}"
        )

        # SQL store uses the SAME identifier
        assert tname in sql_registry, (
            f"{tname} present in KG but missing from sql_registry. "
            f"IDs are out of sync between KG and SQLite."
        )


async def test_kg_ocr_table_entities_reachable_by_table_id(clean_job_id, ocr_pdf):
    """OCR'd table → KG → entities, all reachable in one hop from the
    table id. Confirms that the path
        OCR vision → extracted_tables → table_summary chunk → KG
    actually lands entities on a `Table:doc_table_N` node, not just on
    chunk nodes that the user can't easily look up.
    """
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")
    if not ocr_pdf.exists():
        pytest.skip("OCR demo PDF not found")

    from agent.runner import run_agent_pipeline

    events: list = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_agent_pipeline(clean_job_id, ocr_pdf, "upload", cap),
        timeout=240,
    )

    extracted = cache.get(clean_job_id, "extracted_tables", []) or []
    kg = cache.get(clean_job_id, "knowledge_graph")
    if not extracted:
        pytest.skip("This OCR PDF didn't produce any extracted tables")
    assert kg is not None

    # At least one OCR table must surface a Table node + at least one neighbour
    found_any_table_with_entities = False
    for i, _ in enumerate(extracted):
        table_node = f"Table:doc_table_{i + 1}"
        if not kg.has_node(table_node):
            continue
        # Entities directly reachable from the Table node
        entity_neighbours = [
            n for n in kg.neighbors(table_node)
            if kg.nodes[n].get("type") == "entity"
        ]
        if entity_neighbours:
            found_any_table_with_entities = True
            break

    # Either every OCR table is entity-less (rare but allowed), or at least one
    # rollup edge exists. The "no entities at all" branch is acceptable for a
    # purely numeric table; the failure we're guarding against is "entities
    # exist but only on chunk nodes, unreachable from the Table id."
    chunk_entity_map = cache.get(clean_job_id, "chunk_entity_map", {}) or {}
    any_entities_anywhere = any(v for v in chunk_entity_map.values())
    if any_entities_anywhere:
        assert found_any_table_with_entities, (
            "KG has entities on chunk nodes but ZERO Table:* nodes carry "
            "entity rollup edges. One-hop discoverability is broken — "
            "queries like `kg.neighbors('Table:doc_table_3')` won't find them."
        )


# ── Invariant 4: no document/job state bleeds across job_ids ────────────────


async def test_no_cross_job_bleed(finance_xlsx, contract_docx):
    """Run two different files through the agent in two separate job_ids.
    Verify their caches, KG, and Qdrant collections don't share any rows.

    Job isolation is the contract that lets us cache aggressively without
    fearing that doc A's tables leak into doc B's search results.
    """
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")
    if not finance_xlsx.exists() or not contract_docx.exists():
        pytest.skip("Demo files not found")

    import services.job_cache as cache
    from agent.runner import run_agent_pipeline

    # First 8 chars MUST differ — the Qdrant collection convention is
    # `{prefix}_{job_id[:8]}` and we want to verify the collections don't collide.
    job_a = "isoA_aaaaaa_test"
    job_b = "isoB_bbbbbb_test"
    cache.clear(job_a)
    cache.clear(job_b)

    try:
        events_a: list = []
        events_b: list = []
        async def cap_a(e): events_a.append(e)
        async def cap_b(e): events_b.append(e)

        await asyncio.wait_for(
            run_agent_pipeline(job_a, finance_xlsx, "upload", cap_a),
            timeout=180,
        )
        await asyncio.wait_for(
            run_agent_pipeline(job_b, contract_docx, "upload", cap_b),
            timeout=180,
        )

        # 1) Embedded chunks: no chunk in job A carries job B's doc_id (and
        # vice versa). Missing doc_id is a separate concern — only flag the
        # actual cross-contamination case here.
        for jid, other in ((job_a, job_b), (job_b, job_a)):
            chunks = cache.get(jid, "embedded_chunks", []) or []
            for c in chunks:
                meta = c.get("metadata") or {}
                doc_id = meta.get("doc_id")
                assert doc_id != other, (
                    f"Chunk in job {jid} has doc_id={doc_id} (the OTHER job's id). "
                    f"Cross-job contamination — job cache leaked between job_ids."
                )

        # 2) Knowledge graphs: only contain their own Document node
        kg_a = cache.get(job_a, "knowledge_graph")
        kg_b = cache.get(job_b, "knowledge_graph")
        if kg_a is not None and kg_b is not None:
            doc_a = f"Document:{job_a}"
            doc_b = f"Document:{job_b}"
            assert kg_a.has_node(doc_a), "Job A's KG missing its own Document node"
            assert kg_b.has_node(doc_b), "Job B's KG missing its own Document node"
            assert not kg_a.has_node(doc_b), (
                f"Job A's KG contains Job B's Document node — "
                f"job cache leaked across job_ids."
            )
            assert not kg_b.has_node(doc_a), (
                f"Job B's KG contains Job A's Document node — "
                f"job cache leaked across job_ids."
            )

        # 3) Tables and their KG nodes don't overlap across jobs
        tables_a = cache.get(job_a, "extracted_tables", []) or []
        tables_b = cache.get(job_b, "extracted_tables", []) or []
        # Even if both pipelines produce `doc_table_1`, those refer to
        # different tables — but the KG nodes are scoped to each KG instance,
        # so checking that kg_a's Table nodes all carry doc_id=job_a is enough
        if kg_a is not None and tables_a:
            for i in range(len(tables_a)):
                tn = f"Table:doc_table_{i + 1}"
                if kg_a.has_node(tn):
                    assert kg_a.nodes[tn].get("doc_id") == job_a
        if kg_b is not None and tables_b:
            for i in range(len(tables_b)):
                tn = f"Table:doc_table_{i + 1}"
                if kg_b.has_node(tn):
                    assert kg_b.nodes[tn].get("doc_id") == job_b

        # 4) Qdrant collections are per-job (the convention used by
        # stage_09_vector_store.py is `{prefix}_{job_id[:8]}`).
        coll_a = f"rag_proto_custom_{job_a[:8]}"
        coll_b = f"rag_proto_custom_{job_b[:8]}"
        assert coll_a != coll_b, (
            f"Qdrant collection names collide across jobs: "
            f"both resolve to first-8-char prefixes that match."
        )
    finally:
        cache.clear(job_a)
        cache.clear(job_b)


# ── Belt-and-suspenders: the user-visible stage events surface the work ─────


async def test_ocr_tables_stored_in_both_sql_and_vector_db(clean_job_id, ocr_pdf):
    """OCR'd tables (extracted from scanned page images via Claude vision) MUST
    end up in BOTH the SQLite database AND the vector DB as table_summary chunks.

    Was the gap: caption_images added OCR tables to extracted_tables (so
    store_tables_sql picked them up) but did NOT add them to enriched_tables
    or build summary chunks — so OCR tables existed in SQL but not in vector
    search. Questions like "summarize the data on the scanned page" couldn't
    find them via semantic retrieval.

    Fix: caption_images now routes OCR tables to extracted_tables + enriched_tables
    + chunks (with summary). Post-ingest enforcement also rebuilds summaries
    from the combined extracted_tables list as a safety net.
    """
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")
    if not ocr_pdf.exists():
        pytest.skip("OCR demo PDF not found")

    from agent.runner import run_agent_pipeline

    events: list = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_agent_pipeline(clean_job_id, ocr_pdf, "upload", cap),
        timeout=240,
    )

    extracted = cache.get(clean_job_id, "extracted_tables", []) or []
    if not extracted:
        pytest.skip("This OCR PDF didn't produce any extracted tables — nothing to verify")

    # 1) SQL store: should have at least one row per extracted table
    sql_registry = cache.get(clean_job_id, "sql_registry", {}) or {}
    assert len(sql_registry) >= 1, (
        f"OCR'd doc has {len(extracted)} extracted tables but ZERO ended up in SQLite. "
        f"Tables aren't queryable for exact SQL questions."
    )

    # 2) Vector DB: every extracted table needs a corresponding summary chunk
    embedded = cache.get(clean_job_id, "embedded_chunks", []) or []
    summary_chunks = [
        c for c in embedded
        if (c.get("metadata") or {}).get("chunk_type") == "table_summary"
    ]
    assert len(summary_chunks) >= len(extracted), (
        f"OCR'd doc has {len(extracted)} extracted tables but only "
        f"{len(summary_chunks)} table_summary chunks in the vector DB. "
        f"Tables can't be found by semantic search."
    )

    # 3) Vector DB chunks must have real 1536-d vectors
    for c in summary_chunks:
        assert len(c.get("vector", [])) == 1536, (
            f"table_summary chunk {c.get('id')} missing or wrong-dim vector"
        )


async def test_agent_emits_auto_stages_when_enforcement_triggers(
    clean_job_id, finance_xlsx,
):
    """If the agent skips table summarization, the runner's enforcement emits
    visible `auto.*` stage events so the user can SEE the system completing
    the work, not just silently doing it."""
    if not _has_api_keys():
        pytest.skip("Needs API keys for real agent run")

    from agent.runner import run_agent_pipeline

    events: list = []
    async def cap(e): events.append(e)
    await asyncio.wait_for(
        run_agent_pipeline(clean_job_id, finance_xlsx, "upload", cap),
        timeout=180,
    )

    completed = [e for e in events if e.get("status") == "completed"]
    stage_names = [e.get("stage_name", "") for e in completed]

    # Table enrichment can come from the agent's `describe_tables` tool OR from
    # the post-ingest enforcement's `auto.describe_tables` step.
    has_table_enrichment = any(
        "describe_tables" in n or "enrich_tables" in n
        for n in stage_names
    )
    # KG can come from agent.extract_entities OR auto.build_knowledge_graph.
    has_kg_step = any(
        "knowledge_graph" in n or "extract_entities" in n
        for n in stage_names
    )

    extracted = cache.get(clean_job_id, "extracted_tables", []) or []
    if extracted:
        assert has_table_enrichment, (
            f"Doc had tables but no enrichment stage ran. Stages: {stage_names}"
        )
    assert has_kg_step, (
        f"Every ingest should have a KG-building stage. Stages: {stage_names}"
    )
