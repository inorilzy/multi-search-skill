"""Reddit-specific scraping via old.reddit.com HTML."""
import re
import html as html_lib
import urllib.error
import urllib.parse
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets
from . import _DEFAULT_SCRAPE_TIMEOUT_SECONDS, _safe_http_url


_REDDIT_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "new.reddit.com",
    "np.reddit.com",
    "m.reddit.com",
}
_BLOCKED_MARKERS = (
    "blocked by network security",
    "whoa there, pardner",
    "please wait for verification",
    "your request has been blocked",
)
_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def is_reddit_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0]
    return host in _REDDIT_HOSTS


def is_old_reddit_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0]
    return host == "old.reddit.com"


def is_reddit_blocked_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCKED_MARKERS)


def _old_reddit_url(url: str) -> str:
    parts = urllib.parse.urlparse(url)
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urllib.parse.urlunparse(("https", "old.reddit.com", path, "", "", ""))


def _text(node, sep: str = " ") -> str:
    if not node:
        return ""
    return _SPACE_RE.sub(" ", node.get_text(sep, strip=True)).strip()


def _body_text(thing) -> str:
    body = thing.select_one(".usertext-body .md")
    if not body:
        return ""
    return _text(body, "\n")


def _link_url(node) -> str:
    if not node:
        return ""
    href = node.get("href") or ""
    if href.startswith("/"):
        return "https://www.reddit.com" + href
    return href


def _extract_listing(soup) -> tuple[str, str]:
    title = _text(soup.title) or "Reddit"
    rows = []
    for idx, thing in enumerate(soup.select("div.thing.link"), 1):
        title_node = thing.select_one("a.title")
        item_title = _text(title_node)
        if not item_title:
            continue
        score = _text(thing.select_one(".score.unvoted"))
        comments = _text(thing.select_one("a.comments"))
        url = _link_url(title_node)
        body = _body_text(thing)
        line = f"{idx}. {item_title}"
        details = " | ".join(part for part in (score, comments, url) if part)
        if details:
            line += f"\n   {details}"
        if body:
            line += f"\n   {body[:500]}"
        rows.append(line)
        if len(rows) >= 10:
            break
    if not rows:
        return title, ""
    return title, "## Top posts\n\n" + "\n\n".join(rows)


def _extract_post(soup) -> tuple[str, str]:
    link = soup.select_one("div.thing.link")
    title_node = link.select_one("a.title") if link else None
    title = _text(title_node) or _text(soup.title) or "Reddit post"
    parts = [f"# {title}"]

    if link:
        score = _text(link.select_one(".score.unvoted"))
        author = _text(link.select_one("a.author"))
        comments = _text(link.select_one("a.comments"))
        meta = " | ".join(part for part in (f"u/{author}" if author else "", score, comments) if part)
        if meta:
            parts.append(meta)
        body = _body_text(link)
        if body:
            parts.append("## Post\n\n" + body)

    comments = []
    for comment in soup.select("div.comment"):
        if "deleted" in (comment.get("class") or []):
            continue
        body = _body_text(comment)
        if not body:
            continue
        author = _text(comment.select_one("a.author"))
        score = _text(comment.select_one(".score.unvoted"))
        heading = " | ".join(part for part in (f"u/{author}" if author else "", score) if part)
        comments.append((heading, body))
        if len(comments) >= 12:
            break
    if comments:
        rendered = []
        for idx, (heading, body) in enumerate(comments, 1):
            prefix = f"{idx}. "
            rendered.append(prefix + (f"{heading}\n   " if heading else "") + body[:1200])
        parts.append("## Top comments\n\n" + "\n\n".join(rendered))

    markdown = "\n\n".join(part for part in parts if part.strip())
    return title, markdown


def _strip_html(value: str) -> str:
    return _SPACE_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", value))).strip()


def _extract_simple_old_reddit(html: str, url: str) -> tuple[str, str]:
    """Best-effort old.reddit parser used when BeautifulSoup is unavailable."""
    title_match = re.search(r'<a[^>]+class=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</a>', html, re.I | re.S)
    page_title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = _strip_html(title_match.group(1)) if title_match else _strip_html(page_title_match.group(1)) if page_title_match else "Reddit"
    md_blocks = re.findall(
        r'<div[^>]+class=["\'][^"\']*\busertext-body\b[^"\']*["\'][^>]*>\s*<div[^>]+class=["\'][^"\']*\bmd\b[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
        html,
        re.I | re.S,
    )
    texts = [_strip_html(block) for block in md_blocks]
    texts = [text for text in texts if text]
    if "/comments/" in urllib.parse.urlparse(url).path:
        parts = [f"# {title}"]
        if texts:
            parts.append("## Post\n\n" + texts[0])
        if len(texts) > 1:
            comments = [f"{idx}. {body[:1200]}" for idx, body in enumerate(texts[1:13], 1)]
            parts.append("## Top comments\n\n" + "\n\n".join(comments))
        return title, "\n\n".join(parts)
    rows = []
    for idx, match in enumerate(re.finditer(r'<a[^>]+class=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</a>', html, re.I | re.S), 1):
        rows.append(f"{idx}. {_strip_html(match.group(1))}")
        if len(rows) >= 10:
            break
    return title, "## Top posts\n\n" + "\n\n".join(rows) if rows else ""


def scrape_url_reddit(url: str, timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS) -> dict:
    """Fetch Reddit content from old.reddit.com and extract post/listing text."""
    if not _safe_http_url(url):
        return {"url": url, "error": "rejected non-http(s) URL"}
    if not is_reddit_url(url):
        return {"url": url, "error": "Reddit: not a reddit URL"}

    old_url = _old_reddit_url(url)
    req = urllib.request.Request(
        old_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) multi-search/1.0",
        },
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = str(exc)
        return {"url": url, "error": f"Reddit: HTTP {exc.code}: {scrub_secrets(body)}"}
    except Exception as exc:
        return {"url": url, "error": f"Reddit: {scrub_secrets(exc)}"}

    if is_reddit_blocked_text(html):
        return {"url": url, "error": "Reddit: blocked by Reddit network policy"}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        title, markdown = _extract_simple_old_reddit(html, url)
        if len(markdown.strip()) < 80:
            return {"url": url, "error": "Reddit: empty old.reddit content"}
        return {
            "url": url,
            "title": title,
            "markdown": markdown,
            "length": len(markdown),
            "via": "reddit-old",
        }

    soup = BeautifulSoup(html, "html.parser")
    path = urllib.parse.urlparse(url).path
    if "/comments/" in path:
        title, markdown = _extract_post(soup)
    else:
        title, markdown = _extract_listing(soup)

    if len(markdown.strip()) < 80:
        return {"url": url, "error": "Reddit: empty old.reddit content"}
    return {
        "url": url,
        "title": title,
        "markdown": markdown,
        "length": len(markdown),
        "via": "reddit-old",
    }
