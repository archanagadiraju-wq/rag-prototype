"""OCR detection / ocr_fraction signal — unit tests.

The agent uses `ocr_fraction` from inspect_document to decide whether to
route a PDF to pdfplumber (fast) or Docling (slow but OCR-capable). Bugs
here lead to wrong parser choice → either missed OCR content or wasted
15 minutes on Docling for born-digital PDFs.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from agent.tools import _scan_pdf_ocr_signal


pytestmark = pytest.mark.unit


def _pages_for_test(num_pages: int, scanned_pages: set[int]):
    """Build mock pdfplumber-page-like objects.

    `scanned_pages` (1-indexed) → return empty text (simulating image-only page).
    """
    class MockPage:
        def __init__(self, idx_one_based: int, scanned: bool):
            self.idx = idx_one_based
            self.scanned = scanned
        def extract_text(self):
            return "" if self.scanned else f"Page {self.idx} has substantial text content. " * 20

    return [MockPage(i + 1, (i + 1) in scanned_pages) for i in range(num_pages)]


def test_all_pages_text_ocr_fraction_zero():
    """A born-digital PDF (no scanned pages) → ocr_fraction = 0.0."""
    pages = _pages_for_test(10, scanned_pages=set())
    info = _scan_pdf_ocr_signal(pages)
    assert info["ocr_fraction"] == 0.0
    assert info["pages_needing_ocr"] == 0
    assert info["pages_sampled"] == 10


def test_all_pages_scanned_ocr_fraction_one():
    """A fully-scanned PDF → ocr_fraction = 1.0."""
    pages = _pages_for_test(5, scanned_pages={1, 2, 3, 4, 5})
    info = _scan_pdf_ocr_signal(pages)
    assert info["ocr_fraction"] == 1.0
    assert info["pages_needing_ocr"] == 5


def test_mixed_content_ocr_fraction():
    """3 of 12 pages scanned → ocr_fraction = 0.25."""
    pages = _pages_for_test(12, scanned_pages={1, 5, 9})
    info = _scan_pdf_ocr_signal(pages)
    assert info["ocr_fraction"] == 0.25
    assert info["pages_needing_ocr"] == 3
    assert info["pages_sampled"] == 12


def test_threshold_boundary_detection():
    """Exactly at the 0.2 boundary: 1 of 5 pages scanned → ocr_fraction = 0.2."""
    pages = _pages_for_test(5, scanned_pages={1})
    info = _scan_pdf_ocr_signal(pages)
    assert info["ocr_fraction"] == 0.2


def test_huge_doc_samples_not_full_scan():
    """For docs > 200 pages, we sample (don't scan every page) to keep
    inspection fast. The sampled_indices should NOT be the full page range."""
    pages = _pages_for_test(500, scanned_pages=set(range(450, 500)))  # last 50 scanned
    info = _scan_pdf_ocr_signal(pages)
    assert info["pages_sampled"] <= 200, "Cap should bound scan to ~200 pages"
    # The sampling includes first 20 + last 10 + middles — the trailing
    # scanned section should be detected
    assert info["pages_needing_ocr"] >= 5, "Scanned tail must be sampled"


def test_empty_pdf_does_not_crash():
    """0-page PDF returns zeros, not error."""
    info = _scan_pdf_ocr_signal([])
    assert info["ocr_fraction"] == 0.0
    assert info["pages_sampled"] == 0


def test_pdfplumber_error_per_page_is_caught():
    """One page raising on extract_text should not kill the whole scan."""
    class BrokenPage:
        def extract_text(self):
            raise RuntimeError("page corrupt")
    class GoodPage:
        def extract_text(self):
            return "good content " * 20

    info = _scan_pdf_ocr_signal([BrokenPage(), GoodPage(), GoodPage()])
    # Broken page → counted as needing OCR (zero-text)
    assert info["pages_needing_ocr"] == 1
    assert info["pages_sampled"] == 3
