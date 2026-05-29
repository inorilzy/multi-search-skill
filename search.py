#!/usr/bin/env python3
"""
Multi-source search aggregator: Brave + Tavily + Exa + Firecrawl + SerpAPI + Baidu + GitHub + HN + SO
Usage: python search.py "your query" [--type web|code|repos|community|all] [--count N]
       [--brave-count N] [--tavily-count N] [--exa-count N] [--github-count N]
       [--hn-count N] [--so-count N] [--baidu-count N] [--serpapi-engine google|google_light]
Keys: ~/.search-keys.json  {"brave": "...", "tavily": "...", "github": "ghp_...", "exa": "..."}
"""

import os
import json
import gzip
import re
import ssl
import sys
import subprocess
import concurrent.futures
import urllib.request
import urllib.parse
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
        ("EXA_API_KEY", "exa"),
        ("GITHUB_TOKEN", "github"),
        ("GH_TOKEN", "github"),
        ("FIRECRAWL_API_KEY", "firecrawl"),
        ("BAIDU_API_KEY", "baidu"),
        ("QIANFAN_API_KEY", "baidu"),
        ("SERPAPI_API_KEY", "serpapi"),
        ("SERPAPI_KEY", "serpapi"),
    ]:
        val = os.getenv(env_name)
        if val:
            keys[key_name] = val
    return keys


