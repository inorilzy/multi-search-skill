#!/usr/bin/env python3
"""
Multi-source search aggregator: Brave + Tavily + GitHub + Sourcegraph + HN + SO + PyPI + npm + Exa + SerpAPI + Baidu
Usage: python search.py "your query" [--type web|code|repos|packages|community|all] [--count N]
       [--brave-count N] [--tavily-count N] [--github-count N] [--sg-count N]
Keys: ~/.search-keys.json  {"brave": "...", "tavily": "...", "sourcegraph": "...", "github": "ghp_...", "exa": "..."}
"""

import os
import json
import gzip
import ssl
import sys
import subprocess
import concurrent.futures
import urllib.request
import urllib.parse
import xmlrpc.client
from pathlib import Path


# Global tolerant SSL context — Python 3.12+ is strict about TLS EOF;
# many APIs close TLS mid-response, causing SSLEOFError. Apply ignore flag
# to all our HTTPS calls, and patch urllib's default opener to use it.
_ssl_ctx = ssl.create_default_context()
if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
    _ssl_ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF  # type: ignore[attr-defined]
_https_handler = urllib.request.HTTPSHandler(context=_ssl_ctx)
urllib.request.install_opener(urllib.request.build_opener(_https_handler))


def _urlopen_retry(req_or_url, timeout: int, retries: int = 2):
    """urlopen with up to 2 retries on SSL EOF errors (Python 3.12 + parallel TLS issue)."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req_or_url, timeout=timeout, context=_ssl_ctx)
        except (ssl.SSLEOFError, ssl.SSLError) as e:
            last_exc = e
            continue
        except OSError as e:
            # urlopen wraps SSL errors in URLError; check the message
            msg = str(e)
            if "EOF" in msg or "SSL" in msg:
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]



def load_keys() -> dict:
    """Load API keys from ~/.search-keys.json or environment variables."""
    keys_file = Path.home() / ".search-keys.json"
    keys = {}
    if keys_file.exists():
        try:
            keys = json.loads(keys_file.read_text())
        except Exception:
            pass
    # Environment variables override file
    for env_name, key_name in [
        ("BRAVE_SEARCH_API_KEY", "brave"),
        ("BRAVE_API_KEY", "brave"),
        ("TAVILY_API_KEY", "tavily"),
        ("SOURCEGRAPH_TOKEN", "sourcegraph"),
        ("EXA_API_KEY", "exa"),
        ("GITHUB_TOKEN", "github"),
        ("GH_TOKEN", "github"),
        ("SERPAPI_KEY", "serpapi"),
        ("SERPAPI_API_KEY", "serpapi"),
        ("FIRECRAWL_API_KEY", "firecrawl"),
        ("BAIDU_API_KEY", "baidu"),
        ("QIANFAN_API_KEY", "baidu"),
    ]:
        val = os.getenv(env_name)
        if val:
            keys[key_name] = val
    return keys


def search_brave(query: str, api_key: str, count: int = 10) -> list:
    """Call Brave Search API."""
    url = (
        "https://api.search.brave.com/res/v1/web/search?"
        + urllib.parse.urlencode({"q": query, "count": count})
    )
    req = urllib.request.Request(
        url,
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with _urlopen_retry(req, timeout=15) as resp:
            raw = resp.read()
            # Handle gzip
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw)
    except Exception as e:
        return [{"source": "brave", "error": str(e)}]

    results = []
    for item in data.get("web", {}).get("results", []):
        results.append(
            {
                "source": "brave",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            }
        )
    return results


def search_tavily(query: str, api_key: str, max_results: int = 10) -> list:
    """Call Tavily Search API."""
    payload = json.dumps(
        {
            "query": query,
            "max_results": max_results,
            "api_key": api_key,
            "include_answer": False,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen_retry(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "tavily", "error": str(e)}]

    results = []
    for item in data.get("results", []):
        results.append(
            {
                "source": "tavily",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": (item.get("content") or "")[:300],
            }
        )
    return results


def _run_gh(args: list, timeout: int = 20, retries: int = 2) -> tuple[int, str, str]:
    """Run a gh CLI command, returning (returncode, stdout, stderr).
    Handles Windows encoding by reading bytes and decoding as UTF-8.
    Retries on EOF errors (intermittent GitHub API network issue)."""
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            # Retry on EOF (intermittent GitHub API network issue)
            if result.returncode != 0 and "EOF" in stderr and attempt < retries:
                continue
            return result.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)
    return -1, "", "EOF after retries"


def _github_api(endpoint: str, token: str = "") -> tuple[int, str, str]:
    """Call GitHub REST API directly when token provided, else fall back to gh CLI.
    Returns (returncode, stdout, stderr).
    """
    if token:
        url = f"https://api.github.com/{endpoint}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "multi-search/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with _urlopen_retry(req, timeout=15) as resp:
                return 0, resp.read().decode("utf-8", errors="replace"), ""
        except Exception as e:
            return -1, "", str(e)
    return _run_gh(["gh", "api", endpoint])


def search_github_repos(query: str, count: int = 10, token: str = "") -> list:
    """Search GitHub repositories. Uses token directly if provided, else gh CLI."""
    endpoint = f"search/repositories?q={urllib.parse.quote_plus(query)}&sort=stars&per_page={count}"
    rc, stdout, stderr = _github_api(endpoint, token)
    if rc != 0:
        return [{"source": "github-repos", "error": stderr.strip() or f"exit {rc}"}]
    try:
        data = json.loads(stdout)
    except Exception as e:
        return [{"source": "github-repos", "error": f"JSON parse error: {e}"}]
    items = []
    for item in data.get("items", []):
        items.append(
            {
                "source": "github-repos",
                "title": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "description": item.get("description") or "",
                "stars": item.get("stargazers_count"),
            }
        )
    return items


def search_github_code(query: str, count: int = 10, token: str = "") -> list:
    """Search GitHub code. Uses token directly if provided, else gh CLI."""
    endpoint = f"search/code?q={urllib.parse.quote_plus(query)}&per_page={count}"
    rc, stdout, stderr = _github_api(endpoint, token)
    if rc != 0:
        return [{"source": "github-code", "error": stderr.strip() or f"exit {rc}"}]
    try:
        data = json.loads(stdout)
    except Exception as e:
        return [{"source": "github-code", "error": f"JSON parse error: {e}"}]
    items = []
    for item in data.get("items", []):
        repo = item.get("repository", {})
        items.append(
            {
                "source": "github-code",
                "title": item.get("name", ""),
                "url": item.get("html_url", ""),
                "description": f"{repo.get('full_name', '')}: {item.get('path', '')}",
            }
        )
    return items


def search_sourcegraph(query: str, count: int = 10, token: str = "") -> list:
    """Search Sourcegraph for code in public repos (uses streaming search API)."""
    sg_query = f"{query} count:{count} type:file"
    url = (
        "https://sourcegraph.com/.api/search/stream?"
        + urllib.parse.urlencode({"q": sg_query, "v": "V3", "display": count})
    )
    headers = {
        "Accept": "text/event-stream",
        "User-Agent": "multi-search/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    # Python 3.12+ is strict about TLS EOF; streaming endpoints close mid-response
    ctx = ssl.create_default_context()
    if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF  # type: ignore[attr-defined]
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [{"source": "sourcegraph", "error": str(e)}]

    items = []
    current_event = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: ") and current_event == "matches":
            try:
                matches = json.loads(line[6:])
                for m in matches:
                    if m.get("type") not in ("content", "path", "symbol"):
                        continue
                    repo = m.get("repository", "")
                    path = m.get("path", "")
                    url_fragment = m.get("url", "")
                    if url_fragment.startswith("/"):
                        full_url = "https://sourcegraph.com" + url_fragment
                    elif repo and path:
                        full_url = f"https://sourcegraph.com/{repo}/-/blob/{path}"
                    else:
                        full_url = ""
                    line_matches = m.get("lineMatches") or m.get("chunkMatches") or []
                    preview = ""
                    if line_matches:
                        first = line_matches[0]
                        preview = first.get("preview", "") or first.get("content", "")
                    items.append({
                        "source": "sourcegraph",
                        "title": f"{repo}/{path}" if repo else path,
                        "url": full_url,
                        "description": preview.strip()[:200] if preview else path,
                        "stars": m.get("repoStars"),
                    })
                    if len(items) >= count:
                        break
            except Exception:
                pass
        elif not line:
            current_event = None
        if len(items) >= count:
            break

    return items[:count]


def search_hackernews(query: str, count: int = 10) -> list:
    """Search Hacker News stories via Algolia API (free, no auth)."""
    url = (
        "https://hn.algolia.com/api/v1/search?"
        + urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": count})
    )
    try:
        with _urlopen_retry(url, timeout=15) as resp:
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


def search_stackoverflow(query: str, count: int = 10) -> list:
    """Search Stack Overflow via Stack Exchange API (free, no auth needed for basic access)."""
    url = (
        "https://api.stackexchange.com/2.3/search/advanced?"
        + urllib.parse.urlencode({
            "q": query,
            "site": "stackoverflow",
            "sort": "relevance",
            "order": "desc",
            "pagesize": count,
            "filter": "default",
        })
    )
    try:
        with _urlopen_retry(url, timeout=15) as resp:
            raw = resp.read()
            # Stack Exchange usually gzip-encodes but may not always
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass  # already uncompressed
            data = json.loads(raw)
    except Exception as e:
        return [{"source": "stackoverflow", "error": str(e)}]
    items = []
    for item in data.get("items", []):
        answered = "✅" if item.get("is_answered") else "❓"
        items.append({
            "source": "stackoverflow",
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": f"{answered} score:{item.get('score', 0)} answers:{item.get('answer_count', 0)}",
        })
    return items


def search_pypi(query: str, count: int = 10) -> list:
    """Search PyPI using the JSON API (not blocked by Cloudflare).
    Tries the query as a package name and common variants (hyphens ↔ underscores, etc.).
    Not a full-text search, but works for direct package lookups.
    """
    # Build candidate package names from the query
    candidates: list[str] = [query]
    if " " in query:
        candidates.append(query.replace(" ", "-"))
        candidates.append(query.replace(" ", "_"))
        words = query.split()
        if len(words) >= 2:
            candidates.extend([f"{words[0]}-{words[1]}", words[0], words[1]])
    elif "-" in query:
        candidates.append(query.replace("-", "_"))
        candidates.extend(query.split("-"))
    elif "_" in query:
        candidates.append(query.replace("_", "-"))
        candidates.extend(query.split("_"))

    items = []
    seen: set = set()
    for name in candidates:
        name = name.strip()
        if not name or name in seen:
            continue
        url = "https://pypi.org/pypi/" + urllib.parse.quote(name, safe="") + "/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with _urlopen_retry(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            break
        except Exception:
            break
        info = data.get("info", {})
        pkg_name = info.get("name", name)
        seen.add(pkg_name)
        items.append({
            "source": "pypi",
            "title": f"{pkg_name} {info.get('version', '')}",
            "url": f"https://pypi.org/project/{pkg_name}/",
            "description": (info.get("summary") or "")[:300],
        })
        if len(items) >= count:
            break

    if not items:
        return [{"source": "pypi", "error": f"No PyPI package found for '{query}' (JSON API: exact name lookup only; web search is Cloudflare-protected)"}]
    return items


def search_npm(query: str, count: int = 10) -> list:
    """Search npm packages via registry API (free, no auth)."""
    url = (
        "https://registry.npmjs.org/-/v1/search?"
        + urllib.parse.urlencode({"text": query, "size": count})
    )
    try:
        with _urlopen_retry(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "npm", "error": str(e)}]
    items = []
    for obj in data.get("objects", []):
        pkg = obj.get("package", {})
        items.append({
            "source": "npm",
            "title": pkg.get("name", ""),
            "url": pkg.get("links", {}).get("npm") or f"https://www.npmjs.com/package/{pkg.get('name', '')}",
            "description": pkg.get("description", ""),
        })
    return items


def search_baidu(query: str, api_key: str, count: int = 10) -> list:
    """Search via Baidu Qianfan AI Search (百度千帆搜索).

    Free tier: 1500 requests/month. Endpoint: /v2/ai_search/web_search.
    Auth: Bearer <Qianfan API Key>.
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
        with _urlopen_retry(req, timeout=20) as resp:
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


