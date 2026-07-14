# RAG Ingestion Engine — System Overview

*A three-page document for product, engineering, and stakeholder consumption.*

---

# Page 1 of 3 — The Journey of a Document

A PDF lands on the upload zone. Roughly 5–10 minutes later, the same document
is queryable by five completely different question types — from exact numeric
lookups to entity-anchored graph traversals — each backed by the storage shape
best suited to that question. This is what happens in between.

### 1. Arrival

The user drops a file (or selects a demo doc). The frontend POSTs it to
`/api/jobs`. The backend writes the bytes to a temp file, mints a fresh
`job_id` (UUID), and asynchronously kicks off the chosen pipeline. The
WebSocket `/ws/{job_id}` opens so the user can watch stage events stream in.

If anything crashes here, persistence in the frontend means the in-flight job
isn't lost on browser reload — the WebSocket reconnects and the backend
replays buffered events.

### 2. Parse — turning bytes into structure

The document is read by **pdfplumber + PyMuPDF** (for born-digital PDFs) or
**Docling + RapidOCR** (for scanned content). If a 48-page PDF has
CID-encoded gibberish on most pages (broken font encoding), the agent's
inspector flags `ocr_fraction > 0.2` and routes to the vision path: each page
is rendered to an image and Claude vision transcribes the text. The output is
a uniform `parser_payload` containing **text blocks, tables, and images** —
the same shape regardless of which parser ran.

### 3. Chunk — splitting prose for retrieval

Text is sliced into ~512-token chunks with overlap, respecting heading
boundaries. Each chunk gets a stable `chunk_id` of the form
`{job_id[:8]}_{pipeline}_c{NNNN}`. Tables get a parallel
`table_summary` chunk: a short Claude-generated description plus column
headers and three sample rows — this is what makes tables findable by
semantic search, not just by exact name.

### 4. Embed — projecting text into vector space

Every chunk passes through **OpenAI text-embedding-3-large**, producing a
1536-dimensional vector. Vectors are upserted into a per-job **Qdrant HNSW**
collection (`rag_proto_{mode}_{job_id[:8]}`). At query time, HNSW search is
sub-linear in N — important for documents with hundreds of chunks.

### 5. Enrich — three parallel projections

Three storage projections happen alongside the vector store:

- **BM25 index** — sparse keyword posting list, in-memory. Wins on exact
  matches like reference numbers (`MDI/SMEDD/2024-039`).
- **Knowledge graph** — spaCy NER over each chunk extracts PERSON, ORG, GPE,
  MONEY entities. Each becomes a node in a NetworkX graph, linked to the
  source chunk. A `Document` node and a `Table:doc_table_N` node anchor
  cross-store traversal.
- **SQLite** — every extracted table is loaded into a per-job database
  (`tables.db`) with type-inferred columns. Numeric strings like
  `"3,000.00"` are coerced to REAL at ingest time so SQL aggregates work
  correctly.

### 6. Extract facts — the new top-of-stack layer

A single Claude call reads the chunks and produces a typed JSON document
(`facts.json`) of single-valued document properties: project capacity, budget,
dates, approver, recommended contractors. Every fact must carry a verbatim
source quote that appears in one of the ingested chunks — facts whose quote
can't be located are rejected as hallucination. The validated facts persist
to disk and become the first-stop store for property-lookup questions.

### 7. Ready to query

The document now exists in **five parallel shapes**, all sharing the same
`doc_id`, `chunk_id`, and `table_name` as join keys. A query to `/ask` flows
through:

1. **Facts pre-pass** — embed the question, match against fact labels by
   cosine similarity. On a hit, inject the typed value + source quote as the
   highest-authority context block.
2. **Vector + BM25 + KG fuse** — top-5 chunks via reciprocal rank fusion.
3. **LLM answer** — Claude haiku grounds an answer in the composed context.
4. **Judge verdict** — an independent Claude pass rates correctness against
   the retrieved context, returning a 4-tier verdict and 0-1 score.

The response carries the answer, every retrieved chunk, the fact match (if
any), the system + user prompts (for audit), and the judge's verdict and
rationale. Full provenance, end to end.

---

\pagebreak

# Page 2 of 3 — The Architecture and Philosophy

### The premise

A document is heterogeneous: prose, tables, properties, entities, codes.
The universe of questions about it is heterogeneous too: "what does it say
about X?", "what's the total cost?", "who approved it?", "find the reference
number `MDI/SMEDD/2024-039`", "which companies co-occur with HYPER-AIRE?"

