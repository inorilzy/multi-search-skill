"""Local usage views, quota pace and per-scope totals shared by CLI consumers.

Account keys contain search-key fingerprints and their reports (None on a cache
miss); balance-only credentials contribute reports to totals, never key counts.
The additive ``total`` keeps remaining/limit/percent/unit/relative on every row.
For one unit, shared account/team quotas take precedence over key quotas; each
shared pool (told apart by its reset time) keeps its latest observation instead of
adding duplicates, and distinct pools add up. Key quotas add;
unknown values propagate. Mixed units return an unknown total, not a sum.
Without a limit, percent uses the cycle's historical maximum (relative=True);
without history there is no percent. Existing ``current``/``totals`` stay intact.
"""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ..state.key_state import key_fingerprint
from ..support.secrets import _iter_secret_strings
from . import accounts, balance, oauth_store, usage_store
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


def _shared_pools(rows: list[dict]) -> list[dict]:
    """One report per shared quota: the newest of the rows that describe the same pool.

    Account/team reports cover every key of that account or team, so keys of one
    pool must count once. Keys can belong to different teams (Firecrawl), each with
    its own credits; a pool is told apart by its reset time, which every key of one
    team reports alike, and distinct pools are added up.
    """
    newest: dict[tuple, dict] = {}
    for row in rows:
        pool = (row["scope"], row["unit"], row.get("resets_at"))
        if pool not in newest or _moment(row["fetched_at"]) > _moment(newest[pool]["fetched_at"]):
            newest[pool] = row
    return list(newest.values())


