"""Provider key health tracking and state-aware key selection."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..support.auth import classify_error, is_key_retryable_error, row_kind, row_origin
from ..support.models import (
    ERROR_KIND_INVALID,
    ERROR_KIND_NETWORK,
    ERROR_KIND_QUOTA_EXHAUSTED,
    ERROR_KIND_RATE_LIMIT,
    ERROR_KIND_TARGET,
    ERROR_KIND_TIMEOUT,
    ERROR_ORIGIN_TARGET,
)
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


def summarize_status_rows(rows: list[dict]) -> list[dict]:
    """Return the public, non-secret summary rows used by search diagnostics."""
    return [{
        "provider": row.get("provider"),
        "key_id": row.get("key_id"),
        "fingerprint": row.get("key_fingerprint"),
        "status": row.get("status"),
        "last_error_type": row.get("last_error_type"),
        "cooldown_until": row.get("cooldown_until"),
        "exhausted_until": row.get("exhausted_until"),
    } for row in rows]


def key_fingerprint(key: str) -> str:
    """Irreversible short display identifier for a key; contains no key characters.

    The digest is the 8-hex prefix of the digest in :func:`key_id_for`, so rows
    written by older versions (``前4...后4 (sha8)``) can be rewritten from
    ``key_id`` alone; see ``StateStore._scrub_key_fingerprints``.
    """
    digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]
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
            for key in _ordered_key_pool(key_value)
        ]

    def classify_result(self, provider: str, results: list | dict | None) -> KeyOutcome:
        rows = [results] if isinstance(results, dict) else list(results or [])
        error_rows = [row for row in rows if isinstance(row, dict) and row.get("error")]
        if not error_rows:
            return KeyOutcome(success=True, retryable=False)
        message = "; ".join(str(row.get("error", "")) for row in error_rows)
        # Target failures carry no evidence that a provider credential failed.
        # ``row_origin``/``row_kind`` read the unified ``origin``/``kind`` keys and
        # fall back to the public ``error_origin``/``error_type`` row fields.
        error_rows = [row for row in error_rows if row_origin(row) != ERROR_ORIGIN_TARGET]
        if not error_rows:
            return KeyOutcome(False, False, ERROR_KIND_TARGET, message)
        error_types = [
            classify_error(str(row["error"]), kind=row_kind(row))
            for row in error_rows
        ]
        # Prefer the strongest credential signal; fall back to the first kind.
        error_type = next((
            kind for kind in (
                ERROR_KIND_INVALID, ERROR_KIND_QUOTA_EXHAUSTED, ERROR_KIND_RATE_LIMIT,
                ERROR_KIND_TIMEOUT, ERROR_KIND_NETWORK,
            )
            if kind in error_types
        ), error_types[0])
        return KeyOutcome(False, is_key_retryable_error(error_rows), error_type, message)

    def record_result(
        self, provider: str, candidate: KeyCandidate, outcome: KeyOutcome,
        *, started_at: datetime | None = None,
    ) -> None:
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
        # One connection and one transaction: the rows read here decide which
        # candidates are usable, and missing rows are registered on that same
        # snapshot instead of overwriting a concurrent writer's state.
        with self.store.transaction():
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

    def reserve(self, provider: str, candidates: list[KeyCandidate]) -> KeyCandidate | None:
        """Atomically choose the current LRU eligible candidate and record its use.

        This distributes attempts, not an exclusive lease: providers allow
        concurrent requests per credential. Health is re-checked under the write
        lock, so a key cooled by a concurrent writer since :meth:`candidates`
        is skipped instead of being retried.
        """
        now = _now()
        with self.store.transaction() as conn:
            usable = []
            for order, candidate in enumerate(candidates):
                self._ensure_row(provider, candidate)
                row = conn.execute(
                    "SELECT * FROM key_state WHERE provider = ? AND key_id = ?",
                    (provider, candidate.key_id),
                ).fetchone()
                if row["manually_disabled"] or row["status"] in {INVALID, DISABLED}:
                    continue
                until = _parse_iso(
                    row["exhausted_until"] if row["status"] == QUOTA_EXHAUSTED else row["cooldown_until"]
                )
                if row["status"] in {QUOTA_EXHAUSTED, COOLDOWN, TRANSIENT_INVALID} and until and until > now:
                    continue
                usable.append((row["last_used_at"] or "", order, candidate))
            if not usable:
                return None
            candidate = min(usable, key=lambda item: item[:2])[2]
            # Do not touch updated_at here: it is the credential-state
            # generation used to reject late results (see record_result).
            conn.execute(
                "UPDATE key_state SET use_count = use_count + 1, last_used_at = ? "
                "WHERE provider = ? AND key_id = ?",
                (_iso(now), provider, candidate.key_id),
            )
            return candidate

    def record_use(self, provider: str, candidate: KeyCandidate) -> None:
        # Registering the row and incrementing the counter are one write: no
        # second process can observe a registered key with no use recorded.
        # ``updated_at`` stays a state-generation marker, so use does not bump it.
        with self.store.transaction():
            self._ensure_row(provider, candidate)
            self.store.execute(
                """
                UPDATE key_state
                SET use_count = use_count + 1, last_used_at = ?
                WHERE provider = ? AND key_id = ?
                """,
                (_iso(), provider, candidate.key_id),
            )

    def record_result(
        self, provider: str, candidate: KeyCandidate, outcome: KeyOutcome,
        *, started_at: datetime | None = None,
    ) -> None:
        # Row registration, the read-modify-write decision (invalid strikes,
        # cooldown, quota) and the counters commit as one transaction. Two
        # processes can no longer interleave between the ensure-row write and the
        # outcome update, and a crash leaves no half-applied key health.
        with self.store.transaction():
            self._record_result(provider, candidate, outcome, started_at=started_at)

    def _record_result(
        self, provider: str, candidate: KeyCandidate, outcome: KeyOutcome,
        *, started_at: datetime | None = None,
    ) -> None:
        self._ensure_row(provider, candidate)
        now = _iso()
        if outcome.success:
            # Causality: ``updated_at`` marks the last status-affecting write.
            # A success may only clear a verdict that predates its own request;
            # a failure committed while this request was in flight is newer
            # evidence and must survive. Success counters still advance.
            started = _iso(started_at) if started_at is not None else now
            gated = "updated_at > ?"
            self.store.execute(
                f"""
                UPDATE key_state
                SET status = CASE WHEN {gated} THEN status ELSE ? END,
                    success_count = success_count + 1, last_success_at = ?,
                    last_error_type = CASE WHEN {gated} THEN last_error_type ELSE NULL END,
                    last_error_message = CASE WHEN {gated} THEN last_error_message ELSE NULL END,
                    cooldown_until = CASE WHEN {gated} THEN cooldown_until ELSE NULL END,
                    invalid_strikes = CASE WHEN {gated} THEN invalid_strikes ELSE 0 END,
                    updated_at = ?
                WHERE provider = ? AND key_id = ?
                """,
                (
                    started, ACTIVE, now,
                    started, started, started, started,
                    now, provider, candidate.key_id,
                ),
            )
            return
        error_type = outcome.error_type or classify_error(outcome.error_message)
        if error_type == ERROR_KIND_TARGET:
            # Target-page failures carry no credential-health evidence. The
            # scrape entry point normally filters these before this method;
            # keep the state boundary neutral if one reaches it directly.
            return
        message = scrub_secrets(outcome.error_message, candidate.key)
        if error_type not in {ERROR_KIND_INVALID, ERROR_KIND_RATE_LIMIT, ERROR_KIND_QUOTA_EXHAUSTED}:
            # Neutral failure (timeout/network/unclassified): record the failure
            # but keep the credential state and strikes untouched so a transient
            # error cannot clear a stronger concurrent verdict. ``updated_at`` is
            # not advanced: a neutral error is not a state verdict and must not
            # block a causally-newer success from recovering the key.
            self.store.execute(
                """
                UPDATE key_state
                SET failure_count = failure_count + 1,
                    last_failure_at = ?, last_error_type = ?, last_error_message = ?
                WHERE provider = ? AND key_id = ?
                """,
                (now, error_type, message, provider, candidate.key_id),
            )
            return
        cooldown_until = None
        exhausted_until = None
        rate_inc = 0
        quota_inc = 0
        # Every credential verdict other than an invalid authentication failure
        # breaks the consecutive-invalid streak. The invalid branch below
        # replaces this with an atomic increment.
        strike_assignment = "invalid_strikes = 0"
        # Failure updates never downgrade a stronger stored verdict:
        # invalid > quota_exhausted > cooldown/transient_invalid. All CASE
        # expressions read the same pre-update row, so concurrent outcomes
        # settle in commit order without a lost update.
        stronger = "status IN ('invalid', 'quota_exhausted', 'disabled')"
        # A kept stronger verdict also keeps its own expiry: clearing
        # ``exhausted_until`` under a retained ``quota_exhausted`` status would
        # make the key eligible again immediately.
        exhausted_sql = f"CASE WHEN {stronger} THEN exhausted_until ELSE ? END"
        if error_type == ERROR_KIND_INVALID:
            # A single 401/403 is often a transient upstream blip (Cloudflare,
            # gateway, brief rate misclassification). Cool the key down and only
            # escalate to a permanent INVALID after repeated consecutive hits.
            strike_assignment = "invalid_strikes = invalid_strikes + 1"
            status_sql = (
                f"CASE WHEN {stronger} THEN status "
                f"WHEN invalid_strikes + 1 >= {INVALID_STRIKE_LIMIT} "
                f"THEN '{INVALID}' ELSE ? END"
            )
            cooldown_sql = (
                f"CASE WHEN {stronger} THEN cooldown_until "
                f"WHEN invalid_strikes + 1 >= {INVALID_STRIKE_LIMIT} "
                "THEN NULL ELSE ? END"
            )
            status = TRANSIENT_INVALID
            cooldown_until = _iso(_now() + INVALID_COOLDOWN)
        elif error_type == ERROR_KIND_RATE_LIMIT:
            status = COOLDOWN
            cooldown_until = _iso(_now() + timedelta(minutes=15))
            rate_inc = 1
            status_sql = f"CASE WHEN {stronger} THEN status ELSE ? END"
            cooldown_sql = f"CASE WHEN {stronger} THEN cooldown_until ELSE ? END"
        else:  # quota_exhausted
            status = QUOTA_EXHAUSTED
            exhausted_until = _iso(_now() + timedelta(hours=24))
            quota_inc = 1
            status_sql = "CASE WHEN status IN ('invalid', 'disabled') THEN status ELSE ? END"
            cooldown_sql = "?"
            exhausted_sql = "CASE WHEN status IN ('invalid', 'disabled') THEN exhausted_until ELSE ? END"
        self.store.execute(
            f"""
            UPDATE key_state
            SET status = {status_sql}, failure_count = failure_count + 1,
                rate_limit_count = rate_limit_count + ?, quota_error_count = quota_error_count + ?,
                last_failure_at = ?, last_error_type = ?, last_error_message = ?,
                cooldown_until = {cooldown_sql}, exhausted_until = {exhausted_sql},
                {strike_assignment}, updated_at = ?
            WHERE provider = ? AND key_id = ?
            """,
            (
                status, rate_inc, quota_inc, now, error_type, message,
                cooldown_until, exhausted_until, now, provider, candidate.key_id,
            ),
        )

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
        # A health reset never clears a manual opt-out (``manually_disabled``).
        sql = "UPDATE key_state SET status = ?, cooldown_until = NULL, exhausted_until = NULL, invalid_strikes = 0, updated_at = ?"
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


# ``classify_error`` lives in ``support.auth`` so key health, adapter retries,
# and the CLI's ``provider_status`` all share one classification rule. It is
# re-exported here because ``service`` and tests import it from this module.


def _ordered_key_pool(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]
