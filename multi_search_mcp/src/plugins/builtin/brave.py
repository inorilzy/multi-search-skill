"""Brave Search provider declaration."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta

from .. import usage_store
from ..base import AuthMethod, BalanceContext, BalanceReport, ProviderPlugin
from ..quota_record import quota_entry, quota_report

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
    """Read the quota recorded by the last successful search; never sends a request.

    A free-credit plan is recomputed now, so calls since that search count too.
    """
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
    ),
    balance=balance_brave,
    balance_note='搜索一次后显示本月配额；免费额度按本机调用次数估算。',
)
