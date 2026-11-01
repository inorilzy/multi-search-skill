"""Brave Search API."""
import json
import urllib.error
import urllib.parse
import urllib.request

from ...support.http import decompress_limited, read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.query_limits import limit_query
from ...support.secrets import scrub_secrets

# docs/brave/api-reference-web-search.md: q <= 600 chars and 75 words.
BRAVE_QUERY_MAX_CHARS = 600
BRAVE_QUERY_MAX_WORDS = 75
# docs/brave/authentication.md, rate-limiting.md
_BRAVE_HTTP_ERROR_KINDS = {401: "invalid", 403: "invalid", 429: "rate_limit"}


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

    results = []
    for item in data.get("web", {}).get("results", []):
        desc = item.get("description", "")
        extras = item.get("extra_snippets") or []
        if extras:
            extra_text = " · ".join(s for s in extras if s and s not in desc)
            if extra_text:
                desc = f"{desc} · {extra_text}" if desc else extra_text
        content_kind = "excerpt" if desc else "metadata"
        results.append(
            {
                "source": "brave",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": desc,
                "content_kind": content_kind,
                "search_depth": depth,
                "extra_snippets": extra_snippets == "true",
            }
        )
    return results + notes