def search_brave(query: str, api_key: str, count: int = 10) -> list:
    """Call Brave Search API.
    Uses extra_snippets=true: returns up to 5 additional excerpts per result (free, no extra cost).
    """
    url = (
        "https://api.search.brave.com/res/v1/web/search?"
        + urllib.parse.urlencode({"q": query, "count": count, "extra_snippets": "true"})
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
        # Combine description + extra_snippets into a richer description
        desc = item.get("description", "")
        extras = item.get("extra_snippets") or []
        if extras:
            # Append distinct extras (avoid duplicating the main description)
            extra_text = " · ".join(s for s in extras if s and s not in desc)
            if extra_text:
                desc = f"{desc} · {extra_text}" if desc else extra_text
        results.append(
            {
                "source": "brave",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": desc,
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
            "include_answer": "advanced",
            "include_raw_content": "markdown",
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
        result = {
            "source": "tavily",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("content") or "")[:300],
        }
        raw = item.get("raw_content") or ""
        if raw:
            result["scraped_content"] = raw
        results.append(result)
    if data.get("answer"):
        results.insert(0, {"source": "tavily_answer", "answer": data["answer"]})
    return results


def search_serpapi(query: str, api_key: str, count: int = 10, engine: str = "google_light") -> list:
    """Call SerpAPI to fetch SERP results.
    Default engine: google_light — 3x faster, 250 searches/month free (vs 100 for regular google).
    Switch to engine='google' for full knowledge_graph / shopping / things_to_know etc.
    Docs: https://serpapi.com/search-api  |  https://serpapi.com/google-light-api
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
        with _urlopen_retry(url, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "serpapi", "error": str(e)}]
    if data.get("error"):
        return [{"source": "serpapi", "error": data["error"]}]
    results = []
    # Knowledge graph snippet as a pseudo-answer
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


def search_twitter(query: str, count: int = 10, cookies_path: str = "") -> list:
    """Search Twitter/X via twikit-ng using saved cookies.

    Cookies file should be a JSON dict with at minimum {"auth_token": "...", "ct0": "..."}.
    Default path: ~/.mcp-twikit/cookies.json (shared with mcp-twikit).
    Override via keys.json "twitter_cookies" field or TWITTER_COOKIES_PATH env var.
    """
    try:
        import asyncio
        from twikit import Client  # type: ignore
    except ImportError:
        return [{"source": "twitter", "error": "twikit-ng not installed (pip install twikit-ng)"}]

    if not cookies_path:
        cookies_path = os.path.expanduser("~/.mcp-twikit/cookies.json")
    if not os.path.exists(cookies_path):
        return [{"source": "twitter", "error": f"cookies file not found: {cookies_path}"}]

    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception as e:
        return [{"source": "twitter", "error": f"cookies load failed: {e}"}]

    REPLY_LIMIT = 20  # per tweet

    async def _do_search() -> list:
        client = Client("en-US")
        client.set_cookies(cookies)
        tweets = await client.search_tweet(query, "Top", count=count)
        out = []
        for t in tweets[:count]:
            replies = []
            try:
                full = await client.get_tweet_by_id(t.id)
                page = getattr(full, "replies", None)
                fetched = 0
                while page and fetched < REPLY_LIMIT:
                    for r in page:
                        if fetched >= REPLY_LIMIT:
                            break
                        r_user = getattr(getattr(r, "user", None), "screen_name", "") or "anon"
                        r_text = (getattr(r, "text", "") or "").strip().replace("\n", " ")
                        r_fav = getattr(r, "favorite_count", 0)
                        replies.append(f"  - @{r_user} (♥{r_fav}): {r_text[:200]}")
                        fetched += 1
                    if fetched >= REPLY_LIMIT or not getattr(page, "next_cursor", None):
                        break
                    try:
                        page = await page.next()
                        await asyncio.sleep(0.4)
                    except Exception:
                        break
                await asyncio.sleep(0.6)  # gentle pacing
            except Exception as e:
                replies.append(f"  - _(replies fetch failed: {str(e)[:80]})_")
            out.append((t, replies))
        return out

    try:
        tweet_pairs = asyncio.run(_do_search())
    except Exception as e:
        msg = str(e) or repr(e) or type(e).__name__
        # Retry once on transient 404 / rate-limit
        if "404" in msg or "429" in msg or "rate" in msg.lower():
            import time as _t
            _t.sleep(5)
            try:
                tweet_pairs = asyncio.run(_do_search())
            except Exception as e2:
                return [{"source": "twitter", "error": f"retry failed: {str(e2)[:180]}"}]
        else:
            return [{"source": "twitter", "error": msg[:200]}]

    items = []
    for t, replies in tweet_pairs:
        screen = getattr(getattr(t, "user", None), "screen_name", "") or "i/web"
        tid = getattr(t, "id", "")
        url_val = f"https://x.com/{screen}/status/{tid}" if screen != "i/web" else f"https://x.com/i/web/status/{tid}"
        text = (getattr(t, "text", "") or "").strip()
        first_line = text.split("\n", 1)[0][:120]
        content = text
        if replies:
            content += "\n\n**💬 Top replies:**\n" + "\n".join(replies)
        items.append({
            "source": "twitter",
            "title": f"@{screen}: {first_line}" if screen != "i/web" else first_line,
            "url": url_val,
            "description": f"💬{getattr(t, 'reply_count', 0)} ♥{getattr(t, 'favorite_count', 0)} 🔁{getattr(t, 'retweet_count', 0)}",
            "scraped_content": content,
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


def search_baidu_ai(query: str, api_key: str) -> str:
    """Call Baidu AI Search summary API and return the generated summary text.

    Standard endpoint /v2/ai_search/chat/completions (Authorization: Bearer).
    Offers 100 free calls/day on Qianfan platform.
    """
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
        with _urlopen_retry(req, timeout=30) as resp:
            data = json.loads(resp.read())
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or choices[0].get("delta") or {}
            return (msg.get("content") or "").strip()
        return ""
    except Exception:
        return ""


def search_exa(query: str, api_key: str, count: int = 10) -> list:
    """Search via Exa.ai with highlights + summary + synthesized answer.

    Uses type=auto (router; 'neural' is deprecated per Exa docs).
    Requests contents.highlights + contents.summary, plus a top-level
    outputSchema=text to get a global synthesized answer with grounding.
    """
    payload = json.dumps({
        "query": query,
        "numResults": count,
        "type": "auto",
        "contents": {
            "text": {"maxCharacters": 8000},
            "highlights": True,
            "summary": True,
        },
        "outputSchema": {
            "type": "text",
            "description": "A concise synthesized answer to the user's query, based on the search results.",
        },
    }).encode()
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
        # Combine highlights + summary into a richer description
        highlights = r.get("highlights") or []
        highlight_text = " [...] ".join(highlights) if highlights else ""
        summary = (r.get("summary") or "").strip()
        text = (r.get("text") or "").strip()
        # description prefers summary (LLM-condensed) over raw highlights
        description = summary or highlight_text or text
        result = {
            "source": "exa",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": description[:300],
        }
        # Prefer full page text as scraped_content; fall back to summary+highlights
        if text:
            result["scraped_content"] = text
        else:
            full = []
            if summary:
                full.append(summary)
            if highlight_text:
                full.append(highlight_text)
            if full:
                result["scraped_content"] = "\n\n".join(full)
        items.append(result)
    # Synthesized cross-result answer (from outputSchema)
    output = data.get("output") or {}
    answer = output.get("content") if isinstance(output.get("content"), str) else ""
    if answer:
        items.insert(0, {"source": "exa_answer", "answer": answer})
    return items


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
        with _urlopen_retry(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "firecrawl", "error": str(e)}]

    items = []
    # /v2 response: data.web is the array (sources default to ["web"])
    web_results = (data.get("data") or {}).get("web") or data.get("data") or []
    if isinstance(web_results, dict):
        web_results = [web_results]
    for result in web_results:
        if not isinstance(result, dict):
            continue
        summary = (result.get("summary") or "").strip()
        markdown = result.get("markdown") or ""
        # description prefers LLM summary, falls back to original SERP description
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


def _norm_url(url: str) -> str:
    """Normalize URL for dedup: force https, lowercase host, strip trailing slash, remove UTM/tracking params."""
    try:
        parts = urllib.parse.urlparse(url.strip())
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        qs = {k: v for k, v in qs.items()
              if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "source"))}
        new_query = urllib.parse.urlencode(qs, doseq=True)
        path = parts.path.rstrip("/") or "/"
        return urllib.parse.urlunparse((scheme, parts.netloc.lower(), path, parts.params, new_query, ""))
    except Exception:
        return url


def deduplicate(results: list) -> tuple:
    """Remove duplicate URLs, keeping first occurrence. Returns (deduped, source_counts_raw).

    source_counts_raw counts each source's contribution BEFORE dedup, so users
    see that Brave/Tavily both returned a URL even if only one is shown.
    Each kept item also gets an 'also_from' list of other sources that returned the same URL.
    """
    raw_counts: dict = {}
    for item in results:
        if "error" in item or item.get("source") in ("tavily_answer", "serpapi_answer", "exa_answer"):
            continue
        src = item.get("source", "?")
        raw_counts[src] = raw_counts.get(src, 0) + 1

    seen: dict = {}  # normalized_url -> index in deduped
    deduped: list = []
    for item in results:
        url = item.get("url", "")
        if not url:
            deduped.append(item)  # keep error entries and special items (e.g. tavily_answer)
            continue
        norm = _norm_url(url)
        if norm not in seen:
            seen[norm] = len(deduped)
            item = dict(item)
            item["also_from"] = []
            deduped.append(item)
        else:
            existing = deduped[seen[norm]]
            other_src = item.get("source", "?")
            if other_src != existing.get("source") and other_src not in existing.get("also_from", []):
                existing.setdefault("also_from", []).append(other_src)
    return deduped, raw_counts


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
    # Jina returns "Title: ...\nURL Source: ...\n\n<markdown>" in plain text
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


def scrape_url_smart(url: str, firecrawl_key: str | None, timeout: int = 25, jina_key: str = "", exa_key: str = "") -> dict:
    """Try Jina Reader first, then Exa /contents, then Firecrawl as last resort."""
    result = scrape_url_jina(url, timeout=timeout, jina_key=jina_key)
    if "error" not in result:
        return result
    if exa_key:
        exa_result = scrape_url_exa(url, exa_key, timeout=timeout)
        if "error" not in exa_result:
            return exa_result
    if firecrawl_key:
        fc_result = scrape_url(url, firecrawl_key, timeout=timeout)
        if "error" not in fc_result:
            return fc_result
        return fc_result  # return Firecrawl error as final answer
    if exa_key:
        return exa_result  # type: ignore[return-value]
    return result  # return Jina error if no fallback available


def format_scrapes(scrapes: list, max_chars: int = 2000) -> str:
    """Format scraped pages as markdown sections, with a key-findings summary table up front."""
    if not scrapes:
        return ""

    # --- Summary table (quick scan) ---
    summary_rows = []
    for i, s in enumerate(scrapes, 1):
        if s.get("error"):
            summary_rows.append(f"| {i} | ⚠️ error | {s['url'][:80]} | {s['error'][:80]} |")
        else:
            title = (s.get("title") or s["url"])[:60].replace("|", "｜")
            via = s.get("via", "?")
            # First meaningful line of content (skip Jina metadata and nav/cookie banners)
            first_line = ""
            _skip_prefixes = ("Title:", "URL Source:", "Published Time:", "Markdown Content:",
                              "[", "!", "#", "|", "*", "-", "Skip", "We use", "Cookie",
                              "Subscribe", "Get Started", "Support", "Overview", "Navigation")
            for line in (s.get("markdown") or "").splitlines():
                line = line.strip()
                if (len(line) > 50
                        and not line.startswith(_skip_prefixes)
                        and " | " not in line
                        and not line.endswith(":")):
                    first_line = line[:120]
                    break
            summary_rows.append(f"| {i} | {title} | {via} | {first_line} |")

    table = (
        "| # | 标题 | 来源 | 摘要 |\n"
        "|---|------|------|------|\n"
        + "\n".join(summary_rows)
    )

    lines = ["\n---\n\n## 🔥 Scraped Content\n", "### 📋 关键信息速览\n", table, "\n---\n"]

    # --- Full content sections ---
    for i, s in enumerate(scrapes, 1):
        via = s.get("via", "")
        via_label = f" _(via {via})_" if via else ""
        if s.get("error"):
            lines.append(f"### {i}. ⚠️ {s['url']}\n\n> Scrape error: {s['error']}\n")
            continue
        title = s.get("title") or s["url"]
        md = s.get("markdown", "")
        truncated = md[:max_chars]
        suffix = f"\n\n_...truncated ({s['length']} chars total)_" if len(md) > max_chars else ""
        lines.append(f"### {i}. [{title}]({s['url']}){via_label}\n\n{truncated}{suffix}\n")
    return "\n".join(lines)


def format_results(results: list, query: str, raw_counts: dict | None = None, brief: bool = False, baidu_answer: str = "") -> str:
    """Format aggregated results for display."""
    lines = [f"## Search Results: `{query}`\n"]
    # Extract and display Tavily AI Answer if present
    tavily_answers = [r for r in results if r.get("source") == "tavily_answer"]
    exa_answers = [r for r in results if r.get("source") == "exa_answer"]
    serpapi_answers = [r for r in results if r.get("source") == "serpapi_answer"]
    results = [r for r in results if r.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")]
    if tavily_answers:
        lines.append(f"\n> **Tavily AI Answer:** {tavily_answers[0]['answer']}\n")
    if exa_answers:
        lines.append(f"\n> **Exa AI Answer:** {exa_answers[0]['answer']}\n")
    if serpapi_answers:
        lines.append(f"\n> **Google Knowledge Graph:** {serpapi_answers[0]['answer']}\n")
    if baidu_answer:
        lines.append(f"\n> **百度 AI 总结:** {baidu_answer}\n")
    source_icons = {
        "brave": "🔍",
        "tavily": "🌐",
        "exa": "✨",
        "firecrawl": "🔥",
        "github-repos": "📦",
        "baidu": "🐾",
        "serpapi": "🔎",
        "hackernews": "🟠",
        "stackoverflow": "🏆",
        "twitter": "🐦",
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
        if desc and not brief:
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
        print("       [--brave-count N] [--tavily-count N] [--exa-count N] [--github-count N]")
        print("       [--sg-count N] [--hn-count N] [--so-count N] [--baidu-count N]")
        print("       [--timeout N] [--scrape-top N] [--no-scrape] [--scrape-chars N]")
        sys.exit(1)

    # Parse args
    query_parts = []
    search_type = "all"
    count = None       # None = use per-source optimal defaults; set by --count to override all
    brave_count = None
    tavily_count = None
    exa_count = None
    github_count = None
    hn_count = None
    so_count = None
    baidu_count = None
    serpapi_count = None
    firecrawl_count = None
    twitter_count = None
    serpapi_engine = "google_light"  # default: 3x faster, 250/mo free; use 'google' for full KG
    global_timeout = 60  # default 60 seconds (covers slow Firecrawl scraping; per-source caps are lower)
    scrape_top = 10  # default-on: scrape top 10 URLs (~2 per B-tier source by consensus weight). Use --no-scrape or --scrape-top 0 to disable.
    scrape_chars = 2000  # max chars per scraped page in output
    scrape_per_source = 2  # max URLs to scrape per search source (0 = no per-source limit)
    expand_queries: list = []  # extra queries from --expand, run in parallel with main query
    brief = False  # if True, suppress per-result descriptions (title+URL only)

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
        elif args[i] == "--exa-count" and i + 1 < len(args):
            try:
                exa_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--serpapi-count" and i + 1 < len(args):
            try:
                serpapi_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--serpapi-engine" and i + 1 < len(args):
            serpapi_engine = args[i + 1]
            i += 2
        elif args[i] == "--hn-count" and i + 1 < len(args):
            try:
                hn_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--so-count" and i + 1 < len(args):
            try:
                so_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--baidu-count" and i + 1 < len(args):
            try:
                baidu_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--firecrawl-count" and i + 1 < len(args):
            try:
                firecrawl_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--twitter-count" and i + 1 < len(args):
            try:
                twitter_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            try:
                global_timeout = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--brief":
            brief = True
            i += 1
        elif args[i] == "--scrape-top" and i + 1 < len(args):
            try:
                scrape_top = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--no-scrape":
            scrape_top = 0
            i += 1
        elif args[i] == "--scrape-chars" and i + 1 < len(args):
            try:
                scrape_chars = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--scrape-per-source" and i + 1 < len(args):
            try:
                scrape_per_source = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--expand":
            # --expand "query2" "query3" ... consume all following non-flag tokens
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                expand_queries.append(args[i])
                i += 1
        else:
            query_parts.append(args[i])
            i += 1

    # Per-source defaults — all 10 for balanced coverage; raise per source via --xxx-count.
    # API caps (upper bound per request):
    #   brave:20 | tavily:20 | exa:100 | github:100 | hn:1000 | so:100 | baidu:50 | serpapi:20 | firecrawl:100(1cr/result)
    # --count N overrides all; individual --xxx-count N overrides each source.
    gc = count  # global override (None if --count not passed)
    brave_count   = brave_count   if brave_count   is not None else (min(gc, 20)  if gc is not None else 10)
    tavily_count  = tavily_count  if tavily_count  is not None else (min(gc, 20)  if gc is not None else 10)
    exa_count     = exa_count     if exa_count     is not None else (min(gc, 100) if gc is not None else 10)
    github_count  = github_count  if github_count  is not None else (min(gc, 100) if gc is not None else 10)
    hn_count      = hn_count      if hn_count      is not None else (gc           if gc is not None else 10)
    so_count      = so_count      if so_count      is not None else (min(gc, 100) if gc is not None else 10)
    baidu_count   = baidu_count   if baidu_count   is not None else (min(gc, 50)  if gc is not None else 10)
    serpapi_count = serpapi_count if serpapi_count is not None else (min(gc, 20)  if gc is not None else 10)
    firecrawl_count = firecrawl_count if firecrawl_count is not None else (min(gc, 10) if gc is not None else 5)  # 1 credit/result, stays at 5
    twitter_count = twitter_count if twitter_count is not None else (min(gc, 20) if gc is not None else 10)

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

    # ---------------------------------------------------------------------------
    # Helper: run one query against all selected sources; returns raw result list.
    # Captures all search params via closure — only `q` varies per expand query.
    # lite=True: expand queries only run brave + tavily (saves API quota).
    # ---------------------------------------------------------------------------
    def _run_search(q: str, lite: bool = False) -> list:
        _tasks: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as _pool:
            if (lite or search_type in ("all", "web", "brave")) and "brave" in keys:
                _tasks["brave"] = _pool.submit(search_brave, q, keys["brave"], brave_count)
            if (lite or search_type in ("all", "web", "tavily")) and "tavily" in keys:
                _tasks["tavily"] = _pool.submit(search_tavily, q, keys["tavily"], tavily_count)
            if not lite and search_type in ("all", "web", "exa") and "exa" in keys:
                _tasks["exa"] = _pool.submit(search_exa, q, keys["exa"], exa_count)
            if not lite and search_type in ("all", "web", "baidu") and "baidu" in keys:
                _tasks["baidu"] = _pool.submit(search_baidu, q, keys["baidu"], baidu_count)
            if not lite and search_type in ("all", "web", "serpapi", "google") and "serpapi" in keys:
                _tasks["serpapi"] = _pool.submit(search_serpapi, q, keys["serpapi"], serpapi_count, serpapi_engine)
            if not lite and search_type in ("all", "web", "firecrawl") and "firecrawl" in keys:
                _tasks["firecrawl"] = _pool.submit(search_firecrawl, q, keys["firecrawl"], firecrawl_count)
            # Firecrawl /v2/search now included by default (each result also scraped, 1 credit each)
            if not lite and search_type in ("all", "repos", "github"):
                _tasks["github_repos"] = _pool.submit(search_github_repos, q, github_count, keys.get("github", ""))
            if not lite and search_type in ("all", "community", "hn", "hackernews"):
                _tasks["hackernews"] = _pool.submit(search_hackernews, q, hn_count)
            if not lite and search_type in ("all", "community", "so", "stackoverflow"):
                _tasks["stackoverflow"] = _pool.submit(search_stackoverflow, q, so_count)
            if not lite and search_type in ("all", "community", "twitter", "x"):
                _tasks["twitter"] = _pool.submit(search_twitter, q, twitter_count, keys.get("twitter_cookies", ""))
        _results: list = []
        for _name, _future in _tasks.items():
            try:
                _results.extend(_future.result(timeout=global_timeout))
            except Exception as e:
                _results.append({"source": _name, "error": str(e)})
        return _results

    # Run primary query + any expand queries in parallel, then merge & deduplicate.
    # Expand queries use lite=True: only brave + tavily (avoids N× API quota burn).
    queries_to_run = [query] + expand_queries
    q_label = f"{len(queries_to_run)} quer{'y' if len(queries_to_run) == 1 else 'ies'}"
    print(f"Searching {q_label} across sources...", file=sys.stderr)
    all_results: list = []

    # Run AI Answer APIs in parallel with the main search (avoid sequential 45s wait).
    ai_futures: dict = {}
    ai_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    if keys.get("baidu"):
        ai_futures["baidu"] = ai_executor.submit(search_baidu_ai, query, keys["baidu"])

    if len(queries_to_run) == 1:
        all_results = _run_search(query)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries_to_run)) as outer_pool:
            outer_futures = {outer_pool.submit(_run_search, q, q != query): q for q in queries_to_run}
            for fut in concurrent.futures.as_completed(outer_futures):
                try:
                    all_results.extend(fut.result())
                except Exception:
                    pass

    deduped, raw_counts = deduplicate(all_results)
    valid_count = len([r for r in deduped if "error" not in r and r.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")])
    print(f"Found {valid_count} unique results.", file=sys.stderr)

    # Collect AI Answer results (were running in parallel with the search).
    baidu_answer_text = ""
    if ai_futures:
        if "baidu" in ai_futures:
            try:
                baidu_answer_text = ai_futures["baidu"].result(timeout=60) or ""
            except Exception:
                pass
    ai_executor.shutdown(wait=False)

    output = format_results(deduped, query, raw_counts=raw_counts, brief=brief, baidu_answer=baidu_answer_text)

    # Optional: scrape top N result URLs (Jina Reader first, Firecrawl fallback).
    # Max 30 per run — Jina is 20 RPM; beyond 30 risks timeouts.
    if scrape_top > 0:
        scrape_top = min(scrape_top, 30)
        fc_key = keys.get("firecrawl")  # may be None — Jina works without any key
        # Source tiers for scrape routing:
        #   SKIP    → metadata APIs whose result URL is not a readable article
        #             (scraping wastes Jina quota and yields useless HTML).
        #   PREFER  → snippet-only sources that benefit most from full-page fetch.
        #   (other) → run after PREFER quota is filled.
        SKIP_SCRAPE_SOURCES: set[str] = set()  # github-repos now scrapeable (Jina renders README)
        PREFER_SCRAPE_SOURCES = {"brave", "serpapi", "baidu", "hackernews", "stackoverflow"}
        urls_to_scrape: list = []
        seen_urls: set = set()
        # Order: PREFER tier first (snippet-only sources), then everything else,
        # tie-broken by consensus weight (URLs appearing in multiple sources first).
        deduped_for_scrape = sorted(
            (
                it for it in deduped
                if "error" not in it
                and it.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")
                and it.get("source") not in SKIP_SCRAPE_SOURCES
            ),
            key=lambda x: (
                0 if x.get("source") in PREFER_SCRAPE_SOURCES else 1,
                -(1 + len(x.get("also_from") or [])),
            ),
        )
        # Per-source sampling: take at most `scrape_per_source` URLs from each source
        # so that a single dominant source doesn't crowd out other perspectives.
        source_quota: dict = {}  # source -> count of URLs already picked
        # Build a lookup of URLs with pre-fetched content (Tavily raw_content + Exa highlights).
        prefetched: dict[str, str] = {
            it["url"]: it["scraped_content"]
            for it in deduped
            if it.get("scraped_content") and it.get("url")
        }
        for item in deduped_for_scrape:
            if "error" in item:
                continue
            u = item.get("url", "")
            if not u or u in seen_urls:
                continue
            src = item.get("source", "unknown")
            if scrape_per_source > 0 and source_quota.get(src, 0) >= scrape_per_source:
                continue
            seen_urls.add(u)
            source_quota[src] = source_quota.get(src, 0) + 1
            # Skip Jina scrape if content was already pre-fetched (Tavily/Exa).
            if u not in prefetched:
                urls_to_scrape.append(u)
            if len(urls_to_scrape) + len(prefetched) >= scrape_top:
                break
        scrapes = []
        # Inject pre-fetched content (Tavily raw_content + Exa highlights + Twitter text) directly.
        # Need title/source/markdown/length fields so format_scrapes() renders them.
        prefetched_meta = {it["url"]: it for it in deduped if it.get("url")}
        for u, content in prefetched.items():
            meta = prefetched_meta.get(u, {})
            scrapes.append({
                "url": u,
                "title": meta.get("title") or u,
                "via": meta.get("source", "prefetch"),
                "markdown": content,
                "length": len(content),
            })
        print(f"Scraping top {len(urls_to_scrape)} URL(s) ({len(prefetched)} pre-fetched by Tavily/Exa)...", file=sys.stderr)
        _jina_raw = keys.get("jina", "")
        jina_keys: list[str] = (
            [k for k in _jina_raw if k]
            if isinstance(_jina_raw, list)
            else ([_jina_raw] if _jina_raw else [])
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(urls_to_scrape) or 1)) as pool:
            futures = {
                pool.submit(scrape_url_smart, u, fc_key, 25, jina_keys[i % len(jina_keys)] if jina_keys else "", keys.get("exa", "")): u
                for i, u in enumerate(urls_to_scrape)
            }
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
