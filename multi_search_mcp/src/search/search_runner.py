"""SearchRunner: route fanout, provider auth, timeouts, and key fallback."""
from __future__ import annotations

import inspect
import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

from .capabilities import PROVIDER_CAPABILITIES
from ..state.key_state import _now
from ..support.concurrency import (
    POOL_SATURATED_ERROR_TYPE,
    BoundedDaemonExecutor,
    pool_saturated_message,
)
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

# Ordered display/contract form of the built-in routes. Route membership is
# defined once here; ``search.catalog`` exports this order to the CLI/desktop so
# output and documentation stay deterministic.
ROUTE_SOURCE_ORDER = {
    "default": ("brave", "parallel", "tavily", "exa", "serpapi", "firecrawl", "baidu"),
    "fast": ("baidu", "tavily", "firecrawl", "exa"),
    "social": ("twitter",),
    "dev": ("stackoverflow", "github_repos", "hackernews"),
    "all": (
        "brave", "parallel", "tavily", "exa", "serpapi", "baidu",
        "firecrawl", "twitter", "stackoverflow", "github_repos",
        "hackernews", "sov2ex",
    ),
}
ROUTE_PROFILES = {route: set(sources) for route, sources in ROUTE_SOURCE_ORDER.items()}

ROUTE_ALIASES = {
    "web": "default",
}

BUILTIN_ROUTE_LABELS = {
    "default": "默认（网页综合）",
    "fast": "快速",
    "all": "全部",
    "social": "社交（Twitter）",
    "dev": "开发者（Stack Overflow / GitHub / Hacker News）",
}


def default_routes_config() -> dict[str, dict[str, Any]]:
    """Return the built-in route groups in the desktop JSON shape.

    A missing ``routes`` config key means these defaults. Each call returns
    fresh lists and dicts so validators and UI code may mutate the result.
    """
    return {
        route_id: {
            "label": BUILTIN_ROUTE_LABELS[route_id],
            "sources": list(ROUTE_SOURCE_ORDER[route_id]),
            "timeout": None,
        }
        for route_id in ("default", "fast", "all", "social", "dev")
    }

# Route-level behavior that still runs: fan-out membership plus display defaults.
# Body fetching is always the shared post-RRF stage, so routes carry no scrape
# count or inline-content switches.
DEFAULT_ROUTE_META = {
    "show_snippet": True,
    "count": 10,
    "timeout": 60,
    "degrade_to": set(),
    "primary_success_sources": set(),
    "show_answer": False,
}

