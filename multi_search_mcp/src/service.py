"""Reusable service layer shared by MCP tools and future CLI paths."""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any

from .support.config import ConfigError, config_list, load_config, resolve_config_path
from .support.dedup import deduplicate, rank_results
from .support.format import format_results, format_scrapes
from .state.key_state import BasicKeyManager, SQLiteKeyManager
from .state.keys import count_jina_keys, jina_config_keys, load_keys
from .support.models import ANSWER_SOURCES, as_dicts, is_empty_result
from .scrape.scrape import scrape_url_smart
from .scrape.stage import (
    _backfill_scrape_title,
    run_scrape_stage as _run_scrape_stage,
)
from .search.search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_PROFILES,
    SearchRunner,
    SearchRunnerConfig,
    normalize_source_name,
)
from .search.resolve import (
    COUNT_CAPS,
    DEFAULT_COUNTS,
    _resolve_int,
    _resolve_nonnegative,
    resolve_active_sources,
    resolve_search_plan,
)
from .support.secrets import scrub_secrets
from .state.site_memory import SiteScraperMemory
from .state.state_store import StateStore


MAX_EXPAND_CONCURRENCY = 5

# Upper bound for the snippet shown in ``display_results``. Without this, scraped
# page bodies written back onto result rows (``scraped_content``) leak full text
# into the compact display list, defeating the response-size cap that already
# applies to ``scrapes[]``.
DISPLAY_SNIPPET_CHARS = 600


@dataclass
class MultiSearchRequest:
    query: str
    route: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    scrape_top: int | None = None
    scrape_chars: int | None = None
    scrape_per_source: int | None = None
    scrape_timeout: int | None = None
    scrape_concurrency: int | None = None
    timeout: int | None = None
    output: str = "both"
    config_path: str | None = None
    expand: list[str] = field(default_factory=list)
    brief: bool = False
    verbose: bool = False
    title_url_only: bool = False
    use_state: bool = True


@dataclass
class ScrapeRequest:
    url: str
    backends: list[str] | None = None
    scrape_chars: int | None = None
    timeout: int | None = None
    output: str = "both"
    use_state: bool = True


