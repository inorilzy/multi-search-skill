"""Resolve search request/config defaults into one execution plan."""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Any

from ..support.config import (
    ConfigError,
    config_int,
    config_list,
    resolve_int,
    resolve_nonnegative,
)
from .capabilities import PROVIDER_CAPABILITIES
from .search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_PROFILES,
    default_routes_config,
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

_ROUTE_ID_PATTERN = re.compile(r"[a-z0-9_-]{1,64}\Z", re.ASCII)


@dataclass(frozen=True)
class RouteDefinition:
    label: str
    sources: tuple[str, ...]
    timeout: int | None


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
    route_sources: set[str]
    available_routes: tuple[str, ...]
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
    routes = resolve_configured_routes(config)
    configured_route = _resolve_configured_route(config, routes)
    route = (
        normalize_route(str(request.route))
        if request.route is not None
        else configured_route
    )
    if route not in routes:
        raise ValueError(
            f"unknown route: {route}; valid routes: {', '.join(sorted(routes))}"
        )
    route_definition = routes[route]
    # Built-in route ids keep their behavior metadata even when the user
    # edits labels/sources; custom ids inherit the ``default`` metadata rather
    # than the bare DEFAULT_ROUTE_META floor.
    meta = route_meta(route if route in ROUTE_PROFILES else "default")
    meta["primary_success_sources"] = set(route_definition.sources)
    source_names = _resolve_sources(route, request.sources, set(routes))

    timeout = _resolve_route_timeout(
        request.timeout, config, route_definition.timeout, meta["timeout"]
    )
    scrape_timeout = resolve_nonnegative(request.scrape_timeout, config, "scrape_timeout", 60)
    scrape_timeout = resolve_nonnegative(request.scrape_timeout, config, "scrape_timeout", 60)

    return ResolvedSearchPlan(
        route=route,
        sources=source_names,
        disabled_sources=resolve_disabled_sources(config),
        route_sources=set(route_definition.sources),
        available_routes=tuple(sorted(routes)),
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


def resolve_configured_routes(config: dict) -> dict[str, RouteDefinition]:
    """Validate and normalize the complete route map from desktop JSON."""
    raw_routes = default_routes_config() if "routes" not in config else config.get("routes")
    if not isinstance(raw_routes, dict):
        raise ConfigError("routes requires a JSON object")
    if not raw_routes:
        raise ConfigError("routes requires at least one route")

    routes: dict[str, RouteDefinition] = {}
    for route_id, raw_definition in raw_routes.items():
        if not isinstance(route_id, str) or not _ROUTE_ID_PATTERN.fullmatch(route_id):
            raise ConfigError(
                "routes ids require 1-64 ASCII lowercase letters, digits, underscores, or hyphens"
            )
        if route_id == "web":
            raise ConfigError("routes.web is reserved as an alias for default")
        if not isinstance(raw_definition, dict):
            raise ConfigError(f"routes.{route_id} requires a JSON object")
        unknown_fields = set(raw_definition) - {"label", "sources", "timeout"}
        if unknown_fields:
            raise ConfigError(
                f"routes.{route_id} contains unknown field(s): "
                f"{', '.join(sorted(str(field) for field in unknown_fields))}"
            )

        raw_label = raw_definition.get("label")
        if not isinstance(raw_label, str):
            raise ConfigError(f"routes.{route_id}.label requires a string")
        label = raw_label.strip()
        if not 1 <= len(label) <= 80:
            raise ConfigError(f"routes.{route_id}.label requires 1-80 characters after trimming")

        raw_sources = raw_definition.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ConfigError(f"routes.{route_id}.sources requires at least one source")
        normalized_sources: list[str] = []
        seen_sources: set[str] = set()
        for raw_source in raw_sources:
            if not isinstance(raw_source, str):
                raise ConfigError(f"routes.{route_id}.sources requires a list of strings")
            source_name = raw_source.strip()
            source = normalize_source_name(source_name)
            if source not in ALL_SOURCE_NAMES:
                raise ConfigError(
                    f"routes.{route_id}.sources contains unknown source: {source_name}; "
                    f"valid sources: {', '.join(sorted(ALL_SOURCE_NAMES))}"
                )
            if source not in seen_sources:
                normalized_sources.append(source)
                seen_sources.add(source)
        if not normalized_sources:
            raise ConfigError(f"routes.{route_id}.sources requires at least one source")

        raw_timeout = raw_definition.get("timeout")
        if raw_timeout is not None and (
            isinstance(raw_timeout, bool)
            or not isinstance(raw_timeout, int)
            or not 1 <= raw_timeout <= 60
        ):
            raise ConfigError(f"routes.{route_id}.timeout requires null or an integer from 1 to 60")
        routes[route_id] = RouteDefinition(
            label=label,
            sources=tuple(normalized_sources),
            timeout=raw_timeout,
        )
    return routes


def _resolve_configured_route(
    config: dict, routes: dict[str, RouteDefinition]
) -> str:
    raw_route = config.get("type", "default")
    if raw_route is None:
        raw_route = "default"
    if not isinstance(raw_route, str):
        raise ConfigError("type requires a route id string")
    route = normalize_route(raw_route)
    if route not in routes:
        raise ConfigError(
            f"type references unknown route: {raw_route}; "
            f"valid routes: {', '.join(sorted(routes))}"
        )
    return route


def _resolve_route_timeout(
    request_timeout: Any,
    config: dict,
    route_timeout: int | None,
    meta_timeout: int,
) -> int:
    if request_timeout is not None:
        return max(0, config_int(request_timeout, "timeout"))
    if route_timeout is not None:
        return route_timeout
    if config.get("timeout") is not None:
        return max(0, config_int(config.get("timeout"), "timeout"))
    return meta_timeout


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


def _resolve_sources(
    route: str,
    requested_sources: list[str] | None,
    valid_routes: set[str] | None = None,
) -> set[str] | None:
    if requested_sources:
        source_names = {normalize_source_name(str(source)) for source in requested_sources}
        unknown_sources = source_names - ALL_SOURCE_NAMES
        if unknown_sources:
            raise ValueError(
                f"unknown source(s): {', '.join(sorted(unknown_sources))}; "
                f"valid sources: {', '.join(sorted(ALL_SOURCE_NAMES))}"
            )
        return source_names
    known_routes = set(ROUTE_PROFILES) if valid_routes is None else valid_routes
    if route in known_routes:
        return None
    raise ValueError(
        f"unknown route: {route}; valid routes: {', '.join(sorted(known_routes))}"
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
    route_sources: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    """Return (selected, active) sources, where active drops disabled ones."""
    selected = requested_sources or route_sources or resolve_route(route)
    return selected, selected - disabled_sources
