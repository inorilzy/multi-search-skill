"""SearchRunner: route fanout, provider auth, timeouts, and key fallback."""
from __future__ import annotations

import inspect
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

from .capabilities import PROVIDER_CAPABILITIES
from ..support.concurrency import BoundedDaemonExecutor
from ..support.auth import is_key_retryable_error
from ..state.key_state import BasicKeyManager, KeyCandidate
from ..state.keys import key_pool
from ..support.models import ANSWER_SOURCES, as_dicts, empty_result_row, is_empty_result
from ..support.secrets import scrub_secrets
from .candidate import canonicalize_url


ALL_SOURCE_NAMES = {
    name
    for name, capability in PROVIDER_CAPABILITIES.items()
    if capability.search.can_search
}

SOURCE_ALIASES = {
    "baidu-ai-search": "baidu",
    "github": "github_repos",
    "github-repos": "github_repos",
    "qianfan": "baidu",
    "v2ex": "sov2ex",
}

ROUTE_PROFILES = {
    "default": {"brave", "parallel", "tavily", "exa", "serpapi", "firecrawl", "baidu"},
    "fast": {"baidu", "tavily", "firecrawl", "exa"},
    "social": {"twitter"},
    "dev": {"stackoverflow", "github_repos", "hackernews"},
    "all": {
        "brave", "parallel", "tavily", "exa", "serpapi", "baidu",
        "firecrawl", "twitter", "stackoverflow", "github_repos",
        "hackernews", "sov2ex",
    },
}

ROUTE_ALIASES = {
    "web": "default",
}

# Route-level behavior. A route decides *which sources* to fan out to plus
# source-shaped defaults (count/timeout/snippet rendering) and whether providers
# should return body content inline (``want_content``).
DEFAULT_ROUTE_META = {
    "scrape_top": 20,
    "show_snippet": True,
    "count": 10,
    "timeout": 60,
    "title_url_only": False,
    "degrade_to": set(),
    "primary_success_sources": set(),
    "show_answer": False,
    "want_content": False,
}

ROUTE_META = {
    "default": {
        "scrape_top": 20,
        "show_snippet": True,
        "count": 10,
        "timeout": 60,
        "primary_success_sources": ROUTE_PROFILES["default"],
    },
    # ``fast`` keeps the low-latency provider mix, but the public search
    # contract is still candidate-only. Body retrieval is reserved for
    # explicit fetch/read paths.
    "fast": {
        "scrape_top": 0,
        "show_snippet": True,
        "show_answer": True,
        "want_content": False,
        "count": 10,
        "timeout": 45,
        "primary_success_sources": ROUTE_PROFILES["fast"],
    },
    "all": {
        "scrape_top": 30,
        "show_snippet": True,
        "count": 10,
        "timeout": 90,
        "primary_success_sources": ROUTE_PROFILES["all"],
    },
    "social": {
        "scrape_top": 0,
        "show_snippet": True,
        "count": 10,
        "timeout": 60,
        "degrade_to": set(),
        "primary_success_sources": {"twitter"},
    },
    "dev": {
        "scrape_top": 20,
        "show_snippet": True,
        "count": 10,
        "timeout": 60,
        "primary_success_sources": ROUTE_PROFILES["dev"],
    },
}

def available_routes() -> list[str]:
    return sorted(ROUTE_PROFILES)


def normalize_route(route: str) -> str:
    return ROUTE_ALIASES.get(route, route)


def resolve_route(search_type: str) -> set[str]:
    search_type = normalize_route(search_type)
    return ROUTE_PROFILES.get(search_type, set())


def route_meta(route: str) -> dict[str, Any]:
    route = normalize_route(route)
    meta = dict(DEFAULT_ROUTE_META)
    meta.update(ROUTE_META.get(route, {}))
    return meta


def normalize_source_name(source: str) -> str:
    return SOURCE_ALIASES.get(source, source)


@dataclass
class SearchContext:
    source: str
    timeout: float
    deadline: float
    keys: dict
    options: dict[str, Any] = field(default_factory=dict)
    publish_partial: Callable[[list], None] | None = None


@dataclass
class SearchRunnerConfig:
    route: str
    counts: dict[str, int]
    timeout: int
    serpapi_engine: str
    keys: dict
    want_content: bool = False