def search_grep(query: str, count: int = 10) -> list:
    """Search code via grep.app API (free, no auth)."""
    url = "https://grep.app/api/search?" + urllib.parse.urlencode({"q": query, "n": count})
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "multi-search/1.0"}),
            timeout=15,
        ) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "grep.app", "error": str(e)}]
    items = []
    for hit in (data.get("hits") or {}).get("hits", []):
        src = hit.get("_source", {})
        repo = src.get("repo", {})
        f = src.get("file", {})
        items.append({
            "source": "grep.app",
            "title": f"{repo.get('repository', '')}/{f.get('path', '')}",
            "url": f"https://grep.app/search?q={urllib.parse.quote_plus(query)}",
            "description": f"{f.get('language', '')}",
            "stars": repo.get("stars", 0),
        })
    return items



def search_exa(query: str, api_key: str, count: int = 10) -> list:
    """Search via Exa.ai semantic search API."""
    payload = json.dumps({"query": query, "numResults": count, "type": "neural"}).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=payload,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://dashboard.exa.ai",
            "Referer": "https://dashboard.exa.ai/",
        },
        method="POST",
    )
    try:
        with _urlopen_retry(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "exa", "error": str(e)}]
    items = []
    for r in data.get("results", []):
        items.append({
            "source": "exa",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": (r.get("text") or r.get("summary") or "")[:300],
        })
    return items


