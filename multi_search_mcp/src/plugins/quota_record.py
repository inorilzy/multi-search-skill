"""Passive quota observations recorded from successful search responses.

Brave and Stack Exchange expose their remaining quota only in a real search
response, so their searchers persist what they observed here. Balance adapters
read this file and never send a request of their own. Recording is best effort:
a missing, malformed or unwritable record file must never change a search
result.

Entries are keyed like the balance cache: ``plugin_id|key_fingerprint``. An
anonymous search (no key) uses the fixed ``anonymous`` fingerprint.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..state.key_state import key_fingerprint
from ..support.config import home_from_environment
from .base import BalanceReport
from .cache import _atomic_write, cache_key

logger = logging.getLogger(__name__)

QUOTA_FILE_NAME = "quota-records.json"
QUOTA_SCHEMA_VERSION = 1
ANONYMOUS_KEY_FINGERPRINT = "anonymous"
NO_RECORD_MESSAGE = "搜索一次后显示"

# Concurrent searches in one process must not lose each other's observation
# while replacing the shared record file.
_WRITE_LOCK = threading.Lock()


def default_quota_path(environ=None) -> Path:
    """Resolve ``~/.multi-search/quota-records.json`` at call time."""
    env = os.environ if environ is None else environ
    return (home_from_environment(env) or Path.home()) / ".multi-search" / QUOTA_FILE_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint_for(key: str) -> str:
    return key_fingerprint(key) if key else ANONYMOUS_KEY_FINGERPRINT


def _load_entries(path: Path) -> dict[str, dict[str, Any]]:
    """Read the record file; any read or parse failure is an empty record set."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    candidate = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(candidate, dict):
        return {}
    return {
        key: value for key, value in candidate.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def record_quota(plugin_id: str, key: str, report_fields: dict[str, Any]) -> None:
    """Record the latest quota observation for one plugin key.

    Failures are debug-logged and swallowed: a search must succeed even when
    the user's home directory is read-only.
    """
    try:
        fields = dict(report_fields or {})
        fetched_at = fields.pop("fetched_at", None)
        if not isinstance(fetched_at, str) or not fetched_at:
            fetched_at = _now_iso()
        fingerprint = _fingerprint_for(key)
        path = default_quota_path()
        with _WRITE_LOCK:
            entries = _load_entries(path)
            entries[cache_key(plugin_id, fingerprint)] = {
                "plugin": plugin_id,
                "key_fingerprint": fingerprint,
                "fetched_at": fetched_at,
                "report": fields,
            }
            _atomic_write(path, {"schema_version": QUOTA_SCHEMA_VERSION, "entries": entries})
    except Exception:  # noqa: BLE001 - quota recording must never affect search
        logger.debug("failed to record %s quota", plugin_id, exc_info=True)


def read_quota() -> dict[str, dict[str, Any]]:
    """Return all recorded entries keyed by ``plugin_id|key_fingerprint``."""
    try:
        return _load_entries(default_quota_path())
    except Exception:  # noqa: BLE001 - reading a best-effort record is never fatal
        logger.debug("failed to read quota records", exc_info=True)
        return {}


def quota_entry(plugin_id: str, key: str) -> dict[str, Any] | None:
    """Return one recorded entry for the plugin and credential."""
    entry = read_quota().get(cache_key(plugin_id, _fingerprint_for(key)))
    if not isinstance(entry, dict) or not isinstance(entry.get("report"), dict):
        return None
    return entry


def quota_report(plugin_id: str, key: str, *, unit: str, period: str) -> BalanceReport:
    """Build a balance report from a passive record, or explain it is missing."""
    entry = quota_entry(plugin_id, key)
    if entry is None:
        return BalanceReport(
            provider=plugin_id,
            status="unsupported",
            message=NO_RECORD_MESSAGE,
        )
    fields = entry["report"]
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at:
        fetched_at = _now_iso()
    scope = fields.get("scope")
    if not isinstance(scope, str) or scope not in {"key", "team", "account"}:
        scope = "key"
    observed_unit = fields.get("unit")
    if not isinstance(observed_unit, str) or observed_unit not in {"credits", "tokens", "searches", "usd", "requests"}:
        observed_unit = unit
    observed_period = fields.get("period")
    if not isinstance(observed_period, str) or not observed_period:
        observed_period = period
    return BalanceReport(
        provider=plugin_id,
        status="ok",
        scope=scope,
        unit=observed_unit,
        remaining=_number(fields.get("remaining")),
        limit=_number(fields.get("limit")),
        used=_number(fields.get("used")),
        resets_at=fields.get("resets_at") if isinstance(fields.get("resets_at"), str) else None,
        period=observed_period,
        key_fingerprint=entry.get("key_fingerprint") if isinstance(entry.get("key_fingerprint"), str) else None,
        message=fields.get("message") if isinstance(fields.get("message"), str) else "",
        fetched_at=fetched_at,
    )


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
