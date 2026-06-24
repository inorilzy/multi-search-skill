"""Reddit search via OAuth API (token_v2 Bearer token)."""
import json
import urllib.parse
import urllib.request


def search_reddit_oauth(query, token="", count=10, timeout=20):
    """Search Reddit via oauth.reddit.com/search with token_v2 Bearer token."""
    params = urllib.parse.urlencode({"q": query, "limit": max(1, count), "sort": "relevance", "raw_json": 1})
    url = f"https://oauth.reddit.com/search?{params}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "multi-search/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return [{"source": "reddit", "error": str(e)[:300]}]
    children = data.get("data", {}).get("children", [])
    items = []
    for c in children:
        p = c.get("data", {})
        items.append({
            "source": "reddit",
            "title": (p.get("title") or "")[:300],
            "url": "https://reddit.com" + (p.get("permalink") or ""),
            "description": (
                f"r/{p.get('subreddit', '?')} | {p.get('score', 0)} pts | "
                f"{p.get('num_comments', 0)} comments | by u/{p.get('author', '?')}"
            ),
        })
    return items
