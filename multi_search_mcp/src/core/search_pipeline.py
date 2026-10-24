"""Query planning, fan-out, fusion and result persistence.

The query-expansion fan-out uses a dedicated ``BoundedDaemonExecutor``
*instance* (``_EXPAND_POOL``). It deliberately does not share the provider
pool inside ``SearchRunner`` or the body-fetch pool: a parent expansion task
occupies an expansion slot while waiting for provider work, so sharing one
pool would let nested fan-out occupy every slot and deadlock.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from ..search.candidate import SEARCH_RESULT_LIMIT, canonicalize_url, fuse_search_results
from ..search.capabilities import retention_policy_for_sources
from ..search.query_plan import build_query_plan
from ..search.query_policy import QueryFusionPolicy
from ..search.resolve import (
    resolve_active_sources,
    resolve_search_plan,
)
from ..support.config import config_list, resolve_int, resolve_nonnegative
from ..search.search_runner import SearchRunner, SearchRunnerConfig
from ..scrape.scrapers.twitter import is_twitter_url
from ..scrape.stage import run_ranked_fetch_stage
from ..support.format import body_preview_start
from ..support.models import normalize_scrape_result
from ..state.content_store import ContentStoreError
from ..state.source_registry import SourceRegistry
from ..state.key_state import classify_error
from ..support.models import ANSWER_SOURCES, is_empty_result, search_content
from ..support.secrets import scrub_secrets
from ..support.concurrency import BoundedDaemonExecutor, pool_size_from_env
from . import runtime
from .body_fetch import run_fetch_source
from .requests import FetchSourceRequest, MultiSearchRequest, SearchWebRequest


# Query expansion is a shallow, short fan-out (one task per variant query).
# Capacity is intentionally small and isolated from provider/body pools.
MAX_EXPAND_CONCURRENCY = pool_size_from_env("MULTI_SEARCH_EXPAND_CONCURRENCY", 5)
_EXPAND_POOL = BoundedDaemonExecutor(
    max_workers=MAX_EXPAND_CONCURRENCY,
    thread_name_prefix="multi-search-expand",
)


def run_search_candidates(
    request: SearchWebRequest | dict,
    *,
    providers: dict | None = None,
    keys: dict | None = None,
    config: dict | None = None,
    state_store=None,
    query_runs_observer: Callable[[list[tuple[str, list[dict]]]], None] | None = None,
    prefetched_bodies: dict[str, str] | None = None,
) -> dict:
    """Return compact SearchHits and optionally fill the selected-body map."""
    if isinstance(request, dict):
        request = SearchWebRequest(**request)
    if not request.query:
        raise ValueError("query is required")
    resolved_config = (
        runtime.load_config_safe(request.config_path) if config is None else dict(config)
    )
    expand = (
        request.expand
        if request.expand is not None
        else config_list(resolved_config, "expand")
        or config_list(resolved_config, "expand_queries")
    )
    query_plan = build_query_plan(
        request.query,
        expand,
    )
    queries = list(query_plan.queries)
    query_policy = QueryFusionPolicy.from_config(resolved_config)
    # Validate and allocate against the complete plan, before any query can fail.
    query_weights = query_policy.weights(queries, query_plan.primary_query)

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
    runtime_keys = runtime.load_runtime_keys(resolved_config) if keys is None else dict(keys)
    store = (state_store or runtime.new_state_store()) if request.use_state else None
    key_manager = runtime.key_manager_for(store)

    if providers is None:
        from ..search.registry import build_provider_registry

        providers = build_provider_registry()
    base_sources, active_sources = resolve_active_sources(
        plan.route, plan.sources, plan.disabled_sources, plan.route_sources
    )
    if base_sources and not active_sources:
        raise ValueError(
            f"all selected sources are disabled: {', '.join(sorted(base_sources))}"
        )

    def route_resolver(_route):
        _selected, active = resolve_active_sources(
            _route, plan.sources, plan.disabled_sources, plan.route_sources
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
    search_deadline = time.monotonic() + plan.timeout
    if len(queries) == 1:
        query_results[queries[0]] = runner.run(queries[0], deadline=search_deadline)
    else:
        # The expansion pool bounds *admission*, not each query's runtime: a
        # queued variant that never gets a slot still reports through its own
        # (deadline-bounded) runner call, which is what keeps error accounting
        # identical to a plain bounded executor.
        results_by_item = _EXPAND_POOL.run_all_before(
            search_deadline,
            lambda query: runner.run(query, deadline=search_deadline),
            queries,
            on_admission_failure=lambda query: TimeoutError(
                f"timeout after {plan.timeout}s"
            ),
        )
        for query in queries:
            result = results_by_item.get(id(query))
            if isinstance(result, BaseException):
                query_results[query] = [{
                    "source": "multi-search",
                    "error": scrub_secrets(result, runtime_keys),
                }]
            else:
                query_results[query] = result if result is not None else []
    query_runs = [(query, query_results[query]) for query in queries]
    if query_runs_observer is not None:
        query_runs_observer(query_runs)
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
    query_failures = _query_failures(query_runs)
    response_id = f"resp_{uuid.uuid4().hex}"
    limit = SEARCH_RESULT_LIMIT
    hits = fuse_search_results(
        query_runs, response_id=response_id, limit=limit,
        primary_query=query_plan.primary_query, query_policy=query_policy,
    )
    primary_rows = query_results[query_plan.primary_query]
    primary_has_candidates = bool(fuse_search_results(
        [(query_plan.primary_query, primary_rows)], response_id=response_id, limit=1,
    ))
    primary_has_errors = any(row.get("error") for row in primary_rows)
    primary_status = (
        "partial" if primary_has_candidates and primary_has_errors
        else "ok" if primary_has_candidates
        else "failed" if primary_has_errors else "empty"
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
    # Select once for both persistence and fetching, independently of use_state.
    # Longest body wins; ties use source then body text in ascending order.
    bodies: dict[str, tuple[int, str, str]] = {}
    for _query, query_rows in query_runs:
        for row in query_rows:
            body = search_content(row).body
            if not body or not row.get("url") or row.get("error"):
                continue
            # X details and replies must come from the authenticated scraper,
            # including X links discovered by a generic search provider.
            if is_twitter_url(str(row["url"])):
                continue
            url = canonicalize_url(str(row["url"]))
            candidate = (-len(body), str(row.get("source") or ""), body)
            previous = bodies.get(url)
            if previous is None or candidate < previous:
                bodies[url] = candidate
    selected_bodies = {url: candidate[2] for url, candidate in bodies.items()}
    if prefetched_bodies is not None:
        prefetched_bodies.update(selected_bodies)
    if store is not None:
        for hit in hits:
            retention = retention_policy_for_sources(list(hit.get("providers") or []))
            if not retention.persist_body:
                continue
            body = selected_bodies.get(str(hit["canonical_url"]))
            if not body:
                continue
            try:
                runtime.new_content_store(
                    store, ttl_seconds=retention.max_ttl_seconds,
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
        "outcome": _search_outcome(_query_provider_status(query_runs), failures, hits),
        "provider_status": _query_provider_status(query_runs),
        "key_status_summary": _summarize_key_status(key_manager.status_rows()),
        "errors": failures,
        "diagnostics": {
            "raw_result_count": len(rows),
            "candidate_count": len(hits),
            "queries": queries,
            "query_fusion": {
                **query_policy.to_dict(),
                "applied_stage": "provider" if len(queries) == 1 else "query",
                "weights": query_weights,
                "primary_status": primary_status,
            },
            "primary_query": query_plan.primary_query,
            "duplicate_query_count": query_plan.duplicate_count,
            "discarded_blank_query_count": query_plan.discarded_blank_count,
            "provider_failures": failures,
            "query_failures": query_failures,
            "content_store_errors": content_store_errors,
            "route_sources": sorted(base_sources),
            "disabled_sources": sorted(plan.disabled_sources),
            "active_sources": sorted(active_sources),
            "state_path": str(store.path) if store else None,
        },
    }


def run_search_web(
    request: SearchWebRequest | dict,
    *,
    providers: dict | None = None,
    keys: dict | None = None,
    config: dict | None = None,
    state_store=None,
    query_runs_observer: Callable[[list[tuple[str, list[dict]]]], None] | None = None,
    scraper=None,
    url_resolver=None,
    scrape_chars: int | None = None,
    scrape_timeout: int | None = None,
    scrape_concurrency: int | None = None,
) -> dict:
    """Fuse all returned candidates, then fetch the final 15 in RRF order."""
    if isinstance(request, dict):
        request = SearchWebRequest(**request)
    resolved_config = runtime.load_config_safe(request.config_path) if config is None else dict(config)
    # Candidate planning also validates scrape defaults. Preserve explicit
    # overrides there, before provider calls, as well as in the fetch stage.
    resolved_config.update({
        key: value for key, value in (
            ("scrape_chars", scrape_chars), ("scrape_timeout", scrape_timeout),
            ("scrape_concurrency", scrape_concurrency),
        ) if value is not None
    })
    runtime_keys = runtime.load_runtime_keys(resolved_config) if keys is None else dict(keys)
    store = (state_store or runtime.new_state_store()) if request.use_state else None
    prefetched = {}
    response = run_search_candidates(
        request, providers=providers, keys=runtime_keys, config=resolved_config,
        state_store=store, query_runs_observer=query_runs_observer,
        prefetched_bodies=prefetched,
    )
    if request.no_scrape:
        response["scrapes"] = []
        response["site_scraper_updates"] = []
        response["diagnostics"].update(result_limit=SEARCH_RESULT_LIMIT, body_fetch_count=0,
                                       body_success_count=0, body_failures=[])
        return response
    max_chars = max(1, min(resolve_int(scrape_chars, resolved_config, "scrape_chars", 1200), 20_000))
    body_timeout = resolve_nonnegative(scrape_timeout, resolved_config, "scrape_timeout", 60)
    concurrency = max(1, resolve_int(scrape_concurrency, resolved_config, "scrape_concurrency", 5))
    body_deadline = time.monotonic() + body_timeout

    def fetch(hit, remaining):
        try:
            return run_fetch_source(
                FetchSourceRequest(
                    source_id=hit["source_id"], full_content=True,
                    use_state=request.use_state,
                ),
                state_store=store, scraper=scraper, keys=runtime_keys,
                config=resolved_config, url_resolver=url_resolver, source_record=hit,
                prefetched_body=prefetched.get(hit["canonical_url"]),
                deadline=body_deadline,
                runtime_timeout=remaining,
            )
        except Exception as exc:
            return {"source_id": hit["source_id"], "url": hit["url"],
                    "error": scrub_secrets(exc, runtime_keys)}

    fetched = run_ranked_fetch_stage(
        response["results"], fetch=fetch, timeout=body_timeout, concurrency=concurrency,
        deadline=body_deadline,
    )
    scrapes = []
    for hit, body_result in zip(response["results"], fetched["results"]):
        page = normalize_scrape_result({
            "title": hit["title"], "markdown": body_result.get("body"),
            "length": body_result.get("content_length"),
            "truncated": bool(body_result.get("truncated")),
            "error": body_result.get("error"),
        }, url=hit["url"], via=body_result.get("backend") or "")
        page["source_id"] = hit["source_id"]
        scrapes.append(page)
        if page.get("error"):
            hit["body_error"] = page["error"]
            hit["body_available"] = False
            continue
        body = page["markdown"]
        start = body_preview_start(body, hit["title"], max_chars, hit.get("content") or "")
        end = min(len(body), start + max_chars)
        page.update(
            markdown=body[start:end], preview_start=start, preview_end=end,
            truncated=page["truncated"] or start > 0 or end < len(body),
        )
        hit.update(
            body_available=True,
            body_truncated=page["truncated"],
            body_backend=page["via"],
        )
    response["scrapes"] = scrapes
    response["site_scraper_updates"] = [
        update for result in fetched["results"]
        for update in result.get("site_scraper_updates", [])
    ]
    body_errors = [
        {key: row[key] for key in ("source_id", "url", "error")}
        for row in scrapes if row.get("error")
    ]
    response["errors"].extend({**error, "stage": "fetch"} for error in body_errors)
    response["outcome"] = _search_outcome(
        response.get("provider_status") or [], response["errors"], response["results"],
    )
    response["diagnostics"].update(
        result_limit=SEARCH_RESULT_LIMIT,
        body_fetch_count=len(response["results"]),
        body_success_count=sum(not row.get("error") for row in scrapes),
        body_failures=body_errors,
    )
    return response


def _search_outcome(provider_status: list[dict], errors: list[dict], results: list[dict]) -> str:
    """Business outcome shared by the CLI, service and desktop adapters."""
    if provider_status and all(row.get("status") == "error" for row in provider_status):
        return "failed"
    if errors:
        return "partial"
    return "success" if results else "empty"


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
        succeeded = False
        errors = []
        for query, rows in query_runs:
            for row in rows:
                if str(row.get("source") or "?") != source:
                    continue
                if row.get("error"):
                    # Diagnostic field name stays error_type for output
                    # compatibility; its value is the row's structured ``kind``
                    # (or classify_error's fallback when the row is unclassified).
                    errors.append({
                        "query": query,
                        "error": str(row["error"]),
                        "error_type": classify_error(str(row["error"]), kind=row.get("kind", "")),
                    })
                else:
                    succeeded = True
                    if not is_empty_result(row) and row.get("url"):
                        hits += 1
        status = "partial" if succeeded and errors else "error" if errors else "ok"
        output.append({
            "source": source,
            "status": status,
            "raw_hits": hits,
            "errors": errors,
        })
    return output


def _query_failures(query_runs: list[tuple[str, list[dict]]]) -> list[dict]:
    output = []
    for query, rows in query_runs:
        errors = sorted(
            [
                {
                    "source": str(row.get("source") or "?"),
                    "error": str(row.get("error") or ""),
                }
                for row in rows
                if row.get("error")
            ],
            key=lambda row: (row["source"], row["error"]),
        )
        has_valid_candidate = any(
            not row.get("error")
            and not is_empty_result(row)
            and row.get("url")
            and row.get("source") not in ANSWER_SOURCES
            for row in rows
        )
        if errors and not has_valid_candidate:
            output.append({
                "query": query,
                "errors": errors,
            })
    return output


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