@dataclass
class ProviderSpec:
    name: str
    public_name: str
    call: Callable[[str, SearchRunnerConfig, SearchContext, Any], list]
    key_name: str | None = None
    missing_message: str = "missing API key"
    timeout_default: float = 20
    key_required: bool = True


def missing(source: str, message: str) -> list[dict]:
    return [{"source": source, "error": f"skipped: {message}"}]


def _attach_provider_ranks(rows: list[dict]) -> list[dict]:
    """Preserve a provider's own result order before fanout rows are merged."""
    rank = 0
    output = as_dicts(rows)
    for row in output:
        if (
            row.get("error")
            or is_empty_result(row)
            or row.get("source") in ANSWER_SOURCES
            or not row.get("url")
        ):
            continue
        rank += 1
        row.setdefault("provider_rank", rank)
    return output


def call_optional_timeout(fn, *positional, timeout: float, **keyword_options):
    try:
        params = inspect.signature(fn).parameters
        accepts_timeout = "timeout" in params
    except (TypeError, ValueError):
        accepts_timeout = False
        params = {}
    accepted_options = {
        key: value for key, value in keyword_options.items()
        if key in params
    }
    if accepts_timeout:
        accepted_options["timeout"] = timeout
    return fn(*positional, **accepted_options)


def _merge_partial_rows(
    source: str, partial_rows: list[dict], current_rows: list[dict]
) -> list[dict]:
    """Merge partial provider rows without repeating a candidate identity."""
    merged: list[dict] = []
    positions: dict[tuple[str, str], int] = {}

    def provider_rank(row: dict) -> int | None:
        try:
            rank = row.get("provider_rank")
            return int(rank) if rank is not None else None
        except (TypeError, ValueError):
            return None

    for row in (*partial_rows, *current_rows):
        row = dict(row)
        if (
            row.get("error")
            or is_empty_result(row)
            or row.get("source") in ANSWER_SOURCES
            or not row.get("url")
        ):
            merged.append(row)
            continue
        identity = (
            str(row.get("source") or source),
            canonicalize_url(str(row.get("url") or "")),
        )
        if not identity[1]:
            merged.append(row)
            continue
        existing_index = positions.get(identity)
        if existing_index is None:
            positions[identity] = len(merged)
            merged.append(row)
            continue
        existing = merged[existing_index]
        current_rank = provider_rank(row)
        existing_rank = provider_rank(existing)
        if current_rank is not None and (
            existing_rank is None or current_rank < existing_rank
        ):
            merged[existing_index] = row
    return merged


def run_keyed_source(
    source: str, key_value, call_with_key, deadline: float | None = None,
    key_manager=None, *, provider: str | None = None, key_required: bool = True,
) -> list[dict]:
    manager = key_manager or BasicKeyManager()
    # Credential health uses the config provider identity (e.g. github), while
    # result rows retain the public source name (e.g. github-repos).
    provider = provider or source
    candidates = manager.candidates(provider, key_value)
    if not candidates:
        if key_value and not key_required:
            return [{"source": source, "error": "no usable API keys"}]
        return missing(source, "missing API key")
    last_results: list[dict] = []
    partial_rows: list[dict] = []
    for idx, candidate in enumerate(candidates):
        if deadline is not None and time.monotonic() >= deadline:
            break
        key = candidate.key if isinstance(candidate, KeyCandidate) else str(candidate)
        if hasattr(manager, "record_use") and isinstance(candidate, KeyCandidate):
            manager.record_use(provider, candidate)
        results = _attach_provider_ranks(as_dicts(call_with_key(key) or []))
        outcome = manager.classify_result(provider, results)
        manager.record_result(provider, candidate, outcome)
        if not outcome.retryable:
            return (
                _merge_partial_rows(source, partial_rows, results)
                if partial_rows else results
            )
        partial_rows.extend(row for row in results if "error" not in row)
        last_results = results
        if idx == len(candidates) - 1:
            break
    error_rows = [row for row in last_results if "error" in row]
    err = error_rows[0].get("error", "key pool exhausted") if error_rows else "key pool exhausted"
    err = scrub_secrets(err, key_value)
    error = {"source": source, "error": f"key pool exhausted after {len(candidates)} key(s): {err}"}
    return _merge_partial_rows(source, partial_rows, [error]) if partial_rows else [error]


_SEARCH_POOL = BoundedDaemonExecutor(
    max_workers=max(1, len(ALL_SOURCE_NAMES)),
    thread_name_prefix="multi-search-search",
)


