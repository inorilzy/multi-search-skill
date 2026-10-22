"""Response presentation: summaries, display rows and Markdown rendering."""
from __future__ import annotations

from typing import Any

from ..search.candidate import SEARCH_RESULT_LIMIT
from ..search.resolve import resolve_search_plan
from ..search.search_runner import normalize_source_name
from ..support.format import format_results, format_scrapes
from ..support.models import ANSWER_SOURCES, as_dicts, is_empty_result
from . import runtime
from .requests import MultiSearchRequest, SearchWebRequest
from .search_pipeline import run_search_web


# Upper bound for the snippet shown in ``display_results``. Without this, scraped
# page bodies written back onto result rows (``scraped_content``) leak full text
# into the compact display list, defeating the response-size cap that already
# applies to ``scrapes[]``.
DISPLAY_SNIPPET_CHARS = 600


def run_multi_search(request: MultiSearchRequest | dict) -> dict:
    """Compatibility presentation of the shared RRF search-and-fetch flow."""
    if isinstance(request, dict):
        request = MultiSearchRequest(**request)
    if request.output not in {"json", "markdown", "both"}:
        raise ValueError(
            f"invalid output mode: {request.output!r}; valid: json, markdown, both"
        )
    config = runtime.load_config_safe(request.config_path)
    plan = resolve_search_plan(request, config)
    query_runs = []
    response = run_search_web(
        SearchWebRequest(
            query=request.query, route=request.route, count=request.count,
            sources=request.sources, timeout=request.timeout, expand=request.expand,
            config_path=request.config_path, use_state=request.use_state,
        ),
        config={**config, "scrape_per_source": plan.scrape_per_source},
        query_runs_observer=query_runs.extend,
        scrape_chars=request.scrape_chars, scrape_timeout=request.scrape_timeout,
        scrape_concurrency=request.scrape_concurrency,
    )
    rows = [row for _query, query_rows in query_runs for row in query_rows]
    results = response["results"]
    summaries = _extract_summaries(rows)
    source_briefs = _extract_source_briefs(rows)
    response.update(
        summary=summaries[0]["answer"] if summaries else None,
        summaries=summaries, source_briefs=source_briefs,
        source_summaries=_compat_source_summaries(source_briefs),
        display_results=_display_results(results),
    )
    response["diagnostics"].update(
        valid_result_count=len(results),
        effective_counts=plan.effective_counts,
        route_meta={**plan.route_defaults, "scrape_top": SEARCH_RESULT_LIMIT,
                    "want_content": False, "timeout": plan.timeout,
                    "route_default_count": plan.route_defaults["count"],
                    "route_default_timeout": plan.route_defaults["timeout"]},
        route_degradation=_route_degradation(plan.route, rows, plan.sources, plan.route_defaults),
    )
    if request.scrape_top is not None or request.scrape_per_source is not None:
        response["diagnostics"]["legacy_scrape_limits"] = (
            "scrape_top and scrape_per_source no longer limit fetching; "
            "all final RRF results (at most 15) are fetched"
        )
    if plan.output_mode in {"markdown", "both"}:
        raw_counts = {}
        for row in rows:
            if row.get("url") and not row.get("error") and not is_empty_result(row):
                source = row.get("source", "?")
                raw_counts[source] = raw_counts.get(source, 0) + 1
        response["markdown"] = format_results(
            results + [row for row in rows if row.get("source") in ANSWER_SOURCES or row.get("error") or is_empty_result(row)],
            request.query, raw_counts=raw_counts, brief=request.brief,
            verbose=request.verbose, title_url_only=plan.title_url_only,
            show_answer=plan.show_answer or request.verbose, show_snippet=plan.show_snippet,
            degradation=response["diagnostics"]["route_degradation"],
        ) + format_scrapes(response["scrapes"], max_chars=plan.scrape_chars)
        # Rendered Markdown owns the bodies in these modes; JSON rows retain
        # source references and fetch metadata without another copy of the text.
        response["scrapes"] = [
            {key: value for key, value in row.items() if key != "markdown"}
            for row in response["scrapes"]
        ]
    return response


def _route_degradation(route: str, results: list[dict], source_names: set[str] | None, meta: dict) -> dict | None:
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


def _display_results(results: list[dict]) -> list[dict]:
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
            "snippet": _compact_text(
                row.get("description") or row.get("content") or row.get("scraped_content") or "",
                DISPLAY_SNIPPET_CHARS,
            ),
        })
    return rows


def _extract_summaries(results: list[dict]) -> list[dict]:
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


def _source_from_answer_source(source: str) -> str:
    return source[: -len("_answer")] if source.endswith("_answer") else source


def _compact_text(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _extract_source_briefs(results: list[dict], *, max_items_per_source: int = 3) -> list[dict]:
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
            canonical = _source_from_answer_source(source)
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
            title = _compact_text(row.get("title"), 120)
            description = _compact_text(row.get("description") or row.get("scraped_content"), 240)
            if title and description:
                entry["_parts"].append(f"{title}: {description}")
            elif title or description:
                entry["_parts"].append(title or description)

    output: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        source = str(row.get("source") or "")
        canonical = _source_from_answer_source(source)
        if not canonical or canonical in seen:
            continue
        item = native_by_source.get(canonical) or briefs.get(canonical)
        if not item:
            continue
        seen.add(canonical)
        if item.get("_parts"):
            item["brief"] = _compact_text(" | ".join(item["_parts"]), 900)
        item.pop("_parts", None)
        output.append(item)
    return output


def _compat_source_summaries(source_briefs: list[dict]) -> list[dict]:
    rows = []
    for item in source_briefs:
        compat = dict(item)
        compat.setdefault("summary", compat.get("brief", ""))
        compat.setdefault("summary_type", compat.get("brief_type", "result_brief"))
        rows.append(compat)
    return rows
