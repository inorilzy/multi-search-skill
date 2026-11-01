"""Parallel Search API."""
import json
import urllib.error
import urllib.request

from ...support.http import read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets

# docs/parallel/api-reference-search.md: ErrorResponse {type, error:{ref_id, message}}.
_PARALLEL_HTTP_ERROR_KINDS = {401: "invalid", 402: "quota_exhausted", 403: "invalid", 429: "rate_limit"}


PARALLEL_SEARCH_URL = "https://api.parallel.ai/v1/search"
PARALLEL_SEARCH_MODE = "fast"


def search_parallel(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 15,
    deadline: float | None = None,
) -> list:
    """Search the web through Parallel's current GA Search endpoint.

    Parallel returns relevant excerpts rather than full page bodies, so they
    stay in ``description`` and remain eligible for the normal scrape stage.
    """
    normalized_query = query.strip()
    if not normalized_query:
        # search_queries needs at least one non-empty query; the API would 422.
        return [{"source": "parallel", "error": "empty query", "kind": "target",
                 "error_type": "target", "origin": "target", "error_origin": "target"}]
    max_results = max(1, min(int(count), 20))
    payload = json.dumps({
        "objective": normalized_query[:5000],
        "search_queries": [normalized_query[:200]],
        "mode": PARALLEL_SEARCH_MODE,
        "advanced_settings": {"max_results": max_results},
    }).encode("utf-8")
    req = urllib.request.Request(
        PARALLEL_SEARCH_URL,
        data=payload,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout, deadline=deadline) as resp:
            data = json.loads(read_limited(resp))
    except urllib.error.HTTPError as exc:
        row = http_error_row("parallel", exc, secret=api_key, kinds=_PARALLEL_HTTP_ERROR_KINDS)
        return [row]
    except Exception as exc:
        return [{"source": "parallel", "error": scrub_secrets(exc, api_key)}]

    raw_results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw_results, list):
        return [{"source": "parallel", "error": "invalid response: results must be an array"}]

    results = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        if not url:
            continue
        raw_excerpts = item.get("excerpts") or []
        if isinstance(raw_excerpts, str):
            excerpts = [raw_excerpts] if raw_excerpts else []
        elif isinstance(raw_excerpts, list):
            excerpts = [str(excerpt) for excerpt in raw_excerpts if excerpt]
        else:
            excerpts = []
        result = {
            "source": "parallel",
            "title": item.get("title") or "",
            "url": url,
            "description": "\n\n".join(excerpts),
            "content_kind": "excerpt" if excerpts else "metadata",
        }
        if excerpts:
            result["excerpts"] = excerpts
        if item.get("publish_date") is not None:
            result["publish_date"] = item.get("publish_date")
            result["published_at"] = item.get("publish_date")
        results.append(result)
    for warning in (data.get("warnings") or []) if isinstance(data, dict) else []:
        # input_validation_warning entries (e.g. a clamped max_results).
        text = warning.get("message") if isinstance(warning, dict) else str(warning)
        if text:
            results.append({"source": "parallel", "error": f"Parallel warning: {text}"[:300],
                            "kind": "target", "error_type": "target",
                            "origin": "target", "error_origin": "target"})
    return results
