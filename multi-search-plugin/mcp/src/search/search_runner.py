"""SearchRunner: route fanout, provider auth, timeouts, and key fallback."""
from __future__ import annotations

import inspect
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..support.auth import is_key_retryable_error
from ..state.key_state import BasicKeyManager, KeyCandidate
from ..state.keys import key_pool
from ..support.models import as_dicts
from ..support.secrets import scrub_secrets


ALL_SOURCE_NAMES = {
    "baidu", "bilibili", "brave", "deepseek_web", "exa", "firecrawl",
    "github_repos", "glm_web", "hackernews", "linuxdo", "linuxdo_api",
    "reddit", "reddit_oauth", "serpapi", "stackoverflow", "tavily",
    "twitter", "v2ex", "youtube", "zhihu",
}

SOURCE_ALIASES = {
    "baidu-ai-search": "baidu",
    "deepseek-web": "deepseek_web",
    "glm-web": "glm_web",
    "github": "github_repos",
    "github-repos": "github_repos",
    "linux-do": "linuxdo",
    "linuxdo-api": "linuxdo_api",
    "qianfan": "baidu",
    "reddit-oauth": "reddit_oauth",
}

ROUTE_PROFILES = {
    "default": {"brave", "tavily", "exa", "serpapi", "firecrawl", "baidu", "glm_web", "deepseek_web"},
    "social": {"twitter", "reddit_oauth"},
    "dev": {"stackoverflow", "github_repos", "hackernews"},
    "cn-community": {"zhihu", "v2ex", "linuxdo"},
    "video": {"youtube", "bilibili"},
    # Everything except the video sources (and excluding the bare reddit/
    # linuxdo_api duplicates in favor of the route-canonical reddit_oauth/
    # linuxdo).
    "all": {
        "brave", "tavily", "exa", "serpapi", "baidu", "glm_web", "deepseek_web",
        "firecrawl", "twitter", "reddit_oauth", "stackoverflow", "github_repos",
        "hackernews", "zhihu", "v2ex", "linuxdo",
    },
}

# Route-level behavior. A route only decides *which sources* to fan out to and
# source-shaped defaults (count/timeout/snippet rendering). Search *depth* is an
# orthogonal concern owned by ``level`` (see LEVEL_META), so route meta no longer
# pins ``search_depth``.
DEFAULT_ROUTE_META = {
    "scrape_top": 8,
    "show_snippet": True,
    "count": 8,
    "timeout": 60,
    "title_url_only": False,
    "degrade_to": set(),
    "primary_success_sources": set(),
}

ROUTE_META = {
    "default": {"scrape_top": 8, "show_snippet": True, "count": 8, "timeout": 60},
    "all": {"scrape_top": 8, "show_snippet": True, "count": 8, "timeout": 90},
    "social": {
        "scrape_top": 0,
        "show_snippet": True,
        "count": 8,
        "timeout": 45,
        "degrade_to": set(),
        "primary_success_sources": {"twitter", "reddit-oauth"},
    },
    "dev": {"scrape_top": 5, "show_snippet": True, "count": 8, "timeout": 60},
    "cn-community": {"scrape_top": 5, "show_snippet": True, "count": 8, "timeout": 60},
    "video": {
        "scrape_top": 0,
        "show_snippet": False,
        "count": 10,
        "timeout": 45,
        "title_url_only": True,
    },
}

# Level controls *search depth* and how results are consumed, orthogonally to
# the route's source selection.
#   fast   -> use provider-native summary/answer, no scraping
#   normal -> return URLs, scrape, and let the main model summarize
#   expert -> use provider-native deep search and scrape more
DEFAULT_LEVEL = "normal"

LEVEL_META = {
    "fast": {"search_depth": "fast", "show_answer": True, "scrape_top": 0},
    "normal": {"search_depth": "normal", "show_answer": False},
    "expert": {
        "search_depth": "deep",
        "show_answer": False,
        "scrape_top": 20,
        # Sources that already returned a summary are accepted as-is; only
        # URL-only sources (github/zhihu/...) get scraped.
        "skip_summarized_sources": True,
    },
}


def available_routes() -> list[str]:
    return sorted(ROUTE_PROFILES)


def available_levels() -> list[str]:
    return list(LEVEL_META)


def level_meta(level: str | None) -> dict[str, Any]:
    return dict(LEVEL_META.get(str(level or DEFAULT_LEVEL).strip().lower(), LEVEL_META[DEFAULT_LEVEL]))


def resolve_route(search_type: str, lite: bool = False) -> set[str]:
    if lite:
        return ROUTE_PROFILES["default"]
    return ROUTE_PROFILES.get(search_type, set())


def route_meta(route: str) -> dict[str, Any]:
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


@dataclass
class SearchRunnerConfig:
    route: str
    counts: dict[str, int]
    timeout: int
    serpapi_engine: str
    keys: dict
    search_depth: str = "normal"