Conventional RAG forces one storage shape — usually a vector store — to
serve all five question types. The result is systematic, hard-to-diagnose
failures on whichever question types don't match. We measured this directly:
a SQL-routing experiment dropped the eval from 72% → 56% correct because
the router couldn't reliably pick the right table for property-lookup
questions whose data shape was wrong for SQL.

### The insight

Storage shape should match question shape. Project the same document into
multiple parallel representations, each optimized for one kind of question.
Route every query to the lens whose shape matches it.

### The five lenses

Each lens stores the same underlying content in the shape its question class
prefers:

| Lens | Storage | What it's for |
|---|---|---|
| **Facts** | `facts.json` (typed, cited, NEW) | Property lookups — "what is the project capacity?" |
| **Tables** | SQLite (REAL/TEXT typed, per-job DB) | Multi-row aggregations — "what's the total ductwork cost?" |
| **Chunks** | Qdrant HNSW (1536-d vectors) | Semantic recall — "what does the doc say about the bid evaluation?" |
| **Tokens** | BM25 (sparse index) | Exact strings — codes, IDs, reference numbers |
| **Entities** | NetworkX graph | Entity-anchored questions — "who connects to whom?" |

All five share the same identifier scheme: `doc_id`, `chunk_id`, `table_name`
are the same string in every store. Each lens can be improved, swapped, or
rebuilt independently — the joins still work.

### The query path

The `/ask` flow is not a single retrieval. It is a **composition**:

1. The **facts pre-pass** runs first. When the question embedding matches a
   fact label, the typed value + verbatim quote is injected as the highest-
   authority context block. This is the fast path for property lookups.
2. The **vector + BM25 + KG** fuse always runs. It contributes narrative
   context regardless of what the facts route found.
3. The **answering LLM** sees the composed context and produces an answer.
4. An **independent judge LLM** rates the answer against the retrieved
   context — neither LLM can vouch for itself.

The router doesn't compute the answer. It picks the lens and composes
context. The LLM is the last step, not the only step.

### Verification and provenance

Two principles are non-negotiable:

- **Provenance**. Every fact carries `source.{page, chunk_id, table_name,
  quote}`. Every chunk carries `metadata.{doc_id, page, table_name}`. Every
  entity in the KG edges back to source chunks. No orphan claims.
- **Verification**. Fact extraction is **quote-validated**: the LLM must
  produce a verbatim source quote that appears in one of the ingested chunks,
  or the fact is rejected. On the test document, 17/17 extracted facts
  validated; 0 hallucinations made it through. Answers are independently
  **judge-validated**.

### Current state

On the 25-question evaluation suite against a 48-page bid-evaluation PDF:

- **Baseline** (vector + BM25 + KG only): **72% correct** by judge verdict
- **SQL routing experiment**: 56% (regressed — feature-flagged OFF)
- **Type coercion + JSON facts layer**: in-line with baseline ± LLM noise,
  with key wins on capacity, floor area, and reference-number questions; 0
  hallucinations.

The system is now in a state where the storage architecture matches the
question taxonomy. Future lift will come from tuning the routes (lower
fact-match threshold, better column descriptions) rather than from
restructuring the stores.

### What this buys

- Each lens can be **improved independently**.
- Each lens can be **measured independently** — per-route eval scores show
  exactly where the gap is.
- Each lens has its own **failure mode** — easy to diagnose, easy to fix.
- New question types get **new lenses**, not patches on old ones.
- Cost, latency, and storage veracity are **local to each lens**.

The whole system is one bet: that the cost of maintaining five shapes is
less than the cost of forcing one shape to do everyone's job.

---

\pagebreak

# Page 3 of 3 — The Five-Lens Model (Diagram)

