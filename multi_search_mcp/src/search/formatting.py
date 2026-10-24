"""Presentation projections derived from fused search rows."""
from __future__ import annotations

from typing import Any

from ..support.models import ANSWER_SOURCES, as_dicts, is_empty_result
from .search_runner import normalize_source_name


# Upper bound for the snippet shown in ``display_results``. Without this, scraped
# page bodies written back onto result rows (``scraped_content``) leak full text
# into the compact display list, defeating the response-size cap that already
# applies to ``scrapes[]``.
DISPLAY_SNIPPET_CHARS = 600


def route_degradation(route: str, results: list[dict], source_names: set[str] | None, meta: dict) -> dict | None:
    if source_names is not None:
        return None
    primary_sources = set(meta.get("primary_success_sources") or [])
    if not primary_sources:
        return None
    rows = as_dicts(results)
    # Result rows carry public source names (e.g. ``github-repos``) while
    # ``primary_success_sources`` uses internal names (``github_repos``).
    # Normalize before comparing so a genuine primary
    # success is not misread as a degradation.
    primary_sources = {normalize_source_name(src) for src in primary_sources}
    has_primary_success = any(
        normalize_source_name(str(row.get("source") or "")) in primary_sources
        and "error" not in row
        and not is_empty_result(row)
        for row in rows
    )
    if has_primary_success:
        return None
    fallback_sources = sorted(meta.get("degrade_to") or [])
    return {
        "route": route,
        "reason": "primary providers unavailable or returned no usable results",
        "fallback_sources": fallback_sources,
        "message": (
            f"{route} degraded to {', '.join(fallback_sources)}"
            if fallback_sources else f"{route} primary providers unavailable and no fallback is configured"
        ),
    }


def display_results(results: list[dict]) -> list[dict]:
    rows = []
    for row in as_dicts(results):
        if row.get("error") or is_empty_result(row) or row.get("source") in ANSWER_SOURCES:
            continue
        url = row.get("url")
        if not url:
            continue
        rows.append({
            "title": row.get("title") or url,
            "url": url,
            "source": row.get("source"),
            "snippet": compact_text(
                row.get("description") or row.get("content") or row.get("scraped_content") or "",
                DISPLAY_SNIPPET_CHARS,
            ),
        })
    return rows


def extract_summaries(results: list[dict]) -> list[dict]:
    summaries = []
    for row in as_dicts(results):
        source = row.get("source")
        answer = row.get("answer")
        if source not in ANSWER_SOURCES or not answer or row.get("error"):
            continue
        summaries.append({
            "source": source,
            "answer": answer,
            "endpoint": row.get("endpoint"),
            "request_id": row.get("request_id"),
        })
    return summaries


def source_from_answer_source(source: str) -> str:
    return source[: -len("_answer")] if source.endswith("_answer") else source


def compact_text(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def extract_source_briefs(results: list[dict], *, max_items_per_source: int = 3) -> list[dict]:
    """Return one display-ready brief per provider.

    Provider-native answer rows are kept as the strongest signal. URL-only
    providers still get a source brief built from their highest-ranked result
    snippets so fast searches expose every participating provider, not only the
    providers that happen to emit ``*_answer`` rows.
    """
    rows = as_dicts(results)
    native_by_source: dict[str, dict] = {}
    briefs: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.get("error") or is_empty_result(row):
            continue
        source = str(row.get("source") or "")
        if not source:
            continue
        if source in ANSWER_SOURCES and row.get("answer"):
            canonical = source_from_answer_source(source)
            native_by_source[canonical] = {
                "source": canonical,
                "answer_source": source,
                "brief": row.get("answer"),
                "brief_type": "native_answer",
                "endpoint": row.get("endpoint"),
                "request_id": row.get("request_id"),
                "result_count": 0,
                "top_urls": [],
            }
            continue
        if source in ANSWER_SOURCES:
            continue

        entry = briefs.setdefault(source, {
            "source": source,
            "brief": "",
            "brief_type": "result_brief",
            "result_count": 0,
            "top_urls": [],
            "_parts": [],
        })
        entry["result_count"] += 1
        if row.get("url") and len(entry["top_urls"]) < max_items_per_source:
            entry["top_urls"].append(row.get("url"))
        if len(entry["_parts"]) < max_items_per_source:
            title = compact_text(row.get("title"), 120)
            description = compact_text(row.get("description") or row.get("scraped_content"), 240)
            if title and description:
                entry["_parts"].append(f"{title}: {description}")
            elif title or description:
                entry["_parts"].append(title or description)

    output: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        source = str(row.get("source") or "")
        canonical = source_from_answer_source(source)
        if not canonical or canonical in seen:
            continue
        item = native_by_source.get(canonical) or briefs.get(canonical)
        if not item:
            continue
        seen.add(canonical)
        if item.get("_parts"):
            item["brief"] = compact_text(" | ".join(item["_parts"]), 900)
        item.pop("_parts", None)
        output.append(item)
    return output


def compat_source_summaries(source_briefs: list[dict]) -> list[dict]:
    rows = []
    for item in source_briefs:
        compat = dict(item)
        compat.setdefault("summary", compat.get("brief", ""))
        compat.setdefault("summary_type", compat.get("brief_type", "result_brief"))
        rows.append(compat)
    return rows
