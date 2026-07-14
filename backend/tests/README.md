# Test Suite

Pytest test suite for the RAG Ingestion Engine backend.

## Quick reference

```bash
# From backend/ directory:

# All fast tests (unit + api + regression) — ~3 min
.venv/bin/python -m pytest -m "not slow"

# Just unit tests — < 1 second
.venv/bin/python -m pytest tests/unit

# Just API endpoint tests (uses FastAPI TestClient) — ~3 min
.venv/bin/python -m pytest tests/api

# Just regression tests — < 2 seconds
.venv/bin/python -m pytest tests/regression

# Slow end-to-end functional tests (real LLM calls; needs API keys)
.venv/bin/python -m pytest tests/functional

# Single test
.venv/bin/python -m pytest tests/unit/test_chunker.py::test_safety_net_kicks_in_for_tiny_doc -v
```

## Layout

```
backend/tests/
├── conftest.py           Shared fixtures (paths, TestClient, clean job ids)
├── unit/                 Pure-Python, no I/O, < 1s each
│   ├── test_chunker.py            Smart chunker + safety net
│   ├── test_embedding_split.py    Oversize chunk splitting
│   ├── test_api_retry.py          Retry-with-backoff helper
│   └── test_ocr_detection.py      ocr_fraction scanner
├── api/                  FastAPI TestClient, ~3 min total
│   └── test_endpoints.py          Every public endpoint contract
├── regression/           One test per fixed bug, < 2s total
│   └── test_known_bugs.py         10 specific regressions
└── functional/           Real pipelines on real docs, marked `slow`
    └── test_pipelines_end_to_end.py    Full Mode A + /ask + resume
```

## Markers

- `unit`        — fast, isolated tests
- `api`         — hits FastAPI via TestClient
- `regression`  — guards a specific historical bug
- `functional`  — full pipeline integration
- `slow`        — > 5s; skipped by default in CI
- `needs_api_key` — requires real ANTHROPIC_API_KEY + OPENAI_API_KEY

Combine with `-m`:
```bash
pytest -m "regression and not slow"
pytest -m "unit or api"
```

## What's tested

### Unit tests (27 tests, ~0.5s)

**Chunker**
- Normal heading-aware chunking produces 90%+ coverage
- Tiny docs (sub-MIN_TOKENS) trigger the safety net → at least 1 chunk
- Giant docs in safety net → sliding-window split caps each chunk under 6K
- Empty input doesn't crash

**Embedding oversize split**
- Sub-cap chunks pass through unchanged
- 12K-token chunk splits into 2+ sub-chunks, each under 7500 tokens
- Sub-chunk IDs are unique
- Parent metadata (page, heading) inherited by sub-chunks

**Retry helper**
- Transient errors (429, 5xx, timeouts) classified correctly
- Permanent errors (400) NOT retried
- Sync + async wrappers behave identically
- Exponential backoff grows between retries
- Gives up after max_attempts

**OCR detection**
- All-text PDF → ocr_fraction = 0.0
- All-scanned PDF → ocr_fraction = 1.0
- Mixed-content PDFs → correct fraction
- Threshold-boundary cases
- Huge docs sampled, not full-scanned
- Per-page errors caught without crashing

### API tests (17 tests, ~3 min — pipelines run for some)

- `GET /api/demo-docs` returns catalog with required fields
- `GET /api/demo-docs/{file}` downloads existing demo doc
- `GET /api/demo-docs/{file}` returns 404 on unknown
- Path-traversal attempts (`../`, encoded variants) rejected
- `POST /api/jobs` accepts file upload OR demo_doc form field
- `POST /api/jobs` returns UUID job_id + ISO timestamp
- `GET /api/jobs/{id}` returns 404 on unknown, status on known
- `POST /api/jobs/{id}/ask` rejects empty question (400/422)
- `POST /api/jobs/{id}/ask` returns 404 on un-ingested job
- `POST /api/jobs/{id}/ask` rejects invalid pipeline literal (422)
- `GET /openapi.json` generates without errors, all paths present
- `/docs` (Swagger UI) and `/redoc` serve correctly
- All endpoints carry their documented OpenAPI tags

### Regression tests (10 tests, ~1.5s)

Each guards a specific bug already paid the cost to find once:

| # | Bug | Test |
|---|---|---|
| 1 | Docling produced 1 giant markdown block → 1 chunk for whole doc | `test_docling_markdown_splits_into_multiple_blocks` |
| 2 | `getattr(doc, 'num_pages')` returned bound method, broke JSON serialize | `test_docling_page_count_is_value_not_method` |
| 3 | Docling tables had empty headers/rows → SQL store skipped them | `test_docling_table_to_dataframe_path` |
| 4 | OCR scan only sampled first 3 pages → mixed-content docs wrong-routed | `test_ocr_detection_full_document_scan` |
| 5 | Mode A and Mode B each generated their own questions (Mode C unfair) | `test_shared_questions_used_across_pipelines` |
| 6 | StageEvent literal didn't accept `pipeline='agent'` → agent crashed | `test_stage_event_accepts_agent_pipeline_literal` |
| 7 | Chunker emitted 0 chunks for tiny docs (cascade through all stages) | `test_chunker_safety_net_prevents_zero_chunks` |
| 8 | Mode B's stage dispatch was by ID → wrong vizes rendered | `test_mode_b_stages_dispatch_by_name_not_id` |
| 9 | 12K-token chunk crashed OpenAI embedding (400, kills whole batch) | `test_oversize_chunk_split_prevents_openai_400` |
| 10 | Cache didn't fall back to disk → backend restart re-ran every stage | `test_cache_resume_reads_from_disk_after_memory_clear` |

### Functional tests (4 tests, marked `slow` — only run on demand)

- Full Mode A pipeline on the financial XLSX (all 11 stages, expected outputs)
- Stage events have correct schema (stage_id, status, payload, etc.)
- `/ask` after ingest returns grounded answer with retrieved chunks + judge verdict
- Same job_id after memory clear resumes from disk in < 1/3 the time

## CI recommendation

```yaml
# fast suite — every commit, < 4 minutes
- run: pytest -m "not slow" --tb=short

# slow suite — nightly or pre-release, ~15 minutes total
- run: pytest -m slow --tb=short
  if: needs_api_keys_configured
```

## Adding new tests

- New bug? Add a regression test in `tests/regression/test_known_bugs.py`
  with a docstring explaining what broke and how it was fixed.
- New endpoint? Add cases to `tests/api/test_endpoints.py` covering happy path,
  validation error, missing-resource 404.
- New module? Add a `test_<module>.py` in `tests/unit/`.
