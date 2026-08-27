"""Reusable service layer shared by MCP tools and future CLI paths."""
from __future__ import annotations

import concurrent.futures
import uuid
from dataclasses import dataclass, field
from typing import Any

from .support.config import ConfigError, config_list, load_config, resolve_config_path
from .support.dedup import deduplicate, rank_results
from .support.format import format_results, format_scrapes
from .state.key_state import BasicKeyManager, SQLiteKeyManager
from .state.keys import KEY_ENV_NAMES, KeysError, count_jina_keys, jina_config_keys, load_keys
from .support.models import ANSWER_SOURCES, as_dicts, is_empty_result
from .scrape.scrape import scrape_url_smart
from .scrape.stage import (
    _backfill_scrape_title,
    run_scrape_stage as _run_scrape_stage,
)
from .search.search_runner import (
    ALL_SOURCE_NAMES,
    SearchRunner,
    SearchRunnerConfig,
    available_routes,
    normalize_source_name,
)
from .search.candidate import canonicalize_url, fuse_search_results, make_source_id
from .search.capabilities import retention_policy_for_sources
from .search.resolve import (
    COUNT_CAPS,
    DEFAULT_COUNTS,
    _resolve_int,
    _resolve_nonnegative,
    resolve_active_sources,
    resolve_search_plan,
)
from .support.secrets import scrub_secrets
from .support.url_security import validate_public_http_url
from .state.content_store import ContentStore, ContentStoreError
from .state.site_memory import SiteScraperMemory
from .state.source_registry import SourceRegistry
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


@dataclass
class SearchWebRequest:
    query: str
    route: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    timeout: int | None = None
    config_path: str | None = None
    expand: list[str] = field(default_factory=list)
    use_state: bool = True


@dataclass
class FetchSourceRequest:
    source_id: str | None = None
    url: str | None = None
    backends: list[str] | None = None
    max_chars: int = 20_000
    timeout: int | None = None
    config_path: str | None = None
    use_state: bool = True


@dataclass
class ReadSourceRequest:
    source_id: str
    keyword: str | None = None
    offset: int = 0
    limit: int = 4_000
    use_state: bool = True


def run_read_source(
    request: ReadSourceRequest | dict,
    *,
    state_store: StateStore | None = None,
) -> dict:
    """Read a bounded slice from ContentStore without accessing the network."""
    if isinstance(request, dict):
        request = ReadSourceRequest(**request)
    if not request.source_id:
        raise ValueError("source_id is required")
    if not request.use_state:
        raise ValueError("read_source requires state")
    store = state_store or StateStore()
    cached = ContentStore(store).get(request.source_id)
    if cached is None:
        raise ValueError(
            "cached content is missing or expired; call fetch_source first"
        )

    body = str(cached["content"])
    offset = max(0, int(request.offset))
    limit = max(1, min(int(request.limit), 8_000))
    match_offset = None
    if request.keyword:
        match_offset = body.lower().find(str(request.keyword).lower())
        if match_offset < 0:
            raise ValueError("keyword was not found in cached content")
        start = min(len(body), match_offset + offset)
    else:
        start = min(len(body), offset)
    end = min(len(body), start + limit)
    return {
        "source_id": request.source_id,
        "content": body[start:end],
        "start": start,
        "end": end,
        "match_offset": match_offset,
        "has_more": end < len(body),
        "next_offset": (offset + (end - start)) if end < len(body) else None,
        "content_length": len(body),
        "content_hash": cached["content_hash"],
        "expires_at": cached["expires_at"],
        "untrusted_content": True,
    }


