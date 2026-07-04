"""Browser-backed Reddit content searcher (CloakBrowser).

Unlike the API searchers, this source searches Reddit and reads the top post
bodies inside one logged-in CloakBrowser context, returning results with inline
``scraped_content`` so the scrape stage does not re-fetch them.

The pure helpers here (URL building, block detection, result shaping, config
resolution) are dependency-free and unit-tested without launching a browser.
The browser plumbing is imported lazily so the rest of the MCP keeps working
when ``cloakbrowser`` is not installed.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import quote_plus

from ...support.secrets import scrub_secrets


SOURCE_NAME = "reddit-browser"

_DEFAULT_PROFILE = str(Path.home() / ".multi-search" / "browser-profiles" / "reddit")
_DEFAULT_CONCURRENCY = 10
_DEFAULT_MAX_COMMENTS = 8


# Reddit interstitials we must treat as auth/anti-bot failures rather than
# results. Kept specific so a post body that merely contains "blocked" is not
# misclassified (see tests).
_BLOCK_MARKERS = (
    "blocked by network security",
    "prove your humanity",
    "whoa there, pardner",
    "your request has been blocked",
)


def build_search_url(query: str) -> str:
    """Return the Reddit search URL that reliably renders results for a query.

    ``sort=relevance&t=all`` is required: the bare ``/search/?q=`` entry point
    intermittently trips Reddit's network-security challenge in automation.
    """
    return f"https://www.reddit.com/search/?q={quote_plus(query)}&sort=relevance&t=all"


def is_blocked_text(text: str) -> bool:
    """Return True when page text is a Reddit block/challenge interstitial."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _content_markdown(raw: dict) -> str:
    parts: list[str] = []
    post_text = (raw.get("post_text") or "").strip()
    if post_text:
        parts.append(post_text)
    comments = [c.strip() for c in (raw.get("comments") or []) if c and c.strip()]
    if comments:
        rendered = "\n\n".join(f"{idx}. {body}" for idx, body in enumerate(comments, 1))
        parts.append("## Top comments\n\n" + rendered)
    return "\n\n".join(parts).strip()


def _description(raw: dict) -> str:
    subreddit = (raw.get("subreddit") or "").strip()
    sub = f"r/{subreddit}" if subreddit else ""
    preview = (raw.get("post_text") or "").strip().replace("\n", " ")
    if not preview:
        comments = raw.get("comments") or []
        preview = (comments[0] if comments else "").strip().replace("\n", " ")
    preview = preview[:200]
    return " · ".join(part for part in (sub, preview) if part)


def shape_result(raw: dict, *, want_content: bool) -> dict:
    """Map an extracted post dict to the MCP result contract.

    With ``want_content`` the post body and comments are inlined as
    ``scraped_content`` (and flagged ``scraped``) so the scrape stage skips this
    URL. Without it, only a lightweight search card is returned.
    """
    row: dict = {
        "source": SOURCE_NAME,
        "title": raw.get("title") or raw.get("url") or "",
        "url": raw.get("url") or "",
        "description": _description(raw),
    }
    subreddit = (raw.get("subreddit") or "").strip()
    if subreddit:
        row["subreddit"] = subreddit
    if want_content:
        content = _content_markdown(raw)
        row["scraped_content"] = content
        row["scraped"] = True
        row["scrape_via"] = SOURCE_NAME
    return row


def _coerce_int(value, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 1 else default


def resolve_reddit_config(value) -> dict:
    """Normalize the ``reddit_browser`` key value into a settings dict.

    Accepts a dict (full settings), a string (treated as the cookie export
    path), or falsy (no cookie export). Environment variables provide fallbacks
    so credentials need not live in config files.
    """
    raw: dict = value if isinstance(value, dict) else {}
    cookie_export = raw.get("cookie_export") or ""
    if isinstance(value, str):
        cookie_export = value
    cookie_export = cookie_export or os.getenv("REDDIT_COOKIE_EXPORT", "")
    profile = raw.get("profile") or os.getenv("REDDIT_BROWSER_PROFILE", "") or _DEFAULT_PROFILE
    return {
        "cookie_export": cookie_export,
        "profile": profile,
        "concurrency": _coerce_int(raw.get("concurrency"), _DEFAULT_CONCURRENCY),
        "max_comments": _coerce_int(raw.get("max_comments"), _DEFAULT_MAX_COMMENTS),
    }


def _error_row(message: str) -> list[dict]:
    return [{"source": SOURCE_NAME, "error": message}]


def _default_fetch(query, *, count, config, want_content, deadline):
    # Lazy import so the MCP runs without cloakbrowser installed.
    from ...browser.cloak_runtime import fetch_reddit

    return fetch_reddit(
        query, count=count, config=config, want_content=want_content, deadline=deadline,
    )


def search_reddit_browser(
    query: str,
    count: int = 10,
    key_value=None,
    *,
    want_content: bool = True,
    timeout: float | None = None,
    fetch=None,
) -> list[dict]:
    """Search Reddit via CloakBrowser and return inlined-content result rows.

    ``fetch`` is an injection seam for tests; the default drives a real browser.
    """
    config = resolve_reddit_config(key_value)
    if not config["cookie_export"]:
        return _error_row(
            "skipped: missing reddit cookie export "
            "(set reddit_browser.cookie_export or REDDIT_COOKIE_EXPORT)"
        )

    fetch = fetch or _default_fetch
    deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
    try:
        outcome = fetch(
            query, count=count, config=config, want_content=want_content, deadline=deadline,
        )
    except Exception as exc:  # noqa: BLE001 - provider boundary returns error rows
        return _error_row(f"reddit-browser failed: {scrub_secrets(exc)}")

    if outcome.get("error"):
        return _error_row("reddit cookies expired or blocked; re-export cookies")

    posts = outcome.get("posts") or []
    if not posts and outcome.get("links_found"):
        # Search saw posts but every post page was blocked/empty this run.
        # Surface a retryable error instead of a misleading empty result.
        return _error_row(
            "reddit posts were blocked while reading; retry "
            "(consider lower concurrency or refreshed cookies)"
        )
    return [shape_result(post, want_content=want_content) for post in posts]
