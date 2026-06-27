"""Resolve search request/config defaults into one execution plan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..support.config import config_bool, config_list
from .search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_PROFILES,
    normalize_route,
    normalize_source_name,
    resolve_route,
    route_meta,
)


DEFAULT_COUNTS = {
    "baidu": 10,
    "brave": 10,
    "tavily": 10,
    "exa": 10,
    "github": 10,
    "hackernews": 10,
    "serpapi": 10,
    "youtube": 10,
    "bilibili": 10,
    "stackoverflow": 10,
    "firecrawl": 10,
    "zhihu": 10,
    "linuxdo": 10,
    "linuxdo_api": 10,
    "twitter": 10,
    "glm_web": 10,
    "deepseek_web": 10,
}

COUNT_CAPS = {
    "baidu": 50,
    "brave": 20,
    "tavily": 20,
    "exa": 100,
    "github": 100,
    "hackernews": 100,
    "serpapi": 100,
    "youtube": 50,
    "bilibili": 50,
    "stackoverflow": 100,
    "firecrawl": 100,
    "zhihu": 10,
    "linuxdo": 20,
    "linuxdo_api": 10,
    "twitter": 20,
    "glm_web": 30,
    "deepseek_web": 30,
}


@dataclass(frozen=True)
class ResolvedSearchPlan:
    route: str
    sources: set[str] | None
    disabled_sources: set[str]
    route_defaults: dict[str, Any]
    effective_counts: dict[str, int]
    timeout: int
    scrape_top: int
    scrape_chars: int
    scrape_per_source: int
    scrape_timeout: int
    scrape_url_timeout: int
    scrape_concurrency: int
    output_mode: str
    title_url_only: bool
    want_content: bool
    show_answer: bool
    show_snippet: bool
    serpapi_engine: str


def resolve_search_plan(request: Any, config: dict) -> ResolvedSearchPlan:
    route = normalize_route(str(_resolve_value(request.route, config, "type", "default")))
    meta = route_meta(route)
    source_names = _resolve_sources(route, request.sources)

    timeout = _resolve_nonnegative(request.timeout, config, "timeout", meta["timeout"])
    scrape_top = _resolve_scrape_top(request, config, meta)
    scrape_timeout = _resolve_nonnegative(request.scrape_timeout, config, "scrape_timeout", 60)

    return ResolvedSearchPlan(
        route=route,
        sources=source_names,
        disabled_sources=resolve_disabled_sources(config),
        route_defaults=meta,
        effective_counts=build_counts(config, request.count, route_default=meta["count"]),
        timeout=timeout,
        scrape_top=scrape_top,
        scrape_chars=max(1, _resolve_int(request.scrape_chars, config, "scrape_chars", 6000)),
        scrape_per_source=max(1, _resolve_int(request.scrape_per_source, config, "scrape_per_source", 6)),
        scrape_timeout=scrape_timeout,
        scrape_url_timeout=_resolve_nonnegative(None, config, "scrape_url_timeout", scrape_timeout),
        scrape_concurrency=max(1, _resolve_int(request.scrape_concurrency, config, "scrape_concurrency", 5)),
        output_mode=request.output if request.output in {"json", "markdown", "both"} else "both",
        title_url_only=bool(request.title_url_only or meta.get("title_url_only")),
        want_content=bool(meta.get("want_content", False)),
        show_answer=bool(meta.get("show_answer")),
        show_snippet=bool(meta.get("show_snippet")),
        serpapi_engine=str(config.get("serpapi_engine", "google_light")),
    )


def build_counts(config: dict, global_count: int | None = None, route_default: int = 10) -> dict[str, int]:
    counts_cfg = config.get("counts") if isinstance(config.get("counts"), dict) else {}
    configured_global = global_count if global_count is not None else config.get("count")
    counts = {}
    for source in DEFAULT_COUNTS:
        if global_count is not None:
            value = global_count
        else:
            value = counts_cfg.get(source, config.get(f"{source}_count"))
            if value is None and configured_global is not None:
                value = configured_global
        if value is None:
            value = route_default
        counts[source] = max(1, min(int(value), COUNT_CAPS[source]))
    return counts


def _resolve_sources(route: str, requested_sources: list[str] | None) -> set[str] | None:
    if requested_sources:
        source_names = {normalize_source_name(str(source)) for source in requested_sources}
        unknown_sources = source_names - ALL_SOURCE_NAMES
        if unknown_sources:
            raise ValueError(
                f"unknown source(s): {', '.join(sorted(unknown_sources))}; "
                f"valid sources: {', '.join(sorted(ALL_SOURCE_NAMES))}"
            )
        return source_names
    if route in ROUTE_PROFILES:
        return None
    raise ValueError(
        f"unknown route: {route}; valid routes: {', '.join(sorted(ROUTE_PROFILES))}"
    )


def resolve_disabled_sources(config: dict) -> set[str]:
    """Resolve the globally disabled search sources from config.

    Only search sources are accepted; scrape backends (e.g. ``jina``) are not
    valid here. Unknown names fail loudly instead of being silently ignored.
    """
    disabled = {normalize_source_name(source) for source in config_list(config, "disabled_sources")}
    unknown = disabled - ALL_SOURCE_NAMES
    if unknown:
        raise ValueError(
            f"unknown disabled source(s): {', '.join(sorted(unknown))}; "
            f"valid sources: {', '.join(sorted(ALL_SOURCE_NAMES))}"
        )
    return disabled


def resolve_active_sources(
    route: str,
    requested_sources: set[str] | None,
    disabled_sources: set[str],
    *,
    lite: bool = False,
) -> tuple[set[str], set[str]]:
    """Return (selected, active) sources, where active drops disabled ones."""
    selected = requested_sources or resolve_route(route, lite=lite)
    return selected, selected - disabled_sources

def _resolve_scrape_top(request: Any, config: dict, meta: dict[str, Any]) -> int:
    if request.scrape_top is None and config_bool(config, "no_scrape", False):
        return 0
    return _resolve_nonnegative(request.scrape_top, config, "scrape_top", meta["scrape_top"])


def _resolve_value(request_value: Any, config: dict, key: str, default: Any) -> Any:
    if request_value is not None:
        return request_value
    if key in config and config.get(key) is not None:
        return config.get(key)
    return default


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_int(request_value: Any, config: dict, key: str, default: int) -> int:
    return _int_or_default(_resolve_value(request_value, config, key, default), default)


def _resolve_nonnegative(request_value: Any, config: dict, key: str, default: int) -> int:
    return max(0, _resolve_int(request_value, config, key, default))
