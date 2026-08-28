"""Strict URL safety checks for outbound scraping/fetching."""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from collections.abc import Callable, Iterable


Resolver = Callable[[str], Iterable[str]]
_CGNAT_V4_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class UrlSecurityError(ValueError):
    """Raised when a URL is not safe for outbound fetching."""


def validate_public_http_url(url: str, *, resolver: Resolver | None = None) -> str:
    return _validate_url(url, label="URL", resolver=resolver)


def validate_scrape_url(url: str, *, resolver: Resolver | None = None) -> str:
    return _validate_url(url, label="scrape URL", resolver=resolver)


def validate_redirect_target(url: str, *, resolver: Resolver | None = None) -> str:
    return _validate_url(url, label="redirect target", resolver=resolver)


def _validate_url(url: str, *, label: str, resolver: Resolver | None) -> str:
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
        _ensure_public_ip(direct_ip, label=label, resolved=False)
        return candidate
    answers = list((resolver or _resolve_host_ips)(host))
    if not answers:
        raise UrlSecurityError(f"{label} host did not resolve to any IP")
    for answer in answers:
        ip = _parse_ip(answer)
        if ip is None:
            raise UrlSecurityError(f"{label} host resolved to a non-IP value")
        _ensure_public_ip(ip, label=label, resolved=True)
    return candidate


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
) -> None:
    reason = _unsafe_reason(ip)
    if reason is None:
        return
    address_kind = "resolved address" if resolved else "direct address"
    raise UrlSecurityError(f"unsafe {label}: {address_kind} is {reason}")


def _unsafe_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
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
