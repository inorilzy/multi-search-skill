"""Collect provider balance reports with caching, redaction and a total deadline."""
from __future__ import annotations

import re
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from ..state.key_state import key_fingerprint
from ..state.keys import load_keys
from ..support.auth import classify_error
from ..support.concurrency import BoundedDaemonExecutor
from ..support.models import (
    ERROR_KIND_TIMEOUT,
    normalize_error_kind,
)
from ..support.secrets import _iter_secret_strings, scrub_secrets
from . import registry
from .base import BalanceContext, BalanceReport, ProviderPlugin
from .cache import BalanceCache


SCHEMA_VERSION = 1
BALANCE_TIMEOUT_SECONDS = 10.0
BALANCE_TOTAL_TIMEOUT_SECONDS = 15.0
BALANCE_CONCURRENCY = 8

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_POOL = BoundedDaemonExecutor(
    max_workers=BALANCE_CONCURRENCY,
    thread_name_prefix="multi-search-balance",
)


class UnknownProviderError(ValueError):
    """Raised for a --provider id that no built-in plugin declares."""


@dataclass(frozen=True)
class _Job:
    plugin: ProviderPlugin
    credential: str
    slot: int


def scrub_balance_message(message: Any, secrets: Iterable[str] = ()) -> str:
    """One redaction path for every balance message and cache entry.

    ``scrub_secrets`` covers header/bearer/query patterns and known credential
    values; emails are removed here because provider billing errors sometimes
    echo the account owner.
    """
    text = scrub_secrets(message, secrets)
    return _EMAIL_RE.sub("<redacted-email>", text)


def _now_epoch(now: Any) -> float:
    if now is None:
        return time.time()
    if isinstance(now, (int, float)):
        return float(now)
    if isinstance(now, datetime):
        moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    return float(now)


def _fetched_at(now: Any) -> str:
    if now is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(now, datetime):
        moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return moment.isoformat()
    return datetime.fromtimestamp(float(now), tz=timezone.utc).isoformat()


def _credential_values(value: Any) -> list[str]:
    """Return every distinct key in a string, key pool or Jina-style config."""
    if not value:
        return []
    if isinstance(value, dict):
        candidates = [value.get("key")]
    elif isinstance(value, (list, tuple, set)):
        candidates = []
        for item in value:
            candidates.append(item.get("key") if isinstance(item, dict) else item)
    else:
        candidates = [value]
    values: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate)
        if text and text not in seen:
            seen.add(text)
            values.append(text)
    return values


def _default_builtin_plugins() -> tuple[ProviderPlugin, ...]:
    """Read the registry at call time so registry or module patches both apply."""
    return registry.builtin_plugins()


# Patchable seam for callers/tests that inject a fake plugin set.
builtin_plugins = _default_builtin_plugins


def _select_plugins(provider_ids: Any) -> list[ProviderPlugin]:
    plugins = list(builtin_plugins())
    if provider_ids is None:
        return plugins
    if isinstance(provider_ids, str):
        provider_ids = [provider_ids]
    wanted = list(provider_ids)
    known = {plugin.id for plugin in plugins}
    for provider_id in wanted:
        if provider_id not in known:
            raise UnknownProviderError(f"unknown provider: {provider_id}")
    selected = set(wanted)
    return [plugin for plugin in plugins if plugin.id in selected]


def _unsupported_report(
    plugin: ProviderPlugin,
    now: Any,
    known_secrets: Iterable[str] = (),
) -> BalanceReport:
    return BalanceReport(
        provider=plugin.id,
        status="unsupported",
        message=scrub_balance_message(
            plugin.balance_note or "该服务商不支持余额查询。", known_secrets
        ),
        fetched_at=_fetched_at(now),
    )


def _needs_credential_report(plugin: ProviderPlugin, entry: str | None, now: Any) -> BalanceReport:
    return BalanceReport(
        provider=plugin.id,
        status="needs_credential",
        message=f"未配置凭据：{entry}" if entry else "未配置凭据。",
        fetched_at=_fetched_at(now),
    )


def _normalize_report(
    plugin: ProviderPlugin,
    report: Any,
    credential: str,
    known_secrets: Iterable[str],
) -> BalanceReport:
    if not isinstance(report, BalanceReport):
        raise TypeError(f"{plugin.id} balance returned {type(report).__name__}, expected BalanceReport")
    fingerprint = key_fingerprint(credential) if credential else None
    return replace(
        report,
        provider=plugin.id,
        key_fingerprint=fingerprint,
        message=scrub_balance_message(report.message, known_secrets),
    )


