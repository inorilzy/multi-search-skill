"""Explicit, user-approved migration of a legacy keys file into the credential store.

The legacy file (``~/.search-keys.json`` shape) maps provider names to a string or a list of
strings. Only single-secret providers that the credential store can hold losslessly are migrated.
Everything else is reported as unsupported and left in place; nothing is collapsed to a single key.

This module is the single owner of the migration rules. The desktop calls it through the CLI
and never re-implements the rules. Secrets are never returned: previews are masked, and results
name providers only.

Apply always re-reads the file and the store and refuses if either changed since the preview.
The source file is never modified or deleted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .credential_store import CredentialStore, CredentialStoreError, validate_key

# Single-key search providers this command migrates into the shared SQLite/DPAPI store. Jina is
# also store-backed (keys.CREDENTIAL_STORE_PROVIDERS), but its entries carry per-key metadata
# (lists / ``exhausted`` flags), so it stays in the legacy file and is reported as unsupported.
MIGRATABLE = ("baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github")


class MigrationError(ValueError):
    """The plan cannot be applied safely. Messages never contain secret material."""


def mask(key: str) -> str:
    """Irreversible preview identifier; contains no key characters at any length.

    Same ``sha256:<8 hex>`` form as ``key_state.key_fingerprint``, so a migrated key
    can be matched against ``keys status`` output without revealing any plaintext.
    """
    import hashlib

    return "sha256:" + hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]


def _read_keys_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MigrationError("legacy keys file not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        # Do not echo the parser detail or the file contents.
        raise MigrationError("legacy keys file is not valid JSON") from None
    if not isinstance(data, dict):
        raise MigrationError("legacy keys file must contain a JSON object")
    return data


def _single_key(value: Any) -> str | None:
    """Return the one key when the entry is a single string or a one-element list of strings."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None


def _fingerprint(keys: dict[str, Any]) -> str:
    """Stable digest of the file for change detection. Never returned to callers."""
    import hashlib

    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode("utf-8")).hexdigest()


def _twitter_item(value: Any) -> dict[str, Any]:
    """Twitter is classified by shape only. The cookie file is never opened or read here.

    A string path reference that exists is still read directly by the CLI, so it is kept as-is
    (already_current, no migration). A missing path is not reported as usable. Cookie objects,
    lists, and anything else need store capability this migration does not have, so they stay
    unsupported and the file is left untouched.
    """
    if isinstance(value, str) and value.strip() and "\n" not in value and "\r" not in value:
        try:
            exists = Path(value.strip()).expanduser().is_file()
        except (OSError, ValueError):
            exists = False
        if exists:
            return {"provider": "twitter", "action": "already_current", "path_exists": True,
                    "reason": "cookie file reference is read directly by the CLI; not migrated"}
        return {"provider": "twitter", "action": "unsupported", "path_exists": False,
                "reason": "cookie file reference does not point to an existing file; not verified usable; left in the legacy file"}
    return {"provider": "twitter", "action": "unsupported",
            "reason": "cookie object or complex entry needs store capability not available here; left in the legacy file"}


def plan_migration(keys_file: Path, store: CredentialStore) -> dict[str, Any]:
    keys = _read_keys_file(keys_file)
    items: list[dict[str, Any]] = []
    for provider in sorted(keys):
        value = keys[provider]
        if provider == "twitter":
            items.append(_twitter_item(value))
            continue
        if provider not in MIGRATABLE:
            items.append({"provider": provider, "action": "unsupported",
                          "reason": "not a single-key search provider; left in the legacy file"})
            continue
        single = _single_key(value)
        if single is None:
            items.append({"provider": provider, "action": "unsupported",
                          "reason": "multiple keys or a complex entry; left in the legacy file"})
            continue
        try:
            validated = validate_key(single)
        except ValueError:
            items.append({"provider": provider, "action": "unsupported",
                          "reason": "entry is not a valid single-line key; left in the legacy file"})
            continue
        try:
            existing = store.get(provider)
        except CredentialStoreError as exc:
            items.append({"provider": provider, "action": "blocked", "reason": str(exc)})
            continue
        if existing is None:
            action = "migrate"
        elif existing == validated:
            action = "already_current"
        else:
            action = "conflict"
        items.append({"provider": provider, "action": action, "preview": mask(validated)})
    migratable = [i["provider"] for i in items if i["action"] in ("migrate", "conflict")]
    skipped = [i["provider"] for i in items if i["action"] in ("unsupported", "blocked")]
    return {
        "items": items,
        "migratable": migratable,
        "skipped": skipped,
        # Advisory only: the migration never changes the source file or its mode.
        "warnings": _warnings(keys_file),
        "source_digest": _fingerprint(keys),
        "store_digest": _store_digest(store, MIGRATABLE),
    }


