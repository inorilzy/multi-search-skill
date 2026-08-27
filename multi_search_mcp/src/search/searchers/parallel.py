"""Parallel Search API."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


PARALLEL_SEARCH_URL = "https://api.parallel.ai/v1/search"
PARALLEL_SEARCH_MODE = "fast"


def search_parallel(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 15,
) -> list:
    """Search the web through Parallel's current GA Search endpoint.

    Parallel returns relevant excerpts rather than full page bodies, so they
    stay in ``description`` and remain eligible for the normal scrape stage.
    """
    normalized_query = query.strip()
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
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
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
        results.append(result)
    return results
