"""Agentic ingestion layer.

Instead of a hardcoded stage sequence, a Claude haiku agent inspects a
document, decides which tools to call (parsers, OCR, captioner, embedder),
and orchestrates the ingestion adaptively.
"""