def run_multi_search(request: MultiSearchRequest | dict) -> dict:
    if isinstance(request, dict):
        request = MultiSearchRequest(**request)
    if not request.query:
        raise ValueError("query is required")
    config = _load_config_safe(request.config_path)
    plan = resolve_search_plan(request, config)

    keys = load_keys()

    from .search.registry import build_provider_registry

    store = StateStore() if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
    site_memory = SiteScraperMemory(store) if store else None
    runner_config = SearchRunnerConfig(
        plan.route,
        plan.effective_counts,
        plan.timeout,
        plan.serpapi_engine,
        keys,
        plan.want_content,
    )
    base_sources, active_sources = resolve_active_sources(
        plan.route, plan.sources, plan.disabled_sources,
    )
    if base_sources and not active_sources:
        raise ValueError(
            f"all selected sources are disabled: {', '.join(sorted(base_sources))}"
        )

    def route_resolver(_route, lite=False):
        _selected, active = resolve_active_sources(
            _route, plan.sources, plan.disabled_sources, lite=lite,
        )
        return active

    runner = SearchRunner(runner_config, build_provider_registry(), route_resolver=route_resolver, key_manager=key_manager)

    queries_to_run = [request.query] + list(request.expand or config_list(config, "expand") or config_list(config, "expand_queries"))
    all_results: list[dict] = []
    if len(queries_to_run) == 1:
        all_results = runner.run(request.query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(queries_to_run), MAX_EXPAND_CONCURRENCY)) as pool:
            futures = {pool.submit(runner.run, q, idx > 0): q for idx, q in enumerate(queries_to_run)}
            for fut in concurrent.futures.as_completed(futures):
                q = futures[fut]
                try:
                    all_results.extend(fut.result())
                except Exception as exc:
                    all_results.append({"source": "multi-search", "error": f"query '{q}' failed: {scrub_secrets(exc, keys)}"})

    scrape_result = _run_scrape_stage(
        all_results,
        keys=keys,
        scrape_top=plan.scrape_top,
        scrape_per_source=plan.scrape_per_source,
        scrape_timeout=plan.scrape_timeout,
        scrape_url_timeout=plan.scrape_url_timeout,
        scrape_concurrency=plan.scrape_concurrency,
        scrape_chars=plan.scrape_chars,
        site_memory=site_memory,
        key_manager=key_manager,
        skip_summarized_sources=bool(plan.route_defaults.get("skip_summarized_sources")),
    )
    final_results, _ = deduplicate(
        scrape_result["with_content"] + scrape_result["final_without_content"] + scrape_result["passthrough"]
    )
    # Single ranking shared by JSON results, markdown rendering, and provider
    # status — previously sorting only happened inside format_results, so the
    # JSON `results` order diverged from the markdown order.
    final_results = rank_results(final_results)
    _add_public_content_aliases(final_results)
    valid_count = _valid_result_count(final_results)
    markdown = ""
    if plan.output_mode in {"markdown", "both"}:
        markdown = format_results(
            final_results,
            request.query,
            raw_counts=scrape_result["raw_counts"],
            brief=request.brief,
            verbose=request.verbose,
            title_url_only=plan.title_url_only,
            show_answer=plan.show_answer or request.verbose,
            show_snippet=plan.show_snippet,
            degradation=_route_degradation(plan.route, all_results, plan.sources, plan.route_defaults),
        )
        if plan.scrape_top > 0:
            markdown += format_scrapes(scrape_result["scrapes"], max_chars=plan.scrape_chars)

    errors = [row for row in as_dicts(final_results) + scrape_result["scrape_errors"] if row.get("error")]
    summaries = _extract_summaries(final_results)
    source_briefs = _extract_source_briefs(final_results)
    response = {
        "query": request.query,
        "route": plan.route,
        "summary": summaries[0]["answer"] if summaries else None,
        "summaries": summaries,
        "source_briefs": source_briefs,
        # Compatibility alias for older callers. New code should use
        # source_briefs: these rows may be built from per-result snippets and
        # are not necessarily provider-native query summaries.
        "source_summaries": _compat_source_summaries(source_briefs),
        "display_results": _display_results(final_results),
        "results": as_dicts(final_results),
        "scrapes": _limit_scrape_rows(scrape_result["scrapes"], plan.scrape_chars),
        "provider_status": _provider_status(final_results),
        "key_status_summary": _summarize_key_status(key_manager.status_rows() if hasattr(key_manager, "status_rows") else []),
        "site_scraper_updates": site_memory.consume_updates() if site_memory else [],
        "errors": errors,
        "diagnostics": {
            "valid_result_count": valid_count,
            "raw_result_count": len(all_results),
            "scrape_candidate_count": len(scrape_result["items_to_scrape"]),
            "jina_keys_active_total": count_jina_keys(keys.get("jina")),
            "state_path": str(store.path) if store else None,
            "route_meta": {
                "scrape_top": plan.scrape_top,
                "show_answer": plan.show_answer or request.verbose,
                "show_snippet": plan.show_snippet,
                "count": plan.route_defaults.get("count"),
                "route_default_count": plan.route_defaults.get("count"),
                "timeout": plan.timeout,
                "route_default_timeout": plan.route_defaults.get("timeout"),
                "want_content": plan.want_content,
            },
            "effective_counts": plan.effective_counts,
            "route_sources": sorted(base_sources),
            "disabled_sources": sorted(plan.disabled_sources),
            "active_sources": sorted(active_sources),
            "route_degradation": _route_degradation(plan.route, all_results, plan.sources, plan.route_defaults),
        },
    }
    if plan.output_mode in {"markdown", "both"}:
        response["markdown"] = markdown
    return response


def run_scrape(request: ScrapeRequest | dict) -> dict:
    if isinstance(request, dict):
        request = ScrapeRequest(**request)
    config = _load_config_safe(None)
    keys = load_keys()
    timeout = _resolve_nonnegative(request.timeout, config, "scrape_timeout", 60)
    scrape_chars = max(1, _resolve_int(request.scrape_chars, config, "scrape_chars", 6000))
    store = StateStore() if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
    site_memory = SiteScraperMemory(store) if store else None
    result = scrape_url_smart(
        request.url,
        timeout=timeout,
        backends=tuple(request.backends) if request.backends else None,
        jina_keys=[candidate.key for candidate in key_manager.candidates("jina", jina_config_keys(keys.get("jina")))],
        exa_keys=[candidate.key for candidate in key_manager.candidates("exa", keys.get("exa"))],
        firecrawl_keys=[candidate.key for candidate in key_manager.candidates("firecrawl", keys.get("firecrawl"))],
        tavily_keys=[candidate.key for candidate in key_manager.candidates("tavily", keys.get("tavily"))],
        site_memory=site_memory,
        key_manager=key_manager,
        scrape_chars=scrape_chars,
    )
    response = {
        "url": request.url,
        "result": _limit_scrape_row(result, scrape_chars),
        "site_scraper_updates": site_memory.consume_updates() if site_memory else [],
    }
    if request.output in {"markdown", "both"}:
        response["markdown"] = format_scrapes([result], max_chars=scrape_chars)
    return response


