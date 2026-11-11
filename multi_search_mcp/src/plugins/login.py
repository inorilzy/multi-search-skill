"""API-key login and logout for built-in provider plugins.

Credentials are read from stdin only and written through the same atomic keys
file writer as the rest of the CLI, so a key never appears in argv, output or
logs. OAuth is intentionally left for a later ticket; the dispatch seam lives in
:func:`login`.
"""
from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path
from typing import TextIO

from ..state.keys import (
    KeysError,
    default_keys_file,
    normalize_jina_config,
    write_keys_file_atomic,
)
from ..support.secrets import scrub_secrets
from . import registry
from .balance import collect_balances
from .base import ProviderPlugin


class LoginError(ValueError):
    """Raised for invalid login/logout usage; the CLI maps it to exit code 2."""


def _read_keys_for_write(path: Path) -> dict:
    """Read the keys object; a corrupt file must never be overwritten."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        # Reference only the path: the file body contains plaintext keys.
        raise KeysError(f"keys file is not valid JSON: {path}") from None
    if not isinstance(data, dict):
        raise KeysError(f"keys file is not a JSON object: {path}")
    return data


def _plugin(provider_id: str) -> ProviderPlugin:
    try:
        return registry.get_plugin(provider_id)
    except KeyError:
        raise LoginError(f"unknown provider: {provider_id}") from None


def _resolve_credential(plugin: ProviderPlugin, credential: str | None) -> str:
    entry = (credential or plugin.key_provider or "").strip()
    if not entry:
        raise LoginError(f"provider {plugin.id} does not use a credential")
    if entry not in {method.credential for method in plugin.auth_methods}:
        raise LoginError(f"provider {plugin.id} does not declare credential: {entry}")
    return entry


def _resolve_api_credential(plugin: ProviderPlugin, credential: str | None) -> str:
    entry = _resolve_credential(plugin, credential)
    if not any(method.type == "api" and method.credential == entry for method in plugin.auth_methods):
        raise LoginError(f"provider {plugin.id} does not declare an api login for credential: {entry}")
    return entry


def read_api_key(stream: TextIO | None = None) -> str:
    """Read one credential line; a terminal prompt uses getpass (no echo)."""
    stream = sys.stdin if stream is None else stream
    if getattr(stream, "isatty", lambda: False)():
        value = getpass.getpass("API key: ")
    else:
        value = stream.readline()
    key = str(value or "").strip()
    if not key:
        raise LoginError("credential is empty")
    return key


def _append_key(entry: str, existing, key: str):
    """Return ``(new_value, changed)`` for one keys.json entry."""
    if entry == "jina":
        entries = normalize_jina_config(existing)
        if any(item["key"] == key for item in entries):
            return existing, False
        entries.append({"key": key, "exhausted": False})
        return entries, True
    if not existing:
        return key, True
    if isinstance(existing, str):
        if existing == key:
            return existing, False
        return [existing, key], True
    if isinstance(existing, list):
        if key in existing:
            return existing, False
        return [*existing, key], True
    raise LoginError(f"cannot append credential to non-string entry: {entry}")


def _save_key(entry: str, key: str) -> bool:
    path = default_keys_file()
    data = _read_keys_for_write(path)
    value, changed = _append_key(entry, data.get(entry), key)
    if changed:
        data[entry] = value
        write_keys_file_atomic(path, data)
    return changed


def login(
    provider_id: str,
    credential: str | None = None,
    *,
    method: str = "api",
    stream: TextIO | None = None,
) -> dict:
    """Save one API key for ``provider_id`` and report the resulting balance."""
    if method == "oauth":
        raise LoginError("oauth 登录尚未支持")
    if method != "api":
        raise LoginError(f"unsupported login method: {method}")
    plugin = _plugin(provider_id)
    entry = _resolve_api_credential(plugin, credential)
    key = read_api_key(stream)
    changed = _save_key(entry, key)
    payload = {
        "provider": plugin.id,
        "label": plugin.label,
        "credential": entry,
        "saved": changed,
    }
    if plugin.balance is not None:
        try:
            payload["balance"] = collect_balances(provider_ids=[plugin.id], refresh=True)
        except Exception as exc:  # noqa: BLE001 - saving the key must not fail on a probe
            payload["balance_error"] = scrub_secrets(str(exc) or type(exc).__name__, key)
    return payload


def logout(provider_id: str, credential: str | None = None) -> dict:
    """Delete one credential entry from the keys file; missing entries are OK."""
    plugin = _plugin(provider_id)
    entry = _resolve_credential(plugin, credential)
    path = default_keys_file()
    data = _read_keys_for_write(path)
    if entry not in data:
        return {
            "provider": plugin.id,
            "credential": entry,
            "removed": False,
            "message": "未找到该凭据条目。",
        }
    del data[entry]
    write_keys_file_atomic(path, data)
    return {"provider": plugin.id, "credential": entry, "removed": True}