class SearchRunner:
    """Run configured searchers in parallel under a shared deadline."""

    def __init__(self, config: SearchRunnerConfig, providers: dict[str, ProviderSpec], route_resolver=None, key_manager=None):
        self.config = config
        self.providers = providers
        self.route_resolver = route_resolver or resolve_route
        self.key_manager = key_manager or BasicKeyManager()

    def run(self, query: str, *, deadline: float | None = None) -> list[dict]:
        results: list[dict] = []
        jobs: list[tuple[str, Callable[[], list]]] = []
        source_names = self.route_resolver(self.config.route)
        timeout_seconds = max(0, self.config.timeout if self.config.timeout is not None else 60)
        source_deadline = time.monotonic() + timeout_seconds
        if deadline is not None:
            source_deadline = min(source_deadline, deadline)
        partial_results: dict[str, list[dict]] = {}
        partial_lock = Lock()

        def call_provider(spec: ProviderSpec, api_key) -> list:
            remaining = source_deadline - time.monotonic()
            if remaining <= 0:
                return [{"source": spec.public_name, "error": f"timeout after {timeout_seconds}s"}]
            with partial_lock:
                previous_attempt_rows = partial_results.get(spec.public_name, [])

            def publish_partial(rows: list) -> None:
                snapshot = _attach_provider_ranks(rows)
                with partial_lock:
                    if time.monotonic() < source_deadline:
                        # Each call publishes a complete snapshot. Merge only
                        # earlier key attempts, not this call's outdated rows/errors.
                        partial_results[spec.public_name] = _merge_partial_rows(
                            spec.public_name, previous_attempt_rows, snapshot,
                        )

            ctx = SearchContext(
                source=spec.public_name,
                timeout=min(float(spec.timeout_default), remaining),
                deadline=source_deadline,
                keys=self.config.keys,
                publish_partial=publish_partial,
            )
            return spec.call(query, self.config, ctx, api_key)

        for source in source_names:
            spec = self.providers.get(source)
            if spec is None:
                continue
            key_value = self.config.keys.get(spec.key_name) if spec.key_name else None
            if spec.key_name and key_value:
                jobs.append((
                    spec.public_name,
                    lambda spec=spec, key_value=key_value: self._run_keyed_source(
                        spec.public_name,
                        key_value,
                        lambda api_key: call_provider(spec, api_key),
                        deadline=source_deadline,
                        provider=spec.key_name,
                        key_required=spec.key_required,
                    ),
                ))
            elif spec.key_name and spec.key_required:
                results.extend(missing(spec.public_name, spec.missing_message))
            else:
                jobs.append((
                    spec.public_name,
                    lambda spec=spec: call_provider(spec, None),
                ))

        if not jobs:
            return results
        if time.monotonic() >= source_deadline:
            for name, _ in jobs:
                results.append({"source": name, "error": f"timeout after {timeout_seconds}s"})
            return results

        pending = {name for name, _ in jobs}
        future_sources: dict[Future, str] = {}
        for name, call in jobs:
            future = _SEARCH_POOL.submit_before(source_deadline, call)
            if future is not None:
                future_sources[future] = name

        while future_sources:
            done = {future for future in future_sources if future.done()}
            if not done:
                remaining = source_deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, _ = wait(
                    tuple(future_sources),
                    timeout=remaining,
                    return_when=FIRST_COMPLETED,
                )
            if not done:
                break
            for future in done:
                source = future_sources.pop(future)
                if source not in pending:
                    continue
                pending.remove(source)
                try:
                    source_results = future.result()
                except Exception as exc:
                    with partial_lock:
                        results.extend(partial_results.get(source, []))
                    results.append({"source": source, "error": scrub_secrets(exc, self.config.keys)})
                else:
                    if source_results:
                        results.extend(_attach_provider_ranks(source_results))
                    else:
                        results.append(empty_result_row(source))

        for source in sorted(pending):
            with partial_lock:
                results.extend(partial_results.get(source, []))
            results.append({"source": source, "error": f"timeout after {timeout_seconds}s"})
        return results

    def _run_keyed_source(
        self, source: str, key_value, call_with_key, deadline: float | None = None,
        *, provider: str | None = None, key_required: bool = True,
    ) -> list[dict]:
        return run_keyed_source(
            source, key_value, call_with_key, deadline=deadline,
            key_manager=self.key_manager, provider=provider, key_required=key_required,
        )