def _warnings(keys_file: Path) -> list[str]:
    from ..state.keys import keys_file_permission_warning

    warning = keys_file_permission_warning(keys_file)
    return [warning] if warning else []


def _has_plaintext(keys: dict[str, Any]) -> bool:
    """Whether the legacy file still contains any secret value after the migration."""
    for value in keys.values():
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(isinstance(item, str) and item.strip() for item in value):
            return True
        if isinstance(value, dict) and value.get("key"):
            return True
    return False


def _store_digest(store: CredentialStore, providers) -> str:
    import hashlib

    parts = []
    for provider in providers:
        try:
            value = store.get(provider)
        except CredentialStoreError:
            value = "<unreadable>"
        parts.append(f"{provider}={'' if value is None else hashlib.sha256(value.encode()).hexdigest()}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def plan_token(plan: dict[str, Any]) -> str:
    """Opaque token over both plan digests; it changes when either side changes.

    The CLI returns this instead of the raw digests; apply recomputes it from a
    fresh plan and refuses the request on mismatch. Kept in Core so the token
    contract is covered by unit tests independent of the CLI.
    """
    import hashlib

    raw = json.dumps({"s": plan["source_digest"], "t": plan["store_digest"]}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def apply_migration(
    keys_file: Path,
    store: CredentialStore,
    plan: dict[str, Any],
    *,
    approved: list[str],
    choices: dict[str, str],
) -> dict[str, Any]:
    """Write only approved, planned providers. Re-validates the source and the store first."""
    if _fingerprint(_read_keys_file(keys_file)) != plan["source_digest"]:
        raise MigrationError("legacy keys file changed since the preview; run the preview again")
    if _store_digest(store, MIGRATABLE) != plan["store_digest"]:
        raise MigrationError("credential store changed since the preview; run the preview again")

    by_provider = {i["provider"]: i for i in plan["items"]}
    keys = _read_keys_file(keys_file)
    for provider in approved:
        item = by_provider.get(provider)
        if item is None or item["action"] not in ("migrate", "conflict", "already_current"):
            raise MigrationError(f"{provider} is not migratable in this plan")
        if item["action"] == "conflict" and choices.get(provider) not in ("keep", "replace"):
            raise MigrationError(f"{provider} conflicts with the stored key; choose keep or replace")

    written: list[str] = []
    kept: list[str] = []
    failed: list[str] = []
    unchanged: list[str] = []
    for provider in approved:
        item = by_provider[provider]
        if item["action"] == "already_current":
            unchanged.append(provider)
            continue
        if item["action"] == "conflict" and choices[provider] == "keep":
            kept.append(provider)
            continue
        try:
            store.set(provider, _single_key(keys[provider]))
            written.append(provider)
        except (CredentialStoreError, ValueError):
            failed.append(provider)
    not_done = sorted(set(plan["skipped"]) | set(failed) | (set(plan["migratable"]) - set(approved)))
    return {
        "written": written,
        "kept": kept,
        "unchanged": unchanged,
        "failed": failed,
        "not_done": not_done,
        "complete": not failed and not not_done,
        # The source file is never modified or deleted by this module. Tell the
        # caller when it still holds plaintext so the UI can prompt for cleanup.
        "legacy_file": str(keys_file),
        "legacy_file_has_plaintext": _has_plaintext(keys),
        "warnings": _warnings(keys_file),
    }
