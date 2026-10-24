"""Resolve search request/config defaults into one execution plan."""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

from ..support.config import (
    ConfigError,
    config_int,
    config_list,
    resolve_int,
    resolve_nonnegative,
    resolve_value,
)
from .capabilities import PROVIDER_CAPABILITIES
from .search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_PROFILES,
    normalize_route,
    normalize_source_name,
    resolve_route,
    route_meta,
)


# Per-provider count metadata is derived from the single source of truth in
# capabilities.py. A provider participates in the count system only when it has
# its own count key (``count_key``), can search, and declares a ``max_count``.
# This excludes scrapers (jina). ProviderMetadataDriftTests pins the
# resulting membership and values to the historical snapshot.
DEFAULT_SOURCE_COUNT = 10

_COUNT_PROVIDERS = [
    cap for cap in PROVIDER_CAPABILITIES.values()
    if cap.count_key and cap.search.can_search and cap.search.max_count
]

COUNT_CAPS = {cap.count_key: cap.search.max_count for cap in _COUNT_PROVIDERS}
DEFAULT_COUNTS = {cap.count_key: DEFAULT_SOURCE_COUNT for cap in _COUNT_PROVIDERS}


@dataclass
class SearchPlanRequest:
    """Explicit typed input for search-plan resolution.

    Only planning-relevant fields live here. Callers convert their public
    request DTO (``MultiSearchRequest``, ``SearchWebRequest``) before resolving;
    the resolver never reads arbitrary attributes from a duck-typed object.
    ``query`` is carried for context only and does not affect the plan.
    """

    query: str = ""
    route: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    timeout: int | None = None
    scrape_chars: int | None = None
    scrape_timeout: int | None = None
    scrape_concurrency: int | None = None
    output: str = "both"


@dataclass(frozen=True)
class ResolvedSearchPlan:
    route: str
    sources: set[str] | None
    disabled_sources: set[str]
    route_defaults: dict[str, Any]
    effective_counts: dict[str, int]
    timeout: int
    scrape_chars: int
    scrape_timeout: int
    scrape_url_timeout: int
    scrape_concurrency: int
    output_mode: str
    show_answer: bool
    show_snippet: bool
    serpapi_engine: str


# Keys that no longer affect execution. They are ignored (not validated) and
# warned about once per plan resolution; the next release removes them.
DEPRECATED_CONFIG_KEYS = (
    "scrape_top", "no_scrape", "scrape_per_source", "brief", "verbose",
    "title_url_only", "want_content",
)


def _warn_deprecated_config(config: dict) -> None:
    present = [key for key in DEPRECATED_CONFIG_KEYS if key in config]
    if present:
        warnings.warn(
            "ignored multi-search config key(s) will be removed: "
            + ", ".join(sorted(present)),
            FutureWarning,
            stacklevel=3,
        )


def resolve_search_plan(request: SearchPlanRequest, config: dict) -> ResolvedSearchPlan:
    if not isinstance(request, SearchPlanRequest):
        raise TypeError("resolve_search_plan requires a SearchPlanRequest")
    _warn_deprecated_config(config)
    route = normalize_route(str(resolve_value(request.route, config, "type", "default")))
    meta = route_meta(route)
    source_names = _resolve_sources(route, request.sources)

    timeout = resolve_nonnegative(request.timeout, config, "timeout", meta["timeout"])
    scrape_timeout = resolve_nonnegative(request.scrape_timeout, config, "scrape_timeout", 60)

    return ResolvedSearchPlan(
        route=route,
        sources=source_names,
        disabled_sources=resolve_disabled_sources(config),
        route_defaults=meta,
        effective_counts=build_counts(config, request.count, route_default=meta["count"]),
        timeout=timeout,
        scrape_chars=max(1, resolve_int(request.scrape_chars, config, "scrape_chars", 1200)),
        scrape_timeout=scrape_timeout,
        scrape_url_timeout=resolve_nonnegative(None, config, "scrape_url_timeout", scrape_timeout),
        scrape_concurrency=max(1, resolve_int(request.scrape_concurrency, config, "scrape_concurrency", 5)),
        output_mode=request.output if request.output in {"json", "markdown", "both"} else "both",
        show_answer=bool(meta.get("show_answer")),
        show_snippet=bool(meta.get("show_snippet")),
        serpapi_engine=str(config.get("serpapi_engine", "google_light")),
    )


def build_counts(config: dict, global_count: int | None = None, route_default: int = 10) -> dict[str, int]:
    # An explicit request count overrides every configured count. Null retains
    # its historical meaning of no per-provider defaults.
    counts_cfg = config.get("counts") if global_count is None else None
    if counts_cfg is None:
        counts_cfg = {}
    if not isinstance(counts_cfg, dict):
        raise ConfigError("counts requires a JSON object or null")
    configured_global = global_count if global_count is not None else config.get("count")
    counts = {}
    for source in DEFAULT_COUNTS:
        if global_count is not None:
            value = global_count
            key = "count"
        else:
            value = counts_cfg.get(source, config.get(f"{source}_count"))
            key = f"counts.{source}" if source in counts_cfg else f"{source}_count"
            # Accept the old name only when neither canonical count key was
            # supplied. Explicit sov2ex values (including null) take priority.
            if source == "sov2ex" and source not in counts_cfg and "sov2ex_count" not in config:
                value = counts_cfg.get("v2ex", config.get("v2ex_count"))
                key = "counts.v2ex" if "v2ex" in counts_cfg else "v2ex_count"
            if value is None and configured_global is not None:
                value = configured_global
                key = "count"
        if value is None:
            value = route_default
        counts[source] = max(1, min(config_int(value, key), COUNT_CAPS[source]))
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
) -> tuple[set[str], set[str]]:
    """Return (selected, active) sources, where active drops disabled ones."""
    selected = requested_sources or resolve_route(route)
    return selected, selected - disabled_sources
