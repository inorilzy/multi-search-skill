r"""Fast Xiaohongshu browser search + note body extraction via CloakBrowser.

Mirrors scripts/reddit_cloak_fetch.py. Logs in with an exported Cookie
LocalStorage Exporter session, searches Xiaohongshu in-page (a direct goto to
/search_result is gated by a login overlay), reads tokenized note URLs from
``a.cover.mask`` cards, then concurrently opens each note and extracts the
title/description from ``#detail-title`` / ``#detail-desc`` (present in the DOM
even while a login overlay is shown).

Example:
    python scripts/xhs_cloak_fetch.py "agent memory" \
        --cookie-export C:\path\to\xhs-session-export.json \
        --count 10 --concurrency 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from cloakbrowser import launch_persistent_context_async


DEFAULT_PROFILE = Path.home() / ".multi-search" / "browser-profiles" / "xhs-cloak"
EXPLORE_URL = "https://www.xiaohongshu.com/explore"
SEARCH_INPUT_SELECTORS = (
    "input#search-input",
    "input.search-input",
    "input[placeholder*='搜索']",
    "input[type=text]",
)
TOKEN_CARD_SELECTOR = 'a.cover.mask[href*="xsec_token="]'
BLOCKED_RESOURCE_TYPES = {"font", "image", "media"}


def _same_site(value: Any) -> str:
    mapping = {
        "no_restriction": "None",
        "unspecified": "Lax",
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
    }
    return mapping.get(str(value or "").lower(), "Lax")


def load_cookie_export(path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    cookies: list[dict[str, Any]] = []
    for cookie in data.get("cookies") or []:
        item: dict[str, Any] = {
            "name": cookie["name"],
            "value": cookie.get("value", ""),
            "domain": cookie.get("domain") or ".xiaohongshu.com",
            "path": cookie.get("path") or "/",
            "httpOnly": bool(cookie.get("httpOnly")),
            "secure": bool(cookie.get("secure", True)),
            "sameSite": _same_site(cookie.get("sameSite")),
        }
        if cookie.get("expirationDate"):
            item["expires"] = float(cookie["expirationDate"])
        cookies.append(item)

    local_storage = {
        str(key): str(value)
        for key, value in (data.get("localStorage") or {}).items()
    }
    return cookies, local_storage


async def block_heavy_resources(route) -> None:
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    await route.continue_()


async def prime_session(context, cookies: list[dict[str, Any]], local_storage: dict[str, str]) -> None:
    if cookies:
        await context.add_cookies(cookies)
    page = await context.new_page()
    try:
        await page.goto(EXPLORE_URL, wait_until="domcontentloaded", timeout=30_000)
        if local_storage:
            for key, value in local_storage.items():
                try:
                    await page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, value])
                except Exception:
                    pass
            await page.reload(wait_until="domcontentloaded", timeout=30_000)
    finally:
        await page.close()


async def xhs_search(
    context,
    query: str,
    count: int,
    *,
    settle_ms: int,
    scroll_wait_ms: int,
    search_scrolls: int,
    debug: bool = False,
) -> list[dict[str, str]]:
    """Search in-page (direct /search_result goto is overlay-gated) and read token cards."""
    page = await context.new_page()
    try:
        await page.goto(EXPLORE_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(settle_ms)

        typed = False
        for selector in SEARCH_INPUT_SELECTORS:
            box = page.locator(selector)
            if await box.count() == 0:
                continue
            try:
                await box.first.click(timeout=4_000)
                await box.first.fill(query, timeout=4_000)
                await page.keyboard.press("Enter")
                typed = True
                break
            except Exception:
                continue
        if not typed:
            return [{"source": "xiaohongshu", "error": "search input not found (session/login likely invalid)"}]

        deadline = time.monotonic() + (search_scrolls * (scroll_wait_ms / 1000.0)) + 12
        found = 0
        while time.monotonic() < deadline:
            found = await page.locator(TOKEN_CARD_SELECTOR).count()
            if found >= count:
                break
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(scroll_wait_ms)

        if debug:
            body = await page.locator("body").inner_text(timeout=10_000)
            print(json.dumps({
                "debug": "search_page",
                "url": page.url,
                "token_cards": found,
                "body_prefix": body[:300],
            }, ensure_ascii=False), flush=True)

        cards = await page.evaluate(
            r"""
            (count) => {
              const clean = (s) => (s || '').trim().replace(/\s+/g, ' ');
              const out = [];
              const seen = new Set();
              for (const a of document.querySelectorAll('a.cover.mask[href*="xsec_token="]')) {
                const href = a.href;
                const id = href.split('?')[0];
                if (seen.has(id)) continue;
                seen.add(id);
                const card = a.closest('section') || a.parentElement;
                const pick = (sel) => clean(card && (card.querySelector(sel) || {}).innerText);
                out.push({
                  url: href,
                  note_id: id.split('/explore/')[1] || '',
                  title: pick('.title'),
                  author: pick('.author .name') || pick('.author'),
                  likes: pick('.like-wrapper .count') || pick('.count'),
                });
                if (out.length >= count) break;
              }
              return out;
            }
            """,
            count,
        )
        if not cards:
            return [{"source": "xiaohongshu", "error": "no note cards (session expired or search blocked)"}]
        return cards
    finally:
        await page.close()


async def fetch_note(
    context,
    item: dict[str, str],
    *,
    note_wait_ms: int,
    max_chars: int,
) -> dict[str, Any]:
    page = await context.new_page()
    started = time.perf_counter()
    try:
        await page.goto(item["url"], wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(note_wait_ms)
        detail = await page.evaluate(
            r"""
            (maxChars) => {
              const clean = (s) => (s || '').trim().replace(/\s+/g, ' ');
              const sel = (s) => document.querySelector(s);
              const title = clean(sel('#detail-title')?.innerText);
              const desc = clean(sel('#detail-desc')?.innerText);
              const author = clean(sel('.author-wrapper .username')?.innerText) || clean(sel('.author .name')?.innerText);
              const tags = [...document.querySelectorAll('#detail-desc .tag, a.tag')].map(t => clean(t.innerText)).filter(Boolean);
              const date = clean(sel('.bottom-container .date, .date')?.innerText);
              return {
                title,
                desc: (desc || '').slice(0, maxChars),
                author,
                tags: tags.slice(0, 12),
                date,
                has_body: !!(title || desc),
              };
            }
            """,
            max_chars,
        )
        markdown_parts = []
        if detail.get("title"):
            markdown_parts.append(f"# {detail['title']}")
        meta = " · ".join(p for p in (detail.get("author"), detail.get("date"), item.get("likes") and f"♥{item['likes']}") if p)
        if meta:
            markdown_parts.append(meta)
        if detail.get("desc"):
            markdown_parts.append(detail["desc"])
        if detail.get("tags"):
            markdown_parts.append(" ".join(detail["tags"]))
        return {
            **item,
            "title": detail.get("title") or item.get("title"),
            "author": detail.get("author") or item.get("author"),
            "date": detail.get("date"),
            "tags": detail.get("tags") or [],
            "markdown": "\n\n".join(markdown_parts),
            "has_body": bool(detail.get("has_body")),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - keep batch alive
        return {
            **item,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    finally:
        await page.close()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cookies: list[dict[str, Any]] = []
    local_storage: dict[str, str] = {}
    if args.cookie_export:
        cookies, local_storage = load_cookie_export(Path(args.cookie_export).expanduser())

    context = await launch_persistent_context_async(
        Path(args.profile).expanduser(),
        headless=not args.headed,
        locale=args.locale,
        timezone=args.timezone,
        humanize=not args.no_humanize,
        args=["--disable-http2"],
    )
    await context.route("**/*", block_heavy_resources)

    started = time.perf_counter()
    try:
        await prime_session(context, cookies, local_storage)
        search_started = time.perf_counter()
        cards = await xhs_search(
            context,
            args.query,
            args.count,
            settle_ms=args.settle_ms,
            scroll_wait_ms=args.scroll_wait_ms,
            search_scrolls=args.search_scrolls,
            debug=args.debug,
        )
        search_ms = int((time.perf_counter() - search_started) * 1000)
        if cards and cards[0].get("error"):
            return {
                "query": args.query,
                "error": cards[0]["error"],
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "results": [],
            }

        semaphore = asyncio.Semaphore(args.concurrency)

        async def guarded(item: dict[str, str]) -> dict[str, Any]:
            async with semaphore:
                return await fetch_note(
                    context,
                    item,
                    note_wait_ms=args.note_wait_ms,
                    max_chars=args.max_chars,
                )

        notes = await asyncio.gather(*(guarded(item) for item in cards))
        return {
            "query": args.query,
            "count_requested": args.count,
            "count_found": len(cards),
            "count_fetched": len(notes),
            "count_with_body": sum(1 for n in notes if n.get("has_body")),
            "search_ms": search_ms,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "results": notes,
        }
    finally:
        await context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Xiaohongshu search query")
    parser.add_argument("--cookie-export", help="Cookie LocalStorage Exporter JSON path")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Persistent browser profile path")
    parser.add_argument("--count", type=int, default=10, help="Number of notes to fetch")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent note pages")
    parser.add_argument("--max-chars", type=int, default=4000, help="Max chars of note body")
    parser.add_argument("--settle-ms", type=int, default=2000, help="Wait after loading explore page")
    parser.add_argument("--scroll-wait-ms", type=int, default=800, help="Wait between search scrolls")
    parser.add_argument("--search-scrolls", type=int, default=6, help="Max search-result scroll attempts")
    parser.add_argument("--note-wait-ms", type=int, default=2500, help="Wait after note navigation")
    parser.add_argument("--locale", default="zh-CN")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--headed", action="store_true", help="Run headed for debugging/login")
    parser.add_argument("--no-humanize", action="store_true", help="Disable CloakBrowser humanize patching")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--debug", action="store_true", help="Print search page debug snapshot")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = asyncio.run(run(args))
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
