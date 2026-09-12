"""Shared auth and retry helpers for provider adapters."""
from __future__ import annotations


KEY_RETRY_PATTERNS = (
    "401", "403", "429", "unauthorized", "forbidden", "invalid api",
    "invalid key", "api key expired", "api key disabled", "api key revoked",
    "expired api key", "quota", "rate limit", "rate_limit",
    "too many requests", "limit exceeded", "exceeded your", "credits",
    "billing", "payment", "insufficient",
)

KEY_RETRY_ERROR_TYPES = frozenset({"invalid", "quota_exhausted", "rate_limit"})


def is_key_retryable_error(results: list | dict | None) -> bool:
    """Return True when provider rows indicate a key/quota/rate-limit failure."""
    if not results:
        return False
    rows = [results] if isinstance(results, dict) else list(results)
    error_rows = [row for row in rows if isinstance(row, dict) and "error" in row]
    if not error_rows:
        return False
    for row in error_rows:
        if row.get("error_origin") == "target":
            continue
        if row.get("error_type"):
            if row["error_type"] in KEY_RETRY_ERROR_TYPES:
                return True
            continue
        msg = str(row.get("error", "")).lower()
        if any(pattern in msg for pattern in KEY_RETRY_PATTERNS):
            return True
    return False