def run_fetch_source(
    request: FetchSourceRequest | dict,
    *,
    state_store: StateStore | None = None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
    url_resolver=None,
) -> dict:
    """Fetch one registered source and persist its untrusted body briefly."""
    if isinstance(request, dict):
        request = FetchSourceRequest(**request)
    if bool(request.source_id) == bool(request.url):
        raise ValueError("provide exactly one of source_id or url")
    if not request.use_state and request.source_id:
        raise ValueError("source_id fetch requires state; provide an explicit URL")

    store = (state_store or StateStore()) if request.use_state else None
    source = SourceRegistry(store).get(request.source_id) if store and request.source_id else None
    if request.source_id and source is None:
        raise ValueError(
            "source_id is unknown or expired; call search_web again before fetch_source"
        )
    url = str(request.url or source["url"])
    validate_public_http_url(url, resolver=url_resolver)
    source_providers = list((source or {}).get("providers") or ["direct"])
    retention = retention_policy_for_sources(source_providers)
    source_id = str(request.source_id or "")
    if not source_id:
        response_id = f"resp_{uuid.uuid4().hex}"
        canonical_url = canonicalize_url(url)
        source_id = make_source_id(response_id, canonical_url)
        if store is not None:
            SourceRegistry(
                store, ttl_seconds=retention.max_ttl_seconds
            ).register(response_id, [{
                "source_id": source_id,
                "title": url,
                "url": url,
                "canonical_url": canonical_url,
                "content": "",
                "content_kind": "metadata",
                "providers": ["direct"],
                "body_available": False,
            }])
        source = {"providers": ["direct"]}
    max_chars = max(1, min(int(request.max_chars), 20_000))

    content_store = ContentStore(store) if store is not None else None
    cached = content_store.get(source_id) if content_store and source_id else None
    if cached is not None and not retention.persist_body:
        content_store.delete_source(source_id)
        cached = None
    if cached is not None:
        return {
            "source_id": source_id,
            "url": url,
            "body": str(cached["content"])[:max_chars],
            "content_hash": cached["content_hash"],
            "expires_at": cached["expires_at"],
            "backend": "content-store",
            "cache_hit": True,
            "persisted": True,
            "truncated": len(str(cached["content"])) > max_chars,
            "untrusted_content": True,
        }

    resolved_config = (
        _load_config_safe(request.config_path) if config is None else dict(config)
    )
    scrape_response = run_scrape(
        ScrapeRequest(
            url=url,
            backends=request.backends,
            scrape_chars=max_chars,
            timeout=request.timeout,
            output="json",
            use_state=request.use_state,
        ),
        state_store=store,
        scraper=scraper,
        keys=keys,
        config=resolved_config,
        url_resolver=url_resolver,
    )
    result = scrape_response["result"]
    if result.get("error"):
        raise ValueError(str(result["error"]))
    body = str(result.get("markdown") or "")
    if not body:
        raise ValueError("fetch_source returned empty body")
    stored = (
        ContentStore(
            store, ttl_seconds=retention.max_ttl_seconds
        ).put(source_id, body)
        if content_store and source_id and retention.persist_body
        else None
    )
    return {
        "source_id": source_id or None,
        "url": url,
        "body": body[:max_chars],
        "content_hash": stored.get("content_hash") if stored else None,
        "expires_at": stored.get("expires_at") if stored else None,
        "backend": str(result.get("via") or "unknown"),
        "cache_hit": False,
        "persisted": stored is not None,
        "truncated": len(body) > max_chars,
        "untrusted_content": True,
    }


