"""Hacker News search via Algolia API."""
import json
import urllib.parse

from ..http import urlopen_retry


def search_hackernews(query: str, count: int = 10) -> list:
    """Search Hacker News stories via Algolia API (free, no auth)."""
    url = (
        "https://hn.algolia.com/api/v1/search?"
        + urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": count})
    )
    try:
        with urlopen_retry(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "hackernews", "error": str(e)}]
    items = []
    for hit in data.get("hits", []):
        url_val = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        items.append({
            "source": "hackernews",
            "title": hit.get("title", ""),
            "url": url_val,
            "description": f"HN ⬆{hit.get('points', 0)} 💬{hit.get('num_comments', 0)}",
        })
    return items