@dataclass
class ProviderSpec:
    name: str
    public_name: str
    call: Callable[[str, SearchRunnerConfig, SearchContext, Any], list]
    key_name: str | None = None
    missing_message: str = "missing API key"
    timeout_default: float = 20


def missing(source: str, message: str) -> list[dict]:
    return [{"source": source, "error": f"skipped: {message}"}]


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


def run_keyed_source(source: str, key_value, call_with_key, deadline: float | None = None, key_manager=None) -> list[dict]:
    manager = key_manager or BasicKeyManager()
    candidates = manager.candidates(source, key_value)
    if not candidates:
        return missing(source, "missing API key")
    last_results: list[dict] = []
    partial_rows: list[dict] = []
    for idx, candidate in enumerate(candidates):
        if deadline is not None and time.monotonic() >= deadline:
            break
        key = candidate.key if isinstance(candidate, KeyCandidate) else str(candidate)
        if hasattr(manager, "record_use") and isinstance(candidate, KeyCandidate):
            manager.record_use(source, candidate)
        results = as_dicts(call_with_key(key) or [])
        outcome = manager.classify_result(source, results)
        manager.record_result(source, candidate, outcome)
        if not outcome.retryable:
            if any("error" in row for row in results):
                return partial_rows + results
            return results
        partial_rows.extend(row for row in results if "error" not in row)
        last_results = results
        if idx == len(candidates) - 1:
            break
    error_rows = [row for row in last_results if "error" in row]
    err = error_rows[0].get("error", "key pool exhausted") if error_rows else "key pool exhausted"
    err = scrub_secrets(err, key_value)
    return partial_rows + [{"source": source, "error": f"key pool exhausted after {len(candidates)} key(s): {err}"}]


class SearchRunner:
    """Run configured searchers in parallel with source-level deadlines."""

    def __init__(self, config: SearchRunnerConfig, providers: dict[str, ProviderSpec], route_resolver=None, key_manager=None):
        self.config = config
        self.providers = providers
        self.route_resolver = route_resolver or resolve_route
        self.key_manager = key_manager or BasicKeyManager()

    def run(self, query: str, lite: bool = False) -> list[dict]:
        results: list[dict] = []
        jobs: list[tuple[str, Callable[[], list]]] = []
        source_names = self.route_resolver(self.config.route, lite=lite)
        timeout_seconds = max(0, self.config.timeout if self.config.timeout is not None else 60)
        source_deadline = time.monotonic() + timeout_seconds

        def source_request_timeout(default: float) -> float:
            remaining = source_deadline - time.monotonic()
            if remaining <= 0:
                return 0.1
            return min(float(default), max(0.1, remaining))

        for source in source_names:
            spec = self.providers.get(source)
            if spec is None:
                continue
            ctx = SearchContext(
                source=spec.public_name,
                timeout=source_request_timeout(spec.timeout_default),
                deadline=source_deadline,
                keys=self.config.keys,
            )
            if spec.key_name:
                key_value = self.config.keys.get(spec.key_name)
                if key_value:
                    jobs.append((
                        spec.public_name,
                        lambda spec=spec, ctx=ctx, key_value=key_value: self._run_keyed_source(
                            spec.public_name,
                            key_value,
                            lambda api_key: spec.call(query, self.config, ctx, api_key),
                            deadline=source_deadline,
                        ),
                    ))
                else:
                    results.extend(missing(spec.public_name, spec.missing_message))
            else:
                jobs.append((
                    spec.public_name,
                    lambda spec=spec, ctx=ctx: spec.call(query, self.config, ctx, None),
                ))

        if not jobs:
            return results
        if timeout_seconds <= 0:
            for name, _ in jobs:
                results.append({"source": name, "error": f"timeout after {timeout_seconds}s"})
            return results

        result_queue: queue.Queue = queue.Queue()

        def worker(source: str, call) -> None:
            try:
                result_queue.put((source, call(), None))
            except Exception as exc:
                result_queue.put((source, None, exc))

        pending = {name for name, _ in jobs}
        for name, call in jobs:
            threading.Thread(target=worker, args=(name, call), daemon=True).start()

        while pending:
            remaining = source_deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                source, source_results, error = result_queue.get(timeout=remaining)
            except queue.Empty:
                break
            if source not in pending:
                continue
            pending.remove(source)
            if error is not None:
                results.append({"source": source, "error": scrub_secrets(error, self.config.keys)})
            elif source_results:
                results.extend(as_dicts(source_results))
            else:
                results.append({"source": source, "status": "ok", "raw_hits": 0})

        for source in sorted(pending):
            results.append({"source": source, "error": f"timeout after {timeout_seconds}s"})
        return results

    def _run_keyed_source(self, source: str, key_value, call_with_key, deadline: float | None = None) -> list[dict]:
        return run_keyed_source(source, key_value, call_with_key, deadline=deadline, key_manager=self.key_manager)