def run_search_web(
    request: SearchWebRequest | dict,
    *,
    providers: dict | None = None,
    keys: dict | None = None,
    config: dict | None = None,
    state_store: StateStore | None = None,
) -> dict:
    """Run candidate-only search and return compact, RRF-ranked SearchHits."""
    if isinstance(request, dict):
        request = SearchWebRequest(**request)
    if not request.query:
        raise ValueError("query is required")
    resolved_config = (
        _load_config_safe(request.config_path) if config is None else dict(config)
    )
    queries = [request.query] + list(
        request.expand
        or config_list(resolved_config, "expand")
        or config_list(resolved_config, "expand_queries")
    )

    planning_request = MultiSearchRequest(
        query=request.query,
        route=request.route,
        count=request.count,
        sources=request.sources,
        scrape_top=0,
        timeout=request.timeout,
        output="json",
        config_path=request.config_path,
        use_state=request.use_state,
    )
    plan = resolve_search_plan(planning_request, resolved_config)
    runtime_keys = load_keys() if keys is None else dict(keys)
    store = (state_store or StateStore()) if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()

    if providers is None:
        from .search.registry import build_provider_registry

        providers = build_provider_registry()
    base_sources, active_sources = resolve_active_sources(
        plan.route, plan.sources, plan.disabled_sources
    )
    if base_sources and not active_sources:
        raise ValueError(
            f"all selected sources are disabled: {', '.join(sorted(base_sources))}"
        )

    def route_resolver(_route):
        _selected, active = resolve_active_sources(
            _route, plan.sources, plan.disabled_sources
        )
        return active

    runner = SearchRunner(
        SearchRunnerConfig(
            plan.route,
            plan.effective_counts,
            plan.timeout,
            plan.serpapi_engine,
            runtime_keys,
            False,
        ),
        providers,
        route_resolver=route_resolver,
        key_manager=key_manager,
    )
    query_results: dict[str, list[dict]] = {}
    if len(queries) == 1:
        query_results[queries[0]] = runner.run(queries[0])
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(queries), MAX_EXPAND_CONCURRENCY)
        ) as pool:
            futures = {pool.submit(runner.run, query): query for query in queries}
            for future in concurrent.futures.as_completed(futures):
                query = futures[future]
                try:
                    query_results[query] = future.result()
                except Exception as exc:  # provider boundary diagnostic
                    query_results[query] = [{
                        "source": "multi-search",
                        "error": scrub_secrets(exc, runtime_keys),
                    }]
    query_runs = [(query, query_results[query]) for query in queries]
    rows = [row for _query, query_rows in query_runs for row in query_rows]
    failures = sorted(
        (
            {
                "source": str(row.get("source") or "?"),
                "query": query,
                "error": str(row.get("error") or ""),
            }
            for query, query_rows in query_runs
            for row in query_rows
            if row.get("error")
        ),
        key=lambda row: (row["query"], row["source"], row["error"]),
    )
    response_id = f"resp_{uuid.uuid4().hex}"
    limit = request.count if request.count is not None else int(plan.route_defaults["count"])
    hits = fuse_search_results(
        query_runs, response_id=response_id, limit=limit
    )
    if store is not None:
        for hit in hits:
            retention = retention_policy_for_sources(list(hit.get("providers") or []))
            if not retention.persist_search_result:
                continue
            registry_hit = dict(hit)
            if not retention.persist_content:
                registry_hit["content"] = ""
            SourceRegistry(
                store, ttl_seconds=retention.max_ttl_seconds
            ).register(response_id, [registry_hit])
    content_store_errors = []
    if store is not None:
        bodies: dict[str, list[tuple[str, str]]] = {}
        for _query, query_rows in query_runs:
            for row in query_rows:
                body = str(row.get("scraped_content") or "")
                if row.get("content_kind") != "body" or not body or not row.get("url"):
                    continue
                bodies.setdefault(canonicalize_url(str(row["url"])), []).append(
                    (str(row.get("source") or ""), body)
                )
        for hit in hits:
            retention = retention_policy_for_sources(list(hit.get("providers") or []))
            if not retention.persist_body:
                continue
            candidates = bodies.get(str(hit["canonical_url"])) or []
            if not candidates:
                continue
            _provider, body = sorted(
                candidates, key=lambda item: (-len(item[1]), item[0], item[1])
            )[0]
            try:
                ContentStore(
                    store, ttl_seconds=retention.max_ttl_seconds
                ).put(str(hit["source_id"]), body)
            except ContentStoreError as exc:
                content_store_errors.append({
                    "source_id": hit["source_id"],
                    "error": str(exc),
                })
    return {
        "query": request.query,
        "route": plan.route,
        "response_id": response_id,
        "results": hits,
        "provider_status": _query_provider_status(query_runs),
        "errors": failures,
        "diagnostics": {
            "raw_result_count": len(rows),
            "candidate_count": len(hits),
            "queries": queries,
            "provider_failures": failures,
            "content_store_errors": content_store_errors,
            "route_sources": sorted(base_sources),
            "disabled_sources": sorted(plan.disabled_sources),
            "active_sources": sorted(active_sources),
            "state_path": str(store.path) if store else None,
        },
    }


def _query_provider_status(
    query_runs: list[tuple[str, list[dict]]],
) -> list[dict]:
    sources = sorted({
        str(row.get("source") or "?")
        for _query, rows in query_runs
        for row in rows
    })
    output = []
    for source in sources:
        hits = 0
        errors = []
        for query, rows in query_runs:
            for row in rows:
                if str(row.get("source") or "?") != source:
                    continue
                if row.get("error"):
                    errors.append({"query": query, "error": str(row["error"])})
                elif not is_empty_result(row) and row.get("url"):
                    hits += 1
        status = "partial" if hits and errors else "error" if errors else "ok"
        output.append({
            "source": source,
            "status": status,
            "raw_hits": hits,
            "errors": errors,
        })
    return output


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

    def route_resolver(_route):
        _selected, active = resolve_active_sources(
            _route, plan.sources, plan.disabled_sources,
        )
        return active

    runner = SearchRunner(runner_config, build_provider_registry(), route_resolver=route_resolver, key_manager=key_manager)

    queries_to_run = [request.query] + list(request.expand or config_list(config, "expand") or config_list(config, "expand_queries"))
    all_results: list[dict] = []
    if len(queries_to_run) == 1:
        all_results = runner.run(request.query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(queries_to_run), MAX_EXPAND_CONCURRENCY)) as pool:
            futures = {pool.submit(runner.run, q): q for q in queries_to_run}
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


