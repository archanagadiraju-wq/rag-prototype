# RAG Ingestion Engine — CLAUDE.md

Read this at the start of every session.

## Project overview

Interactive prototype comparing two document ingestion pipelines:
- **Mode A (Custom)**: 10-stage hand-built pipeline (pdfplumber, spaCy, OpenAI embeddings, Qdrant)
- **Mode B (Docling)**: IBM Docling replaces stages 2–5 with a unified ML parse pass (7 stages total)
- **Mode C (Compare)**: Both run in parallel; side-by-side benchmark dashboard

## Current status: ALL 11 STAGES REAL (Mode A), Mode B + Mode C wired

All stages are fully implemented and real for Mode A. Mode B uses the same stage implementations
with a `d_` cache key prefix and separate Qdrant collection. Mode C runs both concurrently.

## Layer completion status
- [x] Layer 1 — Skeleton & Infrastructure
- [x] Layer 2 — Real Intake + Format Detection
- [x] Layer 3 — Custom Parsers (Mode A)
- [x] Layer 4 — Content Intelligence
- [x] Layer 5 — Smart Chunking
- [x] Layer 6 — Multi-Modal Enrichment
- [x] Layer 7 — Embedding + BM25 + Vector Store
- [x] Layer 8 — Metadata Enrichment + RAG Ready (Hybrid Search)
- [x] Layer 9 — Docling Pipeline (Mode B) + Compare Mode (Mode C)
- [ ] Layer 10 — Polish & Demo Readiness (ground truth checking, L2/L3 verification)

## Project structure

```
rag-prototype/
├── backend/
│   ├── main.py           Routes, WebSocket, job management, file preview
│   ├── config.py         Settings (pydantic-settings, reads .env from project root)
│   ├── pipelines/
│   │   ├── base.py       StageEmitter + StageResult
│   │   ├── mock.py       Fallback mock events (used when no file provided)
│   │   ├── custom/       Mode A — stages 01–10
│   │   │   ├── runner.py              All 11 stages wired
│   │   │   ├── stage_01_intake.py
│   │   │   ├── stage_02_format_detect.py
│   │   │   ├── stage_03_parser.py     + stage_03_parsers/
│   │   │   ├── stage_04_content_intel.py
│   │   │   ├── stage_05_chunker.py
│   │   │   ├── stage_06_multimodal.py
│   │   │   ├── stage_07_embedding.py  (cache_prefix param)
│   │   │   ├── stage_08_metadata.py   (cache_prefix param)
│   │   │   ├── stage_09_knowledge_graph.py (cache_prefix param)
│   │   │   ├── stage_09_vector_store.py (cache_prefix param; stage_id=10 in runner)
│   │   │   └── stage_10_rag_ready.py  (cache_prefix param; stage_id=11 in runner)
│   │   └── docling/      Mode B — 8 stages
│   │       ├── runner.py              Stages 1-8
│   │       └── stage_02_unified_parse.py  (chains stages 2-5, falls back to Mode A)
│   ├── services/
│   │   └── job_cache.py  In-memory inter-stage data store (vectors, BM25, chunks)
│   ├── verification/
│   │   └── l1.py         make_check / make_verification helpers
│   └── models/
│       └── events.py     All Pydantic payload models + StageEvent
├── frontend/src/
│   ├── App.tsx
│   ├── hooks/            usePipelineStore (zustand), usePipelineSocket
│   ├── components/
│   │   ├── pipeline/     StageCard, StageDetail, PipelineFlow, LiveFeed,
│   │   │                 LLMUsageSummary, FilePreviewModal
│   │   ├── stages/       IntakeViz, FormatDetectViz, ParserViz,
│   │   │                 ContentIntelViz, ChunkerViz, MultiModalViz,
│   │   │                 EmbeddingViz, MetadataViz, VectorStoreViz, RAGReadyViz
│   │   ├── upload/       DropZone, DemoDocSelector
│   │   └── comparison/   CompareLayout (Mode C side-by-side view)
│   └── types/events.ts
├── demo_docs/            5 demo files (PDF/XLSX/DOCX/HTML/PPTX)
├── docker-compose.yml    Qdrant (6333), backend (8000), frontend (5173)
└── .env                  API keys (Anthropic real, OpenAI placeholder)
```

## Running locally (without Docker)

```bash
# Backend (from backend/ directory)
cd backend && .venv/bin/uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```

## Running with Docker (includes Qdrant)

```bash
docker compose up
```

## Ports
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Qdrant: http://localhost:6333 (only available via Docker)

## Key design rules

- Qdrant local (not cloud) — data stays local; graceful fallback when offline
- text-embedding-3-large at 1536 dims; mock deterministic vectors when no OpenAI key
- Separate Qdrant collections per pipeline per job (`rag_proto_custom_{job_id[:8]}` vs `rag_proto_docling_{job_id[:8]}`)
- BM25 via in-memory index (rank-bm25 style, hand-rolled)
- Job cache (`services/job_cache.py`) stores large inter-stage data (vectors, BM25 index)
- cache_prefix="d_" used by Mode B to avoid key collisions in compare mode
- Mode B (Docling): stages use d_ prefix for cache keys, separate Qdrant collection
- L1 verification on every stage; L2/L3 not yet implemented

## Stage numbering

**Mode A (Custom):** stages 1–11
  1. Intake → 2. Format Detection → 3. Format Parser → 4. Content Intelligence →
  5. Smart Chunking → 6. Multi-Modal → 7. Embedding → 8. Metadata →
  9. Knowledge Graph → 10. Vector Store → 11. RAG Ready

**Mode B (Docling):** stages 1–8
  1. Intake → 2. Docling Unified Parse (collapses 2-5) → 3. Multi-Modal →
  4. Embedding → 5. Metadata → 6. Knowledge Graph → 7. Vector Store → 8. RAG Ready

## API keys (.env)

- `ANTHROPIC_API_KEY` — real key, used for Claude claude-haiku-4-5-20251001 in stages 4 and 6
- `OPENAI_API_KEY` — placeholder (`sk-...`); mock embeddings used when absent/placeholder
- config.py reads .env from `Path(__file__).parent.parent / ".env"` (project root, not backend/)

## WebSocket event schema

```json
{
  "job_id": "...", "pipeline": "custom", "stage_id": 7, "stage_name": "Embedding",
  "status": "completed", "timestamp_ms": 1234567890, "duration_ms": 420,
  "payload": { ... stage-specific ... },
  "verification": { "l1_checks": [...], "l1_pass_rate": 0.94 }
}
```

## Known limitations / next steps for Layer 10

- OpenAI key is placeholder — embedding stage uses mock deterministic vectors
- Qdrant only persists if running via Docker (docker compose up qdrant)
- L2 semantic verification and L3 ground truth scoring not yet implemented
- CompareLayout shows raw payload JSON for selected stage (no rich viz in compare mode)
- File preview (iframe modal) only works for files uploaded in the current server session (hot-reload resets _job_files)
