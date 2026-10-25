"""Shared auth and retry helpers for provider adapters."""
from __future__ import annotations

import re

from .models import (
    ERROR_KIND_INVALID,
    ERROR_KIND_QUOTA_EXHAUSTED,
    ERROR_KIND_RATE_LIMIT,
    ERROR_KIND_TARGET,
    ERROR_ORIGIN_TARGET,
)

# An HTTP status code only counts as a status code when its digits stand alone as
# a token, optionally after an explicit "HTTP"/"status"/"code" prefix. A bare
# substring match used to classify ordinary error text such as
# "content size 4032 exceeds ..." as ``invalid`` and "offset 4291" as
# ``rate_limit``, which put healthy keys into cooldown.
_STATUS_CODE_RE = re.compile(
    r"\b(?:http(?: status)?|status(?: code)?)?\s*(401|403|429)\b",
    re.IGNORECASE,
)

# Fallback text signals, used only when an adapter did not set ``kind``.
# Every signal is a phrase, never a bare status-code digit string; numeric codes
# are handled by ``_STATUS_CODE_RE`` above.
_MISSING_KEY_TEXT = re.compile(
    r"\bmissing\b[^.;\n]{0,64}api[ _-]?key\b"
    r"|\bno api[ _-]?key\b"
    r"|\bapi[ _-]?key (?:is )?not (?:set|configured)\b",
    re.IGNORECASE,
)
_INVALID_KEY_TOKENS = (
    "invalid api", "invalid key", "api key expired", "api key disabled",
    "api key revoked", "expired api key", "unauthorized", "forbidden",
)
_QUOTA_TOKENS = (
    "quota", "credits", "billing", "payment", "insufficient", "exceeded your",
)
_RATE_LIMIT_TOKENS = (
    "rate limit", "rate_limit", "too many requests", "limit exceeded",
)
_TIMEOUT_TOKENS = ("timeout", "timed out")
_NETWORK_TOKENS = ("network", "connection", "dns", "ssl")

# Kept for callers that introspect the historical pattern list. The retry
# decision itself uses :func:`classify_error`, never a bare substring scan.
KEY_RETRY_PATTERNS = (
    "401", "403", "429", *_INVALID_KEY_TOKENS, *_QUOTA_TOKENS,
    *_RATE_LIMIT_TOKENS,
)

# Kinds meaning "the credential itself is implicated"; rotation may recover.
KEY_RETRY_ERROR_KINDS = frozenset({
    ERROR_KIND_INVALID,
    ERROR_KIND_QUOTA_EXHAUSTED,
    ERROR_KIND_RATE_LIMIT,
})

# Backwards-compat alias for callers still using the pre-kind name.
KEY_RETRY_ERROR_TYPES = KEY_RETRY_ERROR_KINDS


def status_codes_in(text: str) -> set[int]:
    """Return the HTTP status codes that appear as standalone tokens in ``text``."""
    return {int(match.group(1)) for match in _STATUS_CODE_RE.finditer(str(text or ""))}


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


def classify_error(message: str, *, error_type: str = "", kind: str = "") -> str:
    """Classify one provider error message, preferring an adapter-set kind/type.

    Adapters that see a real HTTP response should set ``kind`` (preferred) or
    ``error_type`` explicitly; this heuristic is only the fallback for
    unstructured text.
    """
    declared = kind or error_type
    if declared:
        return declared
    text = str(message or "").lower()
    if _MISSING_KEY_TEXT.search(text):
        return "missing_key"
    codes = status_codes_in(text)
    if codes & {401, 403} or any(token in text for token in _INVALID_KEY_TOKENS):
        return ERROR_KIND_INVALID
    if any(token in text for token in _QUOTA_TOKENS):
        return ERROR_KIND_QUOTA_EXHAUSTED
    if 429 in codes or any(token in text for token in _RATE_LIMIT_TOKENS):
        return ERROR_KIND_RATE_LIMIT
    if any(token in text for token in _TIMEOUT_TOKENS):
        return "timeout"
    if any(token in text for token in _NETWORK_TOKENS):
        return "network"
    return "error"


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
        if classify_error(str(row.get("error", ""))) in KEY_RETRY_ERROR_KINDS:
            return True
    return False