def search_serpapi(query: str, api_key: str, count: int = 10) -> list:
    """Search via SerpAPI (Google Search aggregator)."""
    url = "https://serpapi.com/search?" + urllib.parse.urlencode({
        "q": query,
        "num": count,
        "api_key": api_key,
    })
    try:
        with _urlopen_retry(url, timeout=35) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "serpapi", "error": str(e)}]

    items = []
    for result in data.get("organic_results", []):
        items.append({
            "source": "serpapi",
            "title": result.get("title", ""),
            "url": result.get("link", ""),
            "description": result.get("snippet", "")[:300],
        })
        if len(items) >= count:
            break

    return items


def search_firecrawl(query: str, api_key: str, count: int = 10) -> list:
    """Search via Firecrawl (web search + scraping API)."""
    payload = json.dumps({"query": query, "limit": count}).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/search",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen_retry(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "firecrawl", "error": str(e)}]

    items = []
    for result in data.get("data", []):
        items.append({
            "source": "firecrawl",
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": result.get("description", "")[:300],
        })
    return items


def deduplicate(results: list) -> tuple:
    """Remove duplicate URLs, keeping first occurrence. Returns (deduped, source_counts_raw).

    source_counts_raw counts each source's contribution BEFORE dedup, so users
    see that SerpAPI/Brave both returned a URL even if only one is shown.
    Each kept item also gets an 'also_from' list of other sources that returned the same URL.
    """
    raw_counts: dict = {}
    for item in results:
        if "error" in item:
            continue
        src = item.get("source", "?")
        raw_counts[src] = raw_counts.get(src, 0) + 1

    seen: dict = {}  # url -> index in deduped
    deduped: list = []
    for item in results:
        url = item.get("url", "")
        if not url:
            deduped.append(item)  # keep error entries
            continue
        if url not in seen:
            seen[url] = len(deduped)
            item = dict(item)
            item["also_from"] = []
            deduped.append(item)
        else:
            existing = deduped[seen[url]]
            other_src = item.get("source", "?")
            if other_src != existing.get("source") and other_src not in existing["also_from"]:
                existing["also_from"].append(other_src)
    return deduped, raw_counts


