"""Small helpers for redacting secrets from user-visible errors."""
from __future__ import annotations

import re
from collections.abc import Iterable


_QUERY_SECRET_RE = re.compile(r"((?:api[_-]?key|apikey|key|token|auth_token|ct0)=)[^&\s]+", re.I)
_HEADER_SECRET_RE = re.compile(
    r"((?:authorization|x-api-key|x-subscription-token)\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+",
    re.I,
)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I)


def _iter_secret_strings(values) -> Iterable[str]:
    if values is None:
        return
    if isinstance(values, dict):
        for value in values.values():
            yield from _iter_secret_strings(value)
        return
    if isinstance(values, (list, tuple, set)):
        for value in values:
            yield from _iter_secret_strings(value)
        return
    text = str(values)
    if len(text) >= 4:
        yield text


def scrub_secrets(message, secrets=(), limit: int = 300) -> str:
    """Redact likely API keys/tokens from an exception or provider message."""
    text = str(message or "")
    text = _HEADER_SECRET_RE.sub(r"\1<redacted>", text)
    text = _BEARER_RE.sub(r"\1<redacted>", text)
    text = _QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    for secret in sorted(set(_iter_secret_strings(secrets)), key=len, reverse=True):
        text = text.replace(secret, "<redacted>")
    return text[:limit]
