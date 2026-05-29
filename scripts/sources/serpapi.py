"""SerpAPI (Google) search."""
import json
import urllib.parse

from ..http import urlopen_retry


def search_serpapi(query: str, api_key: str, count: int = 10, engine: str = "google_light") -> list:
    """Call SerpAPI to fetch SERP results.
    Default engine: google_light — 3x faster, 250 searches/month free (vs 100 for regular google).
    Switch to engine='google' for full knowledge_graph / shopping / things_to_know etc.
    """
    params = {
        "engine": engine,
        "q": query,
        "api_key": api_key,
        "num": count,
        "output": "json",
    }
    if engine in ("google", "google_light"):
        params["hl"] = "en"
        params["gl"] = "us"
    url = "https://serpapi.com/search?" + urllib.parse.urlencode(params)
    try:
        with urlopen_retry(url, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "serpapi", "error": str(e)}]
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
