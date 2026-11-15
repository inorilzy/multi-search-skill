"""Read Exa's dashboard balance using its login cookie and read-only endpoints.

These undocumented endpoints were verified against the live Billing page. Its
``displayedBalanceCents`` helper subtracts invoice debt for ordinary plans and
clamps credit balances to zero for the two enterprise plans below. Responses
and transport exceptions may contain account data, so diagnostics are fixed.

A Chrome login also links the account's search keys, using the endpoints behind
the dashboard's API keys page: session identity, the key list (public ids and
6-character bearer prefixes), reveal of a legacy key, and key creation. Both
POSTs carry the page's Idempotency-Key header and are never retried.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
import uuid

from ...state.key_state import key_fingerprint
from ...state.keys import _read_keys_file, default_keys_file
from ...support.http import read_limited
from .. import oauth_store
from ..base import BalanceContext

DASHBOARD_ORIGIN = "https://dashboard.exa.ai"
CREDITS_URL = f"{DASHBOARD_ORIGIN}/api/get-credits"
PLAN_URL = f"{DASHBOARD_ORIGIN}/api/orb/get-orb-plan"
SESSION_URL = f"{DASHBOARD_ORIGIN}/api/auth/session"
KEYS_URL = f"{DASHBOARD_ORIGIN}/api/get-api-keys"
REVEAL_URL = f"{DASHBOARD_ORIGIN}/api/reveal-api-key"
CREATE_URL = f"{DASHBOARD_ORIGIN}/api/create-api-key"
NEW_KEY_NAME = "multi-search"
COOKIE_ENV = "EXA_DASHBOARD_COOKIE"
MAX_BYTES = 256 * 1024
_ENTERPRISE_PLANS = {"search_api_enterprise", "search_websets"}
# Vercel answers the default Python-urllib agent with a 429 challenge; a browser agent is served normally.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


class DashboardUnavailable(ValueError):
    """A fixed public diagnostic, with no response or credential content."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def parse_dashboard(credits: dict, plan: dict | None) -> dict:
    """Return only the displayed USD balance and billing-exemption flag."""
    if not isinstance(credits, dict) or "error" in credits:
        raise DashboardUnavailable("Exa: dashboard 余额响应格式未知。")
    if credits.get("orbBillingExempt") is True:
        return {"remaining": None, "billing_exempt": True}
    cents = _number(credits.get("orbCreditsInCents"))
    debt = _number(credits.get("orbInvoiceDebt") if credits.get("orbInvoiceDebt") is not None else 0)
    if cents is None or debt is None:
        raise DashboardUnavailable("Exa: dashboard 余额字段缺失或无效。")
    if not isinstance(plan, dict) or "error" in plan or "subscription" not in plan:
        raise DashboardUnavailable("Exa: dashboard 套餐响应格式未知。")
    subscription = plan["subscription"]
    plan_id = None
    if subscription is not None:
        if not isinstance(subscription, dict) or not isinstance(subscription.get("plan"), dict):
            raise DashboardUnavailable("Exa: dashboard 套餐响应格式未知。")
        plan_id = subscription["plan"].get("external_plan_id")
        if plan_id is not None and not isinstance(plan_id, str):
            raise DashboardUnavailable("Exa: dashboard 套餐响应格式未知。")
    displayed = max(cents, 0) if plan_id in _ENTERPRISE_PLANS else cents - debt
    remaining = _number(displayed / 100)
    if remaining is None:
        raise DashboardUnavailable("Exa: dashboard 余额字段无效。")
    return {"remaining": remaining, "billing_exempt": False}


def _fetch_json(url: str, cookie: str, ctx: BalanceContext, body: dict | None = None):
    headers = {"Cookie": cookie, "Accept": "application/json", "User-Agent": BROWSER_USER_AGENT}
    data = None
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": DASHBOARD_ORIGIN,
                        "Idempotency-Key": str(uuid.uuid4())})
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if body is None else "POST")
    try:
        with ctx.open(request, retries=0) as response:
            return json.loads(read_limited(response, max_bytes=MAX_BYTES))
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise DashboardUnavailable("Exa: dashboard 登录已失效，请重新登录。", "invalid") from None
        if exc.code == 429:
            raise DashboardUnavailable("Exa: dashboard 请求频率受限。", "rate_limit") from None
        raise DashboardUnavailable("Exa: dashboard 请求失败。") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise DashboardUnavailable("Exa: dashboard 请求不可用。") from None
    except (ValueError, TypeError):
        raise DashboardUnavailable("Exa: dashboard 响应无效或超过大小限制。") from None


def _secret(value) -> str:
    if (not isinstance(value, str) or not 0 < len(value.strip()) <= 512
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in value.strip())):
        raise DashboardUnavailable("Exa: dashboard 未返回有效的 API Key。")
    return value.strip()


def fetch_profile(cookie: str, ctx: BalanceContext) -> dict | None:
    """The logged-in user's validated id/email/name, or None when the session has none."""
    from .brave_dashboard import _cookie_secrets, _profile

    session = _fetch_json(SESSION_URL, cookie, ctx)
    return _profile(session.get("user") if isinstance(session, dict) else None, _cookie_secrets(cookie))