ROUTE_META = {
    "default": {
        "show_snippet": True,
        "count": 10,
        "timeout": 60,
        "primary_success_sources": ROUTE_PROFILES["default"],
    },
    # ``fast`` keeps the low-latency provider mix. Like every route it still
    # fetches previews for the final RRF results (at most 15); ``scrape_top=0``
    # does not disable the shared body stage any more.
    "fast": {
        "show_snippet": True,
        "show_answer": True,
        "count": 10,
        "timeout": 45,
        "primary_success_sources": ROUTE_PROFILES["fast"],
    },
    "all": {
        "show_snippet": True,
        "count": 10,
        "timeout": 90,
        "primary_success_sources": ROUTE_PROFILES["all"],
    },
    "social": {
        "show_snippet": True,
        "count": 10,
        "timeout": 60,
        "degrade_to": set(),
        "primary_success_sources": {"twitter"},
    },
    "dev": {
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
    # provider -> error for a credential entry that could not be read. Only that
    # provider fails; every other source (keyed or keyless) keeps running.
    key_errors: dict[str, str] = field(default_factory=dict)


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
    """A provider was skipped because no key is configured.

    ``missing_key`` is an explicit classification, not a provider response: the
    desktop offers "save a key" for it and key-health tracking must never cool
    a key that was never used.
    """
    return [
        {
            "source": source,
            "error": f"skipped: {message}",
            "error_type": "missing_key",
        }
    ]


def credential_unavailable(source: str, message: str) -> list[dict]:
    """Only this provider's stored credential entry could not be read.

    The key is not used and the plaintext file is not substituted (fail closed),
    but the failure stays local to the provider that depends on that entry.
    """
    return [
        {
            "source": source,
            "error": message,
            "error_type": "credential_store",
        }
    ]


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
    remaining_candidates = list(candidates)
    while remaining_candidates:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if hasattr(manager, "reserve") and all(
            isinstance(candidate, KeyCandidate) for candidate in remaining_candidates
        ):
            # State-aware managers re-check health under a write lock and pick
            # the least-recently-used eligible key, so concurrent workers spread
            # attempts instead of all retrying the head of the list.
            candidate = manager.reserve(provider, remaining_candidates)
            if candidate is None:
                break
            remaining_candidates.remove(candidate)
        else:
            candidate = remaining_candidates.pop(0)
            if hasattr(manager, "record_use") and isinstance(candidate, KeyCandidate):
                manager.record_use(provider, candidate)
        key = candidate.key if isinstance(candidate, KeyCandidate) else str(candidate)
        # Generation marker for causal gating: a failure recorded after this
        # call started is newer evidence than a success returned by it.
        started_at = _now()
        results = _attach_provider_ranks(as_dicts(call_with_key(key) or []))
        outcome = manager.classify_result(provider, results)
        if outcome.error_type != "target":
            # ``started_at`` gates late successes against newer failures on
            # managers that implement causal recording; managers without it
            # keep the plain signature.
            try:
                manager.record_result(provider, candidate, outcome, started_at=started_at)
            except TypeError:
                manager.record_result(provider, candidate, outcome)
        if not outcome.retryable:
            return (
                _merge_partial_rows(source, partial_rows, results)
                if partial_rows else results
            )
        partial_rows.extend(row for row in results if "error" not in row)
        last_results = results
    error_rows = [row for row in last_results if "error" in row]
    # Prefer a provider-origin row: target failures are not evidence about the key.
    chosen = next(
        (row for row in error_rows if row.get("error_origin") != "target"),
        error_rows[0] if error_rows else {},
    )
    err = chosen.get("error", "key pool exhausted") if chosen else "key pool exhausted"
    err = scrub_secrets(err, key_value)
    error = {"source": source, "error": f"key pool exhausted after {len(candidates)} key(s): {err}"}
    # Carry only the controlled classification of the chosen row, never its other fields.
    for field_name in ("error_origin", "error_type"):
        value = chosen.get(field_name) if chosen else None
        if isinstance(value, str) and value:
            error[field_name] = value
    return _merge_partial_rows(source, partial_rows, [error]) if partial_rows else [error]


def _search_pool_workers() -> int:
    """Worker budget for the shared search pool, tunable per process.

    ``MULTI_SEARCH_SEARCH_CONCURRENCY`` overrides the default of one slot
    per known source; the pool stays bounded either way.
    """
    raw = os.environ.get("MULTI_SEARCH_SEARCH_CONCURRENCY")
    try:
        return max(1, int(raw)) if raw is not None else max(1, len(ALL_SOURCE_NAMES))
    except ValueError:
        return max(1, len(ALL_SOURCE_NAMES))


_SEARCH_POOL = BoundedDaemonExecutor(
    max_workers=_search_pool_workers(),
    thread_name_prefix="multi-search-search",
)


class SearchRunner:
    """Run configured searchers in parallel under a shared deadline."""

    def __init__(self, config: SearchRunnerConfig, providers: dict[str, ProviderSpec], route_resolver=None, key_manager=None, executor=None):
        self.config = config
        self.providers = providers
        self.route_resolver = route_resolver or resolve_route
        self.key_manager = key_manager or BasicKeyManager()
        # Runtime-injected capacity: embedders and tests can supply their own
        # bounded executor instead of the process-wide default. ``None`` keeps
        # the module-level pool (looked up per run so it stays patchable).
        self.executor = executor

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
            key_error = self.config.key_errors.get(spec.key_name) if spec.key_name else None
            if key_error:
                results.extend(credential_unavailable(spec.public_name, key_error))
            elif spec.key_name and key_value:
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
        saturated: set[str] = set()
        for name, call in jobs:
            had_budget = source_deadline - time.monotonic() > 0
            executor = self.executor or _SEARCH_POOL
            future = executor.submit_before(source_deadline, call)
            if future is not None:
                future_sources[future] = name
            elif had_budget:
                # The request still had time but no worker slot freed up: this
                # is local capacity, not a slow provider.
                saturated.add(name)

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

        for future in future_sources:
            # The caller has given up on these; do not let them block later searches.
            if not future.done():
                (self.executor or _SEARCH_POOL).abandon(future)
        for source in sorted(pending):
            with partial_lock:
                results.extend(partial_results.get(source, []))
            if source in saturated:
                results.append({
                    "source": source,
                    "error": pool_saturated_message("search", timeout_seconds),
                    "error_type": POOL_SATURATED_ERROR_TYPE,
                })
            else:
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
