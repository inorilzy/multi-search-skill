"""Compatibility multi-search presentation over the shared search-and-fetch flow.

The presentation helpers (summaries, briefs, display rows, route degradation)
have one implementation in ``search.formatting``; this module only assembles
the compatibility response around ``run_search_web``.
"""
from __future__ import annotations

from .search.formatting import (
    compat_source_summaries,
    display_results,
    extract_source_briefs,
    extract_summaries,
    route_degradation,
)
from .search.resolve import SearchPlanRequest, resolve_search_plan
from .search_web import run_search_web
from .state import runtime
from .support.format import format_results, format_scrapes
from .support.models import ANSWER_SOURCES, is_empty_result
from .support.requests import MultiSearchRequest, SearchWebRequest


OUTPUT_MODES = ("json", "markdown", "both")


def run_multi_search(request: MultiSearchRequest | dict) -> dict:
    """Compatibility presentation of the shared RRF search-and-fetch flow."""
    if isinstance(request, dict):
        request = MultiSearchRequest(**request)
    if request.output not in OUTPUT_MODES:
        raise ValueError(
            f"invalid output mode: {request.output!r}; valid: {', '.join(OUTPUT_MODES)}"
        )
    config = runtime.load_config_safe(request.config_path)
    plan = resolve_search_plan(
        SearchPlanRequest(
            route=request.route,
            count=request.count,
            sources=request.sources,
            timeout=request.timeout,
            scrape_chars=request.scrape_chars,
            scrape_timeout=request.scrape_timeout,
            scrape_concurrency=request.scrape_concurrency,
            output=request.output,
        ),
        config,
    )
    query_runs = []
    response = run_search_web(
        SearchWebRequest(
            query=request.query, route=request.route, count=request.count,
            sources=request.sources, timeout=request.timeout, expand=request.expand,
            config_path=request.config_path, use_state=request.use_state,
        ),
        config=config,
        query_runs_observer=query_runs.extend,
        scrape_chars=request.scrape_chars, scrape_timeout=request.scrape_timeout,
        scrape_concurrency=request.scrape_concurrency,
    )
    rows = [row for _query, query_rows in query_runs for row in query_rows]
    results = response["results"]
    summaries = extract_summaries(rows)
    source_briefs = extract_source_briefs(rows)
    response.update(
        summary=summaries[0]["answer"] if summaries else None,
        summaries=summaries, source_briefs=source_briefs,
        source_summaries=compat_source_summaries(source_briefs),
        display_results=display_results(results),
    )
    response["diagnostics"].update(
        valid_result_count=len(results),
        effective_counts=plan.effective_counts,
        # Dead knobs (scrape_top/want_content) stay out of route_meta: every
        # route fetches the final RRF results in the shared post-search stage.
        route_meta={**plan.route_defaults, "timeout": plan.timeout,
                    "route_default_count": plan.route_defaults["count"],
                    "route_default_timeout": plan.route_defaults["timeout"]},
        route_degradation=route_degradation(plan.route, rows, plan.sources, plan.route_defaults),
    )
    if plan.output_mode in {"markdown", "both"}:
        raw_counts = {}
        for row in rows:
            if row.get("url") and not row.get("error") and not is_empty_result(row):
                source = row.get("source", "?")
                raw_counts[source] = raw_counts.get(source, 0) + 1
        response["markdown"] = format_results(
            results + [row for row in rows if row.get("source") in ANSWER_SOURCES or row.get("error") or is_empty_result(row)],
            request.query, raw_counts=raw_counts,
            show_answer=plan.show_answer, show_snippet=plan.show_snippet,
            degradation=response["diagnostics"]["route_degradation"],
        ) + format_scrapes(response["scrapes"], max_chars=plan.scrape_chars)
        # Rendered Markdown owns the bodies in these modes; JSON rows retain
        # source references and fetch metadata without another copy of the text.
        response["scrapes"] = [
            {key: value for key, value in row.items() if key != "markdown"}
            for row in response["scrapes"]
        ]
    return response
