"""Baidu Qianfan AI search + AI answer."""
import json
import urllib.request

from ..http import urlopen_retry


def search_baidu(query: str, api_key: str, count: int = 10) -> list:
    """Search via Baidu Qianfan AI Search (百度千帆搜索).

    Free tier: 1500 requests/month. Endpoint: /v2/ai_search/web_search.
    """
    payload = json.dumps({
        "messages": [{"content": query, "role": "user"}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": min(count, 50)}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://qianfan.baidubce.com/v2/ai_search/web_search",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "baidu", "error": str(e)}]
    items = []
    for ref in data.get("references") or []:
        items.append({
            "source": "baidu",
            "title": ref.get("title") or ref.get("web_anchor") or "",
            "url": ref.get("url", ""),
            "description": (ref.get("content") or "")[:300],
        })
    return items


def search_baidu_ai(query: str, api_key: str) -> str:
    """Call Baidu AI Search summary API and return the generated summary text."""
    endpoint = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"
    payload = json.dumps({
        "messages": [{"role": "user", "content": query}],
        "stream": False,
        "search_source": "baidu_search_v2",
        "model": "ernie-4.5-turbo-32k",
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=30) as resp:
            data = json.loads(resp.read())
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or choices[0].get("delta") or {}
            return (msg.get("content") or "").strip()
        return ""
    except Exception:
        return ""
