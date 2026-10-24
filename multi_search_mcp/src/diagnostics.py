"""Diagnostics: source listing, key provenance, and doctor probes."""
from __future__ import annotations

import time
from pathlib import Path

from .search.query_plan import build_query_plan
from .search.query_policy import QueryFusionPolicy
from .search.resolve import SearchPlanRequest, resolve_search_plan
from .search.search_runner import ALL_SOURCE_NAMES, available_routes
from .state import runtime
from .state.key_state import SQLiteKeyManager
from .state.keys import (
    KEY_ENV_NAMES,
    KeysError,
    count_jina_keys,
    key_sources,
    keys_file_permission_warning,
)
from .state.site_memory import SiteScraperMemory
from .state.state_store import StateStore
from .support.config import config_list, load_config, resolve_config_path_source
from .support.secrets import scrub_secrets


def list_sources(include_key_status: bool = False, include_scraper_stats: bool = False) -> dict:
    response = {"routes": available_routes(), "sources": sorted(ALL_SOURCE_NAMES)}
    store = None
    if include_key_status or include_scraper_stats:
        store = StateStore()
    if include_key_status:
        response["key_status"] = SQLiteKeyManager(store).status_rows()
    if include_scraper_stats:
        response["site_scraper_stats"] = SiteScraperMemory(store).stats()
    return response


def keys_file_warnings() -> list[str]:
    """Advisory warnings about the plaintext keys file (POSIX permissions)."""
    try:
        warning = keys_file_permission_warning(Path.home() / ".search-keys.json")
    except OSError:
        return []
    return [warning] if warning else []


def doctor_data(include_keys: bool = True, include_network: bool = False) -> dict:
    keys: dict = {}
    keys_error: str | None = None
    try:
        # Same config-scoped Twitter path reference as runtime, so diagnostics agree with search.
        try:
            doctor_config = load_config()
        except (ValueError, TypeError):
            doctor_config = {}
        keys = runtime.load_runtime_keys(doctor_config)
    except KeysError as exc:
        # doctor exists to diagnose key problems, so a corrupt keys file must be
        # reported, not raised — otherwise the one tool that could explain the
        # failure becomes unusable.
        keys_error = str(exc)
    store = StateStore()
    config_path, config_path_source = resolve_config_path_source()
    config_error = None
    try:
        config = load_config()
        resolve_search_plan(SearchPlanRequest(), config)
        variants = config_list(config, "expand") or config_list(config, "expand_queries")
        query_plan = build_query_plan("doctor", variants)
        QueryFusionPolicy.from_config(config).weights(query_plan.queries, query_plan.primary_query)
    except (ValueError, TypeError) as exc:
        config_error = scrub_secrets(exc, keys)
    data = {
        "server": "multi-search",
        "state_path": str(store.path),
        "config_path": str(config_path),
        "config_path_source": config_path_source,
        "config_loaded": config_error is None and config_path.exists(),
        "config_status": "error" if config_error else "ok" if config_path.exists() else "defaults",
        "key_sources": {
            "env": KEY_ENV_NAMES,
            "file": "~/.search-keys.json",
            "state": str(store.path),
        },
        "routes": available_routes(),
        "keys_file_warnings": keys_file_warnings(),
        "network_checked": False,
        "network_ok": None,
        "network_checks": [],
    }
    if config_error:
        data["config_error"] = config_error
    if include_network:
        from .support.http import urlopen_retry

        deadline = time.monotonic() + 5.0
        for url in (
            "https://hn.algolia.com/api/v1/search?query=python&hitsPerPage=1",
            "https://api.github.com/rate_limit",
        ):
            check = {"url": url, "status": "ok"}
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("network probe budget exhausted")
                with urlopen_retry(url, timeout=remaining) as response:
                    response.read(1)
            except Exception as exc:  # diagnostic boundary: report each failed probe
                check.update(status="error", error=scrub_secrets(exc, keys))
            data["network_checks"].append(check)
        data["network_checked"] = True
        data["network_ok"] = all(row["status"] == "ok" for row in data["network_checks"])
    if keys_error:
        data["keys_error"] = keys_error
    if include_keys:
        try:
            data["key_sources"] = key_sources()
        except Exception as exc:  # diagnostic boundary: provenance is advisory
            data["key_sources_error"] = scrub_secrets(exc, keys)
        data["configured_keys"] = {name: bool(value) for name, value in keys.items()}
        data["key_status"] = SQLiteKeyManager(store).status_rows()
        data["jina_keys_active_total"] = count_jina_keys(keys.get("jina"))
    return data
