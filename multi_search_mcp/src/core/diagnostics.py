"""Source inventory and runtime doctor diagnostics."""
from __future__ import annotations

import time

from ..search.query_plan import build_query_plan
from ..search.query_policy import QueryFusionPolicy
from ..search.resolve import resolve_search_plan
from ..search.search_runner import ALL_SOURCE_NAMES, available_routes
from ..state.keys import KeysError, count_jina_keys, key_sources
from ..state.site_memory import SiteScraperMemory
from ..support.config import config_list, load_config
from ..support.secrets import scrub_secrets
from . import runtime
from .requests import MultiSearchRequest


def list_sources(include_key_status: bool = False, include_scraper_stats: bool = False) -> dict:
    response = {"routes": available_routes(), "sources": sorted(ALL_SOURCE_NAMES)}
    store = None
    if include_key_status or include_scraper_stats:
        store = runtime.new_state_store()
    if include_key_status:
        response["key_status"] = runtime.key_manager_for(store).status_rows()
    if include_scraper_stats:
        response["site_scraper_stats"] = SiteScraperMemory(store).stats()
    return response


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
    store = runtime.new_state_store()
    config_path = runtime.resolve_config_path()
    config_error = None
    route_names = available_routes()
    try:
        config = load_config()
        doctor_plan = resolve_search_plan(MultiSearchRequest(query="doctor"), config)
        route_names = list(doctor_plan.available_routes)
        variants = config_list(config, "expand") or config_list(config, "expand_queries")
        query_plan = build_query_plan("doctor", variants)
        QueryFusionPolicy.from_config(config).weights(query_plan.queries, query_plan.primary_query)
    except (ValueError, TypeError) as exc:
        config_error = scrub_secrets(exc, keys)
    data = {
        "server": "multi-search",
        "twitter_cookie_storage": {
            "mode": doctor_config.get("twitter_cookies_mode", "file"),
            "boundary": "Windows DPAPI; decrypted only for X calls" if doctor_config.get("twitter_cookies_mode") == "managed" else "legacy plaintext cookie file; not encrypted by multi-search",
        },
        "config_storage": {"backend": "sqlite-dpapi", "schema_version": 1},
        "state_path": str(store.path),
        "config_path": str(config_path),
        "config_loaded": config_error is None and config_path.exists(),
        "config_status": "error" if config_error else "ok" if config_path.exists() else "defaults",
        "key_sources": {
            "storage": "sqlite-dpapi",
            "database": str(config_path),
            "legacy_sources": "explicit import only",
            "state": str(store.path),
        },
        "routes": route_names,
        "network_checked": False,
        "network_ok": None,
        "network_checks": [],
    }
    if config_error:
        data["config_error"] = config_error
    if include_network:
        from ..support.http import urlopen_retry

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
        data["key_status"] = runtime.key_manager_for(store).status_rows()
        data["jina_keys_active_total"] = count_jina_keys(keys.get("jina"))
    return data
