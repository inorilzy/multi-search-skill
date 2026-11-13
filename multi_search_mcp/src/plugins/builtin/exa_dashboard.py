"""Read Exa's dashboard balance using its login cookie and read-only endpoints.

These undocumented endpoints were verified against the live Billing page. Its
``displayedBalanceCents`` helper subtracts invoice debt for ordinary plans and
clamps credit balances to zero for the two enterprise plans below. Responses
and transport exceptions may contain account data, so diagnostics are fixed.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from ...support.http import read_limited
from ..base import BalanceContext

CREDITS_URL = "https://dashboard.exa.ai/api/get-credits"
PLAN_URL = "https://dashboard.exa.ai/api/orb/get-orb-plan"
COOKIE_ENV = "EXA_DASHBOARD_COOKIE"
MAX_BYTES = 256 * 1024
_ENTERPRISE_PLANS = {"search_api_enterprise", "search_websets"}


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


def _fetch_json(url: str, cookie: str, ctx: BalanceContext):
    request = urllib.request.Request(url, headers={"Cookie": cookie, "Accept": "application/json"})
    try:
        with ctx.open(request, retries=0) as response:
            return json.loads(read_limited(response, max_bytes=MAX_BYTES))
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise DashboardUnavailable("Exa: dashboard 登录已失效，请重新登录。", "invalid") from None
        if exc.code == 429:
            raise DashboardUnavailable("Exa: dashboard 请求频率受限。", "rate_limit") from None
        raise DashboardUnavailable("Exa: dashboard 余额请求失败。") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise DashboardUnavailable("Exa: dashboard 余额请求不可用。") from None
    except (ValueError, TypeError):
        raise DashboardUnavailable("Exa: dashboard 响应无效或超过大小限制。") from None


def fetch_dashboard(cookie: str, ctx: BalanceContext) -> dict:
    """GET the two dashboard endpoints without creating keys or paid requests."""
    if not cookie.strip() or "\r" in cookie or "\n" in cookie:
        raise DashboardUnavailable("Exa: dashboard 登录凭据格式无效。", "invalid")
    credits = _fetch_json(CREDITS_URL, cookie, ctx)
    if isinstance(credits, dict) and credits.get("orbBillingExempt") is True:
        return parse_dashboard(credits, None)
    return parse_dashboard(credits, _fetch_json(PLAN_URL, cookie, ctx))
