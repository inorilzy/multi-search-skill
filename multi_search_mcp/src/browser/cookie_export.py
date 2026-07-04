"""Convert "Cookie LocalStorage Exporter" JSON into Playwright-ready data.

The browser extension exports cookies with Chrome-style ``sameSite`` values and
an ``expirationDate`` float. Playwright's ``add_cookies`` expects ``sameSite``
in {"Strict", "Lax", "None"} and an integer-ish ``expires`` field. This module
performs that pure, dependency-free translation so it can be unit-tested without
launching a browser.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SAME_SITE = {
    "no_restriction": "None",
    "none": "None",
    "unspecified": "Lax",
    "lax": "Lax",
    "strict": "Strict",
}


def _same_site(value: Any) -> str:
    return _SAME_SITE.get(str(value or "").lower(), "Lax")


def to_playwright_cookies(raw_cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate exporter cookie dicts to Playwright ``add_cookies`` dicts."""
    cookies: list[dict[str, Any]] = []
    for cookie in raw_cookies or []:
        item: dict[str, Any] = {
            "name": cookie["name"],
            "value": cookie.get("value", ""),
            "domain": cookie.get("domain") or ".reddit.com",
            "path": cookie.get("path") or "/",
            "httpOnly": bool(cookie.get("httpOnly")),
            "secure": bool(cookie.get("secure", True)),
            "sameSite": _same_site(cookie.get("sameSite")),
        }
        if cookie.get("expirationDate"):
            item["expires"] = float(cookie["expirationDate"])
        cookies.append(item)
    return cookies


def load_cookie_export(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Load an exporter JSON file into ``(playwright_cookies, local_storage)``.

    ``local_storage`` values are coerced to ``str`` because they are replayed via
    ``localStorage.setItem`` in the page, which only stores strings.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cookies = to_playwright_cookies(data.get("cookies") or [])
    local_storage = {
        str(key): str(value)
        for key, value in (data.get("localStorage") or {}).items()
    }
    return cookies, local_storage
