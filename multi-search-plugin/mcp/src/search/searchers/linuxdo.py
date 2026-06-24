"""Linux.do search via Discourse JSON API."""
import json
import urllib.parse
import urllib.request


def search_linuxdo_api(query, cookie="", count=10, timeout=20):
    """Search linux.do via /search.json API with cookie authentication.
    Requires a logged-in cookie (Cloudflare blocks headless requests).
    """
    params = urllib.parse.urlencode({"q": query, "page": 1})
    url = f"https://linux.do/search.json?{params}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    req.add_header("Accept", "application/json")
    req.add_header("X-Requested-With", "XMLHttpRequest")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return [{"source": "linuxdo-api", "error": str(e)[:300]}]
    posts = data.get("posts", [])
    items = []
    for p in posts[:count]:
        items.append({
            "source": "linuxdo-api",
            "title": (p.get("blurb") or "")[:200].replace("\n", " "),
            "url": f"https://linux.do/t/topic/{p['topic_id']}",
            "description": f"u/{p.get('username', '?')} | {p.get('like_count', 0)} likes",
        })
    return items