def account_search_keys(cookie: str, ctx: BalanceContext, saved: list[str]) -> tuple[list[str], str]:
    """Return the team's search keys for this login and how they were found.

    Saved keys matching a listed key's bearer prefix are reused without revealing
    anything. Otherwise the dashboard's own first usable key (not marketplace
    managed, still revealable) is revealed; a team with no key gets a new one.
    """
    listed = _fetch_json(KEYS_URL, cookie, ctx)
    rows = listed.get("apiKeys") if isinstance(listed, dict) else None
    if not isinstance(rows, list):
        raise DashboardUnavailable("Exa: dashboard Key 列表格式未知。")
    rows = [row for row in rows if isinstance(row, dict) and row.get("enabled") is not False]
    found = []
    for row in rows:
        prefix = row.get("bearerPrefix")
        matches = [key for key in saved if isinstance(prefix, str) and len(prefix) >= 6 and key.startswith(prefix)]
        if len(matches) == 1 and matches[0] not in found:
            found.append(matches[0])
    if found:
        return found, "matched"
    usable = next((row for row in rows if not row.get("managedBy") and row.get("hasLegacyBearer") is not False
                   and isinstance(row.get("publicId"), str)), None)
    if usable is not None:
        revealed = _fetch_json(REVEAL_URL, cookie, ctx, {"publicId": usable["publicId"]})
        return [_secret(revealed.get("legacyBearerSecret") if isinstance(revealed, dict) else None)], "revealed"
    if rows:
        raise DashboardUnavailable("Exa: 账号已有 Key，但新格式 Key 的明文无法再次读取，请手动添加。")
    created = _fetch_json(CREATE_URL, cookie, ctx, {"apiKeyName": NEW_KEY_NAME})
    api_key = created.get("apiKey") if isinstance(created, dict) else None
    return [_secret(api_key.get("bearer") if isinstance(api_key, dict) else None)], "created"


def _saved_search_keys() -> list[str]:
    from ..balance import _credential_values

    return list(_credential_values(_read_keys_file(default_keys_file()).get("exa")))


def sync_account(ctx: BalanceContext, expected_reference: str | None = None) -> tuple[dict | None, str | None]:
    """Link a verified Exa Chrome login to an account holding its search keys.

    Returns ``(account, notice)``. Key lookup failures keep the login and become
    the notice; storage failures propagate to the caller.
    """
    from .. import accounts
    from ..login import _save_key

    if os.environ.get(COOKIE_ENV):
        return None, None
    record = oauth_store.get_entry("exa_admin") or {}
    cookie = record.get("cookie_header")
    reference = oauth_store.balance_credential_ref("exa_admin", record)
    if not isinstance(cookie, str) or not cookie.strip() or (expected_reference and reference != expected_reference):
        return None, None
    _, data = accounts._load(None)
    if data.get("exa_admin"):
        return None, None
    fingerprint = key_fingerprint(reference)
    for row in accounts.list_accounts("exa")["exa"]:
        # A user who moved this login into a manual group keeps that grouping.
        if (row["id"] != accounts.DEFAULT_ACCOUNT_ID and row["source"] == "manual"
                and row["balance_credentials"].get("exa_admin") == fingerprint):
            return row, None
    try:
        profile = fetch_profile(cookie, ctx)
    except DashboardUnavailable:
        profile = None
    notice = None
    try:
        keys, how = account_search_keys(cookie, ctx, _saved_search_keys())
        for key in keys:
            _save_key("exa", key)
        if how == "created":
            notice = f"账号下没有 Key，已自动创建 {NEW_KEY_NAME} Key 并关联到此账号。"
    except DashboardUnavailable as exc:
        keys, notice = [], f"已登录，但自动获取搜索 Key 失败：{exc}"
    login_id = record.get("login_id")
    identity = ((profile or {}).get("email") or ((profile or {}).get("id") and f"exa-user:{profile['id']}")
                or (f"oauth-login:exa:{login_id}" if isinstance(login_id, str) and login_id.strip() else reference))
    row = accounts.upsert_oauth_account(
        "exa", identity, name=(profile or {}).get("name") or (profile or {}).get("email") or "Exa 控制台登录",
        keys=[key_fingerprint(key) for key in keys],
        balance_credentials={"exa_admin": fingerprint},
    )
    return row, notice


def fetch_dashboard(cookie: str, ctx: BalanceContext) -> dict:
    """GET the two dashboard endpoints without creating keys or paid requests."""
    if not cookie.strip() or "\r" in cookie or "\n" in cookie:
        raise DashboardUnavailable("Exa: dashboard 登录凭据格式无效。", "invalid")
    credits = _fetch_json(CREDITS_URL, cookie, ctx)
    if isinstance(credits, dict) and credits.get("orbBillingExempt") is True:
        return parse_dashboard(credits, None)
    return parse_dashboard(credits, _fetch_json(PLAN_URL, cookie, ctx))
