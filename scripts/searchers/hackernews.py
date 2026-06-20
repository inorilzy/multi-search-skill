"""Hacker News search via the Algolia API."""
import json
import re
import urllib.parse
import urllib.request

from ..http import urlopen_retry


_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: str) -> str:
    return _TAG_RE.sub("", value or "").strip()


def _hackernews_item_url(object_id) -> str:
    return f"https://news.ycombinator.com/item?id={object_id}"


def search_hackernews(query: str, count: int = 10, timeout: float = 20) -> list:
    """Search Hacker News stories.

    The Hacker News Algolia API powers practical keyword search for Hacker News.
    Results prefer the story's submitted URL and fall back to the Hacker News
    discussion URL.
    """
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": max(1, count),
    }
    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "multi-search/1.0"},
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "hackernews", "error": str(e)[:300]}]

    items = []
    for hit in data.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        object_id = hit.get("objectID") or hit.get("story_id")
        story_url = hit.get("url") or (hit.get("story_url") or "")
        hackernews_url = _hackernews_item_url(object_id) if object_id else ""
        title = _plain_text(hit.get("title") or hit.get("story_title") or "")
        if not title:
            title = hackernews_url or story_url or "(no title)"
        comments = hit.get("num_comments")
        points = hit.get("points")
        author = hit.get("author") or ""
        created = hit.get("created_at") or ""
        detail = []
        if points is not None:
            detail.append(f"{points} points")
        if comments is not None:
            detail.append(f"{comments} comments")
        if author:
            detail.append(f"by {author}")
        if created:
            detail.append(created[:10])
        items.append({
            "source": "hackernews",
            "title": title,
            "url": story_url or hackernews_url,
            "description": " · ".join(detail),
        })
    return items
