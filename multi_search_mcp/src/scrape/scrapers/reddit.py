"""Reddit-only post scraping using eddrit's anonymous Android authentication."""
from __future__ import annotations

import html
import re
import time
from urllib.parse import parse_qs, urlsplit

from ...support.url_security import UrlSecurityError, validate_scrape_url
from ._eddrit import EddritError, get_post_json, remaining


_POST_PATH = re.compile(r"^/(?:r/[^/]+/|user/[^/]+/)?comments/([a-z0-9]+)(?:/([^/]*)(?:/([a-z0-9]+))?)?/?$", re.I)
_SORTS = {"confidence", "top", "new", "controversial", "old", "random", "qa", "live"}


def is_reddit_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        return parts.scheme.lower() in {"http", "https"} and (
            host == "reddit.com" or host.endswith(".reddit.com") or host == "redd.it"
        )
    except ValueError:
        return False


def _post_target(url: str) -> tuple[str, dict]:
    parts = urlsplit(url)
    if not is_reddit_url(url) or parts.port not in {None, 80, 443}:
        raise EddritError("Reddit scraper only accepts Reddit post URLs")
    path = parts.path.removesuffix(".json").rstrip("/")
    if (parts.hostname or "").lower().rstrip(".") == "redd.it":
        match = re.fullmatch(r"/([a-z0-9]+)", path, re.I)
        post_id, comment_id = (match[1], None) if match else (None, None)
    else:
        match = _POST_PATH.fullmatch(path)
        post_id, comment_id = (match[1], match[3]) if match else (None, None)
    if not post_id:
        raise EddritError("Unsupported Reddit URL; use a post/comment permalink or redd.it post link")
    params = {"raw_json": 1, "limit": 100, "depth": 8}
    query = parse_qs(parts.query)
    if query.get("sort", [None])[0] in _SORTS:
        params["sort"] = query["sort"][0]
    if comment_id:
        params["comment"] = comment_id.lower()
    return post_id.lower(), params


def _media_links(post: dict) -> list[str]:
    links = []
    external = post.get("url_overridden_by_dest") or post.get("url")
    if external and not post.get("is_self"):
        links.append(external)
    for item in (post.get("media_metadata") or {}).values():
        source = item.get("s") or {}
        links.extend(source[key] for key in ("u", "mp4", "gif") if source.get(key))
    for field in ("secure_media", "media"):
        video = (post.get(field) or {}).get("reddit_video") or {}
        if video.get("fallback_url"):
            links.append(video["fallback_url"])
    return list(dict.fromkeys(html.unescape(link) for link in links
                              if isinstance(link, str) and urlsplit(link).scheme in {"https", "http"}))


def _render(data, post_id: str) -> tuple[str, str]:
    try:
        post = data[0]["data"]["children"][0]["data"]
        comments = data[1]["data"]["children"]
        if post["id"].lower() != post_id or not isinstance(post["title"], str) or not isinstance(comments, list):
            raise ValueError()
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        raise EddritError("Reddit returned an invalid post/comment response") from None
    title = html.unescape(post["title"])
    chunks = [f"# {title}"]
    text = post.get("selftext") or ""
    if text:
        chunks.append(text)
    for link in _media_links(post):
        chunks.append(link)
    chunks.append("## Comments (loaded comments only)")
    loaded, omitted = 0, False
    stack = [(item, 0) for item in reversed(comments)]
    while stack:
        item, depth = stack.pop()
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            raise EddritError("Reddit returned an invalid comment")
        comment = item["data"]
        if item.get("kind") == "more":
            omitted = True
            continue
        if item.get("kind") != "t1" or not isinstance(comment.get("body"), str):
            raise EddritError("Reddit returned an invalid comment")
        if loaded >= 100 or depth >= 8:
            omitted = True
            continue
        body = comment["body"]
        prefix = "  " * depth
        chunks.append(f"{prefix}- u/{comment.get('author', '[deleted]')}:\n" +
                      "\n".join(f"{prefix}  {line}" for line in body.splitlines()))
        loaded += 1
        replies = comment.get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            stack.extend((child, depth + 1) for child in reversed(children))
    if omitted:
        chunks.append("Some comments were not loaded; this is not the complete discussion.")
    return title, "\n\n".join(chunks)


def scrape_url_reddit(url: str, timeout: float = 60, *, deadline: float | None = None,
                      url_resolver=None) -> dict:
    end = time.monotonic() + max(0.0, timeout)
    if deadline is not None:
        end = min(end, deadline)
    try:
        remaining(end)
        safe_url = validate_scrape_url(url, resolver=url_resolver)
        post_id, params = _post_target(safe_url)
        data = get_post_json(post_id, params, end, resolver=url_resolver)
        title, markdown = _render(data, post_id)
        return {"url": safe_url, "title": title, "markdown": markdown,
                "length": len(markdown), "via": "reddit"}
    except (EddritError, UrlSecurityError, TimeoutError) as exc:
        return {"url": url, "error": str(exc)}
    except ImportError:
        return {"url": url, "error": "Reddit scraper requires curl-cffi; install project dependencies"}
    except Exception as exc:
        # Curl errors may embed proxy credentials; expose the type only.
        return {"url": url, "error": f"Reddit scrape failed ({type(exc).__name__})"}