def scrape_url(url: str, api_key: str, timeout: int = 25) -> dict:
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
    }


def format_scrapes(scrapes: list, max_chars: int = 2000) -> str:
    """Format scraped pages as markdown sections."""
    if not scrapes:
        return ""
    lines = ["\n---\n\n## 🔥 Scraped Content (Firecrawl)\n"]
    for i, s in enumerate(scrapes, 1):
        if s.get("error"):
            lines.append(f"### {i}. ⚠️ {s['url']}\n\n> Scrape error: {s['error']}\n")
            continue
        title = s.get("title") or s["url"]
        md = s.get("markdown", "")
        truncated = md[:max_chars]
        suffix = f"\n\n_...truncated ({s['length']} chars total)_" if len(md) > max_chars else ""
        lines.append(f"### {i}. [{title}]({s['url']})\n\n{truncated}{suffix}\n")
    return "\n".join(lines)


def format_results(results: list, query: str, raw_counts: dict | None = None) -> str:
    """Format aggregated results for display."""
    lines = [f"## Search Results: `{query}`\n"]
    source_icons = {
        "brave": "🔍",
        "tavily": "🌐",
        "exa": "✨",
        "serpapi": "🔎",
        "firecrawl": "🔥",
        "github-repos": "📦",
        "github-code": "💻",
        "sourcegraph": "🔎",
        "grep.app": "🧬",
        "baidu": "🐾",
        "hackernews": "🟠",
        "stackoverflow": "🏆",
        "pypi": "🐍",
        "npm": "📗",
    }
    # Use raw_counts (pre-dedup) if provided, else count from deduped results
    if raw_counts is None:
        source_counts: dict = {}
        for item in results:
            if "error" in item:
                continue
            src = item.get("source", "?")
            source_counts[src] = source_counts.get(src, 0) + 1
    else:
        source_counts = raw_counts

    summary_parts = [
        f"{source_icons.get(s, '•')} **{s}**: {n}" for s, n in source_counts.items()
    ]
    lines.append("**Sources (raw hits):** " + " | ".join(summary_parts))

    # Sort by consensus weight: 1 (this source) + len(also_from). Higher = more sources agree.
    # Stable sort preserves original order for ties.
    def _weight(item):
        if "error" in item:
            return -1
        return 1 + len(item.get("also_from") or [])
    results = sorted(results, key=_weight, reverse=True)

    # Consensus stats: how many results were found by 2+ sources
    valid = [r for r in results if "error" not in r]
    consensus_count = sum(1 for r in valid if _weight(r) >= 2)
    max_weight = max((_weight(r) for r in valid), default=0)
    if valid:
        lines.append(
            f"**Consensus:** {len(valid)} unique URLs, {consensus_count} "
            f"matched by 2+ sources (top weight: ×{max_weight})\n"
        )
    else:
        lines.append("")

    for i, item in enumerate(results, 1):
        if "error" in item:
            lines.append(f"{i}. ⚠️ [{item['source']} error] {item['error']}")
            continue
        src = item.get("source", "?")
        icon = source_icons.get(src, "•")
        title = item.get("title", "(no title)")
        url = item.get("url", "")
        desc = item.get("description", "")
        stars = item.get("stars")
        stars_str = f" ⭐{stars}" if stars else ""
        also = item.get("also_from") or []
        weight = 1 + len(also)
        # Prominent weight prefix: shows source agreement at a glance
        if weight >= 3:
            weight_prefix = f"**【×{weight}】** "  # high-consensus, bold brackets
        elif weight == 2:
            weight_prefix = f"**【×2】** "
        else:
            weight_prefix = "【 1 】 "  # single-source for visual alignment
        also_str = f"  _from: {src}" + (f", {', '.join(also)}" if also else "") + "_"
        lines.append(f"{i}. {weight_prefix}{icon} **[{title}]({url})**{stars_str}{also_str}")
        if desc:
            # Truncate long descriptions
            short = desc[:200].replace("\n", " ")
            if len(desc) > 200:
                short += "..."
            lines.append(f"   {short}")
        lines.append("")

    return "\n".join(lines)


