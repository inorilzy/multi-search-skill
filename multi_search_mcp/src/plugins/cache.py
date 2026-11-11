"""Persistent cache for provider balance reports.

Entries are keyed by plugin id and key fingerprint, live under the user's
``~/.multi-search`` directory, and expire on the plugin's declared
``balance_ttl_seconds``. Only ``ok`` reports are stored: an error is transient
evidence and must be refreshed, not replayed from disk. Reads and writes are
best effort so a read-only or corrupt cache can never fail a balance query; a
corrupt file is treated as empty and replaced atomically on the next save.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..support.config import home_from_environment
from .base import BalanceReport


CACHE_SCHEMA_VERSION = 1
CACHE_FILE_NAME = "balance-cache.json"
CACHE_FILE_MODE = 0o600


def default_cache_path(environ=None) -> Path:
    """Resolve ``~/.multi-search/balance-cache.json`` at call time.

    ``home_from_environment`` keeps the cache inside a test/desktop isolated
    ``HOME`` instead of using an import-time path.
    """
    env = os.environ if environ is None else environ
    return (home_from_environment(env) or Path.home()) / ".multi-search" / CACHE_FILE_NAME


def cache_key(plugin_id: str, key_fingerprint: str | None) -> str:
    """Stable cache identity; an anonymous plugin has an empty fingerprint part."""
    return f"{plugin_id}|{key_fingerprint or ''}"


def _now_epoch(now: Any) -> float:
    if now is None:
        return time.time()
    if isinstance(now, (int, float)):
        return float(now)
    if isinstance(now, datetime):
        moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    return float(now)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temporary, CACHE_FILE_MODE)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class BalanceCache:
    """One balance cache file, loaded lazily and written once per collection."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path is not None else default_cache_path()
        self._entries: dict[str, dict[str, Any]] | None = None
        self._dirty = False

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        entries: dict[str, dict[str, Any]] = {}
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raw = ""
        if raw:
            try:
                data = json.loads(raw)
                candidate = data.get("entries") if isinstance(data, dict) else None
                if isinstance(candidate, dict):
                    entries = {
                        key: value for key, value in candidate.items()
                        if isinstance(key, str) and isinstance(value, dict)
                    }
                else:
                    self._dirty = True
            except (TypeError, ValueError):
                # A corrupt cache is never fatal; rewrite it on the next flush.
                self._dirty = True
        self._entries = entries
        return entries

    def get(
        self,
        plugin_id: str,
        key_fingerprint: str | None,
        *,
        ttl_seconds: float,
        now: Any = None,
    ) -> list[BalanceReport] | None:
        entry = self._load().get(cache_key(plugin_id, key_fingerprint))
        if not isinstance(entry, dict):
            return None
        cached_at = entry.get("cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        ttl = max(0.0, float(ttl_seconds))
        if _now_epoch(now) - float(cached_at) >= ttl:
            return None
        data = entry.get("reports")
        if data is None:
            # Entries written before multi-report support held one report.
            data = [entry["report"]] if isinstance(entry.get("report"), dict) else None
        if not isinstance(data, list):
            return None
        known = {item.name for item in fields(BalanceReport)}
        reports = []
        for item in data:
            if not isinstance(item, dict):
                return None
            try:
                report = BalanceReport(**{key: value for key, value in item.items() if key in known})
            except (TypeError, ValueError):
                return None
            if report.status != "ok":
                return None
            reports.append(report)
        return reports or None

    def put(
        self,
        plugin_id: str,
        reports: BalanceReport | list[BalanceReport],
        *,
        ttl_seconds: float,
        now: Any = None,
    ) -> None:
        """Store only successful report sets; errors are fetched again next time."""
        items = [reports] if isinstance(reports, BalanceReport) else list(reports)
        if not items or any(report.status != "ok" for report in items):
            return
        entries = self._load()
        entries[cache_key(plugin_id, items[0].key_fingerprint)] = {
            "plugin": plugin_id,
            "key_fingerprint": items[0].key_fingerprint,
            "cached_at": _now_epoch(now),
            "ttl_seconds": max(0.0, float(ttl_seconds)),
            "reports": [report.to_dict() for report in items],
        }
        self._dirty = True

    def flush(self) -> None:
        """Atomically replace the cache file; a failed write is ignored."""
        if not self._dirty:
            return
        payload = {"schema_version": CACHE_SCHEMA_VERSION, "entries": self._load()}
        try:
            _atomic_write(self.path, payload)
        except OSError:
            return
        self._dirty = False
