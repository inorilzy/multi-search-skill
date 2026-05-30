"""URL scraping: Tavily / Exa / Firecrawl first, Jina Reader fallback.

GitHub repo root URLs are rewritten to raw README to avoid nav/chrome noise.
"""
import json
import re
import urllib.parse
import urllib.request

from .http import urlopen_retry


_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s#?]+)/?$")


def _safe_http_url(url: str) -> str | None:
    """Reject non-http(s) URLs (javascript:, file:, gopher:, ...) before we hand
    them to a fetcher. Returns the URL unchanged if safe, else None."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return url


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
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
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
        with urlopen_retry(req, timeout=timeout) as resp:
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
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
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
        with urlopen_retry(req, timeout=timeout) as resp:
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
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
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
        with urlopen_retry(req, timeout=timeout) as resp:
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


def scrape_url_tavily(url: str, api_key: str, timeout: int = 25) -> dict:
    """Fetch page content via Tavily /extract API."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    payload = json.dumps({
        "urls": [url],
        "extract_depth": "basic",
        "format": "markdown",
    }).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/extract",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        results = data.get("results") or []
        if not results:
            failed = data.get("failed_results") or []
            msg = failed[0].get("error", "no content") if failed else "no results"
            return {"url": url, "error": f"Tavily: {msg}"}
        r = results[0]
        md = r.get("raw_content") or ""
        if not md:
            return {"url": url, "error": "Tavily: empty content"}
        return {
            "url": url,
            "title": url,
            "markdown": md,
            "length": len(md),
            "via": "tavily",
        }
    except Exception as e:
        return {"url": url, "error": f"Tavily: {e}"}


def scrape_url_smart(url: str, firecrawl_key: str | None, timeout: int = 25,
                     jina_key: str = "", exa_key: str = "",
                     tavily_key: str = "", primary: str = "tavily",
                     allow_jina: bool = True) -> dict:
    """Scrape `url` starting with `primary` backend, falling back through the others.

    primary ∈ {jina, tavily, exa, firecrawl}. On failure, tries the remaining
    keyed backends first and keeps Jina as the final zero-config fallback.
    """
    def _call(backend: str) -> dict | None:
        if backend == "jina":
            return scrape_url_jina(url, timeout=timeout, jina_key=jina_key) if allow_jina else None
        if backend == "tavily":
            return scrape_url_tavily(url, tavily_key, timeout=timeout) if tavily_key else None
        if backend == "exa":
            return scrape_url_exa(url, exa_key, timeout=timeout) if exa_key else None
        if backend == "firecrawl":
            return scrape_url_firecrawl(url, firecrawl_key, timeout=timeout) if firecrawl_key else None
        return None

    order = [primary] + [b for b in ("tavily", "exa", "firecrawl") if b != primary]
    if allow_jina and "jina" not in order:
        order.append("jina")
    last: dict | None = None
    for backend in order:
        r = _call(backend)
        if r is None:
            continue
        last = r
        if "error" not in r:
            return r
    return last or {"url": url, "error": "no scrape backend available"}