def main():
    # Ensure UTF-8 output on Windows (avoids GBK codec errors with emoji)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if not args:
        print("Usage: python search.py <query> [--type all|web|code|repos|...] [--count N]")
        print("       [--brave-count N] [--tavily-count N] [--github-count N] [--sg-count N]")
        print("       [--timeout N] [--include-grep] [--scrape-top N] [--scrape-chars N]")
        sys.exit(1)

    # Parse args
    query_parts = []
    search_type = "all"
    count = 10
    brave_count = None
    tavily_count = None
    github_count = None
    sg_count = None
    global_timeout = 60  # default 60 seconds (covers slow Firecrawl scraping; per-source caps are lower)
    include_grep = True  # default enabled (low search frequency = no 429 issues)
    scrape_top = 0  # if >0, scrape top N result URLs via Firecrawl after search
    scrape_chars = 2000  # max chars per scraped page in output

    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            search_type = args[i + 1]
            i += 2
        elif args[i] == "--count" and i + 1 < len(args):
            try:
                count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--brave-count" and i + 1 < len(args):
            try:
                brave_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--tavily-count" and i + 1 < len(args):
            try:
                tavily_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--github-count" and i + 1 < len(args):
            try:
                github_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--sg-count" and i + 1 < len(args):
            try:
                sg_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            try:
                global_timeout = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--include-grep":
            include_grep = True
            i += 1
        elif args[i] == "--scrape-top" and i + 1 < len(args):
            try:
                scrape_top = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--scrape-chars" and i + 1 < len(args):
            try:
                scrape_chars = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            query_parts.append(args[i])
            i += 1

    # Per-source counts fall back to global --count
    brave_count = brave_count if brave_count is not None else count
    tavily_count = tavily_count if tavily_count is not None else count
    github_count = github_count if github_count is not None else count
    sg_count = sg_count if sg_count is not None else count

    query = " ".join(query_parts)
    if not query:
        print("Error: query is required")
        sys.exit(1)

    keys = load_keys()
    missing = []
    if search_type in ("all", "web") and "brave" not in keys:
        missing.append("brave (BRAVE_SEARCH_API_KEY or ~/.search-keys.json)")
    if search_type in ("all", "web") and "tavily" not in keys:
        missing.append("tavily (TAVILY_API_KEY or ~/.search-keys.json)")

    if missing and search_type not in ("repos", "code"):
        print(f"⚠️  Missing API keys: {', '.join(missing)}")
        print("Add them to ~/.search-keys.json: {\"brave\": \"...\", \"tavily\": \"...\"}")
        if search_type == "all":
            print("Falling back to GitHub-only search...\n")
            search_type = "github"
        elif search_type == "web":
            print("Cannot perform web search without API keys. Use --type repos for GitHub search.")
            sys.exit(1)

    tasks = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        # Web search
        if search_type in ("all", "web") and "brave" in keys:
            tasks["brave"] = pool.submit(search_brave, query, keys["brave"], brave_count)
        if search_type in ("all", "web") and "tavily" in keys:
            tasks["tavily"] = pool.submit(search_tavily, query, keys["tavily"], tavily_count)

        if search_type in ("all", "web", "exa") and "exa" in keys:
            tasks["exa"] = pool.submit(search_exa, query, keys["exa"], count)
        # SerpAPI now in default --type all (Firecrawl search still optional - too slow)
        if search_type in ("all", "web", "serpapi") and "serpapi" in keys:
            tasks["serpapi"] = pool.submit(search_serpapi, query, keys["serpapi"], count)
        if search_type in ("all", "web", "baidu") and "baidu" in keys:
            tasks["baidu"] = pool.submit(search_baidu, query, keys["baidu"], count)
        if search_type in ("web", "firecrawl") and "firecrawl" in keys:
            tasks["firecrawl"] = pool.submit(search_firecrawl, query, keys["firecrawl"], count)
        # GitHub (uses keys["github"] token if present, else falls back to gh CLI)
        if search_type in ("all", "repos", "github"):
            tasks["github_repos"] = pool.submit(search_github_repos, query, github_count, keys.get("github", ""))
        # Code search
        if search_type in ("all", "code", "sourcegraph"):
            tasks["sourcegraph"] = pool.submit(search_sourcegraph, query, sg_count, keys.get("sourcegraph", ""))
        # grep.app removed (low signal, frequent 429/SSL). Use --type code/grep to opt back in.
        if search_type in ("code", "grep"):
            tasks["grep.app"] = pool.submit(search_grep, query, count)
        # Community
        if search_type in ("all", "community", "hn", "hackernews"):
            tasks["hackernews"] = pool.submit(search_hackernews, query, count)
        if search_type in ("all", "community", "so", "stackoverflow"):
            tasks["stackoverflow"] = pool.submit(search_stackoverflow, query, count)
        # Packages
        if search_type in ("packages", "pypi"):
            tasks["pypi"] = pool.submit(search_pypi, query, count)
        if search_type in ("packages", "npm"):
            tasks["npm"] = pool.submit(search_npm, query, count)
        # Legacy: explicit github-code type still works
        if search_type == "github-code":
            tasks["github_code"] = pool.submit(search_github_code, query, github_count, keys.get("github", ""))

    all_results = []
    for name, future in tasks.items():
        try:
            all_results.extend(future.result(timeout=global_timeout))
        except Exception as e:
            all_results.append({"source": name, "error": str(e)})

    deduped, raw_counts = deduplicate(all_results)
    output = format_results(deduped, query, raw_counts=raw_counts)

    # Optional: scrape top N result URLs via Firecrawl
    if scrape_top > 0:
        if "firecrawl" not in keys:
            output += "\n\n⚠️  --scrape-top requires firecrawl key in ~/.search-keys.json\n"
        else:
            urls_to_scrape = []
            seen = set()
            for item in deduped:
                if "error" in item:
                    continue
                u = item.get("url", "")
                if u and u not in seen:
                    seen.add(u)
                    urls_to_scrape.append(u)
                if len(urls_to_scrape) >= scrape_top:
                    break
            scrapes = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(urls_to_scrape) or 1)) as pool:
                futures = {pool.submit(scrape_url, u, keys["firecrawl"], 25): u for u in urls_to_scrape}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        scrapes.append(fut.result(timeout=30))
                    except Exception as e:
                        scrapes.append({"url": futures[fut], "error": str(e)})
            # Preserve original order
            order = {u: i for i, u in enumerate(urls_to_scrape)}
            scrapes.sort(key=lambda s: order.get(s["url"], 999))
            output += format_scrapes(scrapes, max_chars=scrape_chars)

    print(output)


if __name__ == "__main__":
    main()
