"""Stage 9 — Knowledge Graph.

Builds an entity graph from all document chunks using spaCy NER.

Node types (all sharing one NetworkX graph, distinguished by `type` attr):
  • `Document:{doc_id}`     — one per ingested file
  • `Table:{table_name}`    — one per extracted table (e.g. `Table:doc_table_3`)
  • `chunk:{chunk_id}`      — one per embedded chunk
  • `{LABEL}:{text_lower}`  — one per named entity (PERSON, ORG, GPE, …)

Edges:
  • Document → chunk         (contains)
  • Document → Table         (contains)
  • Table    → chunk         (summarized_by — links to the table_summary chunk)
  • Table    → entity        (mentions — rollup so entities are 1-hop from the table)
  • chunk    → entity        (mentions)
  • entity   ↔ entity        (co-occurrence in same chunk)

The Table node uses the SAME identifier as the SQLite table name and the
Qdrant `metadata.table_name` payload field, so a single ID
(`doc_table_N`) joins all three stores. The graph is stored in job_cache
and used by Stage 11 (RAG Ready) to boost retrieval scores for chunks
that share entities with top results.
"""
from __future__ import annotations
import time
from collections import defaultdict

from models.events import KnowledgeGraphPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult
import services.job_cache as cache

_USEFUL_TYPES = {"PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "LAW", "WORK_OF_ART", "FAC", "NORP"}
_MIN_LEN = 2


async def run(job_id: str, cache_prefix: str = "") -> StageResult:
    import networkx as nx
    import spacy

    embedded_chunks = cache.get(job_id, f"{cache_prefix}embedded_chunks", [])

    if not embedded_chunks:
        payload = KnowledgeGraphPayload(
            entity_count=0, relationship_count=0,
            unique_entity_types=[], top_entities=[], chunk_count=0,
        )
        checks = [make_check("graph_built", False, "No chunks to build graph from", severity="warn")]
        return StageResult(payload=payload.model_dump(), verification=make_verification(checks))

    t0 = time.perf_counter()

    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        nlp = None

    G = nx.Graph()
    entity_mentions: dict[str, int] = defaultdict(int)
    entity_types: set[str] = set()
    chunk_entity_map: dict[str, list[str]] = {}
    table_nodes: set[str] = set()
    document_nodes: set[str] = set()

    for chunk in embedded_chunks:
        text = chunk.get("text", "")
        meta = chunk.get("metadata", {})
        chunk_id = meta.get("chunk_id", f"c{chunk.get('chunk_idx', 0):04d}")
        chunk_node = f"chunk:{chunk_id}"
        doc_id = meta.get("doc_id") or job_id
        chunk_type = meta.get("chunk_type")
        table_name = meta.get("table_name")
        source_filename = meta.get("source_filename")

        chunk_attrs = {"type": "chunk", "chunk_id": chunk_id, "doc_id": doc_id}
        if chunk_type:
            chunk_attrs["chunk_type"] = chunk_type
        if table_name:
            chunk_attrs["table_name"] = table_name
        G.add_node(chunk_node, **chunk_attrs)
        chunk_entity_map[chunk_id] = []

        # Document node — one per doc_id; links to every chunk in the doc
        doc_node = f"Document:{doc_id}"
        if not G.has_node(doc_node):
            doc_attrs = {"type": "document", "doc_id": doc_id}
            if source_filename:
                doc_attrs["source_filename"] = source_filename
            G.add_node(doc_node, **doc_attrs)
            document_nodes.add(doc_node)
        G.add_edge(doc_node, chunk_node, rel="contains")

        # Table node — only for table_summary chunks; shares ID with SQLite/Qdrant
        table_node: str | None = None
        if chunk_type == "table_summary" and table_name:
            table_node = f"Table:{table_name}"
            if not G.has_node(table_node):
                G.add_node(
                    table_node,
                    type="table",
                    table_name=table_name,
                    doc_id=doc_id,
                )
                table_nodes.add(table_node)
            G.add_edge(doc_node, table_node, rel="contains")
            G.add_edge(table_node, chunk_node, rel="summarized_by")

        if not nlp:
            continue

        doc = nlp(text[:1200])
        seen_in_chunk: set[str] = set()

        for ent in doc.ents:
            if ent.label_ not in _USEFUL_TYPES:
                continue
            if len(ent.text.strip()) < _MIN_LEN:
                continue

            entity_key = f"{ent.label_}:{ent.text.strip().lower()}"
            entity_mentions[entity_key] += 1
            entity_types.add(ent.label_)

            if not G.has_node(entity_key):
                G.add_node(entity_key, type="entity", label=ent.label_, text=ent.text.strip())

            if entity_key not in seen_in_chunk:
                G.add_edge(chunk_node, entity_key, weight=1)
                chunk_entity_map[chunk_id].append(entity_key)
                seen_in_chunk.add(entity_key)
            else:
                if G.has_edge(chunk_node, entity_key):
                    G[chunk_node][entity_key]["weight"] += 1

            # Table → entity rollup: 1-hop discoverability of entities per table
            if table_node:
                if G.has_edge(table_node, entity_key):
                    G[table_node][entity_key]["weight"] += 1
                else:
                    G.add_edge(table_node, entity_key, rel="mentions", weight=1)

        # Co-occurrence edges between entities sharing a chunk
        entities = list(seen_in_chunk)
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                a, b = entities[i], entities[j]
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1, rel="co-occurrence")

    cache.put(job_id, f"{cache_prefix}knowledge_graph", G)
    cache.put(job_id, f"{cache_prefix}chunk_entity_map", chunk_entity_map)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    entity_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "entity"]
    top_entities = sorted(entity_mentions.items(), key=lambda x: -x[1])[:10]
    top_entity_list = [
        {
            "key": k,
            "text": G.nodes[k].get("text", k) if k in G.nodes else k,
            "label": k.split(":")[0],
            "mentions": v,
        }
        for k, v in top_entities
    ]

    payload = KnowledgeGraphPayload(
        entity_count=len(entity_nodes),
        relationship_count=G.number_of_edges(),
        unique_entity_types=sorted(entity_types),
        top_entities=top_entity_list,
        chunk_count=len(embedded_chunks),
    )
    payload_dict = payload.model_dump()
    payload_dict["build_ms"] = round(elapsed_ms, 1)
    payload_dict["graph_nodes"] = G.number_of_nodes()
    payload_dict["linked_tables"] = len(table_nodes)
    payload_dict["linked_documents"] = len(document_nodes)

    checks = [
        make_check(
            "graph_built",
            G.number_of_nodes() > 0,
            f"{G.number_of_nodes()} nodes · {G.number_of_edges()} edges built in {elapsed_ms:.0f}ms",
        ),
        make_check(
            "entities_found",
            len(entity_nodes) > 0,
            f"{len(entity_nodes)} unique entities across {len(embedded_chunks)} chunks"
            if entity_nodes else "No named entities found — graph traversal will use structure only",
            severity="warn" if not entity_nodes else "info",
        ),
        make_check(
            "entity_types",
            bool(entity_types),
            f"Types detected: {', '.join(sorted(entity_types))}" if entity_types else "None",
        ),
    ]
    return StageResult(payload=payload_dict, verification=make_verification(checks))
