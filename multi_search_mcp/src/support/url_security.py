"""Strict URL safety checks for outbound scraping/fetching."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import os
import socket
import time
import urllib.parse
from collections.abc import Callable, Iterable

from .concurrency import BoundedDaemonExecutor


Resolver = Callable[[str], Iterable[str]]
_CGNAT_V4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
FAKE_IP_ENV = "MULTI_SEARCH_ALLOW_FAKE_IP"
_NAT64_WKP = ipaddress.ip_network("64:ff9b::/96")
_6TO4 = ipaddress.ip_network("2002::/16")
_DNS_MAX_WORKERS = 8
_DNS_POOL = BoundedDaemonExecutor(
    max_workers=_DNS_MAX_WORKERS,
    thread_name_prefix="multi-search-dns",
)


class UrlSecurityError(ValueError):
    """Raised when a URL is not safe for outbound fetching."""


class DnsResolutionError(OSError):
    """Raised when bounded DNS work cannot complete for a request."""


def validate_public_http_url(
    url: str, *, resolver: Resolver | None = None, deadline: float | None = None,
    allow_fake_ip: bool | None = None,
) -> str:
    return _validate_url(
        url, label="URL", resolver=resolver, deadline=deadline,
        allow_fake_ip=allow_fake_ip,
    )


def validate_scrape_url(
    url: str, *, resolver: Resolver | None = None, deadline: float | None = None,
    allow_fake_ip: bool | None = None,
) -> str:
    return _validate_url(
        url, label="scrape URL", resolver=resolver, deadline=deadline,
        allow_fake_ip=allow_fake_ip,
    )


def validate_redirect_target(
    url: str, *, resolver: Resolver | None = None, deadline: float | None = None,
    allow_fake_ip: bool | None = None,
) -> str:
    return _validate_url(
        url, label="redirect target", resolver=resolver, deadline=deadline,
        allow_fake_ip=allow_fake_ip,
    )


def allow_fake_ip_default() -> bool:
    """Accept resolved TUN benchmark addresses only after an explicit opt-in."""
    return os.environ.get(FAKE_IP_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_url(
    url: str, *, label: str, resolver: Resolver | None, deadline: float | None,
    allow_fake_ip: bool | None = None,
) -> str:
    candidate = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(candidate)
    except Exception as exc:
        raise UrlSecurityError(f"{label} is not a valid URL: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in {"http", "https"}:
        shown = parts.scheme or "<missing>"
        raise UrlSecurityError(f"{label} uses unsupported URL scheme: {shown}")
    if not parts.hostname:
        raise UrlSecurityError(f"{label} is missing host")
    if parts.username is not None or parts.password is not None:
        raise UrlSecurityError(f"{label} must not include credentials")

    host = parts.hostname
    direct_ip = _parse_ip(host)
    if direct_ip is not None:
        _ensure_deadline(deadline, label)
        _ensure_public_ip(direct_ip, label=label, resolved=False)
        return candidate
    accept_fake_ip = allow_fake_ip_default() if allow_fake_ip is None else bool(allow_fake_ip)
    resolve = resolver or _resolve_host_ips
    try:
        if deadline is None:
            answers = list(resolve(host))
        else:
            answers = _run_bounded_dns(
                lambda: list(resolve(host)), deadline=deadline,
            )
    except DnsResolutionError as exc:
        raise UrlSecurityError(f"{label} {exc}") from exc
    if not answers:
        raise UrlSecurityError(f"{label} host did not resolve to any IP")
    for answer in answers:
        ip = _parse_ip(answer)
        if ip is None:
            raise UrlSecurityError(f"{label} host resolved to a non-IP value")
        _ensure_public_ip(
            ip, label=label, resolved=True, allow_fake_ip=accept_fake_ip,
        )
    return candidate


def resolve_validated_addresses(
    host: str, port: int, *, deadline: float | None = None,
    allow_fake_ip: bool | None = None,
) -> list[tuple]:
    """Resolve once and validate exactly the addresses that will be dialed."""
    addresses = resolve_host_addresses(host, port, deadline=deadline)
    accept_fake_ip = allow_fake_ip_default() if allow_fake_ip is None else bool(allow_fake_ip)
    for family, _socktype, _proto, _canonname, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        ip = _parse_ip(str(sockaddr[0]))
        if ip is None:
            raise UrlSecurityError("HTTP DNS resolution returned a non-IP address")
        ensure_public_ip(
            str(ip), label="HTTP connection", resolved=True,
            allow_fake_ip=accept_fake_ip,
        )
    return addresses


def _resolve_host_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlSecurityError(f"host DNS resolution failed: {exc.strerror or exc}") from exc
    answers: list[str] = []
    seen: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        addr = sockaddr[0]
        if addr not in seen:
            seen.add(addr)
            answers.append(addr)
    return answers


def resolve_host_addresses(
    host: str, port: int, *, deadline: float | None = None,
) -> list[tuple]:
    """Resolve a socket destination through the same bounded DNS boundary."""
    def resolve() -> list[tuple]:
        return list(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))

    if deadline is None:
        return resolve()
    return _run_bounded_dns(resolve, deadline=deadline, label="HTTP DNS resolution")


def _run_bounded_dns(fn: Callable[[], Iterable], *, deadline: float, label: str = "DNS resolution"):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DnsResolutionError(f"{label} deadline exceeded")
    future = _DNS_POOL.submit_nowait(fn)
    if future is None:
        raise DnsResolutionError(f"{label} capacity exhausted")
    try:
        # Admission can consume budget; never wait for the original full window.
        result = future.result(timeout=max(0.0, deadline - time.monotonic()))
    except concurrent.futures.TimeoutError as exc:
        # A running resolver cannot be cancelled safely.  Abandoning it frees
        # its admission slot while BoundedDaemonExecutor still bounds the
        # number of detached resolver threads; past that bound the slot stays
        # held and new lookups fail fast with "capacity exhausted".
        _DNS_POOL.abandon(future)
        raise DnsResolutionError(f"{label} deadline exceeded") from exc
    if deadline - time.monotonic() <= 0:
        raise DnsResolutionError(f"{label} deadline exceeded")
    return result


def _ensure_deadline(deadline: float | None, label: str) -> None:
    if deadline is not None and deadline - time.monotonic() <= 0:
        raise UrlSecurityError(f"{label} deadline exceeded")


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _ensure_public_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    label: str,
    resolved: bool,
    allow_fake_ip: bool = False,
) -> None:
    if allow_fake_ip and resolved and ip in _FAKE_IP_NETWORK:
        # Opt-in covers only a resolved TUN benchmark answer, never a literal.
        return
    reason = _unsafe_reason(ip)
    if reason is None:
        return
    address_kind = "resolved address" if resolved else "direct address"
    raise UrlSecurityError(f"unsafe {label}: {address_kind} is {reason}")


def ensure_public_ip(
    value: str, *, label: str = "connection", resolved: bool = True,
    allow_fake_ip: bool = False,
) -> None:
    """Raise when an address is not internet-routable."""
    ip = _parse_ip(str(value))
    if ip is None:
        raise UrlSecurityError(f"unsafe {label}: address is not an IP")
    _ensure_public_ip(
        ip, label=label, resolved=resolved, allow_fake_ip=allow_fake_ip,
    )


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Extract the IPv4 destination hidden in a transition address."""
    if ip in _NAT64_WKP:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in _6TO4:
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return None


def _unsafe_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            # Judge the tunnel by its actual IPv4 destination.
            return _unsafe_reason(embedded)
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "reserved"
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_V4_NETWORK:
        return "shared"
    if ip.is_private:
        return "private"
    if not ip.is_global:
        return "non-public"
    return None
