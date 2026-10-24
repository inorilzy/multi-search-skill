"""Shared auth and retry helpers for provider adapters."""
from __future__ import annotations

import re

# An HTTP status code only counts as a status code when its digits stand alone as
# a token, optionally after an explicit "HTTP"/"status"/"code" prefix. A bare
# substring match used to classify ordinary error text such as
# "content size 4032 exceeds ..." as ``invalid`` and "offset 4291" as
# ``rate_limit``, which put healthy keys into cooldown.
_STATUS_CODE_RE = re.compile(
    r"\b(?:http(?: status)?|status(?: code)?)?\s*(401|403|429)\b",
    re.IGNORECASE,
)

# Adapter-set error types that justify rotating to the next key.
KEY_RETRY_ERROR_TYPES = frozenset({"invalid", "quota_exhausted", "rate_limit"})

# Fallback text signals, used only when an adapter did not set ``error_type``.
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


def status_codes_in(text: str) -> set[int]:
    """Return the HTTP status codes that appear as standalone tokens in ``text``."""
    return {int(match.group(1)) for match in _STATUS_CODE_RE.finditer(str(text or ""))}


def classify_error(message: str, *, error_type: str = "") -> str:
    """Classify one provider error message, preferring an adapter-set type.

    Adapters that see a real HTTP response should set ``error_type`` explicitly;
    this heuristic is only the fallback for unstructured text.
    """
    if error_type:
        return error_type
    text = str(message or "").lower()
    if _MISSING_KEY_TEXT.search(text):
        return "missing_key"
    codes = status_codes_in(text)
    if codes & {401, 403} or any(token in text for token in _INVALID_KEY_TOKENS):
        return "invalid"
    if any(token in text for token in _QUOTA_TOKENS):
        return "quota_exhausted"
    if 429 in codes or any(token in text for token in _RATE_LIMIT_TOKENS):
        return "rate_limit"
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
        if row.get("error_origin") == "target":
            continue
        if row.get("error_type"):
            if row["error_type"] in KEY_RETRY_ERROR_TYPES:
                return True
            continue
        # Reuse the single classifier so the retry decision and the surfaced
        # ``error_type`` cannot disagree.
        if classify_error(str(row.get("error", ""))) in KEY_RETRY_ERROR_TYPES:
            return True
    return False
