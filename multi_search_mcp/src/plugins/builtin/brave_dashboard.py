"""Brave's real monthly usage, read from its API dashboard.

Brave's API responses carry no credit balance, and its docs point to the
dashboard only (api-dashboard.search.brave.com). The dashboard is a SvelteKit
app: ``/app/dashboard/__data.json`` returns the page data devalue-encoded, one
JSON object per line, with the usage numbers streamed in later "chunk" lines.

The desktop captures the dashboard cookie in its login window and saves it in
owner-only oauth.json, separate from search keys. BRAVE_DASHBOARD_COOKIE may
override it for a single process. A session cookie's lack of an expiry does not
prove that its server-side session expires when a window closes. Reuse the saved
credential until the server rejects it. This page endpoint is undocumented: a
changed shape or expired login makes the caller use a labelled local estimate.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

from .. import oauth_store
from ..base import BalanceContext

DATA_URL = "https://api-dashboard.search.brave.com/app/dashboard/__data.json"
DASHBOARD_URL = "https://api-dashboard.search.brave.com/app/dashboard"
COOKIE_ENV = "BRAVE_DASHBOARD_COOKIE"
_MAX_BYTES = 2 * 1024 * 1024


class DashboardUnavailable(Exception):
    """The dashboard could not be read: logged out, changed shape, or unreachable."""


def _hydrate(data: list, index: Any, active: frozenset = frozenset(), memo: dict | None = None) -> Any:
    """Resolve devalue references, rejecting cycles/deep trees from a changed page."""
    if type(index) is not int or index < 0 or index >= len(data):
        return None
    memo = {} if memo is None else memo
    if index in memo:
        return memo[index]
    if index in active or len(active) >= 48:
        raise DashboardUnavailable("invalid references")
    resolve = lambda ref: _hydrate(data, ref, active | {index}, memo)
    value = data[index]
    if isinstance(value, dict):
        value = {key: resolve(ref) for key, ref in value.items()}
    elif isinstance(value, list):
        if value and value[0] == "Promise":
            # The tag's argument is itself an index, not the promise id.
            value = {"$ref": resolve(value[1]) if len(value) == 2 else None}
        elif value and isinstance(value[0], str):
            value = None  # Date/Set/Map metadata does not carry usage numbers.
        else:
            value = [resolve(ref) for ref in value]
    memo[index] = value
    return value


def cookie_header(reference: str | None = None) -> str:
    """Return a private header value; callers never include it in diagnostics."""
    value = os.environ.get(COOKIE_ENV) or None
    if value is None:
        try:
            record = oauth_store.get_entry("brave_dashboard") or {}
        except oauth_store.OAuthStoreError:
            record = {}
        if reference and oauth_store.balance_credential_ref("brave_dashboard", record) != reference:
            return ""
        value = record.get("cookie_header", "")
    if not isinstance(value, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return ""
    return value.strip()


def _number(value: Any) -> int | float | None:
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def parse_dashboard(text: str) -> dict:
    """Return ``{"days_left", "plans": [{"name", "credit", "requests", "cost", "projected"}]}``."""
    root = None
    chunks: dict[int, Any] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            raise DashboardUnavailable("unparsable line") from None
        if not isinstance(item, dict):
            continue
        if item.get("type") == "redirect":
            raise DashboardUnavailable("logged out")
        if item.get("type") == "data" and isinstance(item.get("nodes"), list):
            root = item
        elif item.get("type") == "chunk" and isinstance(item.get("id"), int) and isinstance(item.get("data"), list):
            chunks[item["id"]] = _hydrate(item["data"], 0)
    if root is None:
        if "<html" in text.lower() or "<!doctype" in text.lower():
            raise DashboardUnavailable("logged out")
        raise DashboardUnavailable("no page data")
    page: dict = {}
    for node in root["nodes"]:
        if isinstance(node, dict) and isinstance(node.get("data"), list) and node["data"]:
            hydrated = _hydrate(node["data"], 0)
            if isinstance(hydrated, dict) and "daysLeftInCycle" in hydrated:
                page = hydrated
    subscription = page.get("subscriptionData")
    usages = (chunks.get(subscription["$ref"]) if "$ref" in subscription else subscription
              ) if isinstance(subscription, dict) else None
    rows = usages.get("subscriptionUsages") if isinstance(usages, dict) else None
    if not isinstance(rows, list):
        raise DashboardUnavailable("no subscription usage")
    plans = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current = row.get("currentMonthUsage") if isinstance(row.get("currentMonthUsage"), dict) else {}
        plans.append({
            "name": row.get("name"),
            "credit": _number(row.get("creditAmount")),
            "requests": _number(current.get("requests")),
            "cost": _number(current.get("cost")),
            "projected": _number(current.get("requestsProjected")),
        })
    if not plans:
        raise DashboardUnavailable("no plans")
    days_left = page.get("daysLeftInCycle")
    return {"days_left": days_left if isinstance(days_left, int) else None, "plans": plans}


def fetch_dashboard(cookie: str, ctx: BalanceContext) -> dict:
    """Read and parse the dashboard data with the given cookie header value."""
    if not cookie or any(ord(ch) < 32 or ord(ch) == 127 for ch in cookie):
        raise DashboardUnavailable("invalid cookie")
    request = urllib.request.Request(DATA_URL, headers={"Cookie": cookie, "Accept": "*/*"})
    try:
        with ctx.open(request, retries=0) as response:
            if hasattr(response, "geturl") and "/login" in response.geturl():
                raise DashboardUnavailable("logged out")
            raw = response.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        reason = "logged out" if exc.code in (401, 403) else "HTTP error"
        exc.close()
        raise DashboardUnavailable(reason) from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        raise DashboardUnavailable("request failed") from None
    if len(raw) > _MAX_BYTES:
        raise DashboardUnavailable("response too large")
    return parse_dashboard(raw.decode("utf-8", errors="replace"))
