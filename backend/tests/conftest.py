"""Shared pytest fixtures.

Adds the backend dir to sys.path so tests can import `pipelines.*`,
`services.*`, `agent.*`, `main` directly without packaging gymnastics.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make backend/ importable regardless of where pytest is invoked from
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEMO_DOCS_DIR = BACKEND_DIR.parent / "demo_docs"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def demo_docs_dir() -> Path:
    """Path to the bundled demo documents."""
    return DEMO_DOCS_DIR


@pytest.fixture
def pharma_pdf(demo_docs_dir: Path) -> Path:
    """4-page born-digital PDF (text-extractable, no OCR needed)."""
    return demo_docs_dir / "01_pharmaceutical_trial.pdf"


@pytest.fixture
def finance_xlsx(demo_docs_dir: Path) -> Path:
    """6-sheet XLSX with structured tables (tests SQL store path)."""
    return demo_docs_dir / "02_financial_model.xlsx"


@pytest.fixture
def contract_docx(demo_docs_dir: Path) -> Path:
    """Multi-section DOCX (tests python-docx parser path)."""
    return demo_docs_dir / "03_vendor_contract.docx"


@pytest.fixture
def ocr_pdf(demo_docs_dir: Path) -> Path:
    """4-page mixed-content PDF (1 page scanned, tests OCR detection)."""
    return demo_docs_dir / "06_vision_ocr_demo.pdf"


@pytest.fixture
def clean_job_id(request) -> str:
    """Unique job id per test. Clears any persisted state on teardown."""
    import services.job_cache as cache
    jid = f"test_{request.node.name[:40]}".replace("[", "_").replace("]", "_")
    cache.clear(jid)
    yield jid
    cache.clear(jid)


@pytest.fixture
def test_client():
    """FastAPI TestClient bound to the live app — no network required."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)