def _error_report(
    plugin: ProviderPlugin,
    credential: str,
    exc: BaseException,
    known_secrets: Iterable[str],
) -> BalanceReport:
    raw = str(exc) or type(exc).__name__
    kind = ERROR_KIND_TIMEOUT if isinstance(exc, TimeoutError) else normalize_error_kind(
        classify_error(raw)
    )
    return BalanceReport(
        provider=plugin.id,
        status="error",
        error_kind=kind,
        message=scrub_balance_message(raw, known_secrets),
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def _timeout_report(plugin: ProviderPlugin, credential: str, timeout: float) -> BalanceReport:
    return BalanceReport(
        provider=plugin.id,
        status="error",
        error_kind=ERROR_KIND_TIMEOUT,
        message=f"查询超时（总时限 {timeout:g} 秒）",
        key_fingerprint=key_fingerprint(credential) if credential else None,
    )


def _run_job(job: _Job, deadline: float, known_secrets: Iterable[str]) -> BalanceReport:
    if job.plugin.balance is None:  # pragma: no cover - jobs are only built for callbacks
        return _unsupported_report(job.plugin, None)
    context = BalanceContext(timeout=BALANCE_TIMEOUT_SECONDS, deadline=deadline)
    try:
        report = job.plugin.balance(job.credential, context)
        return _normalize_report(job.plugin, report, job.credential, known_secrets)
    except Exception as exc:  # noqa: BLE001 - one provider must not break the others
        return _error_report(job.plugin, job.credential, exc, known_secrets)


def _collect_reports(
    plugins: list[ProviderPlugin],
    key_map: dict,
    cache: BalanceCache,
    now: Any,
    refresh: bool,
    known_secrets: list[str],
) -> dict[str, list[BalanceReport]]:
    reports: dict[str, list[BalanceReport | None]] = {}
    jobs: list[_Job] = []
    now_epoch = _now_epoch(now)

    for plugin in plugins:
        if plugin.balance is None:
            reports[plugin.id] = [_unsupported_report(plugin, now, known_secrets)]
            continue
        entry = plugin.balance_credential
        credentials = _credential_values(key_map.get(entry)) if entry else [""]
        if not credentials:
            reports[plugin.id] = [_needs_credential_report(plugin, entry, now)]
            continue
        slots: list[BalanceReport | None] = []
        for credential in credentials:
            fingerprint = key_fingerprint(credential) if credential else None
            cached = None
            if not refresh:
                cached = cache.get(
                    plugin.id,
                    fingerprint,
                    ttl_seconds=plugin.balance_ttl_seconds,
                    now=now_epoch,
                )
            if cached is not None:
                slots.append(replace(
                    cached,
                    provider=plugin.id,
                    message=scrub_balance_message(cached.message, known_secrets),
                ))
                continue
            slots.append(None)
            jobs.append(_Job(plugin, credential, len(slots) - 1))
        reports[plugin.id] = slots

    def store(job: _Job, report: BalanceReport) -> None:
        reports[job.plugin.id][job.slot] = report
        if report.status == "ok":
            cache.put(
                job.plugin.id,
                report,
                ttl_seconds=job.plugin.balance_ttl_seconds,
                now=now_epoch,
            )

    deadline = time.monotonic() + BALANCE_TOTAL_TIMEOUT_SECONDS
    active: dict[Future, _Job] = {}
    next_index = 0
    while next_index < len(jobs) or active:
        while next_index < len(jobs) and len(active) < BALANCE_CONCURRENCY:
            job = jobs[next_index]
            future = _POOL.submit_before(
                deadline, _run_job, job, deadline, known_secrets,
            )
            if future is None:
                break
            active[future] = job
            next_index += 1
        done = {future for future in active if future.done()}
        if not done:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not active:
                break
            done, _ = wait(tuple(active), timeout=remaining, return_when=FIRST_COMPLETED)
        if not done:
            break
        for future in done:
            job = active.pop(future)
            try:
                store(job, future.result())
            except Exception as exc:  # noqa: BLE001 - defensive: jobs normally catch
                store(job, _error_report(job.plugin, job.credential, exc, known_secrets))
        if time.monotonic() >= deadline:
            break

    for future, job in active.items():
        if future.done():
            try:
                store(job, future.result())
            except Exception as exc:  # noqa: BLE001
                store(job, _error_report(job.plugin, job.credential, exc, known_secrets))
        else:
            _POOL.abandon(future)
            store(job, _timeout_report(job.plugin, job.credential, BALANCE_TOTAL_TIMEOUT_SECONDS))
    for job in jobs[next_index:]:
        store(job, _timeout_report(job.plugin, job.credential, BALANCE_TOTAL_TIMEOUT_SECONDS))

    return {
        plugin_id: [report for report in rows if report is not None]
        for plugin_id, rows in reports.items()
    }


def collect_balances(
    provider_ids: Any = None,
    refresh: bool = False,
    keys: dict | None = None,
    now: Any = None,
) -> dict:
    """Return the spec's balance payload for the selected plugins.

    Each configured key gets its own report. Unsupported providers and missing
    credentials are represented as status rows rather than errors. Provider
    callbacks run concurrently under one deadline, and a failure in one plugin
    only marks that plugin's report as ``error``. Cache reads/writes and all
    messages pass through :func:`scrub_balance_message`.
    """
    plugins = _select_plugins(provider_ids)
    if keys is None:
        needs_keys = any(
            plugin.balance is not None and plugin.balance_credential
            for plugin in plugins
        )
        key_map = dict(load_keys()) if needs_keys else {}
    else:
        key_map = keys
    known_secrets = list(_iter_secret_strings(key_map))
    cache = BalanceCache()
    try:
        reports = _collect_reports(plugins, key_map, cache, now, refresh, known_secrets)
    finally:
        cache.flush()

    return {
        "schema_version": SCHEMA_VERSION,
        "providers": [
            {
                "id": plugin.id,
                "label": plugin.label,
                "auth_methods": [asdict(method) for method in plugin.auth_methods],
                "balance_supported": plugin.balance is not None,
                "balance_note": scrub_balance_message(plugin.balance_note, known_secrets),
                "reports": [report.to_dict() for report in reports.get(plugin.id, [])],
            }
            for plugin in plugins
        ],
    }
