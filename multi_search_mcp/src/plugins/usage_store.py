"""Best-effort local usage history; no credentials, network or state migrations.

Interface for balance collection, search/scrape recording and the usage CLI:

* ``append_balance(report: BalanceReport, *, path=None, now=None) -> None``
  appends only an ``ok`` report. Call only for a fresh observation, not a cache
  hit. Identity is (provider, key_fingerprint, scope, unit, fetched_at); the
  first observation wins, including when the fingerprint is None.
* ``record_call(provider: str, purpose: Literal["search", "scrape"], *,
  failed=False, path=None, now=None) -> None`` counts one actual attempt, plus
  one failure when failed=True. Provider is the plugin id, not a search source
  or scrape channel. Callers own skipped/cache-hit/--no-state decisions.
* ``read_usage(provider: str | None = None, *, days=30, path=None, now=None)
  -> UsageSnapshot`` reads both tables in one snapshot. None selects all
  providers; days must be an integer in 1..USAGE_RETENTION_DAYS (ValueError
  otherwise). ``history`` contains dicts with exactly the balance_history
  columns below, ordered by fetched_at/provider/fingerprint/scope/unit;
  ``daily`` contains day/provider/purpose/calls/failures dicts ordered by
  day/provider/purpose. No zero-filled days or aggregates are synthesized.
  Missing files yield empty lists and usage_error=None; corrupt, incompatible
  or unreadable files yield empty lists and usage_error="unreadable". Reads
  never create, repair, chmod or prune the database.

``path`` is an optional str/Path for an isolated store; the default is resolved
at each call through home_from_environment. ``now`` is an optional datetime;
naive values use local time. Daily buckets use the machine's local date, even
when now has another timezone. Balance timestamps accept ISO8601 (naive means
UTC) and are stored as UTC ISO8601 with microseconds. Balance reads span
[now - days, now]; daily reads include today and the preceding days - 1 dates.
Each write prunes both tables using these same 30-day lower bounds, including
when its observation is a duplicate. Unknown numbers stay NULL. Only existing
sha256:xxxxxxxx fingerprints, None and the passive-quota "anonymous" sentinel
are accepted. Non-ISO reset times and unknown periods become None; supported
periods are minute/hour/day/week/month/year. Invalid identities are discarded.

Design decisions (T01): keep a separate SQLite file rather than reuse StateStore
and its versioned schema, so old CLIs retain access to state.sqlite. Reuse
BalanceReport rather than invent a parallel input model; explicitly project its
fields instead of serializing messages or response metadata. A single read
result keeps the error flag and both datasets consistent, rather than mutable
last-error state or independent reads. Use SQL UPSERT and WAL with a 100 ms
busy timeout, not a process-local lock or retries that delay searches. Each
operation owns/closes its connection. Failed writes are discarded and logged
at debug with no payload or exception text. Existing files are checked before
any mutation; automatic replacement/recovery is deliberately excluded. Retain
rolling balance instants but local calendar call buckets: rolling instants
cannot describe a partly expired daily aggregate accurately.
"""
from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from ..support.config import home_from_environment
from .base import BalanceReport

logger = logging.getLogger(__name__)

USAGE_RETENTION_DAYS = 30
USAGE_FILE_NAME = "usage.sqlite"
USAGE_FILE_MODE = 0o600
BUSY_TIMEOUT_SECONDS = 0.1