def _limit_scrape_row(row: dict, max_chars: int) -> dict:
    limited = dict(row)
    markdown = limited.get("markdown")
    if isinstance(markdown, str) and len(markdown) > max_chars:
        limited["markdown"] = markdown[:max_chars]
    return limited


def _limit_scrape_rows(rows: list[dict], max_chars: int) -> list[dict]:
    return [_limit_scrape_row(row, max_chars) for row in rows]


def list_sources(include_key_status: bool = False, include_scraper_stats: bool = False) -> dict:
    store = StateStore()
    response = {"routes": sorted(ROUTE_PROFILES), "sources": sorted(ALL_SOURCE_NAMES)}
    if include_key_status:
        response["key_status"] = SQLiteKeyManager(store).status_rows()
    if include_scraper_stats:
        response["site_scraper_stats"] = SiteScraperMemory(store).stats()
    return response


def doctor_data(include_keys: bool = True, include_network: bool = False) -> dict:
    keys = load_keys()
    store = StateStore()
    data = {
        "server": "multi-search-mcp",
        "state_path": str(store.path),
        "config_path": str(resolve_config_path()),
        "config_loaded": resolve_config_path().exists(),
        "key_sources": {
            "env": [
                "BRAVE_SEARCH_API_KEY",
                "BRAVE_API_KEY",
                "BAIDU_QIANFAN_API_KEY",
                "QIANFAN_API_KEY",
                "APPBUILDER_API_KEY",
                "TAVILY_API_KEY",
                "EXA_API_KEY",
                "JINA_API_KEY",
                "JINA_KEY",
                "GITHUB_TOKEN",
                "GH_TOKEN",
                "FIRECRAWL_API_KEY",
                "SERPAPI_API_KEY",
                "SERPAPI_KEY",
                "ZHIHU_ACCESS_SECRET",
                "YOUTUBE_API_KEY",
                "BILIBILI_COOKIE",
                "TWITTER_COOKIES_PATH",
                "DEEPSEEK_WEB_TOKEN",
                "DEEPSEEK_USER_TOKEN",
                "DEEPSEEK_WEB_COOKIE",
                "DEEPSEEK_WEB_AUTH_EXPORT",
            ],
            "file": "~/.search-keys.json",
            "state": str(store.path),
        },
        "routes": sorted(ROUTE_PROFILES),
        "network_checked": bool(include_network),
    }
    if include_keys:
        data["configured_keys"] = {name: bool(value) for name, value in keys.items()}
        data["key_status"] = SQLiteKeyManager(store).status_rows()
        data["jina_keys_active_total"] = count_jina_keys(keys.get("jina"))
    return data


def _route_degradation(route: str, results: list[dict], source_names: set[str] | None, meta: dict) -> dict | None:
    if source_names is not None:
        return None
    primary_sources = set(meta.get("primary_success_sources") or [])
    if not primary_sources:
        return None
    rows = as_dicts(results)
    # Result rows carry public source names (e.g. ``deepseek-web``,
    # ``github-repos``) while ``primary_success_sources`` uses internal names
    # (``deepseek_web``). Normalize before comparing so a genuine primary
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


def _provider_status(results: list[dict]) -> list[dict]:
    rows = as_dicts(results)
    sources = sorted({row.get("source", "?") for row in rows})
    status = []
    for source in sources:
        source_rows = [row for row in rows if row.get("source") == source]
        errors = [row.get("error") for row in source_rows if row.get("error")]
        hits = len([row for row in source_rows if not row.get("error") and not is_empty_result(row)])
        status.append({"source": source, "raw_hits": hits, "status": "error" if errors and not hits else "ok", "errors": errors})
    return status


def _summarize_key_status(rows: list[dict]) -> list[dict]:
    return [{
        "provider": row.get("provider"),
        "key_id": row.get("key_id"),
        "fingerprint": row.get("key_fingerprint"),
        "status": row.get("status"),
        "last_error_type": row.get("last_error_type"),
        "cooldown_until": row.get("cooldown_until"),
        "exhausted_until": row.get("exhausted_until"),
    } for row in rows]


def _valid_result_count(results: list[dict]) -> int:
    return len([
        row for row in as_dicts(results)
        if "error" not in row and not is_empty_result(row)
        and row.get("source") not in ANSWER_SOURCES
    ])


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


def _add_public_content_aliases(results: list[dict]) -> None:
    """Expose stable public field names without dropping legacy ones."""
    for row in results:
        if not isinstance(row, dict) or row.get("error"):
            continue
        description = row.get("description")
        body = row.get("scraped_content")
        if description and not row.get("content"):
            row["content"] = description
        if body:
            row.setdefault("body", body)
            row.setdefault("full_content", body)


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


def _load_config_safe(path: str | None) -> dict:
    try:
        return load_config(path)
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc


