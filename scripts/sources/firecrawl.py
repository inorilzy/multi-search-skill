"""Firecrawl /v2/search with inline scraping."""
import json
import urllib.request

from ..http import urlopen_retry


def search_firecrawl(query: str, api_key: str, count: int = 10) -> list:
    """Search via Firecrawl /v2/search with inline scraping.

    Uses scrapeOptions to get markdown + summary for each result in one call,
    so we don't need a separate /scrape pass. Cost: ~1 credit per scraped result.
    """
    payload = json.dumps({
        "query": query,
        "limit": count,
        "scrapeOptions": {
            "formats": ["markdown", "summary"],
            "onlyMainContent": True,
        },
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v2/search",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "firecrawl", "error": str(e)}]

    items = []
    web_results = (data.get("data") or {}).get("web") or data.get("data") or []
    if isinstance(web_results, dict):
        web_results = [web_results]
    for result in web_results:
        if not isinstance(result, dict):
            continue
        summary = (result.get("summary") or "").strip()
        markdown = result.get("markdown") or ""
        description = summary or (result.get("description") or "")
        item = {
            "source": "firecrawl",
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": description[:300],
        }
        if markdown:
            item["scraped_content"] = markdown
        items.append(item)
    return items
