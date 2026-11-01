"""Read one provider HTTP error into a classified, redacted error row.

Every adapter used to turn ``urllib.error.HTTPError`` into a bare string, so
the documented JSON error body (code, message, tag) and the ``Retry-After``
header were lost: 429 could not be told apart from an exhausted quota, and a
feature/site refusal (403) was treated as a bad key. Adapters now call
:func:`http_error_row` with their own status-to-kind table; the body and
retry hint are parsed once here.

Kinds follow ``support.models``: ``invalid``, ``quota_exhausted`` and
``rate_limit`` are credential signals; ``provider`` means the key is fine but
the request or plan was refused (feature not enabled, unsupported site);
``target`` means the requested page failed.
"""
from __future__ import annotations

import email.utils
import json
import time
import urllib.error
from typing import Any, Callable, Mapping

from .http import read_error_body
from .secrets import scrub_secrets

ERROR_BODY_LIMIT = 4096
# Upper bound on an honoured server wait, so a hostile header cannot park a key.
MAX_RETRY_AFTER_SECONDS = 24 * 3600


def parse_retry_after(value: Any, *, now: float | None = None) -> int | None:
    """Seconds to wait from a ``Retry-After`` value (delta seconds or HTTP date)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        seconds = when.timestamp() - (time.time() if now is None else now)
    if seconds != seconds or seconds < 0:  # NaN or past date
        return 0 if seconds == seconds else None
    return int(min(seconds, MAX_RETRY_AFTER_SECONDS) + 0.999)


def reset_epoch_wait(value: Any, *, now: float | None = None) -> int | None:
    """Seconds until an epoch-seconds reset header (e.g. ``x-ratelimit-reset``)."""
    try:
        reset = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    wait = reset - (time.time() if now is None else now)
    return max(0, int(min(wait, MAX_RETRY_AFTER_SECONDS) + 0.999))


def read_json_error(exc: urllib.error.HTTPError) -> tuple[Any, str]:
    """Return ``(parsed JSON or None, raw text)`` of a bounded error body."""
    raw = b""
    try:
        if exc.fp is not None:
            raw = read_error_body(exc, ERROR_BODY_LIMIT)
    except Exception:
        raw = b""
    finally:
        try:
            exc.close()
        except Exception:
            pass
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return None, ""
    try:
        return json.loads(text), text
    except (TypeError, ValueError):
        return None, text


def body_message(data: Any, raw: str) -> str:
    """Best human-readable message from common error body shapes."""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            parts = [error.get("code"), error.get("message") or error.get("detail")]
            text = " ".join(str(p) for p in parts if p)
            if text and error.get("ref_id"):
                text = f"{text} (ref_id {error['ref_id']})"
            if text:
                return text
        for key in ("message", "error_message", "detail", "error", "tag"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, (list, dict)) and value:
                return json.dumps(value, ensure_ascii=False)
    return raw


def http_error_row(
    source: str,
    exc: urllib.error.HTTPError,
    *,
    secret: str = "",
    kinds: Mapping[int, str] | None = None,
    refine: Callable[[int, Any, str], str | None] | None = None,
    prefix: str = "",
) -> dict:
    """Classified error row for one HTTP failure.

    ``kinds`` maps status codes to kinds; ``refine(status, body, message)`` may
    override that from the parsed body (e.g. a 402 that is a tier restriction,
    not an exhausted balance). Unknown statuses become ``error``. A
    ``retry_after`` (seconds) is attached whenever the server sent a hint.
    """
    data, raw = read_json_error(exc)
    status = int(getattr(exc, "code", 0) or 0)
    detail = body_message(data, raw) or str(exc.reason or exc)
    message = f"{prefix}HTTP {status}: {detail}"
    kind = (kinds or {}).get(status, "error")
    if refine is not None:
        kind = refine(status, data, detail) or kind
    row: dict[str, Any] = {
        "source": source,
        "error": scrub_secrets(message[:500], secret) if secret else message[:500],
        "kind": kind,
        "error_type": kind,
        "origin": "target" if kind == "target" else "provider",
        "error_origin": "target" if kind == "target" else "provider",
        "http_status": status,
    }
    headers = getattr(exc, "headers", None)
    retry_after = parse_retry_after(headers.get("Retry-After")) if headers is not None else None
    if retry_after is None and isinstance(data, dict):
        for key in ("retryAfter", "retry_after", "backoff"):
            if data.get(key) is not None:
                retry_after = parse_retry_after(data.get(key))
                break
    if retry_after is not None:
        row["retry_after"] = retry_after
    if kind == "rate_limit":
        row["rate_limited"] = True
    return row
