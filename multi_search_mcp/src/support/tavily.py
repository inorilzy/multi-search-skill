"""Tavily-specific HTTP error details and status classification."""
from __future__ import annotations

import json
import urllib.error

from .secrets import scrub_secrets


_TAVILY_ERROR_BODY_LIMIT = 4096
_TAVILY_HTTP_ERROR_TYPES = {
    401: "invalid",
    403: "invalid",
    429: "rate_limit",
    432: "quota_exhausted",
    433: "quota_exhausted",
}


def _error_body_text(raw: bytes) -> str:
    text = raw[:_TAVILY_ERROR_BODY_LIMIT].decode("utf-8", "replace")
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return text
    if not isinstance(payload, dict):
        return text
    detail = payload.get("detail")
    if isinstance(detail, dict):
        detail = detail.get("error") or detail.get("message")
    detail = detail or payload.get("message") or payload.get("error")
    if isinstance(detail, (dict, list)):
        return json.dumps(detail, ensure_ascii=False)
    return str(detail) if detail else text


def tavily_http_error(exc: urllib.error.HTTPError, api_key: str = "") -> tuple[str, str]:
    """Return a bounded, redacted message and status-driven error type."""
    body = ""
    body_diagnostic = ""
    if exc.fp is not None:
        try:
            body = _error_body_text(exc.read(_TAVILY_ERROR_BODY_LIMIT))
        except Exception as read_error:
            body_diagnostic = f"error body unavailable ({type(read_error).__name__})"
        finally:
            try:
                exc.close()
            except Exception as close_error:
                body_diagnostic = body_diagnostic or (
                    f"error body close failed ({type(close_error).__name__})"
                )

    code = exc.code
    fallback = str(exc) or f"HTTP Error {code}"
    message = f"HTTP Error {code}: {body}" if body else fallback
    if body_diagnostic:
        message = f"{message}; {body_diagnostic}"
    return scrub_secrets(message, api_key), _TAVILY_HTTP_ERROR_TYPES.get(code, "error")
