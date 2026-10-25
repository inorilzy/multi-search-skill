"""Candidate search: fuse provider rows into ranked SearchHits.

This is the public candidate-search seam. Callers that only need ranked
candidates use this function instead of the full search-and-fetch flow; tests
and snapshot capture use the same entry point.
"""
from __future__ import annotations

import concurrent.futures
import time
import uuid
from collections.abc import Callable

from ..state import runtime
from ..state.content_store import ContentStore, ContentStoreError
from ..state.key_state import BasicKeyManager, SQLiteKeyManager, classify_error, summarize_status_rows
from ..state.source_registry import SourceRegistry
from ..state.state_store import StateStore
from ..scrape.scrapers.twitter import is_twitter_url
from ..support.concurrency import BoundedDaemonExecutor
from ..support.config import config_list
from ..support.models import ANSWER_SOURCES, is_empty_result, search_content
from ..support.requests import SearchWebRequest
from ..support.secrets import scrub_secrets
from .candidate import SEARCH_RESULT_LIMIT, canonicalize_url, fuse_search_results
from .capabilities import retention_policy_for_sources
from .query_plan import build_query_plan
from .query_policy import QueryFusionPolicy
from .resolve import (
    SearchPlanRequest,
    resolve_active_sources,
    resolve_search_plan,
)
from .search_runner import SearchRunner, SearchRunnerConfig


# Query expansion is a shallow, short fan-out (one task per variant query).
# Capacity is intentionally small and isolated from the provider pool inside
# ``SearchRunner``: a parent expansion task occupies an expansion slot while
# waiting for provider work, so sharing one pool would let nested fan-out
# occupy every slot and deadlock.
MAX_EXPAND_CONCURRENCY = 5
_EXPAND_POOL = BoundedDaemonExecutor(
    max_workers=MAX_EXPAND_CONCURRENCY,
    thread_name_prefix="multi-search-expand",
)


def run_search_candidates(
    request: SearchWebRequest | dict,
    *,
    providers: dict | None = None,
    keys: dict | None = None,
    key_errors: dict[str, str] | None = None,
    config: dict | None = None,
    state_store: StateStore | None = None,
    query_runs_observer: Callable[[list[tuple[str, list[dict]]]], None] | None = None,
    prefetched_bodies: dict[str, str] | None = None,
    persist_bodies: bool = True,
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

    plan = resolve_search_plan(
        SearchPlanRequest(
            route=request.route,
            count=request.count,
            sources=request.sources,
            timeout=request.timeout,
            output="json",
        ),
        resolved_config,
    )
    if keys is None:
        loaded = runtime.load_runtime_key_context(resolved_config)
        runtime_keys, runtime_key_errors = loaded.keys, loaded.errors
    else:
        runtime_keys, runtime_key_errors = dict(keys), dict(key_errors or {})
    store = (state_store or StateStore()) if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()

    if providers is None:
        from .registry import build_provider_registry

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
            key_errors=runtime_key_errors,
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
        # deadline-bounded runner call, which keeps error accounting identical
        # to a plain bounded executor.
        futures = {
            _EXPAND_POOL.submit_before(search_deadline, runner.run, query, deadline=search_deadline): query
            for query in queries
        }
        futures = {future: query for future, query in futures.items() if future is not None}
        pending_queries = set(queries) - set(futures.values())
        for future in concurrent.futures.as_completed(futures):
            query = futures[future]
            try:
                query_results[query] = future.result()
            except Exception as exc:  # provider boundary diagnostic
                query_results[query] = [{
                    "source": "multi-search",
                    "error": scrub_secrets(exc, runtime_keys),
                }]
        for query in pending_queries:
            # No worker slot freed up before the search deadline: this is
            # local capacity, not a slow provider.
            query_results[query] = [{
                "source": "multi-search",
                "error": f"timeout after {plan.timeout}s",
            }]
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
    query_failure_rows = query_failures(query_runs)
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
    if store is not None and persist_bodies:
        for hit in hits:
            retention = retention_policy_for_sources(list(hit.get("providers") or []))
            if not retention.persist_body:
                continue
            body = selected_bodies.get(str(hit["canonical_url"]))
            if not body:
                continue
            try:
                ContentStore(
                    store, ttl_seconds=retention.max_ttl_seconds
                ).put(str(hit["source_id"]), body)
            except ContentStoreError as exc:
                content_store_errors.append({
                    "source_id": hit["source_id"],
                    "error": str(exc),
                })
    provider_status = query_provider_status(query_runs)
    return {
        "query": request.query,
        "route": plan.route,
        "response_id": response_id,
        "results": hits,
        "outcome": search_outcome(provider_status, failures, hits),
        "provider_status": provider_status,
        "key_status_summary": summarize_key_status(key_manager.status_rows()),
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
            "query_failures": query_failure_rows,
            "content_store_errors": content_store_errors,
            "route_sources": sorted(base_sources),
            "disabled_sources": sorted(plan.disabled_sources),
            "active_sources": sorted(active_sources),
            "state_path": str(store.path) if store else None,
        },
    }



def search_outcome(provider_status: list[dict], errors: list[dict], results: list[dict]) -> str:
    """Business outcome shared by the CLI, service and desktop adapters."""
    if provider_status and all(row.get("status") == "error" for row in provider_status):
        return "failed"
    if errors:
        return "partial"
    return "success" if results else "empty"


def query_provider_status(
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
                    # error_type lets callers tell auth, quota, and network failures apart.
                    errors.append({
                        "query": query,
                        "error": str(row["error"]),
                        "error_type": classify_error(str(row["error"]), error_type=row.get("error_type", "")),
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



def query_failures(query_runs: list[tuple[str, list[dict]]]) -> list[dict]:
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

def summarize_key_status(rows: list[dict]) -> list[dict]:
    """Public wrapper kept on the candidate seam for response diagnostics."""
    return summarize_status_rows(rows)
