"""CloakBrowser runtime for browser-backed sources.

Phase-1 lifecycle model: a module-level lock serializes every browser session
so the SearchRunner daemon-thread fanout and the service layer ``expand``
concurrency cannot open multiple Chromium instances against the same persistent
profile (single-instance profile lock) or leak overlapping browsers.

Each call launches a persistent context and closes it in ``finally`` so a
timed-out search thread cannot leak a Chromium process. ``cloakbrowser`` is
imported lazily inside the session runner so importing this module never
requires the optional dependency.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable

from .cookie_export import load_cookie_export


# Serializes browser sessions across threads (see module docstring).
_SESSION_LOCK = threading.Lock()

# Reddit recipe constants validated against the live site during development.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
_LAUNCH_ARGS = ["--disable-http2"]
_BLOCKED_RESOURCE_TYPES = {"font", "image", "media"}


def fetch_reddit(
    query: str,
    *,
    count: int,
    config: dict,
    want_content: bool,
    deadline: float | None,
    _run: "Callable[..., dict] | None" = None,
) -> dict:
    """Run one Reddit browser session under the global session lock.

    ``_run`` is an injection seam for tests; the default drives CloakBrowser.
    Returns ``{"posts": [...]}`` or ``{"posts": [], "error": "..."}``.
    """
    runner = _run or _run_reddit_session
    with _SESSION_LOCK:
        return runner(
            query, count=count, config=config, want_content=want_content, deadline=deadline,
        )


def _run_reddit_session(query, *, count, config, want_content, deadline) -> dict:
    return asyncio.run(
        _reddit_session_async(
            query, count=count, config=config, want_content=want_content,
        )
    )


async def _reddit_session_async(query, *, count, config, want_content) -> dict:
    from cloakbrowser import launch_persistent_context_async

    from ..search.searchers.reddit_browser import build_search_url, is_blocked_text

    cookies: list[dict[str, Any]] = []
    local_storage: dict[str, str] = {}
    if config.get("cookie_export"):
        cookies, local_storage = load_cookie_export(config["cookie_export"])

    context = await launch_persistent_context_async(
        config["profile"],
        headless=True,
        locale="en-US",
        timezone="America/Los_Angeles",
        humanize=True,
        user_agent=_USER_AGENT,
        args=_LAUNCH_ARGS,
    )

    async def _block(route):
        if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()

    try:
        await context.route("**/*", _block)
        if cookies:
            await context.add_cookies(cookies)
        await _prime_session(context, local_storage)
        links = await _search_links(context, query, count, build_search_url)
        semaphore = asyncio.Semaphore(max(1, int(config.get("concurrency", 10))))
        max_comments = max(1, int(config.get("max_comments", 8)))

        async def _guarded(item):
            async with semaphore:
                return await _fetch_post(context, item, max_comments, is_blocked_text)

        posts = await asyncio.gather(*(_guarded(item) for item in links))
        return {"posts": [p for p in posts if p], "links_found": len(links)}
    finally:
        await context.close()


async def _prime_session(context, local_storage: dict) -> None:
    page = await context.new_page()
    try:
        await page.goto("https://www.reddit.com/", wait_until="domcontentloaded", timeout=30_000)
        if local_storage:
            for key, value in local_storage.items():
                await page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, value])
            await page.reload(wait_until="domcontentloaded", timeout=30_000)
    finally:
        await page.close()


async def _search_links(context, query, count, build_search_url):
    page = await context.new_page()
    try:
        await page.goto(build_search_url(query), wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(1_800)
        for _ in range(3):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(500)
            if await page.locator('a[href*="/comments/"]').count() >= count:
                break
        return await page.evaluate(
            r"""
            (count) => {
              const clean = (s) => (s || '').trim().replace(/\s+/g, ' ');
              const out = [];
              const seen = new Set();
              for (const a of document.querySelectorAll('a[href]')) {
                const href = a.href.split('?')[0];
                const title = clean(a.innerText || a.getAttribute('aria-label'));
                if (!href.includes('/comments/') || href.includes('/user/')) continue;
                if (!title || title.length < 8 || seen.has(href)) continue;
                seen.add(href);
                const subreddit = (href.match(/\/r\/([^/]+)\//) || [])[1] || '';
                out.push({title, url: href, subreddit});
                if (out.length >= count) break;
              }
              return out;
            }
            """,
            count,
        )
    finally:
        await page.close()


async def _fetch_post(context, item, max_comments, is_blocked_text):
    page = await context.new_page()
    try:
        await page.goto(item["url"], wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(800)
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(500)
        detail = await page.evaluate(
            r"""
            (maxComments) => {
              const clean = (s) => (s || '').trim().replace(/\s+/g, ' ');
              const post = document.querySelector('shreddit-post');
              const comments = [...document.querySelectorAll('shreddit-comment')]
                .slice(0, maxComments)
                .map((node) => clean(node.innerText))
                .filter(Boolean);
              return {
                h1: clean(document.querySelector('h1')?.innerText),
                postText: clean(post?.innerText),
                comments,
                bodyText: clean(document.body.innerText).slice(0, 400),
              };
            }
            """,
            max_comments,
        )
        if is_blocked_text(detail.get("bodyText") or ""):
            return None
        return {
            "title": detail.get("h1") or item.get("title"),
            "url": item["url"],
            "subreddit": item.get("subreddit", ""),
            "post_text": detail.get("postText") or "",
            "comments": detail.get("comments") or [],
        }
    finally:
        await page.close()
