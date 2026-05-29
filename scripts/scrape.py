"""URL scraping: Jina Reader → Exa /contents → Firecrawl fallback chain.

GitHub repo root URLs are rewritten to raw README to avoid nav/chrome noise.
"""
import json
import re
import urllib.request

from .http import urlopen_retry


_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s#?]+)/?$")


def _rewrite_for_clean_scrape(url: str) -> str:
    """Rewrite GitHub repo root URLs to raw README to avoid nav/chrome noise."""
    m = _GH_REPO_RE.match(url)
    if m:
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    return url


def scrape_url_jina(url: str, timeout: int = 20, jina_key: str = "") -> dict:
    """Scrape a single URL via Jina Reader.
    Without key: 20 RPM (free). With key: higher RPM limit.
    Returns {url, title, markdown, error?}."""
    target = _rewrite_for_clean_scrape(url)
    jina_url = "https://r.jina.ai/" + target
    headers = {
        "Accept": "text/plain",
        "User-Agent": "multi-search/1.0",
        "X-Return-Format": "markdown",
    }
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"
    req = urllib.request.Request(jina_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            md = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"url": url, "error": str(e)}
    if not md or len(md) < 50:
        return {"url": url, "error": "empty response from Jina"}
    title = ""
    lines = md.split("\n")
    for line in lines[:5]:
        if line.startswith("Title:"):
            title = line[6:].strip()
            break
    return {
        "url": url,
        "title": title or url,
        "markdown": md,
        "length": len(md),
        "via": "jina",
    }


def scrape_url_firecrawl(url: str, api_key: str, timeout: int = 25) -> dict:
    """Scrape a single URL via Firecrawl /v1/scrape, return {url, title, markdown, error?}."""
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/scrape",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"url": url, "error": str(e)}
    if not data.get("success"):
        return {"url": url, "error": data.get("error", "scrape failed")}
    d = data.get("data", {}) or {}
    md = d.get("markdown", "") or ""
    return {
        "url": url,
        "title": (d.get("metadata") or {}).get("title", ""),
        "markdown": md,
        "length": len(md),
        "via": "firecrawl",
    }


def scrape_url_exa(url: str, api_key: str, timeout: int = 25) -> dict:
    """Fetch page content via Exa /contents API. Returns highlights + full text."""
    payload = json.dumps({
        "urls": [url],
        "highlights": True,
        "text": {"maxCharacters": 8000},
    }).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/contents",
        data=payload,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        statuses = data.get("statuses") or []
        if statuses and statuses[0].get("status") != "success":
            return {"url": url, "error": f"Exa status: {statuses[0].get('status', 'unknown')}"}
        results = data.get("results") or []
        if not results:
            return {"url": url, "error": "Exa: no results returned"}
        r = results[0]
        highlights = r.get("highlights") or []
        text = r.get("text") or ""
        markdown = "\n\n".join(highlights) + ("\n\n---\n\n" + text if text else "")
        return {
            "url": url,
            "title": r.get("title") or url,
            "markdown": markdown,
            "length": len(markdown),
            "via": "exa",
        }
    except Exception as e:
        return {"url": url, "error": f"Exa: {e}"}


def scrape_url_smart(url: str, firecrawl_key: str | None, timeout: int = 25,
                     jina_key: str = "", exa_key: str = "") -> dict:
    """Try Jina Reader first, then Exa /contents, then Firecrawl as last resort."""
    result = scrape_url_jina(url, timeout=timeout, jina_key=jina_key)
    if "error" not in result:
        return result
    if exa_key:
        exa_result = scrape_url_exa(url, exa_key, timeout=timeout)
        if "error" not in exa_result:
            return exa_result
    if firecrawl_key:
        fc_result = scrape_url_firecrawl(url, firecrawl_key, timeout=timeout)
        if "error" not in fc_result:
            return fc_result
        return fc_result
    if exa_key:
        return exa_result  # type: ignore[return-value]
    return result
