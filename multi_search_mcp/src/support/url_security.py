"""Strict URL safety checks for outbound scraping/fetching.

Trust model: outbound destinations are provider addresses fixed in code, and
external URLs are only handed to those providers as parameters or reduced to
an identifier. So these checks never resolve a name and never inspect resolved
addresses; a fake-IP/TUN answer is just a provider's routing. What stays is
every check that needs no DNS: scheme, host, credentials, ``localhost``, and
non-public IP literals in all numeric spellings.

Code that connects from this machine to an externally supplied URL must add
resolved-address checks before it dials. Nothing does so today.
"""

from __future__ import annotations

import ipaddress
import re
import time
import unicodedata
import urllib.parse


_CGNAT_V4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_NAT64_WKP = ipaddress.ip_network("64:ff9b::/96")
_6TO4 = ipaddress.ip_network("2002::/16")


class UrlSecurityError(ValueError):
    """Raised when a URL is not safe for outbound fetching."""


def validate_public_http_url(url: str, *, deadline: float | None = None) -> str:
    """Validate a URL that this process never dials itself (format checks only)."""
    candidate = str(url or "").strip()
    _validate_format(candidate, label="URL", deadline=deadline)
    return candidate


def validate_scrape_url(url: str, *, deadline: float | None = None) -> str:
    """Validate a scrape target (format checks only, no DNS)."""
    candidate = str(url or "").strip()
    _validate_format(candidate, label="scrape URL", deadline=deadline)
    return candidate


def _validate_format(candidate: str, *, label: str, deadline: float | None) -> None:
    _parts, host, _port = http_target(candidate, label=label)
    _ensure_deadline(deadline, label)
    if host == "localhost" or host.endswith(".localhost"):
        raise UrlSecurityError(f"unsafe {label}: localhost is not allowed")
    literal = numeric_host(host)
    if literal is not None:
        _ensure_public_ip(literal, label=label, resolved=False)


def normalize_http_host(host: str) -> str:
    """Normalize hosts before telling literal addresses from names."""
    try:
        decoded = urllib.parse.unquote(str(host).strip("[]"), errors="strict")
        if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
            raise ValueError("control character")
        normalized = unicodedata.normalize("NFKC", decoded).translate(
            str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."}),
        ).lower().removesuffix(".")
        if ":" in normalized:
            ip = ipaddress.IPv6Address(normalized)
            if ip.scope_id is not None:
                raise ValueError("scope identifier")
            return ip.compressed
        normalized = normalized.encode("idna").decode("ascii").lower()
        if not re.fullmatch(r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?(?:\.[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?)*", normalized):
            raise ValueError("invalid characters")
        return normalized
    except (ValueError, UnicodeError) as exc:
        raise UrlSecurityError("unsafe URL: host is not a valid hostname") from exc


def http_target(url: str, *, label: str = "URL") -> tuple:
    """Parse a logical HTTP target without DNS, never disclosing credentials."""
    candidate = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"}:
            raise UrlSecurityError(f"{label} uses unsupported URL scheme")
        if not parts.hostname:
            raise UrlSecurityError(f"{label} is missing host")
        if parts.username is not None or parts.password is not None:
            raise UrlSecurityError(f"{label} must not include credentials")
        if "\\" in parts.netloc or any(ord(c) < 32 or ord(c) == 127 for c in candidate):
            raise UrlSecurityError(f"unsafe {label}: invalid authority or control characters")
        port = parts.port if parts.port is not None else (443 if parts.scheme.lower() == "https" else 80)
        host = normalize_http_host(parts.hostname)
    except ValueError as exc:
        if isinstance(exc, UrlSecurityError):
            raise
        raise UrlSecurityError(f"{label} is not a valid URL") from exc
    return parts, host, port


def numeric_host(host: str):
    """Classify literal and alternate numeric addresses (no DNS)."""
    host = normalize_http_host(host)
    literal = _parse_ip(host)
    if literal is not None:
        return literal
    if not re.fullmatch(r"(?:0x[0-9a-f]*|[0-9]+)", host.rsplit(".", 1)[-1]):
        return None
    labels = host.split(".")
    if not 1 <= len(labels) <= 4:
        raise UrlSecurityError("unsafe URL: non-canonical numeric address")
    values = []
    for part in labels:
        if not re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part) or (
            len(part) > 1 and part.startswith("0") and not part.startswith("0x")
        ):
            raise UrlSecurityError("unsafe URL: non-canonical numeric address")
        values.append(int(part, 16 if part.startswith("0x") else 10))
    if any(v > 255 for v in values[:-1]) or values[-1] >= 1 << (8 * (5-len(values))):
        raise UrlSecurityError("unsafe URL: non-canonical numeric address")
    number = values[-1]
    for i, value in enumerate(values[:-1]):
        number += value << (8 * (3-i))
    return ipaddress.IPv4Address(number)


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
) -> None:
    reason = _unsafe_reason(ip)
    if reason is None:
        return
    address_kind = "resolved address" if resolved else "direct address"
    raise UrlSecurityError(f"unsafe {label}: {address_kind} is {reason}")


def ensure_public_ip(
    value: str, *, label: str = "connection", resolved: bool = True,
) -> None:
    """Raise when an address literal is not internet-routable."""
    ip = _parse_ip(str(value))
    if ip is None:
        raise UrlSecurityError(f"unsafe {label}: address is not an IP")
    _ensure_public_ip(ip, label=label, resolved=resolved)


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Extract the IPv4 destination hidden in a transition address."""
    if ip in _NAT64_WKP:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in _6TO4:
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return None


def _unsafe_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or _embedded_ipv4(ip)
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
