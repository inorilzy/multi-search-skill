"""V2EX topic search via the public SOV2EX API."""
import html
import json
import math
import re
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry


_HIGHLIGHT_TAG_RE = re.compile(r"</?em\b[^>]*>", re.IGNORECASE)


def _description(highlight: dict) -> str:
    for field, label in (
        ("content", ""),
        ("reply_list.content", "Reply: "),
        ("postscript_list.content", "Postscript: "),
        ("title", ""),
    ):
        fragments = highlight.get(field, [])
        if not isinstance(fragments, list) or any(
            not isinstance(fragment, str) for fragment in fragments
        ):
            raise ValueError(f"invalid highlight field: {field}")
        text = "\n".join(
            html.unescape(_HIGHLIGHT_TAG_RE.sub("", fragment)).strip()
            for fragment in fragments
        ).strip()
        if text:
            return (label + text)[:300]
    return ""


def _row_from_hit(hit: dict) -> dict:
    if not isinstance(hit, dict) or not isinstance(hit.get("_source"), dict):
        raise ValueError("hit must contain a _source object")
    topic = hit["_source"]
    topic_id = topic.get("id", hit.get("_id"))
    if (
        isinstance(topic_id, bool)
        or not isinstance(topic_id, (str, int))
        or not re.fullmatch(r"[0-9]+", str(topic_id))
        or int(topic_id) <= 0
    ):
        raise ValueError("hit is missing a valid numeric topic id")
    title = topic.get("title", "")
    if title is None:
        title = ""
    if not isinstance(title, str):
        raise ValueError("topic title must be a string")
    highlight = hit.get("highlight", {})
    if highlight is None:
        highlight = {}
    if not isinstance(highlight, dict):
        raise ValueError("highlight must be an object")
    # The index also supplies topic content. Discard it: selected URLs are
    # fetched by the shared body stage only after RRF ranking.
    description = _description(highlight)
    row = {
        "source": "sov2ex",
        "title": title,
        "url": f"https://www.v2ex.com/t/{int(topic_id)}",
        "description": description,
        "content_kind": "excerpt" if description else "metadata",
    }
    created = topic.get("created")
    if isinstance(created, str) and created:
        row["published_at"] = created
    author = topic.get("member")
    if isinstance(author, str) and author:
        row["author"] = author
    replies = topic.get("replies")
    if isinstance(replies, int) and not isinstance(replies, bool):
        row["reply_count"] = replies
    score = hit.get("_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
        row["score"] = score
    return row


def search_sov2ex(query: str, count: int = 10, timeout: float = 20) -> list:
    """Search SOV2EX's V2EX index by relevance, returning only candidates."""
    size = min(50, max(1, count))
    params = {"q": query, "from": 0, "size": size, "sort": "sumup"}
    req = urllib.request.Request(
        "https://www.sov2ex.com/api/search?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "multi-search/1.0", "Accept": "application/json"},
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        if not isinstance(data, dict):
            raise ValueError("response must be an object")
        if data.get("error"):
            raise ValueError(str(data["error"]))
        if not isinstance(data.get("hits"), list):
            raise ValueError("response hits must be an array")
    except Exception as exc:
        return [{"source": "sov2ex", "error": f"SOV2EX: {exc}"[:300]}]

    rows = []
    for index, hit in enumerate(data["hits"][:size], start=1):
        try:
            rows.append(_row_from_hit(hit))
        except ValueError as exc:
            rows.append({"source": "sov2ex", "error": f"SOV2EX hit {index}: {exc}"[:300]})
    if data.get("timed_out"):
        rows.append({
            "source": "sov2ex",
            "error": "SOV2EX search timed out; results may be incomplete",
        })
    return rows
