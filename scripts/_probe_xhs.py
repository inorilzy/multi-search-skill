import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

from cloakbrowser import launch_persistent_context_async

EXPORT = Path(r"C:\Users\zhiyu_liu\.codex\attachments\c607076d-5d58-417e-8d76-3dfd6565b229\pasted-text.txt")
PROFILE = Path.home() / ".multi-search" / "browser-profiles" / "xhs-probe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")


def same_site(v):
    return {"no_restriction": "None", "unspecified": "Lax", "lax": "Lax",
            "strict": "Strict", "none": "None"}.get(str(v or "").lower(), "Lax")


def redact(url: str) -> str:
    return re.sub(r"xsec_token=[^&]+", "xsec_token=<redacted>", url)


async def main():
    data = json.loads(EXPORT.read_text(encoding="utf-8-sig"))
    cookies = []
    for c in data.get("cookies") or []:
        item = {
            "name": c["name"], "value": c.get("value", ""),
            "domain": c.get("domain") or ".xiaohongshu.com",
            "path": c.get("path") or "/",
            "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure", True)),
            "sameSite": same_site(c.get("sameSite")),
        }
        if c.get("expirationDate"):
            item["expires"] = float(c["expirationDate"])
        cookies.append(item)
    local_storage = {str(k): str(v) for k, v in (data.get("localStorage") or {}).items()}

    ctx = await launch_persistent_context_async(
        PROFILE, headless=True, locale="zh-CN", timezone="Asia/Shanghai",
        humanize=True, user_agent=UA,
    )
    await ctx.add_cookies(cookies)
    page = await ctx.new_page()
    print("cookies_to_add=", len(cookies), "local_storage_keys=", len(local_storage))
    applied = await ctx.cookies("https://www.xiaohongshu.com")
    print("cookies_in_ctx=", len(applied))
    want = {c["name"] for c in cookies}
    got = {c.get("name") for c in applied}
    print("missing_cookies=", sorted(want - got))
    await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(1500)
    home_body = await page.locator("body").inner_text(timeout=10000)
    print("home_prefix=", home_body[:160].replace("\n", " "))

    url = f"https://www.xiaohongshu.com/search_result?keyword={quote_plus('agent memory')}"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2500)
    for _ in range(2):
        await page.mouse.wheel(0, 1600)
        await page.wait_for_timeout(800)

    body = await page.locator("body").inner_text(timeout=10000)
    logged_in = "登录后查看搜索结果" not in body
    print("search_prefix=", body[:200].replace("\n", " "))
    tokens = await page.evaluate(
        """
        () => {
          const sel = 'a.cover.mask[href*="xsec_token="], a.cover[href*="xsec_token="], a.mask[href*="xsec_token="]';
          const out = []; const seen = new Set();
          for (const a of document.querySelectorAll(sel)) {
            if (seen.has(a.href)) continue; seen.add(a.href); out.push(a.href);
          }
          return out;
        }
        """
    )
    print("logged_in=", logged_in)
    print("token_count=", len(tokens))
    if tokens:
        print("sample=", redact(tokens[0]))

    if tokens:
        note = await ctx.new_page()
        await note.goto(tokens[0], wait_until="domcontentloaded", timeout=30000)
        await note.wait_for_timeout(2500)
        probe = await note.evaluate(
            """
            () => {
              const t = (s) => (document.querySelector(s)?.innerText || '').trim().replace(/\\s+/g,' ').slice(0,160);
              return {
                title: document.title,
                detail_title: t('#detail-title'),
                note_title: t('.note-content .title'),
                detail_desc: t('#detail-desc'),
                note_text: t('.note-text'),
                desc: t('.desc'),
                author: t('.author-wrapper .username') || t('.author .name') || t('.username'),
                meta_desc: document.querySelector('meta[name=\"description\"]')?.content?.slice(0,160) || '',
              };
            }
            """
        )
        print("note_probe=", json.dumps(probe, ensure_ascii=False, indent=2))
        await note.close()
    await ctx.close()


asyncio.run(main())
