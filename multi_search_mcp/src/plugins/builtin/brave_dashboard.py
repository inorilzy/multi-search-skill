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
import urllib.parse
import urllib.request
from typing import Any

from ...state.key_state import key_fingerprint
from ...state.keys import _read_keys_file, default_keys_file
from ...support.secrets import scrub_secrets
from .. import oauth_store
from ..base import BalanceContext

DASHBOARD_ORIGIN = "https://api-dashboard.search.brave.com"
DATA_URL = f"{DASHBOARD_ORIGIN}/app/dashboard/__data.json"
DASHBOARD_URL = f"{DASHBOARD_ORIGIN}/app/dashboard"
# The API keys page lists every key (in full) under its plan subscription; ?/addApiKey adds one.
KEYS_DATA_URL = f"{DASHBOARD_ORIGIN}/app/keys/__data.json"
ADD_KEY_URL = f"{DASHBOARD_ORIGIN}/app/keys?/addApiKey"
NEW_KEY_NAME = "multi-search"
NO_SEARCH_PLAN = "no search plan"
# Plans whose keys cannot call web search; every other plan (Search, Free, Base, Pro, ...) can.
_NON_SEARCH_PLANS = ("answer", "suggest", "spell")
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


def _read(url: str, cookie: str, ctx: BalanceContext, form: dict | None = None) -> str:
    if not cookie or any(ord(ch) < 32 or ord(ch) == 127 for ch in cookie):
        raise DashboardUnavailable("invalid cookie")
    headers = {"Cookie": cookie, "Accept": "*/*"}
    data = None
    if form is not None:
        # A SvelteKit form action answers JSON when asked, and checks the Origin for CSRF.
        headers.update({"Accept": "application/json", "Origin": DASHBOARD_ORIGIN, "x-sveltekit-action": "true",
                        "Content-Type": "application/x-www-form-urlencoded"})
        data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if form is None else "POST")
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
    return raw.decode("utf-8", errors="replace")


def fetch_dashboard(cookie: str, ctx: BalanceContext) -> dict:
    """Read and parse the dashboard data with the given cookie header value."""
    data = parse_dashboard(_read(DATA_URL, cookie, ctx))
    data["profile"] = _profile(data["profile"], _cookie_secrets(cookie))
    return data


def _searchable(plan: Any) -> bool:
    name = plan.get("name") if isinstance(plan, dict) else None
    return isinstance(name, str) and not any(word in name.lower() for word in _NON_SEARCH_PLANS)


def _search_key(value: Any) -> str | None:
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 256 or any(ord(ch) < 33 or ord(ch) == 127 for ch in value.strip()):
        return None
    return value.strip()


def parse_keys_page(text: str) -> dict:
    """Return the page csrf, active search-plan keys and active search-plan subscription ids."""
    page: dict = {}
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
            for node in item["nodes"]:
                if isinstance(node, dict) and isinstance(node.get("data"), list) and node["data"]:
                    hydrated = _hydrate(node["data"], 0)
                    if isinstance(hydrated, dict):
                        page.update(hydrated)
        elif item.get("type") == "chunk" and isinstance(item.get("id"), int) and isinstance(item.get("data"), list):
            chunks[item["id"]] = _hydrate(item["data"], 0)
    resolve = lambda value: chunks.get(value["$ref"]) if isinstance(value, dict) and "$ref" in value else value
    tokens, subscriptions = resolve(page.get("tokens")), resolve(page.get("subscriptions"))
    if not isinstance(tokens, list) or not isinstance(subscriptions, list):
        raise DashboardUnavailable("no keys page data")
    live = lambda row: isinstance(row, dict) and row.get("status") == "active" and row.get("deleted_at") is None
    keys = [key for row in tokens if live(row) and _searchable(row.get("plan")) and (key := _search_key(row.get("token")))]
    plans = [row["id"] for row in subscriptions
             if live(row) and _searchable(row.get("plan")) and isinstance(row.get("id"), str) and row["id"]]
    csrf = page.get("csrf")
    return {"csrf": csrf if isinstance(csrf, str) and csrf else None, "keys": list(dict.fromkeys(keys)), "subscriptions": plans}


def search_keys(cookie: str, ctx: BalanceContext, saved: list[str]) -> tuple[list[str], str]:
    """Return this login's search keys and how they were found: matched, listed or created.

    The API keys page lists every key in full. Saved keys that appear there are
    linked as they are; otherwise the first search-plan key is used. Only a
    search subscription without any key gets a new one; a subscription itself
    is never created, because that is a billing decision.
    """
    page = parse_keys_page(_read(KEYS_DATA_URL, cookie, ctx))
    matched = [key for key in page["keys"] if key in saved]
    if matched:
        return matched, "matched"
    if page["keys"]:
        return page["keys"][:1], "listed"
    if not page["subscriptions"] or not page["csrf"]:
        raise DashboardUnavailable(NO_SEARCH_PLAN)
    result = _read(ADD_KEY_URL, cookie, ctx, {
        "csrf": page["csrf"], "subscription_id": page["subscriptions"][0], "name": NEW_KEY_NAME,
    })
    try:
        reply = json.loads(result)
        added = _hydrate(json.loads(reply["data"]), 0) if reply.get("type") == "success" else None
    except (ValueError, TypeError, KeyError, AttributeError):
        added = None
    key = _search_key(added.get("token")) if isinstance(added, dict) else None
    if key is None:
        raise DashboardUnavailable("add key failed")
    return [key], "created"


def link_account_keys(cookie: str, ctx: BalanceContext, account_id: str | None) -> str | None:
    """Save this login's search keys and move unassigned ones into its account; return a notice."""
    from .. import accounts
    from ..balance import _credential_values
    from ..login import _save_key

    saved = list(_credential_values(_read_keys_file(default_keys_file()).get("brave")))
    try:
        keys, how = search_keys(cookie, ctx, saved)
    except DashboardUnavailable as exc:
        if str(exc) == NO_SEARCH_PLAN:
            return "已登录，但 Brave 账号还没有可用于搜索的套餐；请先在控制台订阅（订阅后会自动生成 Key）。"
        return "已登录，但自动获取搜索 Key 失败，请稍后重试或手动添加。"
    for key in keys:
        _save_key("brave", key)
    if account_id:
        owners = {fp: row["id"] for row in accounts.list_accounts("brave")["brave"] for fp in row["keys"]}
        for key in keys:
            # Keys a user already grouped elsewhere keep that grouping.
            if owners.get(key_fingerprint(key)) == accounts.DEFAULT_ACCOUNT_ID:
                accounts.move_key("brave", key_fingerprint(key), account_id)
    return f"账号下没有 Key，已自动创建 {NEW_KEY_NAME} Key 并关联到此账号。" if how == "created" else None
