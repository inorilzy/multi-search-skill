"""Bring a query within a provider's documented length limits before sending.

Over-long queries are rejected upstream with 400/422, which used to surface as
a provider failure. Truncation keeps the leading words (the most specific part
of a fused query) and reports it as a notice row, so the change is visible
without counting as a provider error or against key health.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"\S+")


def limit_query(
    source: str,
    query: str,
    *,
    max_chars: int | None = None,
    max_words: int | None = None,
) -> tuple[str, list[dict]]:
    """Return ``(query, notes)``; ``notes`` holds one row when truncated."""
    original = " ".join(str(query or "").split())
    text = original
    if max_words is not None:
        words = _WORD.findall(text)
        if len(words) > max_words:
            text = " ".join(words[:max_words])
    if max_chars is not None and len(text) > max_chars:
        cut = text[:max_chars]
        # Prefer a word boundary when one exists in the last fifth.
        space = cut.rfind(" ")
        if space >= int(max_chars * 0.8):
            cut = cut[:space]
        text = cut.rstrip()
    if text == original:
        return text, []
    limits = []
    if max_chars is not None:
        limits.append(f"{max_chars} characters")
    if max_words is not None:
        limits.append(f"{max_words} words")
    note = {
        "source": source,
        "notice": f"query truncated to the provider limit ({' / '.join(limits)})",
    }
    return text, [note]
