"""Provider key health tracking and state-aware key selection."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..support.auth import is_key_retryable_error
from .keys import key_pool
from ..support.secrets import scrub_secrets
from .state_store import StateStore


ACTIVE = "active"
COOLDOWN = "cooldown"
QUOTA_EXHAUSTED = "quota_exhausted"
INVALID = "invalid"
TRANSIENT_INVALID = "transient_invalid"
DISABLED = "disabled"

# Number of consecutive "invalid"-classified failures (e.g. transient 401/403)
# tolerated before a key is escalated to a permanent INVALID state.
INVALID_STRIKE_LIMIT = 3
# Cooldown applied to a transiently-invalid key before it is retried.
INVALID_COOLDOWN = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def key_id_for(provider: str, key: str) -> str:
    digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]
    return f"{provider}:{digest}"


def key_fingerprint(key: str) -> str:
    text = str(key)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    if len(text) >= 8:
        return f"{text[:4]}...{text[-4:]} ({digest})"
    return f"sha256:{digest}"


@dataclass
class KeyCandidate:
    key: str
    key_id: str
    fingerprint: str


@dataclass
class KeyOutcome:
    success: bool
    retryable: bool
    error_type: str = ""
    error_message: str = ""


class BasicKeyManager:
    """Compatibility key manager using the existing random key pool."""

    def candidates(self, provider: str, key_value: Any) -> list[KeyCandidate]:
        return [
            KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))
            for key in key_pool(key_value)
        ]

    def classify_result(self, provider: str, results: list | dict | None) -> KeyOutcome:
        rows = [results] if isinstance(results, dict) else list(results or [])
        error_rows = [row for row in rows if isinstance(row, dict) and row.get("error")]
        if not error_rows:
            return KeyOutcome(success=True, retryable=False)
        message = "; ".join(str(row.get("error", "")) for row in error_rows)
        return KeyOutcome(False, is_key_retryable_error(rows), classify_error(message), message)

    def record_result(self, provider: str, candidate: KeyCandidate, outcome: KeyOutcome) -> None:
        return None

    def record_use(self, provider: str, candidate: KeyCandidate) -> None:
        return None

    def status_rows(self, provider: str | None = None) -> list[dict]:
        return []

    def reset(self, provider: str | None = None, key_id: str | None = None) -> int:
        return 0


class SQLiteKeyManager(BasicKeyManager):
    """State-aware key manager backed by ``key_state``."""

    def __init__(self, store: StateStore | None = None):
        self.store = store or StateStore()

    def candidates(self, provider: str, key_value: Any) -> list[KeyCandidate]:
        raw = [
            KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))
            for key in _ordered_key_pool(key_value)
        ]
        now = _now()
        rows = {
            row["key_id"]: row
            for row in self.store.rows(
                "SELECT * FROM key_state WHERE provider = ?",
                (provider,),
            )
        }
        usable: list[tuple[int, str, str, KeyCandidate]] = []
        for order, cand in enumerate(raw):
            row = rows.get(cand.key_id)
            if not row:
                self._ensure_row(provider, cand)
                usable.append((0, "", f"{order:08d}", cand))
                continue
            status = row.get("status") or ACTIVE
            if row.get("manually_disabled") or status in {DISABLED, INVALID}:
                continue
            cooldown_until = _parse_iso(row.get("cooldown_until"))
            exhausted_until = _parse_iso(row.get("exhausted_until"))
            if status == COOLDOWN and cooldown_until and cooldown_until > now:
                continue
            if status == TRANSIENT_INVALID and cooldown_until and cooldown_until > now:
                continue
            if status == QUOTA_EXHAUSTED and exhausted_until and exhausted_until > now:
                continue
            last_used_at = row.get("last_used_at") or ""
            never_used = 0 if not last_used_at else 1
            usable.append((never_used, last_used_at, f"{order:08d}", cand))
        usable.sort(key=lambda item: (item[0], item[1], item[2]))
        return [cand for *_unused, cand in usable]

    def record_use(self, provider: str, candidate: KeyCandidate) -> None:
        self._ensure_row(provider, candidate)
        now = _iso()
        self.store.execute(
            """
            UPDATE key_state
            SET use_count = use_count + 1, last_used_at = ?, updated_at = ?
            WHERE provider = ? AND key_id = ?
            """,
            (now, now, provider, candidate.key_id),
        )

    def record_result(self, provider: str, candidate: KeyCandidate, outcome: KeyOutcome) -> None:
        self._ensure_row(provider, candidate)
        now = _iso()
        if outcome.success:
            self.store.execute(
                """
                UPDATE key_state
                SET status = ?, success_count = success_count + 1, last_success_at = ?,
                    last_error_type = NULL, last_error_message = NULL, cooldown_until = NULL,
                    invalid_strikes = 0, updated_at = ?
                WHERE provider = ? AND key_id = ?
                """,
                (ACTIVE, now, now, provider, candidate.key_id),
            )
            return
        error_type = outcome.error_type or classify_error(outcome.error_message)
        status = ACTIVE
        cooldown_until = None
        exhausted_until = None
        rate_inc = 0
        quota_inc = 0
        strike_assignment = "invalid_strikes = invalid_strikes"
        if error_type == "invalid":
            # A single 401/403 is often a transient upstream blip (Cloudflare,
            # gateway, brief rate misclassification). Cool the key down and only
            # escalate to a permanent INVALID after repeated consecutive hits.
            current_strikes = self._invalid_strikes(provider, candidate.key_id)
            new_strikes = current_strikes + 1
            strike_assignment = f"invalid_strikes = {int(new_strikes)}"
            if new_strikes >= INVALID_STRIKE_LIMIT:
                status = INVALID
            else:
                status = TRANSIENT_INVALID
                cooldown_until = _iso(_now() + INVALID_COOLDOWN)
        elif error_type == "rate_limit":
            status = COOLDOWN
            cooldown_until = _iso(_now() + timedelta(minutes=15))
            rate_inc = 1
        elif error_type == "quota_exhausted":
            status = QUOTA_EXHAUSTED
            exhausted_until = _iso(_now() + timedelta(hours=24))
            quota_inc = 1
        else:
            # Any other failure type breaks the consecutive-invalid streak.
            strike_assignment = "invalid_strikes = 0"
        self.store.execute(
            f"""
            UPDATE key_state
            SET status = ?, failure_count = failure_count + 1,
                rate_limit_count = rate_limit_count + ?, quota_error_count = quota_error_count + ?,
                last_failure_at = ?, last_error_type = ?, last_error_message = ?,
                cooldown_until = ?, exhausted_until = ?, {strike_assignment}, updated_at = ?
            WHERE provider = ? AND key_id = ?
            """,
            (
                status, rate_inc, quota_inc, now, error_type,
                scrub_secrets(outcome.error_message, candidate.key), cooldown_until,
                exhausted_until, now, provider, candidate.key_id,
            ),
        )

    def _invalid_strikes(self, provider: str, key_id: str) -> int:
        rows = self.store.rows(
            "SELECT invalid_strikes FROM key_state WHERE provider = ? AND key_id = ?",
            (provider, key_id),
        )
        if not rows:
            return 0
        value = rows[0].get("invalid_strikes")
        return int(value or 0)

    def status_rows(self, provider: str | None = None) -> list[dict]:
        if provider:
            return self.store.rows(
                "SELECT * FROM key_state WHERE provider = ? ORDER BY provider, key_fingerprint",
                (provider,),
            )
        return self.store.rows("SELECT * FROM key_state ORDER BY provider, key_fingerprint")

    def reset(self, provider: str | None = None, key_id: str | None = None) -> int:
        where = []
        params: list[Any] = []
        if provider:
            where.append("provider = ?")
            params.append(provider)
        if key_id:
            where.append("key_id = ?")
            params.append(key_id)
        sql = "UPDATE key_state SET status = ?, cooldown_until = NULL, exhausted_until = NULL, manually_disabled = 0, invalid_strikes = 0, updated_at = ?"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self.store.connect() as conn:
            cur = conn.execute(sql, (ACTIVE, _iso(), *params))
            return int(cur.rowcount or 0)

    def _ensure_row(self, provider: str, candidate: KeyCandidate) -> None:
        now = _iso()
        self.store.execute(
            """
            INSERT OR IGNORE INTO key_state (
                provider, key_id, key_fingerprint, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (provider, candidate.key_id, candidate.fingerprint, ACTIVE, now, now),
        )


def classify_error(message: str) -> str:
    text = str(message or "").lower()
    if any(token in text for token in ("invalid api", "invalid key", "unauthorized", "forbidden", "401", "403")):
        return "invalid"
    if any(token in text for token in ("quota", "credits", "billing", "payment", "insufficient", "exceeded your")):
        return "quota_exhausted"
    if any(token in text for token in ("429", "rate limit", "rate_limit", "too many requests", "limit exceeded")):
        return "rate_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(token in text for token in ("network", "connection", "dns", "ssl")):
        return "network"
    return "error"


def _ordered_key_pool(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]