def run_scrape(
    request: ScrapeRequest | dict,
    *,
    state_store: StateStore | None = None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
    url_resolver=None,
) -> dict:
    if isinstance(request, dict):
        request = ScrapeRequest(**request)
    resolved_config = _load_config_safe(None) if config is None else dict(config)
    runtime_keys = load_keys() if keys is None else dict(keys)
    timeout = _resolve_nonnegative(request.timeout, resolved_config, "scrape_timeout", 60)
    scrape_chars = max(1, _resolve_int(request.scrape_chars, resolved_config, "scrape_chars", 6000))
    store = (state_store or StateStore()) if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
    site_memory = SiteScraperMemory(store) if store else None
    scraper_fn = scraper or scrape_url_smart
    result = scraper_fn(
        request.url,
        timeout=timeout,
        backends=tuple(request.backends) if request.backends else None,
        jina_keys=[candidate.key for candidate in key_manager.candidates("jina", jina_config_keys(runtime_keys.get("jina")))],
        exa_keys=[candidate.key for candidate in key_manager.candidates("exa", runtime_keys.get("exa"))],
        firecrawl_keys=[candidate.key for candidate in key_manager.candidates("firecrawl", runtime_keys.get("firecrawl"))],
        tavily_keys=[candidate.key for candidate in key_manager.candidates("tavily", runtime_keys.get("tavily"))],
        site_memory=site_memory,
        key_manager=key_manager,
        scrape_chars=scrape_chars,
        url_resolver=url_resolver,
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
    response = {"routes": available_routes(), "sources": sorted(ALL_SOURCE_NAMES)}
    store = None
    if include_key_status or include_scraper_stats:
        store = StateStore()
    if include_key_status:
        response["key_status"] = SQLiteKeyManager(store).status_rows()
    if include_scraper_stats:
        response["site_scraper_stats"] = SiteScraperMemory(store).stats()
    return response


def doctor_data(include_keys: bool = True, include_network: bool = False) -> dict:
    keys: dict = {}
    keys_error: str | None = None
    try:
        keys = load_keys()
    except KeysError as exc:
        # doctor exists to diagnose key problems, so a corrupt keys file must be
        # reported, not raised — otherwise the one tool that could explain the
        # failure becomes unusable.
        keys_error = str(exc)
    store = StateStore()
    data = {
        "server": "multi-search-mcp",
        "state_path": str(store.path),
        "config_path": str(resolve_config_path()),
        "config_loaded": resolve_config_path().exists(),
        "key_sources": {
            "env": KEY_ENV_NAMES,
            "file": "~/.search-keys.json",
            "state": str(store.path),
        },
        "routes": available_routes(),
        "network_checked": bool(include_network),
    }
    if keys_error:
        data["keys_error"] = keys_error
    if include_keys:
        data["configured_keys"] = {name: bool(value) for name, value in keys.items()}
        data["key_status"] = SQLiteKeyManager(store).status_rows()
        data["jina_keys_active_total"] = count_jina_keys(keys.get("jina"))
    data["cloak"] = _cloak_health(keys)
    return data


def _cloak_health(keys: dict) -> dict:
    """Report CloakBrowser availability without importing/launching it.

    Uses importlib spec lookup so a missing optional dependency is reported as a
    boolean rather than raising. Also surfaces whether a Reddit cookie export is
    configured, since that is the common reason the browser source returns an
    error row.
    """
    import importlib.util

    def _installed(module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    reddit_cfg = keys.get("reddit_browser")
    if isinstance(reddit_cfg, dict):
        reddit_cookie = bool(reddit_cfg.get("cookie_export"))
    elif isinstance(reddit_cfg, str):
        reddit_cookie = bool(reddit_cfg)
    else:
        reddit_cookie = False
    return {
        "cloakbrowser_installed": _installed("cloakbrowser"),
        "playwright_installed": _installed("playwright"),
        "reddit_cookie_configured": reddit_cookie,
    }


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


