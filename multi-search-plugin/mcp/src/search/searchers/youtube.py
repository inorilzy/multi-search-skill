"""YouTube video search via YouTube Data API."""
import json
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


def search_youtube(query: str, api_key: str, count: int = 10, timeout: float = 20) -> list:
    """Search YouTube videos and return metadata-only results."""
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max(1, min(count, 50)),
        "key": api_key,
    }
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "multi-search/1.0"},
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return [{"source": "youtube", "error": scrub_secrets(exc, api_key)}]

    if isinstance(data, dict) and data.get("error"):
        return [{"source": "youtube", "error": scrub_secrets(json.dumps(data["error"], ensure_ascii=False), api_key)}]

    items = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        video_id = ((row.get("id") or {}).get("videoId") or "").strip()
        snippet = row.get("snippet") if isinstance(row.get("snippet"), dict) else {}
        if not video_id:
            continue
        channel = snippet.get("channelTitle") or ""
        published = snippet.get("publishedAt") or ""
        desc_parts = []
        if channel:
            desc_parts.append(channel)
        if published:
            desc_parts.append(published[:10])
        description = snippet.get("description") or ""
        if description:
            desc_parts.append(description[:200])
        items.append({
            "source": "youtube",
            "title": snippet.get("title") or video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "description": " · ".join(desc_parts),
            "video_id": video_id,
            "channel": channel,
            "published_at": published,
        })
    return items
