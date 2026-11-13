"""Brave Search provider declaration."""
from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .. import oauth_store, usage_store
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin
from ..quota_record import quota_entry, quota_report
from . import brave_dashboard

# Prepaid Search plan (api-dashboard.search.brave.com/documentation/pricing, 2026-11):
# $5 per 1,000 requests, with $5 of free credit every month. Its responses carry a
# monthly window of 0 ("X-RateLimit-Limit: 50, 0"), because it bills credits, not
# requests, so the credit left is estimated from this machine's billable calls.
BRAVE_PRICE_PER_REQUEST = 5.0 / 1000
BRAVE_FREE_CREDIT_USD = 5.0
# X-RateLimit-Policy names the monthly window: w=2592000 seconds.
BRAVE_WINDOW_DAYS = 30
CREDIT_PLAN_MARKER = "免费额度"


def _window_calls(resets_at: str | None, extra: int = 0) -> int:
    """Billable (non-failed) local Brave searches inside the current monthly window."""
    start_day = None
    if resets_at:
        try:
            start = datetime.fromisoformat(resets_at) - timedelta(days=BRAVE_WINDOW_DAYS)
            start_day = start.astimezone().date().isoformat()
        except ValueError:
            start_day = None
    snapshot = usage_store.read_usage("brave", days=BRAVE_WINDOW_DAYS)
    calls = sum(
        int(row["calls"]) - int(row["failures"]) for row in snapshot.daily
        if row["purpose"] == "search" and (start_day is None or row["day"] >= start_day)
    )
    return calls + extra


def credit_fields(per_second: int | None, resets_at: str | None, *, extra_calls: int = 0) -> dict:
    """Report fields for the free monthly credit, as far as this machine has spent it."""
    used = round(_window_calls(resets_at, extra_calls) * BRAVE_PRICE_PER_REQUEST, 4)
    remaining = round(max(0.0, BRAVE_FREE_CREDIT_USD - used), 4)
    rate = f" · 每秒 {per_second} 次" if per_second else ""
    note = " · 已用完，充值前搜索会失败" if remaining <= 0 else ""
    fields = {
        "unit": "usd", "limit": BRAVE_FREE_CREDIT_USD, "remaining": remaining, "used": used,
        "period": "month",
        "message": f"{CREDIT_PLAN_MARKER} ${BRAVE_FREE_CREDIT_USD:g}/月{rate} · 本机估算{note}",
    }
    if resets_at:
        fields["resets_at"] = resets_at
    return fields


def balance_brave(credential: str, ctx: BalanceContext) -> BalanceReport:
    """Prefer real Search-plan usage; without a usable login read the local quota."""
    reference = credential if credential.startswith("oauth-login:brave_dashboard:") else None
    expected_reference = reference
    if os.environ.get(brave_dashboard.COOKIE_ENV):
        expected_reference = None
    elif expected_reference is None:
        try:
            record = oauth_store.get_entry("brave_dashboard")
            if record:
                expected_reference = oauth_store.balance_credential_ref("brave_dashboard", record)
        except oauth_store.OAuthStoreError:
            pass
    cookie = brave_dashboard.cookie_header(expected_reference or reference)
    reason = "dashboard 登录已失效" if reference and not cookie else ""
    if cookie:
        try:
            data = brave_dashboard.fetch_dashboard(cookie, ctx)
            plan = next((row for row in data["plans"] if row["name"] == "Search"), None)
            if plan is None or any(plan[field] is None for field in ("credit", "cost", "requests")):
                raise brave_dashboard.DashboardUnavailable("no Search usage")
            profile_note = ""
            if expected_reference:
                try:
                    brave_dashboard.sync_account(data.get("profile"), expected_reference)
                except (ValueError, OSError):
                    # Local account storage cannot invalidate a successfully read quota.
                    profile_note = " · 账号资料暂未保存"
            now = datetime.now(timezone.utc)
            reset = (now.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return BalanceReport(
                provider="brave", status="ok", scope="account", unit="usd", period="month",
                limit=plan["credit"], used=plan["cost"],
                remaining=round(max(0, plan["credit"] - plan["cost"]), 6),
                resets_at=reset.isoformat(),
                message=f"dashboard · Search 本月 {plan['requests']:g} 次 · 剩余免费额度{profile_note}",
            )
        except brave_dashboard.DashboardUnavailable as exc:
            reason = "dashboard 登录已失效" if str(exc) == "logged out" else "dashboard 暂不可用"
    if reference:
        keys = ctx.credentials.get("brave", [])
        keys = [keys] if isinstance(keys, str) else keys if isinstance(keys, list) else []
        observations = [_local_balance(key) for key in keys if isinstance(key, str) and key]
        report = max(observations, key=lambda row: (row.status == "ok", row.fetched_at),
                     default=_local_balance(""))
    else:
        report = _local_balance(credential)
    return replace(report, message=f"{reason} · {report.message}") if reason else report


def _local_balance(credential: str) -> BalanceReport:
    """Recompute a free-credit estimate without making a billable search call."""
    report = quota_report("brave", credential, unit="requests", period="month")
    entry = quota_entry("brave", credential)
    fields = entry["report"] if entry else {}
    if report.status != "ok" or fields.get("unit") != "usd":
        return report
    # The record carries only report fields, so the observed rate survives in its message.
    rate = re.search(r"每秒 (\d+) 次", fields.get("message") or "")
    per_second = int(rate.group(1)) if rate else None
    fresh = credit_fields(per_second, report.resets_at)
    fresh.pop("period", None)
    return replace(report, **fresh)


def search_specs():
    # Resolve the historical module symbols at call time for monkeypatch callers.
    from ...search import registry

    return (
        registry._provider_spec(
            "brave",
            missing_message="missing BRAVE_SEARCH_API_KEY / BRAVE_API_KEY",
            call=lambda q, cfg, ctx, key: registry.call_optional_timeout(
                registry.search_brave, q, key, cfg.counts["brave"], timeout=ctx.timeout, deadline=ctx.deadline,
            ),
        ),
    )


PLUGIN = ProviderPlugin(
    id='brave',
    label='Brave Search',
    key_provider='brave',
    search_sources=('brave',),
    search_specs=search_specs,
    auth_methods=(
        AuthMethod("api", "API Key", "brave"),
        AuthMethod("web", "Chrome 登录（查用量）", "brave_dashboard", "balance_only"),
    ),
    balance=balance_brave,
    balance_credential="brave_dashboard",
    balance_fallback_credential="brave",
    balance_note='登录控制台后读取真实用量；登录不可用时显示搜索记录与本机估算。',
)
