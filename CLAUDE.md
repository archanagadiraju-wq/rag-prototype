# RAG Ingestion Engine — CLAUDE.md

Read this at the start of every session.

## Project focus

This repository is now centered on Mode D: an agent-driven ingestion workflow. The core idea is simple:

- the backend launches a Claude-based agent
- the agent chooses tools dynamically instead of following a fixed stage list
- each tool call emits live stage events so the UI can show the plan unfolding in real time
- the final result is a document stored for semantic retrieval, SQL-style table access, and entity-aware exploration

Mode D is the primary experience in this repo. Everything else is secondary.

## What Mode D does

The agent runtime lives in backend/agent/runner.py and backend/agent/tools.py.

The flow is:

1. The UI submits a document and starts a job.
2. backend/main.py routes the request into run_agent_pipeline.
3. The agent begins with inspect_document, which inspects format, page count, OCR signal, tables, images, and text extractability.
4. Based on that signal, the agent chooses the right parser:
   - parse_pdf_native for born-digital PDFs
   - parse_with_docling for scanned or complex PDFs
   - parse_with_vision_ocr for fully scanned or broken-font PDFs
   - parse_office_document for DOCX, PPTX, XLSX, and HTML
5. The agent then runs chunking, optional enrichment, embedding/indexing, and finalization.

The agent is not a hardcoded pipeline. It adapts to the document and uses a tool catalog with strict ordering rules.

## Hard constraints the agent must follow

These rules are enforced by the system prompt in backend/agent/runner.py:

- inspect_document must be the first tool call
- a parse_* tool must run before chunk_text
- chunk_text must run before embed_and_index
- finalize must be the last tool call
- describe_tables is mandatory when tables are present
- caption_images is used only when visuals are actually meaningful
- extract_entities is used when there is rich natural-language prose

The tool order is part of the product. Do not break it casually.

## Tool catalog

The agent can call these tools:

- inspect_document
- parse_pdf_native
- parse_with_docling
- parse_with_vision_ocr
- parse_office_document
- chunk_text
- describe_tables
- caption_images
- embed_and_index
- store_tables_sql
- extract_entities
- finalize

These tools are defined in backend/agent/tools.py and surfaced to the frontend through the existing WebSocket stage-event mechanism.

## Backend structure

Key files to know:

- backend/main.py — API routes, WebSocket updates, job management, file preview
- backend/config.py — environment configuration, including Anthropic and OpenAI settings
- backend/agent/runner.py — system prompt, model selection, agent loop, tool-call orchestration
- backend/agent/tools.py — tool schemas and tool executors
- backend/services/job_cache.py — cache-backed state used across tool calls
- backend/models/events.py — event payloads emitted to the UI

## Frontend structure

The frontend exposes the agent workflow visually:

- frontend/src/App.tsx — main app shell
- frontend/src/hooks/ — WebSocket and store hooks for live job state
- frontend/src/components/pipeline/ — live stage cards, feed, and pipeline visualization
- frontend/src/components/stages/ — per-stage visualizations
- frontend/src/components/pipeline/SystemDesignTab.tsx — agent design reference and copy-paste tool cards

The UI is meant to feel like a live reasoning trace, not a static pipeline diagram.

## Running locally

Backend:

```bash
cd backend
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

If you want the local vector store as well, run the Qdrant service from the repo root:

```bash
docker compose up qdrant
```

## Ports

- Frontend: http://127.0.0.1:5173
- Backend API: http://127.0.0.1:8000
- Qdrant: http://127.0.0.1:6333 (when running via Docker)

## Environment notes

- ANTHROPIC_API_KEY is required for the agent runtime.
- OPENAI_API_KEY is optional; embeddings fall back to deterministic mock vectors when absent.
- backend/config.py reads the project-level .env file from the repository root.

## Important implementation notes

- The agent uses a single shared job cache so tool calls can pass state forward.
- The backend emits stage events for each tool call, which keeps the UI synchronized with the agent’s behavior.
- The agent is intentionally budgeted and should stay deliberate; the system prompt encourages concise, high-value tool use.
- The repo currently emphasizes the agentic path, not a fixed multi-mode comparison UI.
