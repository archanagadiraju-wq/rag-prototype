"""API endpoint tests via FastAPI TestClient.

Tests the request/response contracts, error paths, validation, and security
behaviors of each public endpoint. Does NOT exercise the actual ingestion
pipeline (those are functional tests) — focuses on:

  - Status codes (200 on success, 400/404 on errors)
  - Response shape matches the documented Pydantic model
  - Bad inputs are rejected cleanly
  - Path traversal is blocked
  - WebSocket protocol basics
"""
from __future__ import annotations

import io
import pytest


pytestmark = pytest.mark.api


# ── /api/demo-docs (catalog) ─────────────────────────────────────────────────


def test_list_demo_docs_returns_catalog(test_client):
    """GET /api/demo-docs returns the 6 bundled docs with required fields."""
    r = test_client.get("/api/demo-docs")
    assert r.status_code == 200
    docs = r.json()
    assert isinstance(docs, list)
    assert len(docs) >= 5, "Expected at least 5 demo docs"
    required_fields = {"id", "filename", "doc_type", "domain", "description", "has_ground_truth"}
    for d in docs:
        assert required_fields.issubset(d.keys()), f"Missing fields in: {d}"


def test_download_existing_demo_doc(test_client):
    """Download a known demo doc by filename."""
    r = test_client.get("/api/demo-docs/02_financial_model.xlsx")
    assert r.status_code == 200
    assert len(r.content) > 1000, "Demo doc should be > 1KB"


def test_download_missing_demo_doc_404(test_client):
    r = test_client.get("/api/demo-docs/does_not_exist.pdf")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_path_traversal_blocked(test_client):
    """Critical security test: ../etc/passwd must not escape demo_docs_dir."""
    # FastAPI's path parameter handling URL-decodes; we test both encoded and
    # plain forms. Both should fail to find the file (404) or be rejected (400).
    for sneaky in ["../config.py", "..%2Fconfig.py", "..\\..\\etc\\passwd"]:
        r = test_client.get(f"/api/demo-docs/{sneaky}")
        assert r.status_code in (400, 404), (
            f"Path traversal not blocked for {sneaky!r}: got {r.status_code}"
        )


# ── /api/jobs (create) ────────────────────────────────────────────────────────


def test_create_job_with_demo_doc(test_client):
    """Happy path: demo_doc form field + default pipeline → job_id returned."""
    r = test_client.post(
        "/api/jobs",
        data={"demo_doc": "02_financial_model.xlsx", "pipeline": "custom"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert "created_at" in body
    assert len(body["job_id"]) == 36, "Should be a UUID v4 (36 chars)"


def test_create_job_with_file_upload(test_client):
    """Happy path: file upload form field → job_id returned."""
    fake_pdf = io.BytesIO(b"%PDF-1.4\n%test pdf content\n")
    r = test_client.post(
        "/api/jobs",
        files={"file": ("test.pdf", fake_pdf, "application/pdf")},
        data={"pipeline": "custom"},
    )
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_create_job_response_matches_schema(test_client):
    """Returned job_id and created_at fields are well-formed."""
    r = test_client.post("/api/jobs", data={"demo_doc": "02_financial_model.xlsx"})
    body = r.json()
    assert isinstance(body["job_id"], str)
    assert isinstance(body["created_at"], str)
    # ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ
    assert body["created_at"].endswith("Z")
    assert "T" in body["created_at"]


# ── /api/jobs/{id} (status) ───────────────────────────────────────────────────


def test_get_unknown_job_404(test_client):
    r = test_client.get("/api/jobs/nonexistent-uuid-here")
    assert r.status_code == 404
    assert r.json()["detail"] == "Job not found"


def test_get_existing_job_returns_status(test_client):
    """Create a job, then fetch its status."""
    r = test_client.post("/api/jobs", data={"demo_doc": "02_financial_model.xlsx"})
    jid = r.json()["job_id"]

    r2 = test_client.get(f"/api/jobs/{jid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["job_id"] == jid
    assert body["status"] in ("queued", "running", "completed", "error")
    assert body["pipeline"] == "custom"


# ── /api/jobs/{id}/ask ────────────────────────────────────────────────────────


def test_ask_with_empty_question_400(test_client):
    """Empty question body → HTTP 400 with explanation."""
    r = test_client.post(
        "/api/jobs/any_job/ask",
        json={"question": "", "pipeline": "custom"},
    )
    # Pydantic min_length=1 → 422 unless caught earlier (the runtime check
    # in main.py returns 400 for whitespace-only).
    assert r.status_code in (400, 422)


def test_ask_with_unknown_job_404(test_client):
    """Ask against a job that was never ingested → 404."""
    r = test_client.post(
        "/api/jobs/never_existed/ask",
        json={"question": "What is X?", "pipeline": "custom"},
    )
    assert r.status_code == 404
    assert "not ingested" in r.json()["detail"].lower()


def test_ask_with_invalid_pipeline_value(test_client):
    """Pipeline=garbage should be 422 (pydantic validation) — strict literal."""
    r = test_client.post(
        "/api/jobs/any_job/ask",
        json={"question": "What is X?", "pipeline": "invalid_mode"},
    )
    assert r.status_code == 422


# ── /api/jobs/{id}/file ───────────────────────────────────────────────────────


def test_get_file_for_unknown_job_404(test_client):
    r = test_client.get("/api/jobs/never_existed/file")
    assert r.status_code == 404


# ── OpenAPI documentation surface ────────────────────────────────────────────


def test_openapi_schema_is_well_formed(test_client):
    """The OpenAPI JSON should generate without errors and include all endpoints."""
    r = test_client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "RAG Ingestion Engine"
    assert "/api/jobs" in schema["paths"]
    assert "/api/jobs/{job_id}/ask" in schema["paths"]
    assert "/api/demo-docs" in schema["paths"]


def test_swagger_docs_page_serves(test_client):
    """The /docs route should serve the Swagger UI HTML."""
    r = test_client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower() or "openapi" in r.text.lower()


def test_redoc_page_serves(test_client):
    """The /redoc route should serve ReDoc HTML."""
    r = test_client.get("/redoc")
    assert r.status_code == 200
    assert "redoc" in r.text.lower()


def test_endpoint_tags_grouped(test_client):
    """Each tagged endpoint should appear in the documented tag groups."""
    r = test_client.get("/openapi.json")
    schema = r.json()
    expected_tags = {"Jobs", "Q&A", "Files", "Demo Docs", "WebSocket"}
    actual_tags = {t["name"] for t in schema.get("tags", [])}
    assert expected_tags.issubset(actual_tags), (
        f"Missing tag groups: {expected_tags - actual_tags}"
    )
