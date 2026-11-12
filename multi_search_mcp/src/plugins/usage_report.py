"""Local usage views, quota pace and per-scope totals shared by CLI consumers."""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ..state.key_state import key_fingerprint
from ..support.secrets import _iter_secret_strings
from . import balance, oauth_store, usage_store
from .cache import BalanceCache


SCHEMA_VERSION = 1
_HISTORY_FIELDS = ("key_fingerprint", "scope", "unit", "remaining", "limit", "fetched_at")


def _moment(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _cycle_start(report: dict, now: datetime) -> datetime:
    reset = report.get("resets_at")
    if not reset:
        return now - timedelta(days=7)
    try:
        end = _moment(reset)
        if end <= now:
            return end
        period = report.get("period")
        durations = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1),
                     "day": timedelta(days=1), "week": timedelta(weeks=1)}
        if period in durations:
            return end - durations[period]
        if period in {"month", "year"}:
            month_index = end.year * 12 + end.month - 1 - (1 if period == "month" else 12)
            year, month = divmod(month_index, 12)
            month += 1
            return end.replace(year=year, month=month,
                               day=min(end.day, calendar.monthrange(year, month)[1]))
    except (TypeError, ValueError, OverflowError):
        pass
    return now - timedelta(days=7)


def _pace(history: list[dict], current: list[dict], now: datetime) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in [*history, *current]:
        identity = tuple(row.get(field) for field in ("key_fingerprint", "scope", "unit"))
        groups.setdefault(identity, [])
    for row in history:
        identity = tuple(row.get(field) for field in ("key_fingerprint", "scope", "unit"))
        groups[identity].append(row)
    results = []
    for identity, rows in groups.items():
        result = dict(zip(("key_fingerprint", "scope", "unit"), identity))
        result.update(rate_per_day=None, projected_empty_at=None,
                      lasts_until_reset=None, reason="insufficient_data")
        reports = [row for row in current if tuple(row.get(field) for field in
                   ("key_fingerprint", "scope", "unit")) == identity]
        metadata = max([*rows, *reports], key=lambda row: _moment(row["fetched_at"]), default={})
        start = _cycle_start(metadata, now)
        points = [row for row in rows if start <= _moment(row["fetched_at"]) <= now]
        segment = []
        previous = None
        for row in points:
            remaining = row["remaining"]
            if remaining is not None:
                if previous is not None and remaining > previous:
                    segment = []
                previous = remaining
            segment.append(row)
        known = [row for row in segment if row["remaining"] is not None]
        if len(known) >= 2 and segment[-1]["remaining"] is not None:
            first, last = known[0], known[-1]
            elapsed = (_moment(last["fetched_at"]) - _moment(first["fetched_at"])).total_seconds()
            if elapsed >= 3600:
                rate = max(0.0, (first["remaining"] - last["remaining"]) * 86400 / elapsed)
                result.update(rate_per_day=rate, reason=None)
                if rate > 0:
                    try:
                        empty_at = _moment(last["fetched_at"]) + timedelta(days=max(0, last["remaining"]) / rate)
                        result["projected_empty_at"] = empty_at.isoformat()
                    except OverflowError:
                        empty_at = None
                else:
                    empty_at = None
                if metadata.get("resets_at"):
                    result["lasts_until_reset"] = rate == 0 or (
                        empty_at is not None and empty_at >= _moment(metadata["resets_at"])
                    )
        results.append(result)
    return results


