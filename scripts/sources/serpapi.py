"""SerpAPI (Google) search."""
import json
import re
import urllib.parse
import urllib.request

from ..http import urlopen_retry


_KEY_RE = re.compile(r"(api_key|apikey|key)=[^&\s]+", re.I)


def _scrub(msg: str) -> str:
    return _KEY_RE.sub(r"\1=<redacted>", msg)[:300]


def search_serpapi(query: str, api_key: str, count: int = 10, engine: str = "google_light") -> list:
    """Call SerpAPI to fetch SERP results.
    Default engine: google_light — 3x faster, 250 searches/month free (vs 100 for regular google).
    Switch to engine='google' for full knowledge_graph / shopping / things_to_know etc.
    """
    params = {
        "engine": engine,
        "q": query,
        "num": count,
        "output": "json",
    }
    if engine in ("google", "google_light"):
        params["hl"] = "en"
        params["gl"] = "us"
    # Key passed via Authorization header (NOT query) to avoid leakage through
    # exception strings, proxy logs, or shell history.
    url = "https://serpapi.com/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urlopen_retry(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "serpapi", "error": _scrub(str(e))}]
    if data.get("error"):
        return [{"source": "serpapi", "error": data["error"]}]
    results = []
    kg = data.get("knowledge_graph") or {}
    if kg.get("description"):
        results.append({
            "source": "serpapi_answer",
            "answer": f"[{kg.get('title', '')}] {kg['description']}",
        })
    for item in (data.get("organic_results") or [])[:count]:
        results.append({
            "source": "serpapi",
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": (item.get("snippet") or "")[:300],
        })
    return results
