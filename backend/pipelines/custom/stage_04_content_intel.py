"""Stage 4 — Content Intelligence (Mode A).

Uses Claude (haiku) for doc_type/domain classification + 2-sentence summary.
Uses spaCy en_core_web_sm for named-entity extraction.
"""
from __future__ import annotations
import json
import re

import anthropic

from config import settings
from models.events import ContentIntelPayload
from verification.l1 import make_check, make_verification
from pipelines.base import StageResult

_DOC_TYPES  = ["research_paper", "financial_report", "contract",
                "technical_spec", "presentation", "memo", "other"]
_DOMAINS    = ["medical", "financial", "legal", "technical", "general"]
_FLAGS      = ["contains_tables", "contains_code", "contains_figures",
               "has_executive_summary", "is_regulatory", "multi_column"]
_NER_LABELS = {"PERSON", "ORG", "PRODUCT", "GPE", "DATE", "MONEY", "LAW"}

_SAMPLE_CHARS  = 4000   # chars sent to Claude
_NER_CHARS     = 6000   # chars fed to spaCy
_MAX_ENTITIES  = 30


def _build_sample(payload: dict) -> str:
    parts: list[str] = []
    for b in (payload.get("text_blocks") or [])[:25]:
        t = b.get("text", "").strip()
        if t:
            parts.append(t)
    # For XLSX/table-only docs, fall back to table content
    if not parts:
        for tbl in (payload.get("tables") or [])[:5]:
            if tbl.get("headers"):
                parts.append(" | ".join(str(h) for h in tbl["headers"]))
            for row in (tbl.get("rows") or [])[:10]:
                parts.append(" | ".join(str(c) for c in row))
    return "\n".join(parts)[:_SAMPLE_CHARS].strip()


def _run_ner(text: str) -> list[dict]:
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        doc = nlp(text[:_NER_CHARS])
        seen: set[tuple] = set()
        entities = []
        for ent in doc.ents:
            if ent.label_ not in _NER_LABELS:
                continue
            key = (ent.text.strip().lower(), ent.label_)
            if key in seen or len(ent.text.strip()) < 2:
                continue
            seen.add(key)
            entities.append({"text": ent.text.strip(), "label": ent.label_})
        return entities[:_MAX_ENTITIES]
    except Exception:
        return []


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    return re.sub(r"\n?```$", "", text).strip()


async def run(parser_payload: dict, mime: str) -> StageResult:
    sample = _build_sample(parser_payload)

    if not sample:
        payload = ContentIntelPayload(
            doc_type="other", doc_type_confidence=0.0,
            language="unknown", domain="general",
            summary="No text content available for analysis.",
            content_flags=[],
        )
        checks = [
            make_check("doc_type_classified", False, "No text to classify", severity="warn"),
            make_check("summary_generated",   False, "No text available",   severity="warn"),
        ]
        return StageResult(payload=payload.model_dump(), verification=make_verification(checks))

    # ── Claude classification ──────────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = f"""Analyze this document excerpt and return a JSON object with exactly these fields:
- "doc_type": one of {_DOC_TYPES}
- "domain": one of {_DOMAINS}
- "doc_type_confidence": float 0.0–1.0
- "content_flags": array of zero or more flags from {_FLAGS}
- "summary": exactly 2 sentences — the document's purpose and its most important finding or conclusion
- "key_dates": array of up to 5 significant dates mentioned (ISO format preferred, e.g. "2026-03-15")
- "language": ISO 639-1 code (e.g. "en")

Document excerpt:
---
{sample}
---

Return ONLY valid JSON. No markdown, no explanation."""

    from services.api_retry import with_retry_sync
    import asyncio
    response = await asyncio.to_thread(
        with_retry_sync,
        client.messages.create,
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        label="content_intel",
    )
    intel = json.loads(_strip_fences(response.content[0].text))

    # claude-haiku-4-5 pricing: $0.80/M input, $4.00/M output
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = (input_tokens * 0.80 + output_tokens * 4.00) / 1_000_000

    # ── spaCy NER ─────────────────────────────────────────────────────────────
    entities = _run_ner(sample)

    payload = ContentIntelPayload(
        doc_type=intel.get("doc_type", "other"),
        doc_type_confidence=float(intel.get("doc_type_confidence", 0.5)),
        language=intel.get("language", "en"),
        domain=intel.get("domain", "general"),
        entities=entities,
        key_dates=intel.get("key_dates", [])[:10],
        summary=intel.get("summary", ""),
        content_flags=intel.get("content_flags", []),
        llm_input_tokens=input_tokens,
        llm_output_tokens=output_tokens,
        llm_cost_usd=round(cost_usd, 6),
    )

    checks = [
        make_check(
            "doc_type_classified",
            payload.doc_type != "other",
            f"{payload.doc_type} ({payload.doc_type_confidence:.0%} confidence)",
        ),
        make_check(
            "domain_detected",
            payload.domain != "general",
            f"Domain: {payload.domain}",
        ),
        make_check(
            "summary_generated",
            bool(payload.summary),
            f"{len(payload.summary.split())} words" if payload.summary else "empty",
        ),
        make_check(
            "entities_extracted",
            len(entities) > 0,
            f"{len(entities)} entit{'y' if len(entities)==1 else 'ies'} found",
            severity="warn",
        ),
    ]

    return StageResult(payload=payload.model_dump(), verification=make_verification(checks))
