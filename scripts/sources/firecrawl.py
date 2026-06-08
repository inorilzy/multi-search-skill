"""Firecrawl /v2/search."""
import json
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets


def search_firecrawl(query: str, api_key: str, count: int = 10, timeout: float = 60) -> list:
    """Search via Firecrawl /v2/search without inline scraping."""
    payload = json.dumps({
        "query": query,
        "limit": count,
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v2/search",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "firecrawl", "error": scrub_secrets(e, api_key)}]

    if data.get("success") is False:
        error = data.get("error") or data.get("message") or "request failed"
        if isinstance(error, dict):
            error = json.dumps(error, ensure_ascii=False)
        return [{"source": "firecrawl", "error": scrub_secrets(error, api_key)}]

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
            "source": "firecrawl",
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": (result.get("description") or "")[:300],
        }
        items.append(item)
    return items
