"""Full search-and-fetch flow: candidates first, then ranked body previews."""
from __future__ import annotations

import time

from .scrape.fetch import run_fetch_source
from .scrape.stage import run_ranked_fetch_stage
from .search.candidate import SEARCH_RESULT_LIMIT
from .search.candidates import run_search_candidates, search_outcome
from .state import runtime
from .state.state_store import StateStore
from .support.config import resolve_int, resolve_nonnegative
from .support.format import body_preview_start
from .support.models import normalize_scrape_result
from .support.requests import FetchSourceRequest, SearchWebRequest
from .support.secrets import scrub_secrets


def run_search_web(
    request: SearchWebRequest | dict,
    *,
    providers: dict | None = None,
    keys: dict | None = None,
    config: dict | None = None,
    state_store: StateStore | None = None,
    query_runs_observer: Callable[[list[tuple[str, list[dict]]]], None] | None = None,
    scraper=None,
    reranker=None,
    scrape_chars: int | None = None,
    scrape_timeout: int | None = None,
    scrape_concurrency: int | None = None,
) -> dict:
    """Fuse all returned candidates, then fetch the final 15 in RRF order.

    With ``request.no_fetch`` the flow stops after fusion: no body fetch, no
    body-cache write, and ``diagnostics.body_fetch_mode == "candidates"``.
    """
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
    if keys is None:
        loaded = runtime.load_runtime_key_context(resolved_config)
        runtime_keys, runtime_key_errors = loaded.keys, loaded.errors
    else:
        runtime_keys, runtime_key_errors = dict(keys), {}
    store = (state_store or StateStore()) if request.use_state else None
    prefetched = {}
    response = run_search_candidates(
        request, providers=providers, keys=runtime_keys, key_errors=runtime_key_errors,
        config=resolved_config,
        state_store=store, query_runs_observer=query_runs_observer,
        prefetched_bodies=prefetched, persist_bodies=not request.no_fetch,
        reranker=reranker,
    )
    if request.no_fetch:
        # Candidate-only mode: the response keeps the ranked hits and provider
        # status, but no body is fetched and no body cache entry is written, so
        # only the search budget (not the scrape budget) can make it time out.
        response["scrapes"] = []
        response["site_scraper_updates"] = []
        response["diagnostics"].update(
            result_limit=SEARCH_RESULT_LIMIT,
            body_fetch_count=0,
            body_success_count=0,
            body_failures=[],
            body_fetch_mode="candidates",
        )
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
                config=resolved_config, source_record=hit,
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
    persist_failures = []
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
        if body_result.get("persist_error"):
            # The preview is valid, but the full body was too large to cache.
            page["persisted"] = False
            page["persist_error"] = body_result["persist_error"]["message"]
            hit["body_persisted"] = False
            persist_failures.append({
                "source_id": hit["source_id"], "url": hit["url"],
                **body_result["persist_error"],
            })
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
    response["outcome"] = search_outcome(
        response.get("provider_status") or [], response["errors"], response["results"],
    )
    response["diagnostics"].update(
        result_limit=SEARCH_RESULT_LIMIT,
        body_fetch_count=len(response["results"]),
        body_success_count=sum(not row.get("error") for row in scrapes),
        body_failures=body_errors,
        body_persist_failures=persist_failures,
    )
    return response