```
═════════════════════════════════════════════════════════════════════════
                       THE FUNDAMENTAL PREMISE
═════════════════════════════════════════════════════════════════════════

  A document is heterogeneous — prose, tables, properties, entities, codes.
  The universe of questions about it is heterogeneous too.
  Force one storage shape to serve all question types and you get
  systematic failures on the question types whose shape doesn't match.

═════════════════════════════════════════════════════════════════════════
                       THE CORE ABSTRACTION
═════════════════════════════════════════════════════════════════════════

                            ┌─────────────┐
                            │  DOCUMENT   │
                            │ (raw bytes) │
                            └──────┬──────┘
                                   │
                       ingest projects the SAME content
                       into FIVE canonical shapes
                                   │
        ┌─────────┬─────────┬──────┴──────┬─────────┬──────────┐
        ▼         ▼         ▼             ▼         ▼
     ┌─────┐   ┌─────┐  ┌───────┐    ┌──────┐  ┌────────┐
     │FACTS│   │TABLE│  │CHUNKS │    │TOKENS│  │ GRAPH  │
     ├─────┤   ├─────┤  ├───────┤    ├──────┤  ├────────┤
     │ key │   │ row │  │vector │    │ bag  │  │ nodes  │
     │ →   │   │  ×  │  │ space │    │  of  │  │   +    │
     │ val │   │ col │  │ 1536d │    │words │  │ edges  │
     ├─────┤   ├─────┤  ├───────┤    ├──────┤  ├────────┤
     │JSON │   │SQL  │  │Qdrant │    │BM25  │  │NetworkX│
     │typed│   │REAL │  │HNSW   │    │idf   │  │directed│
     │cited│   │/TEXT│  │ann    │    │      │  │ multi  │
     └──┬──┘   └──┬──┘  └───┬───┘    └──┬───┘  └───┬────┘
        │         │         │           │          │
        │         │  SAME doc_id, chunk_id,        │
        │         │  table_name everywhere         │
        │         │  (universal join keys)         │
        ▼         ▼         ▼           ▼          ▼
   ┌─────────┬─────────┬─────────┬─────────┬─────────────┐
   │"what is │"sum,    │"what    │"find    │"who         │
   │ X?"     │filter,  │does the │chunks   │connects     │
   │         │aggregate│doc say  │with     │to whom?     │
   │property │many     │about    │exact    │which        │
   │lookup   │rows"    │Y?"      │string"  │entities     │
   │         │         │         │         │share        │
   │         │         │meaning  │codes,   │context?"    │
   │         │         │recall   │IDs,     │             │
   │         │         │         │names    │entity-      │
   │         │         │         │         │anchored     │
   └─────────┴─────────┴─────────┴─────────┴─────────────┘

              FIVE QUESTION CLASSES,
              EACH SOLVED BY THE LENS WHOSE SHAPE MATCHES.

              The /ask router doesn't compute answers.
              It picks the lens and composes context.
              The LLM is the last step, not the only step.

═════════════════════════════════════════════════════════════════════════
                       FIVE PRINCIPLES THAT FALL OUT
═════════════════════════════════════════════════════════════════════════

  ① RIGHT SHAPE FOR THE QUESTION
     Flat key-value data → JSON.   Multi-row data → SQL.
     Continuous semantics → vectors.   Exact strings → BM25.
     Relationships → graph.

  ② SHARED IDENTITY, INDEPENDENT SHAPES
     doc_id, chunk_id, table_name are the same string in every store.
     Each lens can be improved without touching the others.

  ③ PROVENANCE IS NON-NEGOTIABLE
     Every fact carries source.{page, chunk_id, quote}.
     Every chunk carries metadata.{doc_id, page, table_name}.
     Every KG entity edges back to its source chunks.

  ④ VERIFY BEFORE TRUSTING
     Extraction is quote-validated. Answers are judge-validated.
     Neither LLM can vouch for itself.

  ⑤ DEFENSE IN DEPTH
     Facts route, SQL route, vector retrieval — parallel paths.
     When one fails or doesn't match, the next picks up.
     New layers can only lift, not regress.

═════════════════════════════════════════════════════════════════════════
                       THE CONTRAST
═════════════════════════════════════════════════════════════════════════

  Conventional RAG:                  This system:

  ┌────────────────────┐             ┌──────────────────────────────┐
  │ "All retrieval is  │             │ "Retrieval shape should      │
  │  semantic search"  │             │  match question shape."      │
  │                    │             │                              │
  │ One vector store   │             │ Five projections, one        │
  │ One similarity     │             │ identity scheme, one         │
  │ One ranker         │             │ router.                      │
  └────────────────────┘             └──────────────────────────────┘

  Property lookups,                  Property lookup → facts.json
  table aggregations,                Table aggregation → SQL
  entity questions —                 Entity question → KG
  all fight for top-k                Narrative question → vector
  in the vector store.               Code lookup → BM25

  When one wins, others lose.        Each question type gets its
  Failures are systematic and        own optimal path. Failures
  hard to fix.                       are local — improving one
                                     lens doesn't risk the others.
```

---

*End of document. For implementation requirements, see `STORAGE_ARCHITECTURE_REQUIREMENTS.md`. For the empirical eval and gap analysis, see `qa_eval_report.md` under each job's directory.*