def _totals(current: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in current:
        groups.setdefault((row["scope"], row["unit"]), []).append(row)
    totals = []
    for (scope, unit), rows in groups.items():
        # Account/team reports already cover every key; keep one per pool.
        selected = rows if scope == "key" else _shared_pools(rows)
        total = {"scope": scope, "unit": unit, "key_count": len(rows), "message": ""}
        for field in ("remaining", "limit"):
            values = [row.get(field) for row in selected]
            total[field] = None if any(value is None for value in values) else sum(values)
        if scope == "key" and len(rows) > 1 and any(total[field] is None for field in ("remaining", "limit")):
            total["message"] = "部分 Key 未知"
        totals.append(total)
    return totals


def _total(current: list[dict], history: list[dict], now: datetime, *, missing: bool = False) -> dict:
    total = dict(remaining=None, limit=None, percent=None, unit=None, relative=False)
    if not current or len({row["unit"] for row in current}) != 1:
        return total
    shared = [row for row in current if row["scope"] in {"team", "account"}]
    selected = _shared_pools(shared) if shared else current
    values = _totals(selected)[0]
    if values["remaining"] is None and values["limit"] is None:
        return total
    total.update({field: values[field] for field in ("remaining", "limit", "unit")})
    if missing and not shared:
        total.update(remaining=None, limit=None)
        return total
    denominator = total["limit"]
    if denominator is None:
        total["relative"] = True
        maxima = []
        for report in selected:
            start = _cycle_start(report, now)
            points = [row["remaining"] for row in history
                      if row["scope"] == report["scope"] and row["unit"] == report["unit"]
                      and (shared or row["key_fingerprint"] == report["key_fingerprint"])
                      and start <= _moment(row["fetched_at"]) <= now and row["remaining"] is not None]
            if not points:
                break
            maxima.append(max(points))
        denominator = sum(maxima) if len(maxima) == len(selected) else None
    if total["remaining"] is not None and denominator is not None and denominator > 0:
        total["percent"] = max(0, min(100, total["remaining"] / denominator * 100))
    return total


def _account_views(plugin, current: list[dict], key_map: dict, history: list[dict], now: datetime) -> list[dict]:
    groups = accounts.list_accounts(plugin.id)[plugin.id]
    claimed = {fp for group in groups for fp in group["keys"]}
    # Environment/injected keys have no persistent owner, so remain virtual.
    groups[0]["keys"].extend(fp for key in balance._credential_values(key_map.get(plugin.key_provider))
                             if (fp := key_fingerprint(key)) not in claimed)
    claimed_reports = {fp for group in groups
                       for fp in [*group["keys"], *group["balance_credentials"].values()]}
    views = []
    for group in groups:
        fingerprints = {*group["keys"], *group["balance_credentials"].values()}
        reports = [row for row in current if row["key_fingerprint"] in fingerprints
                   or (group["id"] == accounts.DEFAULT_ACCOUNT_ID
                       and row["key_fingerprint"] not in claimed_reports)]
        keys = []
        for fp in group["keys"]:
            candidates = [row for row in reports if row["key_fingerprint"] == fp]
            report = max(candidates, key=lambda row: (row["scope"] == "key", _moment(row["fetched_at"])),
                         default=None)
            keys.append({"key_fingerprint": fp, "report": report})
        missing = plugin.balance_credential == plugin.key_provider and any(row["report"] is None for row in keys)
        report_fps = {row["key_fingerprint"] for row in reports}
        account_history = [row for row in history if row["key_fingerprint"] in report_fps]
        views.append({**{field: group[field] for field in ("id", "name", "source")}, "keys": keys,
                      "total": _total(reports, account_history, now, missing=missing)})
    return views


def _alert(total: dict, pace: list[dict], current: list[dict], account_views: list[dict], plugin) -> str | None:
    percent = total["percent"]
    if percent is not None and percent < 5:
        return "critical"
    active = {(row["key_fingerprint"], row["scope"], row["unit"]) for row in current}
    if any(row["lasts_until_reset"] is False and
           (row["key_fingerprint"], row["scope"], row["unit"]) in active for row in pace):
        return "wont_last"
    if percent is not None and percent < 20:
        return "low"
    if any(row["status"] == "needs_credential" for row in current) or any(
        plugin.key_provider and row["source"] == "oauth" and not row["keys"] for row in account_views
    ):
        return "needs_credential"
    return None


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
    key_map = dict(keys) if keys is not None else dict(balance.load_keys())
    # Account IDs and fingerprints are public metadata, not credential values.
    key_map.pop("accounts", None)
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
        plugin = next(plugin for plugin in plugins if plugin.id == provider["id"])
        account_views = _account_views(plugin, current, key_map, history, moment)
        missing = plugin.balance_credential == plugin.key_provider and any(
            key["report"] is None for account in account_views for key in account["keys"]
        )
        total = _total(current, history, moment, missing=missing)
        pace = _pace(history, current, moment)
        payload["providers"].append({
            **{field: provider[field] for field in ("id", "label", "balance_supported", "balance_note")},
            "current": current,
            "totals": _totals(current),
            "history": [{field: row[field] for field in _HISTORY_FIELDS} for row in history
                        if _moment(row["fetched_at"]) >= moment - timedelta(days=days)],
            "pace": pace,
            "accounts": account_views,
            "total": total,
            "alert": _alert(total, pace, current, account_views, plugin),
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
        number = lambda value: "未知" if value is None else f"{value:g}"
        for account in provider.get("accounts", []):
            total = account["total"]
            if (account["id"] == accounts.DEFAULT_ACCOUNT_ID and not account["keys"]
                    and total["unit"] is None and len(provider["accounts"]) > 1):
                continue
            amount = f"剩余 {number(total['remaining'])}/{number(total['limit'])} {total['unit'] or ''}".rstrip()
            if total["percent"] is not None:
                amount += f" · {total['percent']:g}%" + ("（相对值）" if total["relative"] else "")
            lines.append(f"账号 {account['name']}（{account['id']}）：{amount}")
            for key in account["keys"]:
                report = key["report"]
                detail = (f"剩余 {number(report['remaining'])}/{number(report['limit'])} {report['unit']}"
                          if report else "余额未知（无缓存）")
                lines.append(f"  Key {key['key_fingerprint']}：{detail}")
        alerts = {"critical": "余额严重不足", "wont_last": "撑不到重置", "low": "余额偏低",
                  "needs_credential": "需要凭据"}
        if provider.get("alert"):
            lines.append(f"提醒：{alerts[provider['alert']]}")
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
