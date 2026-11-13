"""API-key and OAuth login/logout for built-in provider plugins.

API keys are read from stdin only and written through the same atomic keys
file writer as the rest of the CLI, so a key never appears in argv, output or
logs. OAuth flows live in :mod:`multi_search_mcp.src.plugins.oauth`; this module
resolves the declared credential entry and turns flow failures into the public
jsonl/text error event.
"""
from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path
from typing import TextIO

from ..state.key_state import key_fingerprint
from ..state.keys import (
    KeysError,
    default_keys_file,
    normalize_jina_config,
    write_keys_file_atomic,
)
from ..support.secrets import scrub_secrets
from . import accounts, oauth, oauth_store, registry
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


def _resolve_oauth_credential(plugin: ProviderPlugin, credential: str | None) -> str:
    entries = [method.credential for method in plugin.auth_methods if method.type == "oauth"]
    if not entries:
        raise LoginError(f"provider {plugin.id} 尚未支持 oauth 登录")
    if credential:
        entry = credential.strip()
    elif len(entries) == 1:
        entry = entries[0]
    else:
        raise LoginError(f"provider {plugin.id} declares multiple oauth credentials; pass --credential")
    if entry not in entries:
        raise LoginError(f"provider {plugin.id} does not declare an oauth login for credential: {entry}")
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


def _probe_balance(plugin: ProviderPlugin) -> dict | None:
    """Run one post-login balance confirmation; a probe never rolls back a key."""
    if plugin.balance is None:
        return None
    try:
        return collect_balances(provider_ids=[plugin.id], refresh=True)
    except Exception as exc:  # noqa: BLE001 - saving the credential already succeeded
        return {"error": scrub_secrets(str(exc) or type(exc).__name__)}


def _login_oauth(
    plugin: ProviderPlugin,
    credential: str | None,
    *,
    output_format: str | None,
    no_browser: bool,
    timeout: float,
    stream: TextIO | None,
    emit,
) -> dict:
    entry = _resolve_oauth_credential(plugin, credential)
    fmt = output_format or "text"
    if fmt not in {"jsonl", "text"}:
        raise LoginError("oauth 登录只支持 --format jsonl 或 text")
    emitter = emit or (lambda event: None)

    try:
        if plugin.id == "firecrawl":
            oauth.firecrawl_login(
                credential=entry,
                emit=emitter,
                save_credential=lambda key: _save_key(entry, key),
                no_browser=no_browser,
                timeout=timeout,
                stdin=stream,
            )
            balance = _probe_balance(plugin)
        elif plugin.id == "parallel":
            oauth.parallel_login(
                credential=entry,
                save_credential=lambda key: _save_key(plugin.key_provider or "parallel", key),
                emit=emitter,
                no_browser=no_browser,
                timeout=timeout,
                stdin=stream,
            )
            balance = None
        else:  # pragma: no cover - both oauth providers are handled above
            raise LoginError(f"provider {plugin.id} 尚未支持 oauth 登录")
    except oauth.OAuthFlowError as exc:
        emitter({"event": "error", "error_kind": exc.kind, "message": exc.message})
        return {"ok": False, "exit_code": 1}
    except (oauth_store.OAuthStoreError, KeysError) as exc:
        emitter({"event": "error", "error_kind": "error", "message": scrub_secrets(str(exc))})
        return {"ok": False, "exit_code": 1}
    except KeyboardInterrupt:
        emitter({"event": "error", "error_kind": "cancelled", "message": "登录已取消。"})
        return {"ok": False, "exit_code": 1}
    except Exception as exc:  # noqa: BLE001 - keep the jsonl stream to event objects
        emitter({
            "event": "error",
            "error_kind": "internal",
            "message": scrub_secrets(str(exc) or type(exc).__name__),
        })
        return {"ok": False, "exit_code": 1}

    return {
        "ok": True,
        "exit_code": 0,
        "provider": plugin.id,
        "credential": entry,
        "balance": balance,
    }


def login(
    provider_id: str,
    credential: str | None = None,
    *,
    method: str = "api",
    account_id: str | None = None,
    stream: TextIO | None = None,
    output_format: str | None = None,
    no_browser: bool = False,
    timeout: float = 300.0,
    emit=None,
) -> dict:
    """Save one credential for ``provider_id`` and report the resulting state."""
    plugin = _plugin(provider_id)
    if method == "oauth":
        if account_id is not None:
            raise LoginError("--account is only supported for api login")
        return _login_oauth(
            plugin,
            credential,
            output_format=output_format,
            no_browser=no_browser,
            timeout=timeout,
            stream=stream,
            emit=emit,
        )
    if method != "api":
        raise LoginError(f"unsupported login method: {method}")
    entry = _resolve_api_credential(plugin, credential)
    if account_id is not None:
        try:
            rows = accounts.list_accounts(plugin.id)[plugin.id]
            if not any(row["id"] == account_id for row in rows):
                raise accounts.AccountError("account not found")
        except accounts.AccountError as exc:
            raise LoginError(str(exc)) from exc
    key = read_api_key(stream)
    changed = _save_key(entry, key)
    if account_id is not None:
        try:
            accounts.move_key(plugin.id, key_fingerprint(key), account_id, credential=entry)
        except accounts.AccountError as exc:
            raise LoginError(str(exc)) from exc
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


def logout(provider_id: str, credential: str | None = None, *, http=None) -> dict:
    """Delete one credential entry; OAuth-only accounts are revoked first."""
    plugin = _plugin(provider_id)
    entry = _resolve_credential(plugin, credential)
    oauth_entries = {method.credential for method in plugin.auth_methods if method.type == "oauth"}
    api_entries = {method.credential for method in plugin.auth_methods if method.type == "api"}
    if entry in oauth_entries and entry not in api_entries:
        result = oauth.parallel_logout(entry, http=http)
        return {"provider": plugin.id, "credential": entry, **result}
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