_HISTORY_COLUMNS = 'provider, key_fingerprint, scope, unit, remaining, "limit", used, resets_at, period, fetched_at'
_DAILY_COLUMNS = "day, provider, purpose, calls, failures"
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS balance_history (
        provider TEXT NOT NULL,
        key_fingerprint TEXT,
        scope TEXT NOT NULL,
        unit TEXT NOT NULL,
        remaining REAL,
        "limit" REAL,
        used REAL,
        resets_at TEXT,
        period TEXT,
        fetched_at TEXT NOT NULL
    )""",
    # SQLite UNIQUE treats NULLs as distinct; anonymous reports must deduplicate.
    """CREATE UNIQUE INDEX IF NOT EXISTS balance_history_identity
       ON balance_history(provider, COALESCE(key_fingerprint, ''), scope, unit, fetched_at)""",
    "CREATE INDEX IF NOT EXISTS balance_history_time ON balance_history(fetched_at)",
    """CREATE TABLE IF NOT EXISTS call_daily (
        day TEXT NOT NULL,
        provider TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK (purpose IN ('search', 'scrape')),
        calls INTEGER NOT NULL,
        failures INTEGER NOT NULL,
        PRIMARY KEY (day, provider, purpose)
    )""",
)


@dataclass(frozen=True)
class UsageSnapshot:
    """Detached JSON-compatible rows, plus a non-sensitive storage error flag."""

    history: list[dict[str, Any]] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)
    usage_error: str | None = None


def default_usage_path(environ=None) -> Path:
    """Resolve the shared home contract at call time, including isolated HOME."""
    env = os.environ if environ is None else environ
    return (home_from_environment(env) or Path.home()) / ".multi-search" / USAGE_FILE_NAME


def _timestamp(value: str) -> str:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _window(now: datetime | None, days: int) -> tuple[str, str, str, str]:
    moment = (now or datetime.now().astimezone()).astimezone(timezone.utc)
    today = moment.astimezone().date()
    return (
        (moment - timedelta(days=days)).isoformat(timespec="microseconds"),
        moment.isoformat(timespec="microseconds"),
        (today - timedelta(days=days - 1)).isoformat(),
        today.isoformat(),
    )


def _check_database(conn: sqlite3.Connection) -> None:
    if [row[0] for row in conn.execute("PRAGMA quick_check")] != ["ok"]:
        raise sqlite3.DatabaseError("invalid usage database")
    conn.execute(f"SELECT {_HISTORY_COLUMNS} FROM balance_history LIMIT 0")
    conn.execute(f"SELECT {_DAILY_COLUMNS} FROM call_daily LIMIT 0")


def _write(statement: str, parameters: tuple, *, path, now) -> None:
    try:
        history_start, _, first_day, _ = _window(now, USAGE_RETENTION_DAYS)
        target = Path(path).expanduser() if path is not None else default_usage_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, USAGE_FILE_MODE)
        except FileExistsError:
            created = False
        else:
            os.close(descriptor)
            created = True
        with closing(sqlite3.connect(
            target.absolute().as_uri() + "?mode=rw", uri=True, timeout=BUSY_TIMEOUT_SECONDS,
        )) as conn:
            if not created:
                _check_database(conn)
            if os.name == "posix":
                target.chmod(USAGE_FILE_MODE)
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                for schema in _SCHEMA:
                    conn.execute(schema)
                conn.execute(statement, parameters)
                conn.execute("DELETE FROM balance_history WHERE fetched_at < ?", (history_start,))
                conn.execute("DELETE FROM call_daily WHERE day < ?", (first_day,))
    except Exception:  # noqa: BLE001 - usage must never fail a search or balance query
        logger.debug("failed to write usage data")


def append_balance(
    report: BalanceReport, *, path: str | Path | None = None, now: datetime | None = None,
) -> None:
    """Append a fresh successful observation; see the module's interface contract."""
    try:
        if report.status != "ok":
            return
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", report.provider):
            raise ValueError("invalid plugin id")
        fingerprint = report.key_fingerprint
        if fingerprint not in (None, "anonymous") and not re.fullmatch(r"sha256:[0-9a-f]{8}", fingerprint):
            raise ValueError("invalid fingerprint")
        if report.scope not in {"key", "team", "account"} or report.unit not in {
            "credits", "tokens", "searches", "usd", "requests",
        }:
            raise ValueError("invalid balance identity")
        numbers = tuple(
            value if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) else None
            for value in (report.remaining, report.limit, report.used)
        )
        try:
            resets_at = _timestamp(report.resets_at) if report.resets_at else None
        except (AttributeError, TypeError, ValueError):
            resets_at = None
        period = report.period if report.period in {"minute", "hour", "day", "week", "month", "year"} else None
        values = (
            report.provider, fingerprint, report.scope, report.unit, *numbers,
            resets_at, period, _timestamp(report.fetched_at),
        )
        _write(
            f"INSERT OR IGNORE INTO balance_history ({_HISTORY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values, path=path, now=now,
        )
    except Exception:  # noqa: BLE001 - invalid telemetry must not affect the caller
        logger.debug("failed to append usage balance")


def record_call(
    provider: str, purpose: Literal["search", "scrape"], *, failed: bool = False,
    path: str | Path | None = None, now: datetime | None = None,
) -> None:
    """Count one attempt under its plugin id and local calendar day."""
    try:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", provider):
            raise ValueError("invalid plugin id")
        if purpose not in {"search", "scrape"} or not isinstance(failed, bool):
            raise ValueError("invalid call outcome")
        # Capture the clock once, so the row and retention agree across midnight.
        moment = now or datetime.now().astimezone()
        day = moment.astimezone().date().isoformat()
        _write(
            """INSERT INTO call_daily (day, provider, purpose, calls, failures)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(day, provider, purpose) DO UPDATE SET
               calls = calls + 1, failures = failures + excluded.failures""",
            (day, provider, purpose, int(failed)), path=path, now=moment,
        )
    except Exception:  # noqa: BLE001 - usage must never fail a search or scrape
        logger.debug("failed to record usage call")


def read_usage(
    provider: str | None = None, *, days: int = USAGE_RETENTION_DAYS,
    path: str | Path | None = None, now: datetime | None = None,
) -> UsageSnapshot:
    """Read chronological history and daily buckets without changing stored data."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= USAGE_RETENTION_DAYS:
        raise ValueError(f"days must be between 1 and {USAGE_RETENTION_DAYS}")
    try:
        history_start, history_end, first_day, today = _window(now, days)
        target = Path(path).expanduser() if path is not None else default_usage_path()
        try:
            target.stat()
        except FileNotFoundError:
            return UsageSnapshot()
        with closing(sqlite3.connect(
            target.absolute().as_uri() + "?mode=ro", uri=True, timeout=BUSY_TIMEOUT_SECONDS,
        )) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            _check_database(conn)
            provider_filter = " AND provider = ?" if provider is not None else ""
            provider_args = (provider,) if provider is not None else ()
            history = conn.execute(
                f"SELECT {_HISTORY_COLUMNS} FROM balance_history WHERE fetched_at >= ? AND fetched_at <= ?"
                + provider_filter + " ORDER BY fetched_at, provider, key_fingerprint, scope, unit",
                (history_start, history_end, *provider_args),
            )
            history_rows = [dict(row) for row in history]
            daily = conn.execute(
                f"SELECT {_DAILY_COLUMNS} FROM call_daily WHERE day >= ? AND day <= ?"
                + provider_filter + " ORDER BY day, provider, purpose",
                (first_day, today, *provider_args),
            )
            return UsageSnapshot(history=history_rows, daily=[dict(row) for row in daily])
    except Exception:  # noqa: BLE001 - callers surface the stable error flag, not SQLite details
        logger.debug("failed to read usage data")
        return UsageSnapshot(usage_error="unreadable")
