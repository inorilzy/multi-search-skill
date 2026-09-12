"""Fetch the final ranked results under a shared deadline and bounded pool."""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import Any, Callable

from ..support.concurrency import BoundedDaemonExecutor
from ..support.secrets import scrub_secrets


_SCRAPE_POOL = BoundedDaemonExecutor(
    max_workers=30,
    thread_name_prefix="multi-search-scrape",
)


def run_ranked_fetch_stage(
    hits: list[dict], *, fetch: Callable[[dict, float], dict],
    timeout: float, concurrency: int = 5,
) -> dict:
    """Fetch already-ranked hits under one deadline without changing their order.

    The callback receives the time remaining for the whole batch. Running work
    retains its bounded pool slot after timeout; queued work is cancelled and
    checks the deadline again before invoking the callback.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    deadline = time.monotonic() + timeout
    results: list[dict | None] = [None] * len(hits)
    active: dict[Future, int] = {}
    next_index = 0

    def error_row(hit: dict, error: Any) -> dict:
        return {
            "source_id": hit.get("source_id", ""),
            "url": hit.get("url", ""),
            "error": scrub_secrets(error),
        }

    def timeout_row(hit: dict) -> dict:
        return error_row(hit, f"fetch timeout after {timeout}s")

    def fetch_hit(hit: dict) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return timeout_row(hit)
        result = fetch(hit, remaining)
        if time.monotonic() >= deadline:
            return timeout_row(hit)
        if not isinstance(result, dict) or not result:
            return error_row(hit, "empty or invalid fetch result")
        if result.get("error"):
            return {**result, **error_row(hit, result["error"])}
        return result

    def collect(future: Future, index: int) -> None:
        try:
            results[index] = future.result()
        except Exception as exc:
            results[index] = error_row(hits[index], str(exc) or type(exc).__name__)

    while next_index < len(hits) or active:
        while next_index < len(hits) and len(active) < concurrency:
            future = _SCRAPE_POOL.submit_before(deadline, fetch_hit, hits[next_index])
            if future is None:
                break
            active[future] = next_index
            next_index += 1
        # Submitting can itself exhaust the deadline while the global pool is
        # busy. Keep successes that finished during that wait.
        done = {future for future in active if future.done()}
        if not done:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not active:
                break
            done, _ = wait(tuple(active), timeout=remaining, return_when=FIRST_COMPLETED)
        if not done:
            break
        for future in done:
            collect(future, active.pop(future))
        if time.monotonic() >= deadline:
            break

    for future, index in active.items():
        if future.done():
            collect(future, index)
        else:
            future.cancel()
    final_results = [
        result if result is not None else timeout_row(hit)
        for hit, result in zip(hits, results)
    ]
    return {
        "results": final_results,
        "errors": [result for result in final_results if result.get("error")],
    }