def _totals(current: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in current:
        groups.setdefault((row["scope"], row["unit"]), []).append(row)
    totals = []
    for (scope, unit), rows in groups.items():
        # Account/team reports already cover every key; retain one observation.
        selected = rows if scope == "key" else [max(rows, key=lambda row: _moment(row["fetched_at"]))]
        total = {"scope": scope, "unit": unit, "key_count": len(rows), "message": ""}
        for field in ("remaining", "limit"):
            values = [row.get(field) for row in selected]
            total[field] = None if any(value is None for value in values) else sum(values)
        if scope == "key" and len(rows) > 1 and any(total[field] is None for field in ("remaining", "limit")):
            total["message"] = "部分 Key 未知"
        totals.append(total)
    return totals


def _calls(daily: list[dict], now: datetime, days: int, unavailable: bool) -> dict:
    today = now.astimezone().date()
    buckets: dict[str, dict] = {}
    for row in daily:
        bucket = buckets.setdefault(row["day"], {"day": row["day"], "search": 0, "scrape": 0, "failures": 0})
        bucket[row["purpose"]] += row["calls"]
        bucket["failures"] += row["failures"]
    def total(first_day):
        return {field: sum(row[field] for day, row in buckets.items() if day >= first_day)
                for field in ("search", "scrape", "failures")}
    return {
        "today": {} if unavailable else total(today.isoformat()),
        "last_7_days": {} if unavailable else total((today - timedelta(days=6)).isoformat()),
        "daily": [row for day, row in sorted(buckets.items())
                  if day >= (today - timedelta(days=days - 1)).isoformat()],
    }


def _cached_providers(plugins, key_map: dict, now: datetime, secrets: list[str]) -> list[dict]:
    cache = BalanceCache()
    providers = []
    for plugin in plugins:
        reports = []
        if plugin.balance is None:
            reports = [balance._unsupported_report(plugin, now, secrets)]
        else:
            entry = plugin.balance_credential
            credentials = balance._credential_values(key_map.get(entry or plugin.key_provider))
            if not credentials and not entry:
                credentials = [""]
            if not credentials:
                reports = [balance._needs_credential_report(plugin, entry, now)]
            for credential in credentials:
                fingerprint = key_fingerprint(credential) if credential else None
                # An offline view retains the last observation even after TTL;
                # only an explicit refresh may replace it with a network query.
                cached = cache.get(plugin.id, fingerprint, ttl_seconds=float("inf"), now=now)
                reports.extend(replace(report, provider=plugin.id) for report in cached or [])
        providers.append({"id": plugin.id, "label": plugin.label,
                          "balance_supported": plugin.balance is not None,
                          "balance_note": plugin.balance_note,
                          "reports": [report.to_dict() for report in reports]})
    return providers


def collect_usage(provider_ids=None, *, days: int = 30, refresh: bool = False,
                  now: datetime | None = None, keys: dict | None = None) -> dict[str, Any]:
    """Read local data, optionally asking balance collection to honor plugin TTLs.

    ``current`` preserves individual BalanceReports. ``totals`` groups those by
    scope/unit for collapsed views; shared account/team quotas are never added.
    ``now`` fixes both the rolling history window and local calendar call counts.
    """
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= usage_store.USAGE_RETENTION_DAYS:
        raise ValueError("days must be between 1 and 30")
    moment = now or datetime.now().astimezone()
    if moment.tzinfo is None:
        moment = moment.astimezone()
    plugins = balance._select_plugins(provider_ids)
    needs_keys = any(plugin.balance is not None and (plugin.balance_credential or plugin.key_provider)
                     for plugin in plugins)
    key_map = dict(keys) if keys is not None else dict(balance.load_keys()) if needs_keys else {}
    try:
        for entry, token in oauth_store.balance_credentials().items():
            if not key_map.get(entry):
                key_map[entry] = token
    except oauth_store.OAuthStoreError:
        pass
    secrets = list(_iter_secret_strings(key_map))
    try:
        secrets.extend(oauth_store.secret_values())
    except oauth_store.OAuthStoreError:
        pass
    providers = (balance.collect_balances(provider_ids, refresh=False, keys=key_map, now=moment)["providers"]
                 if refresh else _cached_providers(plugins, key_map, moment, secrets))
    # Pace needs the retained cycle and seven-day counts stay meaningful even
    # when --days requests a shorter chart/daily list.
    snapshot = usage_store.read_usage(days=usage_store.USAGE_RETENTION_DAYS, now=moment)
    payload = {"schema_version": SCHEMA_VERSION, "retention_days": usage_store.USAGE_RETENTION_DAYS, "providers": []}
    for provider in providers:
        history = [row for row in snapshot.history if row["provider"] == provider["id"]]
        current = provider["reports"]
        payload["providers"].append({
            **{field: provider[field] for field in ("id", "label", "balance_supported", "balance_note")},
            "current": current,
            "totals": _totals(current),
            "history": [{field: row[field] for field in _HISTORY_FIELDS} for row in history
                        if _moment(row["fetched_at"]) >= moment - timedelta(days=days)],
            "pace": _pace(history, current, moment),
            "calls": _calls([row for row in snapshot.daily if row["provider"] == provider["id"]],
                            moment, days, snapshot.usage_error is not None),
        })
    if snapshot.usage_error:
        payload["usage_error"] = snapshot.usage_error
    # Reuse the balance redactor for cached messages and plugin metadata too.
    def scrub(value):
        if isinstance(value, str):
            return balance.scrub_balance_message(value, secrets)
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        return value
    return scrub(payload)


def render_usage_text(payload: dict) -> str:
    """One concise Chinese paragraph per provider, with local-call labels."""
    paragraphs = []
    for provider in payload["providers"]:
        lines = [f"{provider['label']}（{provider['id']}）"]
        if not provider["balance_supported"]:
            lines.append(f"仅本机统计：{provider['balance_note'] or '不支持余额查询'}")
        elif not provider["current"]:
            lines.append("余额未知（无缓存；可用 --refresh 查询）")
        else:
            for total in provider["totals"]:
                number = lambda value: "未知" if value is None else f"{value:g}"
                lines.append(f"剩余 {number(total['remaining'])}/{number(total['limit'])} {total['unit']}"
                             f"（{total['scope']}）" + (f" · {total['message']}" if total["message"] else ""))
            for report in provider["current"]:
                if report.get("resets_at"):
                    lines.append(f"重置 {report['resets_at']}")
                if report.get("status") != "ok":
                    lines.append(report.get("message") or "余额未知")
        for pace in provider["pace"]:
            identity = f"{pace.get('key_fingerprint') or '匿名'} · {pace['scope']} · {pace['unit']}"
            if pace["reason"]:
                lines.append(f"配速（{identity}）：数据不足")
                continue
            text = f"配速（{identity}）：每日 {pace['rate_per_day']:g}"
            if pace["projected_empty_at"]:
                text += f" · 预计 {pace['projected_empty_at']} 用完"
            if pace["lasts_until_reset"] is not None:
                text += " · 能撑到重置" if pace["lasts_until_reset"] else " · 撑不到重置"
            lines.append(text)
        for field, label in (("today", "今天"), ("last_7_days", "近 7 天")):
            counts = provider["calls"][field]
            lines.append(f"本机调用（{label}）：搜索 {counts['search']}，抓取 {counts['scrape']}，失败 {counts['failures']}"
                         if counts else f"本机调用（{label}）：未知")
        paragraphs.append("\n".join(lines))
    if payload.get("usage_error"):
        paragraphs.append("用量库不可读，历史与本机调用统计暂不可用。")
    return "\n\n".join(paragraphs) or "（没有匹配的服务商）"
