"""Shared auth and retry helpers for provider adapters."""
from __future__ import annotations

from .models import (
    ERROR_KIND_QUOTA_EXHAUSTED,
    ERROR_KIND_RATE_LIMIT,
    ERROR_KIND_INVALID,
    ERROR_KIND_TARGET,
    ERROR_ORIGIN_TARGET,
)


# Legacy free-text patterns; only used when a row lacks a structured ``kind``.
KEY_RETRY_PATTERNS = (
    "401", "403", "429", "unauthorized", "forbidden", "invalid api",
    "invalid key", "api key expired", "api key disabled", "api key revoked",
    "expired api key", "quota", "rate limit", "rate_limit",
    "too many requests", "limit exceeded", "exceeded your", "credits",
    "billing", "payment", "insufficient",
)

# Kinds meaning "the credential itself is implicated"; rotation may recover.
KEY_RETRY_ERROR_KINDS = frozenset({
    ERROR_KIND_INVALID,
    ERROR_KIND_QUOTA_EXHAUSTED,
    ERROR_KIND_RATE_LIMIT,
})

# Backwards-compat alias for callers still using the pre-kind name.
KEY_RETRY_ERROR_TYPES = KEY_RETRY_ERROR_KINDS


def row_kind(row: dict) -> str:
    """Best-effort kind for an error row.

    ``kind`` is the single unified field. ``error_type`` is accepted as a
    transitional alias so pre-kind rows still classify; both are absent only
    for unclassified internal errors, which never signal key health.
    """
    if not isinstance(row, dict):
        return ""
    kind = row.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    legacy = row.get("error_type")
    if isinstance(legacy, str) and legacy:
        return legacy
    # Legacy boolean flags that predated structured kind.
    if row.get("key_exhausted") or row.get("exhausted"):
        return ERROR_KIND_QUOTA_EXHAUSTED
    if row.get("rate_limited"):
        return ERROR_KIND_RATE_LIMIT
    return ""


def row_origin(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    origin = row.get("origin")
    if isinstance(origin, str) and origin:
        return origin
    legacy = row.get("error_origin")
    if isinstance(legacy, str) and legacy:
        return legacy
    if row_kind(row) == ERROR_KIND_TARGET:
        return ERROR_ORIGIN_TARGET
    return ""


def is_key_retryable_error(results: list | dict | None) -> bool:
    """Return True when provider rows indicate a key/quota/rate-limit failure."""
    if not results:
        return False
    rows = [results] if isinstance(results, dict) else list(results)
    error_rows = [row for row in rows if isinstance(row, dict) and "error" in row]
    if not error_rows:
        return False
    for row in error_rows:
        if row_origin(row) == ERROR_ORIGIN_TARGET:
            continue
        kind = row_kind(row)
        if kind:
            if kind in KEY_RETRY_ERROR_KINDS:
                return True
            continue
        # Fallback when no structured classification exists.
        msg = str(row.get("error", "")).lower()
        if any(pattern in msg for pattern in KEY_RETRY_PATTERNS):
            return True
    return False
