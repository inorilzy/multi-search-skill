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
import re
import unicodedata
import urllib.error
import urllib.request
from typing import Any

from ...state.key_state import key_fingerprint
from ...support.secrets import scrub_secrets
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


def _profile(user: Any, secrets=()) -> dict | None:
    """Allow only bounded identity fields; billing data never leaves the parser."""
    if not isinstance(user, dict):
        return None
    profile = {}
    for field, limit in (("id", 128), ("email", 254), ("name", 120)):
        value = user.get(field)
        if (not isinstance(value, str) or not 0 < len(value) <= limit
                or any(unicodedata.category(ch).startswith("C") or ch in "\u2028\u2029" for ch in value)):
            continue
        value = value.strip()
        if not value or scrub_secrets(value, secrets, limit=len(value)) != value:
            continue
        if field == "id" and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            continue
        if field == "email":
            local, separator, domain = value.rpartition("@")
            labels = domain.split(".")
            if (not separator or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}", local)
                    or local.startswith(".") or local.endswith(".") or ".." in local
                    or len(labels) < 2 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                                             for label in labels)):
                continue
        profile[field] = value
    return profile or None


def _cookie_secrets(cookie: str) -> list[str]:
    return [cookie, *(part.partition("=")[2].strip() for part in cookie.split(";"))]


def sync_account(profile: Any, expected_reference: str | None = None) -> dict | None:
    """Fill unassigned account metadata without rewriting a saved browser session."""
    from .. import accounts

    if os.environ.get(COOKIE_ENV):
        return None
    record = oauth_store.get_entry("brave_dashboard") or {}
    cookie = record.get("cookie_header")
    reference = oauth_store.balance_credential_ref("brave_dashboard", record)
    # The request may finish after another Chrome login has replaced this session.
    if not isinstance(cookie, str) or not cookie or (expected_reference and reference != expected_reference):
        return None
    profile = _profile(profile, _cookie_secrets(cookie))
    if not profile or not (profile.get("email") or profile.get("id")):
        return None
    current = oauth_store.get_entry("brave_dashboard") or {}
    if (oauth_store.balance_credential_ref("brave_dashboard", current) != reference
            or current.get("cookie_header") != cookie):
        return None
    fingerprint = key_fingerprint(reference)
    for row in accounts.list_accounts("brave")["brave"]:
        if row["id"] != accounts.DEFAULT_ACCOUNT_ID and row["balance_credentials"].get("brave_dashboard") == fingerprint:
            return row
    # Refreshes may fill an unassigned login, but must respect a user's grouping.
    identity = profile.get("email") or f"brave-user:{profile['id']}"
    return accounts.upsert_oauth_account(
        "brave", identity, name=profile.get("name") or profile.get("email") or "Brave Search 登录",
        balance_credentials={"brave_dashboard": fingerprint},
    )


def parse_dashboard(text: str) -> dict:
    """Return usage fields and optional validated ``profile`` (id/email/name only)."""
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
    profile = None
    for node in root["nodes"]:
        if isinstance(node, dict) and isinstance(node.get("data"), list) and node["data"]:
            hydrated = _hydrate(node["data"], 0)
            if isinstance(hydrated, dict):
                if "daysLeftInCycle" in hydrated:
                    page = hydrated
                if "user" in hydrated:
                    profile = _profile(hydrated["user"])
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
    return {"days_left": days_left if isinstance(days_left, int) else None, "plans": plans, "profile": profile}


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
    data = parse_dashboard(raw.decode("utf-8", errors="replace"))
    data["profile"] = _profile(data["profile"], _cookie_secrets(cookie))
    return data
