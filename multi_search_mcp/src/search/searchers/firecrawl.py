"""Firecrawl /v2/search."""
import json
import time
import urllib.error
import urllib.request

from ...support.http import read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.query_limits import limit_query
from ...support.secrets import scrub_secrets

# docs/firecrawl/search-api-reference.md
FIRECRAWL_QUERY_MAX_CHARS = 500
FIRECRAWL_LIMIT_MAX = 100
# docs/firecrawl/errors.md (same table the scraper uses).
_SEARCH_HTTP_ERROR_KINDS = {
    401: "invalid",
    402: "quota_exhausted",
    403: "provider",
    408: "timeout",
    429: "rate_limit",
}


def search_firecrawl(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 60,
    deadline: float | None = None,
    include_domains: list[str] | tuple[str, ...] | None = None,
    source: str = "firecrawl",
    want_content: bool = False,
) -> list:
    """Search via Firecrawl /v2/search.

    When ``want_content`` is set, request inline markdown scraping so each
    result carries body content; otherwise return URLs/snippets only.
    """
    query, notes = limit_query(source, query, max_chars=FIRECRAWL_QUERY_MAX_CHARS)
    body = {
        "query": query,
        "limit": max(1, min(int(count), FIRECRAWL_LIMIT_MAX)),
        # Firecrawl now defaults to query highlights, which replace the search
        # snippet with long page-markdown passages. Ask for the plain snippet
        # (docs.firecrawl.dev/features/search-highlights).
        "highlights": False,
    }
    if include_domains:
        body["includeDomains"] = list(include_domains)
    if want_content:
        body["scrapeOptions"] = {"formats": ["markdown"]}
    if deadline is not None:
        # Let Firecrawl stop (and stop billing scrapeOptions) when we give up.
        remaining = deadline - time.monotonic()
        body["timeout"] = int(max(1.0, min(remaining, float(timeout))) * 1000)
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v2/search",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout, deadline=deadline) as resp:
            data = json.loads(read_limited(resp))
    except urllib.error.HTTPError as e:
        return notes + [http_error_row(source, e, secret=api_key, kinds=_SEARCH_HTTP_ERROR_KINDS)]
    except Exception as e:
        return notes + [{"source": source, "error": scrub_secrets(e, api_key)}]

    if data.get("success") is False:
        error = data.get("error") or data.get("message") or "request failed"
        if isinstance(error, dict):
            error = json.dumps(error, ensure_ascii=False)
        return notes + [{"source": source, "error": scrub_secrets(error, api_key)}]

    items = []
    data_field = data.get("data") or []
    if isinstance(data_field, dict):
        web_results = data_field.get("web")
        if web_results is None:
            web_results = [data_field] if any(k in data_field for k in ("title", "url", "description")) else []
    else:
        web_results = data_field
    if isinstance(web_results, dict):
        web_results = [web_results]
    if not isinstance(web_results, list):
        web_results = []
    for result in web_results:
        if not isinstance(result, dict):
            continue
        item = {
            "source": source,
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": (result.get("description") or "")[:300],
        }
        if result.get("markdown"):
            item["scraped_content"] = result.get("markdown")
            item["content_kind"] = "body"
        elif result.get("description"):
            item["content_kind"] = "excerpt"
        else:
            item["content_kind"] = "metadata"
        items.append(item)
    return items + notes
