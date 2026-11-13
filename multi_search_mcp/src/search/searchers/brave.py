"""Brave Search API."""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ...plugins.quota_record import record_quota
from ...support.http import decompress_limited, read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.query_limits import limit_query
from ...support.secrets import scrub_secrets

# docs/brave/api-reference-web-search.md: q <= 600 chars and 75 words.
BRAVE_QUERY_MAX_CHARS = 600
BRAVE_QUERY_MAX_WORDS = 75
# docs/brave/authentication.md, rate-limiting.md
_BRAVE_HTTP_ERROR_KINDS = {401: "invalid", 403: "invalid", 429: "rate_limit"}

logger = logging.getLogger(__name__)


def _header_value(headers, name: str):
    """Read a response header from urllib or a plain mapping, case-insensitively."""
    if headers is None:
        return None
    try:
        value = headers.get(name)
        if value is not None:
            return value
        for key, candidate in headers.items():
            if str(key).lower() == name.lower():
                return candidate
    except (AttributeError, TypeError):
        return None
    return None


def _second_csv_number(value) -> int | None:
    """Read the monthly value from a ``<per-second>, <monthly>`` header."""
    if not isinstance(value, str):
        return None
    parts = value.split(",")
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[1].strip()))
    except (TypeError, ValueError):
        return None


def _first_csv_number(value) -> int | None:
    """Read the per-second value from a ``<per-second>, <monthly>`` header."""
    if not isinstance(value, str):
        return None
    try:
        return int(float(value.split(",")[0].strip()))
    except (TypeError, ValueError):
        return None


def _record_brave_quota(api_key: str, headers) -> None:
    """Persist the monthly quota advertised by a successful response."""
    try:
        remaining = _second_csv_number(_header_value(headers, "X-RateLimit-Remaining"))
        limit = _second_csv_number(_header_value(headers, "X-RateLimit-Limit"))
        reset = _second_csv_number(_header_value(headers, "X-RateLimit-Reset"))
        if remaining is None or limit is None:
            return
        resets_at = None
        if reset is not None:
            # The reset value is seconds until the monthly window resets.
            resets_at = (datetime.now(timezone.utc) + timedelta(seconds=max(0, reset))).isoformat()
        if limit == 0:
            # The prepaid credit plan has no monthly request cap; see plugins/builtin/brave.py.
            # This search is counted only after it returns, so add it here.
            from ...plugins.builtin.brave import credit_fields

            per_second = _first_csv_number(_header_value(headers, "X-RateLimit-Limit"))
            fields = credit_fields(per_second, resets_at, extra_calls=1)
        else:
            fields = {"remaining": remaining, "limit": limit, "unit": "requests", "period": "month"}
            if resets_at:
                fields["resets_at"] = resets_at
        record_quota("brave", api_key, fields)
    except Exception:  # noqa: BLE001 - quota observation must never affect search
        logger.debug("failed to read Brave quota headers", exc_info=True)


def search_brave(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 15,
    search_depth: str = "normal",
    deadline: float | None = None,
) -> list:
    """Call Brave Search API.
    Uses extra_snippets=true: returns up to 5 additional excerpts per result (free, no extra cost).
    """
    query, notes = limit_query(
        "brave", query, max_chars=BRAVE_QUERY_MAX_CHARS, max_words=BRAVE_QUERY_MAX_WORDS,
    )
    depth = (search_depth or "normal").lower()
    extra_snippets = "false" if depth == "fast" else "true"
    url = (
        "https://api.search.brave.com/res/v1/web/search?"
        + urllib.parse.urlencode({"q": query, "count": count, "extra_snippets": extra_snippets})
    )
    req = urllib.request.Request(
        url,
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urlopen_retry(req, timeout=timeout, deadline=deadline) as resp:
            raw = read_limited(resp)
            if (resp.headers.get("Content-Encoding") or "").strip().lower() == "gzip":
                raw = decompress_limited(raw, "gzip")
            data = json.loads(raw)
            response_headers = resp.headers
    except urllib.error.HTTPError as e:
        row = http_error_row("brave", e, secret=api_key, kinds=_BRAVE_HTTP_ERROR_KINDS)
        reset = (e.headers.get("X-RateLimit-Reset") or "") if e.headers is not None else ""
        if "retry_after" not in row and reset:
            # Comma-separated per-window resets in seconds; the first is the 1s window.
            try:
                row["retry_after"] = max(0, int(float(reset.split(",")[0])))
            except ValueError:
                pass
        return notes + [row]
    except Exception as e:
        return notes + [{"source": "brave", "error": scrub_secrets(e, api_key)}]

    _record_brave_quota(api_key, response_headers)

    results = []
    for item in data.get("web", {}).get("results", []):
        desc = item.get("description", "")
        extras = item.get("extra_snippets") or []
        if extras:
            extra_text = " · ".join(s for s in extras if s and s not in desc)
            if extra_text:
                desc = f"{desc} · {extra_text}" if desc else extra_text
        content_kind = "excerpt" if desc else "metadata"
        row = {
            "source": "brave",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": desc,
            "content_kind": content_kind,
            "search_depth": depth,
            "extra_snippets": extra_snippets == "true",
        }
        published_at = item.get("page_age")
        if isinstance(published_at, str) and published_at:
            row["published_at"] = published_at
        results.append(row)
    return results + notes
