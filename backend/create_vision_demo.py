"""Generate demo_docs/06_vision_ocr_demo.pdf — exercises the full vision pipeline.

Pages:
  1  Typed text  — pdfplumber extracts normally
  2  Data table  — pdfplumber extracts as structured table
  3  Embedded chart image  — PyMuPDF extracts, Claude vision captions
  4  Scanned page (image-only, no text layer)  — Claude vision OCR

Run from project root:
  backend/.venv/bin/python backend/create_vision_demo.py
"""
from __future__ import annotations
import io
from pathlib import Path

import fitz                          # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent.parent / "demo_docs" / "06_vision_ocr_demo.pdf"

DARK   = (30, 30, 50)
WHITE  = (255, 255, 255)
SLATE  = (100, 116, 139)
INDIGO = (99, 102, 241)
EMERALD= (16, 185, 129)
AMBER  = (245, 158, 11)


# ── helpers ───────────────────────────────────────────────────────────────────

def _font(size: int):
    """Return a PIL font; falls back to default if truetype not available."""
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:
        return ImageFont.load_default()


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Page 3: bar chart image ───────────────────────────────────────────────────

def _make_chart_png(w: int = 700, h: int = 420) -> bytes:
    img = Image.new("RGB", (w, h), WHITE)
    draw = ImageDraw.Draw(img)

    title_font = _font(22)
    label_font = _font(14)
    val_font   = _font(13)

    quarters = ["Q1 2024", "Q2 2024", "Q3 2024", "Q4 2024"]
    revenue  = [4.2, 5.8, 6.1, 7.4]   # $M
    costs    = [2.9, 3.4, 3.7, 4.1]

    margin_l, margin_b = 80, 60
    chart_w  = w - margin_l - 40
    chart_h  = h - margin_b - 80
    top      = 70
    bar_gap  = chart_w // len(quarters)
    bar_w    = bar_gap // 3
    max_val  = 9.0

    # Title
    draw.text((w // 2, 30), "Quarterly Revenue vs. Operating Costs ($M)",
              fill=DARK, font=title_font, anchor="mm")

    # Y-axis gridlines + labels
    for tick in range(0, 10, 2):
        y = top + chart_h - int(tick / max_val * chart_h)
        draw.line([(margin_l, y), (w - 40, y)], fill=(220, 220, 230), width=1)
        draw.text((margin_l - 8, y), f"${tick}M", fill=SLATE, font=label_font, anchor="rm")

    # Bars
    for i, (q, rev, cost) in enumerate(zip(quarters, revenue, costs)):
        x_center = margin_l + i * bar_gap + bar_gap // 2
        # Revenue bar
        rev_h = int(rev / max_val * chart_h)
        rx = x_center - bar_w - 4
        draw.rectangle([rx, top + chart_h - rev_h, rx + bar_w, top + chart_h],
                        fill=INDIGO)
        draw.text((rx + bar_w // 2, top + chart_h - rev_h - 6),
                  f"${rev}M", fill=DARK, font=val_font, anchor="mb")
        # Cost bar
        cost_h = int(cost / max_val * chart_h)
        cx = x_center + 4
        draw.rectangle([cx, top + chart_h - cost_h, cx + bar_w, top + chart_h],
                        fill=EMERALD)
        draw.text((cx + bar_w // 2, top + chart_h - cost_h - 6),
                  f"${cost}M", fill=DARK, font=val_font, anchor="mb")
        # Quarter label
        draw.text((x_center, top + chart_h + 18), q, fill=SLATE,
                  font=label_font, anchor="mm")

    # Legend
    lx, ly = margin_l, h - 28
    draw.rectangle([lx, ly, lx + 14, ly + 14], fill=INDIGO)
    draw.text((lx + 20, ly + 7), "Revenue", fill=DARK, font=label_font, anchor="lm")
    draw.rectangle([lx + 100, ly, lx + 114, ly + 14], fill=EMERALD)
    draw.text((lx + 120, ly + 7), "Operating Costs", fill=DARK, font=label_font, anchor="lm")

    return _png_bytes(img)


# ── Page 4: scanned page (image rendered from text, no PDF text layer) ───────

def _make_scan_png(w: int = 680, h: int = 880) -> bytes:
    img = Image.new("RGB", (w, h), (252, 250, 245))   # slightly off-white, like paper
    draw = ImageDraw.Draw(img)

    h2_font  = _font(24)
    body_font= _font(16)
    cap_font = _font(13)

    # Simulate a handwritten/scanned memo
    content = [
        ("INTERNAL MEMORANDUM", h2_font, DARK, 30),
        ("", body_font, DARK, 10),
        ("TO:   Executive Leadership Team", body_font, DARK, 0),
        ("FROM: Chief Operating Officer", body_font, DARK, 0),
        ("DATE: March 15, 2024", body_font, DARK, 0),
        ("RE:   Q1 Operational Review — Action Items", body_font, DARK, 0),
        ("", body_font, DARK, 10),
        ("Following the Q1 revenue results presented in the board deck,", body_font, SLATE, 0),
        ("the following action items require immediate attention:", body_font, SLATE, 0),
        ("", body_font, DARK, 8),
        ("  1.  Supply chain renegotiation: Target 12% cost reduction", body_font, DARK, 0),
        ("      by end of Q2. Owner: VP Supply Chain.", body_font, DARK, 0),
        ("", body_font, DARK, 6),
        ("  2.  Headcount freeze: No new hires in non-revenue roles", body_font, DARK, 0),
        ("      until EBITDA margin exceeds 18%. Owner: CHRO.", body_font, DARK, 0),
        ("", body_font, DARK, 6),
        ("  3.  Customer churn analysis: Identify top 20 at-risk accounts", body_font, DARK, 0),
        ("      and assign dedicated success managers. Owner: CRO.", body_font, DARK, 0),
        ("", body_font, DARK, 6),
        ("  4.  CapEx review: Defer non-critical infrastructure spend", body_font, DARK, 0),
        ("      of $2.3M to Q3. Owner: CFO.", body_font, DARK, 0),
        ("", body_font, DARK, 14),
        ("All owners to report status at the April 1 leadership sync.", body_font, SLATE, 0),
        ("", body_font, DARK, 14),
        ("Approved: ___________________________", body_font, DARK, 0),
        ("              Chief Executive Officer", cap_font, SLATE, 0),
    ]

    y = 40
    for text, font, color, extra_top in content:
        y += extra_top
        if text:
            draw.text((50, y), text, fill=color, font=font)
            bbox = draw.textbbox((0, 0), text, font=font)
            y += (bbox[3] - bbox[1]) + 4
        else:
            y += 4

    # Subtle scan artifacts: faint noise / slight rotation illusion via a border
    draw.rectangle([12, 12, w - 12, h - 12], outline=(200, 195, 185), width=1)

    return _png_bytes(img)


# ── Build PDF ─────────────────────────────────────────────────────────────────

def build():
    doc = fitz.open()

    # ── Page 1: Typed text ─────────────────────────────────────────────────────
    page = doc.new_page(width=595, height=842)    # A4

    page.insert_text((60, 70), "Acme Corp — Annual Performance Report 2024",
                     fontsize=18, color=(0.12, 0.12, 0.20))
    page.insert_text((60, 100), "Confidential · Prepared by the Office of the CFO",
                     fontsize=10, color=(0.40, 0.45, 0.54))

    body = (
        "This report summarises Acme Corp's financial and operational performance for the fiscal year\n"
        "ending December 31, 2024. Revenue grew 34% year-over-year, driven by strong enterprise\n"
        "sales and the successful launch of the Acme Cloud Platform in Q2.\n\n"
        "Operating costs increased by 18% due to headcount expansion and infrastructure investment,\n"
        "resulting in an EBITDA margin improvement from 14.2% to 19.7%.\n\n"
        "Key highlights:\n"
        "  •  Total revenue: $23.5M  (+34% YoY)\n"
        "  •  Gross margin: 68.4%    (+3.1 pp)\n"
        "  •  EBITDA:       $4.6M    (+87% YoY)\n"
        "  •  Headcount:    312 FTEs  (+41 net new hires)\n"
        "  •  Customer NPS: 72       (+8 points)\n\n"
        "The following pages contain detailed quarterly breakdowns, operational cost analysis,\n"
        "and forward-looking guidance for FY2025."
    )
    page.insert_text((60, 130), body, fontsize=11,
                     color=(0.15, 0.18, 0.25), lineheight=1.6)

    # ── Page 2: Data table (PDF text layer so pdfplumber can extract it) ───────
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((60, 60), "Quarterly Financial Summary",
                      fontsize=16, color=(0.12, 0.12, 0.20))

    headers = ["Quarter", "Revenue ($M)", "Op. Costs ($M)", "Gross Margin", "EBITDA ($M)"]
    rows = [
        ["Q1 2024", "4.2", "2.9", "65.2%", "0.62"],
        ["Q2 2024", "5.8", "3.4", "67.1%", "1.10"],
        ["Q3 2024", "6.1", "3.7", "68.9%", "1.24"],
        ["Q4 2024", "7.4", "4.1", "70.8%", "1.64"],
        ["FY 2024", "23.5", "14.1", "68.4%", "4.60"],
    ]

    col_x = [60, 155, 275, 385, 470]
    row_h  = 22
    y_tbl  = 95

    # Header row
    for i, h in enumerate(headers):
        page2.draw_rect(fitz.Rect(col_x[i] - 4, y_tbl - 4,
                                  (col_x[i + 1] if i + 1 < len(col_x) else 540) - 2, y_tbl + row_h - 2),
                        color=None, fill=(0.39, 0.40, 0.95))
        page2.insert_text((col_x[i], y_tbl + 4), h, fontsize=9,
                          color=(1, 1, 1))

    # Data rows
    for r_idx, row in enumerate(rows):
        y = y_tbl + (r_idx + 1) * row_h
        bg = (0.97, 0.97, 0.99) if r_idx % 2 == 0 else (1, 1, 1)
        if r_idx == len(rows) - 1:
            bg = (0.93, 0.95, 0.99)  # totals row
        for i, cell in enumerate(row):
            x0 = col_x[i] - 4
            x1 = (col_x[i + 1] if i + 1 < len(col_x) else 540) - 2
            page2.draw_rect(fitz.Rect(x0, y - 2, x1, y + row_h - 2),
                            color=(0.85, 0.85, 0.90), fill=bg, width=0.5)
            page2.insert_text((col_x[i], y + 4), cell, fontsize=9,
                              color=(0.10, 0.12, 0.20))

    page2.insert_text((60, y_tbl + (len(rows) + 2) * row_h),
                      "All figures unaudited. EBITDA excludes stock-based compensation.",
                      fontsize=8, color=(0.55, 0.55, 0.60))

    # ── Page 3: Embedded chart image ──────────────────────────────────────────
    page3 = doc.new_page(width=595, height=842)
    page3.insert_text((60, 60), "Revenue & Cost Trend (Chart)",
                      fontsize=16, color=(0.12, 0.12, 0.20))
    page3.insert_text((60, 84), "Figure 1: Quarterly comparison generated from management accounts.",
                      fontsize=9, color=(0.50, 0.50, 0.55))

    chart_png = _make_chart_png()
    img_rect  = fitz.Rect(60, 110, 535, 440)
    page3.insert_image(img_rect, stream=chart_png)

    page3.insert_text((60, 460),
                      "The chart above confirms consistent margin expansion across all four quarters,\n"
                      "with revenue growth outpacing cost growth in every period.",
                      fontsize=10, color=(0.20, 0.22, 0.30), lineheight=1.5)

    # ── Page 4: Scanned page (image only — no text layer) ────────────────────
    page4 = doc.new_page(width=595, height=842)
    scan_png  = _make_scan_png()
    scan_rect = fitz.Rect(30, 30, 565, 812)
    page4.insert_image(scan_rect, stream=scan_png)
    # Deliberately NO insert_text — pdfplumber will find nothing → needs_ocr=True

    doc.save(str(OUT))
    doc.close()
    print(f"Saved: {OUT}")
    print("Pages: 1=text  2=table  3=chart-image  4=scanned-memo")


if __name__ == "__main__":
    build()
