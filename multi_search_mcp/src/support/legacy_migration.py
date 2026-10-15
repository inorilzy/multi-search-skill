"""Explicit preview/apply import. Sources stay untouched; secrets never leave this module."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .credential_store import (
    CredentialStore, CredentialStoreError, ConfigDatabase, PROVIDERS,
    legacy_store as default_legacy_store, validate_value,
)

MIGRATABLE = PROVIDERS


class MigrationError(ValueError):
    """Safe user-visible import failure."""


def mask(key: str) -> str:
    return "***" if len(key) < 12 else f"{key[:5]}…{key[-4:]}"


def _preview(value):
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [_preview(item) for item in value]
    if isinstance(value, dict):
        # Extra legacy Jina metadata is retained internally, never exposed.
        return {"key": mask(value["key"]), "exhausted": bool(value.get("exhausted"))}
    return "***"


def _read_keys_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MigrationError("legacy file not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        raise MigrationError("legacy file is not valid JSON") from None
    if not isinstance(data, dict):
        raise MigrationError("legacy file must contain a JSON object")
    return data


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _settings_database(store, database):
    if database is not None:
        return database
    backend = getattr(store, "_backend", None)
    return getattr(backend, "database", None) or ConfigDatabase()


def _validate_settings(data):
    # Reuse Core routing/source/query validation; preserve unrelated JSON fields.
    from ..service import MultiSearchRequest
    from ..search.resolve import resolve_search_plan
    from ..search.query_plan import build_query_plan
    from ..search.query_policy import QueryFusionPolicy
    from .config import config_list, config_str
    if any(name in data for name in MIGRATABLE) or any(name in data for name in ("key", "api_key", "token", "auth_token", "ct0")):
        raise MigrationError("settings cannot contain credentials")
    try:
        resolve_search_plan(MultiSearchRequest(query="migration"), data)
        config_str(data, "twitter_cookies_path")
        plan = build_query_plan("migration", config_list(data, "expand") or config_list(data, "expand_queries"))
        QueryFusionPolicy.from_config(data).weights(plan.queries, plan.primary_query)
    except (ValueError, TypeError):
        raise MigrationError("legacy settings are invalid") from None
    return data


def _sources(keys_file, *, settings_file=None, include_credentials=False,
             include_environment=False, legacy_store=None, environ=None):
    candidates: dict[str, dict[str, Any]] = {}
    unsupported = []
    source_data = {}

    def add(provider, source, value):
        try:
            valid = validate_value(provider, value)
        except ValueError:
            unsupported.append({"provider": provider, "action": "unsupported", "source": source,
                                "reason": "invalid credential shape; source left untouched"})
            return
        candidates.setdefault(provider, {})[source] = valid

    cookie_refs = {}
    if keys_file is not None:
        data = _read_keys_file(Path(keys_file))
        source_data["file"] = data
        for provider, value in data.items():
            if provider in MIGRATABLE:
                add(provider, "file", value)
            elif provider in ("twitter", "twitter_cookies") and isinstance(value, str) and value.strip() and not any(ord(c) < 32 for c in value):
                cookie_refs["file"] = {"twitter_cookies_path": value.strip()}
            else:
                unsupported.append({"provider": provider, "action": "unsupported",
                                    "reason": "unsupported entry; source left untouched"})
    if settings_file is not None:
        data = _read_keys_file(Path(settings_file))
        source_data["settings_file"] = data
        candidates.setdefault("settings", {})["settings_file"] = _validate_settings(data)
    if include_credentials:
        old = legacy_store if legacy_store is not None else default_legacy_store()
        snapshot = {}
        for provider in MIGRATABLE:
            try:
                value = old.get(provider)
            except CredentialStoreError:
                raise MigrationError("legacy credential source is unreadable") from None
            snapshot[provider] = value
            if value is not None:
                add(provider, "credentials", value)
        source_data["credentials"] = snapshot
    if include_environment:
        from ..state.keys import KEY_ENV_PAIRS
        env = os.environ if environ is None else environ
        snapshot = {name: env.get(name) for name, _ in KEY_ENV_PAIRS}
        source_data["environment"] = snapshot
        for name, provider in KEY_ENV_PAIRS:
            value = snapshot[name]
            if not value:
                continue
            source = "environment:" + name
            if provider == "twitter_cookies":
                cookie_refs[source] = {"twitter_cookies_path": value}
            else:
                add(provider, source, value)
    for source, reference in cookie_refs.items():
        candidates.setdefault("settings", {})[source] = _validate_settings(reference)
    return candidates, unsupported, _fingerprint(source_data)


def _store_digest(store, providers, database=None) -> str:
    values = {}
    for provider in providers:
        try:
            values[provider] = store.get(provider)
        except CredentialStoreError:
            values[provider] = {"unreadable": True}
    if database is not None:
        values["settings"] = database.read_settings()
    return _fingerprint(values)


def plan_migration(keys_file: Path | None, store: CredentialStore, *, settings_file=None,
                   include_credentials=False, include_environment=False, legacy_store=None,
                   environ=None, database=None) -> dict[str, Any]:
    candidates, unsupported, digest = _sources(
        keys_file, settings_file=settings_file, include_credentials=include_credentials,
        include_environment=include_environment, legacy_store=legacy_store, environ=environ,
    )
    db = _settings_database(store, database) if "settings" in candidates else None
    items = list(unsupported)
    for provider in sorted(candidates):
        values = candidates[provider]
        try:
            existing = db.read_settings() if provider == "settings" else store.get(provider)
        except CredentialStoreError:
            items.append({"provider": provider, "action": "blocked", "reason": "destination unreadable"})
            continue
        unique = {_fingerprint(v) for v in values.values()}
        first = next(iter(values.values()))
        source_conflict = len(unique) > 1
        target_present = bool(existing) if provider == "settings" else existing is not None
        target_conflict = target_present and any(value != existing for value in values.values())
        action = "conflict" if source_conflict or target_conflict else "already_current" if target_present else "migrate"
        preview = "settings fields: " + ", ".join(sorted(first)) if provider == "settings" else _preview(first)
        items.append({"provider": provider, "action": action, "preview": preview,
                      "source_conflict": source_conflict, "target_conflict": target_conflict,
                      "sources": [{"source": source, "preview": ("settings fields: " + ", ".join(sorted(value)))
                                   if provider == "settings" else _preview(value)} for source, value in values.items()]})
    return {"items": items,
            "migratable": sorted({i["provider"] for i in items if i["action"] in ("migrate", "conflict")}),
            "skipped": sorted({i["provider"] for i in items if i["action"] in ("unsupported", "blocked")}),
            "source_digest": digest, "store_digest": _store_digest(store, MIGRATABLE, db)}


def apply_migration(keys_file: Path | None, store: CredentialStore, plan: dict[str, Any], *,
                    approved: list[str], choices: dict[str, str], sources=None, settings_file=None,
                    include_credentials=False, include_environment=False, legacy_store=None,
                    environ=None, database=None) -> dict[str, Any]:
    candidates, _, digest = _sources(
        keys_file, settings_file=settings_file, include_credentials=include_credentials,
        include_environment=include_environment, legacy_store=legacy_store, environ=environ,
    )
    db = _settings_database(store, database) if "settings" in candidates else None
    if digest != plan["source_digest"]:
        raise MigrationError("legacy source changed since preview; run preview again")
    if _store_digest(store, MIGRATABLE, db) != plan["store_digest"]:
        raise MigrationError("configuration store changed since preview; run preview again")
    by_provider = {i["provider"]: i for i in plan["items"] if i["action"] != "unsupported"}
    selected = {}
    sources = sources or {}
    for provider in dict.fromkeys(approved):
        item = by_provider.get(provider)
        if item is None or item["action"] not in ("migrate", "conflict", "already_current"):
            raise MigrationError("approved entry is not migratable in this plan")
        values = candidates[provider]
        source = sources.get(provider)
        if item.get("source_conflict") and source not in values:
            raise MigrationError("conflicting legacy sources require an explicit source choice")
        if source is not None and source not in values:
            raise MigrationError("selected legacy source is not in this plan")
        value = values[source] if source is not None else next(iter(values.values()))
        existing = db.read_settings() if provider == "settings" else store.get(provider)
        if existing and existing != value and choices.get(provider) not in ("keep", "replace"):
            raise MigrationError("stored entry conflicts; choose keep or replace")
        selected[provider] = (value, existing)
    written, kept, failed, unchanged = [], [], [], []
    backend = getattr(store, "_backend", None)
    if hasattr(backend, "import_batch"):
        writes = {}
        settings = None
        for provider, (value, existing) in selected.items():
            if existing == value:
                unchanged.append(provider)
            elif existing and choices.get(provider) == "keep":
                kept.append(provider)
            else:
                if provider == "settings":
                    settings = {**existing, **value}
                else:
                    writes[provider] = value
                written.append(provider)

        def check():
            _, _, current = _sources(
                keys_file, settings_file=settings_file, include_credentials=include_credentials,
                include_environment=include_environment, legacy_store=legacy_store, environ=environ,
            )
            if current != plan["source_digest"] or _store_digest(store, MIGRATABLE, db) != plan["store_digest"]:
                raise MigrationError("migration inputs changed since preview; run preview again")

        if written:
            try:
                backend.import_batch(writes, settings, check)
            except CredentialStoreError:
                failed, written = written, []
        not_done = sorted(set(plan["skipped"]) | set(failed) | (set(plan["migratable"]) - set(approved)))
        return {"written": written, "kept": kept, "unchanged": unchanged, "failed": failed,
                "not_done": not_done, "complete": not failed and not not_done}
    for provider, (value, existing) in selected.items():
        if existing == value:
            unchanged.append(provider)
        elif existing and choices.get(provider) == "keep":
            kept.append(provider)
        else:
            try:
                if provider == "settings":
                    # Preserve fields not supplied by the chosen legacy source.
                    db.write_settings({**existing, **value})
                else:
                    store.set(provider, value)
                written.append(provider)
            except (CredentialStoreError, ValueError):
                failed.append(provider)
    not_done = sorted(set(plan["skipped"]) | set(failed) | (set(plan["migratable"]) - set(approved)))
    return {"written": written, "kept": kept, "unchanged": unchanged, "failed": failed,
            "not_done": not_done, "complete": not failed and not not_done}
