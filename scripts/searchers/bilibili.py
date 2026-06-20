"""Bilibili video search via public web interface API."""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets


_TAG_RE = re.compile(r"<[^>]+>")
_VIDEO_CARD_RE = re.compile(
    r'<a[^>]+href="//www\.bilibili\.com/video/([^"/?#]+)[^"]*"[^>]*>.*?'
    r'<img[^>]+alt="([^"]+)"',
    re.S,
)


def _plain_text(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value or "")).strip()


def _browser_headers(query: str, accept: str) -> dict:
    return {
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://search.bilibili.com",
        "Referer": "https://search.bilibili.com/all?" + urllib.parse.urlencode({"keyword": query}),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    }


def _search_bilibili_html(query: str, count: int, timeout: float) -> list:
    url = "https://search.bilibili.com/all?" + urllib.parse.urlencode({"keyword": query})
    req = urllib.request.Request(
        url,
        headers=_browser_headers(query, "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return [{"source": "bilibili", "error": scrub_secrets(exc)}]

    items = []
    seen = set()
    for bvid, title in _VIDEO_CARD_RE.findall(text):
        if bvid in seen:
            continue
        seen.add(bvid)
        items.append({
            "source": "bilibili",
            "title": _plain_text(title),
            "url": f"https://www.bilibili.com/video/{bvid}",
            "description": "from Bilibili search page",
            "video_id": bvid,
        })
        if len(items) >= max(1, min(count, 50)):
            break
    if not items:
        return [{"source": "bilibili", "error": "Bilibili HTML fallback returned no video results"}]
    return items


def search_bilibili(query: str, cookie: str = "", count: int = 10, timeout: float = 20) -> list:
    """Search Bilibili videos and return metadata-only results."""
    params = {
        "search_type": "video",
        "keyword": query,
        "page": 1,
        "page_size": max(1, min(count, 50)),
        "platform": "pc",
    }
    url = "https://api.bilibili.com/x/web-interface/search/type?" + urllib.parse.urlencode(params)
    headers = _browser_headers(query, "application/json, text/plain, */*")
    if cookie:
        headers["Cookie"] = cookie
    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if cookie and exc.code in (401, 403, 412):
            try:
                exc.close()
            except Exception:
                pass
            return search_bilibili(query, "", count, timeout=timeout)
        if exc.code in (403, 412):
            try:
                exc.close()
            except Exception:
                pass
            return _search_bilibili_html(query, count, timeout)
        try:
            message = exc.read().decode("utf-8", "replace")
        except Exception:
            message = str(exc)
        return [{"source": "bilibili", "error": scrub_secrets(f"HTTP {exc.code}: {message}", cookie)}]
    except Exception as exc:
        return [{"source": "bilibili", "error": scrub_secrets(exc, cookie)}]

    if not isinstance(data, dict):
        return _search_bilibili_html(query, count, timeout)
    if data.get("code") not in (0, None):
        if data.get("code") in (-412, -403):
            return _search_bilibili_html(query, count, timeout)
        message = data.get("message") or data.get("msg") or "request failed"
        return [{"source": "bilibili", "error": scrub_secrets(message, cookie)}]

    result_rows = ((data.get("data") or {}).get("result") or [])
    if isinstance(result_rows, dict):
        result_rows = [result_rows]
    items = []
    for row in result_rows:
        if not isinstance(row, dict):
            continue
        bvid = row.get("bvid") or ""
        arcurl = row.get("arcurl") or ""
        url = arcurl or (f"https://www.bilibili.com/video/{bvid}" if bvid else "")
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        if not url:
            continue
        author = row.get("author") or row.get("mid") or ""
        duration = row.get("duration") or ""
        play = row.get("play")
        danmaku = row.get("danmaku")
        published = row.get("pubdate") or row.get("senddate")
        details = []
        if author:
            details.append(str(author))
        if duration:
            details.append(str(duration))
        if play is not None:
            details.append(f"{play} plays")
        if danmaku is not None:
            details.append(f"{danmaku} danmaku")
        if published:
            details.append(str(published))
        description = _plain_text(row.get("description") or "")
        if description:
            details.append(description[:200])
        items.append({
            "source": "bilibili",
            "title": _plain_text(row.get("title") or bvid or url),
            "url": url,
            "description": " · ".join(details),
            "video_id": bvid,
            "author": str(author) if author else "",
        })
    return items
