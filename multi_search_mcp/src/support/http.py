"""HTTP requests with safe redirects and a shared retry/read deadline."""
import gzip
import http.client
import ipaddress
import io
import socket
import ssl
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable
from functools import partial

from .url_security import (
    UrlSecurityError,
    allow_fake_ip_default,
    ensure_public_ip,
    resolve_host_addresses,
    resolve_validated_addresses,
    _resolve_host_ips,
    validate_redirect_target,
)


_ssl_ctx = ssl.create_default_context()
if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
    _ssl_ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF  # type: ignore[attr-defined]


# Bound every body read; providers never legitimately need more than this in
# one response and an unbounded read lets a hostile endpoint exhaust memory.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Only these methods are safe to retry after SSL/EOF. POST-like requests may
# charge money or mutate remote state on the first, apparently failed attempt.
_RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


_CREDENTIAL_HEADERS = {
    "authorization", "proxy-authorization", "cookie",
    "x-api-key", "x-subscription-token", "x-appbuilder-authorization",
}


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port if parts.port is not None else {"http": 80, "https": 443}.get(scheme)
    return scheme, (parts.hostname or "").lower(), port


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("HTTP request deadline exceeded")
    return remaining


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def read_limited(response, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a response body with a hard size ceiling.

    Returns at most ``limit`` bytes; a larger body raises so callers never hold
    an unbounded payload in memory. JSON callers see a clear failure instead of
    a multi-gigabyte allocation.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"HTTP response body exceeds {limit} bytes")
    return body


def gunzip_limited(data: bytes, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Decompress at most ``limit`` bytes, rejecting compression bombs."""
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"decompressed response body exceeds {limit} bytes")
    return body


def _configured_proxy_addresses() -> set[tuple[str, int]]:
    """Local proxy endpoints the user configured for this process.

    A local HTTP proxy is a trusted local hop: the connect target is the proxy,
    not the internet destination, so private/loopback proxy addresses are
    expected. Only exact host/port matches get this exemption.
    """
    targets: set[tuple[str, int]] = set()
    defaults = {"http": 80, "https": 443, "socks": 1080, "socks5": 1080, "socks4": 1080}
    for proxy_url in urllib.request.getproxies().values():
        try:
            parts = urllib.parse.urlsplit(str(proxy_url))
            host = (parts.hostname or "").lower()
        except ValueError:
            continue
        if not host:
            continue
        port = parts.port or defaults.get(parts.scheme.lower(), 80)
        targets.add((host, port))
    return targets


def _ensure_connect_address(raw_address: str, port: int, *, resolved: bool = False) -> None:
    host = str(raw_address).strip("[]").lower()
    ensure_public_ip(
        host, label="HTTP connection", resolved=resolved,
        allow_fake_ip=allow_fake_ip_default(),
    )


def _proxy_host_port(target: str) -> tuple[str, int] | None:
    """Parse a ``host[:port]`` / ``scheme://host:port`` proxy target."""
    text = str(target or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "//" + text
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").strip("[]").lower()
    if not host:
        return None
    port = parts.port
    if port is None:
        return None
    return host, int(port)


def _trusted_proxy_targets(req) -> set[tuple[str, int]]:
    """Exact hop endpoints this request may use as its configured proxy.

    Sources: process proxy settings, plus the proxy urllib itself configured on
    this request. Both are explicit user configuration; nothing here trusts a
    destination parsed out of an arbitrary request URL.
    """
    targets = set(_configured_proxy_addresses())
    if req.has_proxy() or bool(getattr(req, "_tunnel_host", None)):
        request_proxy = _proxy_host_port(getattr(req, "host", ""))
        if request_proxy is not None:
            targets.add(request_proxy)
    return targets


def _is_trusted_proxy_hop(req, host: str, port: int) -> bool:
    if not (req.has_proxy() or bool(getattr(req, "_tunnel_host", None))):
        return False
    normalized = str(host or "").strip("[]").lower()
    return (normalized, int(port)) in _trusted_proxy_targets(req)


def _sockaddr_host(sockaddr) -> tuple[str, int]:
    return str(sockaddr[0]).strip("[]"), int(sockaddr[1])


class _DeadlineReader(io.RawIOBase):
    """Refresh the socket budget before each individual buffered-stream read.

    A single HTTPResponse.read() can perform many socket reads, so setting the
    timeout just once still lets a slow, continuously arriving body run forever.
    read1 performs at most one underlying read, including for chunked bodies.
    """

    def __init__(self, stream, sock, deadline: float):
        self.stream, self.sock, self.deadline = stream, sock, deadline

    def readable(self):
        return True

    def readinto(self, target):
        if not target:
            return 0
        try:
            self.sock.settimeout(_remaining(self.deadline))
            chunk = self.stream.read1(len(target))
            _remaining(self.deadline)
            target[:len(chunk)] = chunk
            return len(chunk)
        except BaseException:
            # urllib may drain a redirect body before returning any response
            # to the caller, so its failure cannot rely on a caller's `with`.
            self.stream.close()
            raise

    def close(self):
        try:
            self.stream.close()
        finally:
            super().close()


class _DeadlineHTTPResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, deadline: float, **kwargs):
        super().__init__(sock, *args, **kwargs)
        self.fp = io.BufferedReader(_DeadlineReader(self.fp, sock, deadline))

    def read(self, amt=None):
        # Central size ceiling: every urlopen_retry response is bounded, so no
        # call site can accidentally buffer an unbounded provider body.
        if amt is None:
            body = super().read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"HTTP response body exceeds {MAX_RESPONSE_BYTES} bytes"
                )
            return body
        return super().read(amt)


def _open_with_deadline(handler, connection_type, req, **connection_options):
    deadline = getattr(req, "_multi_search_deadline", None)

    def connection(host, **options):
        if deadline is not None:
            options["timeout"] = _remaining(deadline)
        conn = connection_type(host, **options)
        if deadline is not None:
            conn.response_class = partial(_DeadlineHTTPResponse, deadline=deadline)
            create_connection = conn._create_connection
            tunnel = conn._tunnel

            def connect_socket(address, timeout=None, source_address=None, **socket_options):
                remaining = _remaining(deadline)
                if timeout is not None:
                    remaining = min(remaining, timeout)
                target_host, target_port = address
                proxy_hop = _is_trusted_proxy_hop(req, target_host, target_port)
                pinned = getattr(req, "_multi_search_pinned_addresses", None) or {}
                addresses = pinned.get((str(target_host).lower(), int(target_port)))
                if addresses is None:
                    if _is_ip_literal(target_host):
                        if not proxy_hop:
                            _ensure_connect_address(str(target_host), int(target_port))
                        sock = create_connection(
                            address, timeout=remaining,
                            source_address=source_address, **socket_options,
                        )
                        try:
                            sock.settimeout(_remaining(deadline))
                        except BaseException:
                            sock.close()
                            raise
                        return sock
                    # Validate the exact answers used for the connect call;
                    # a second unchecked getaddrinfo is a rebinding window.
                    # A trusted proxy hop is exempt: its loopback/private
                    # address is the user's configured proxy, not a destination.
                    if proxy_hop:
                        addresses = resolve_host_addresses(
                            target_host, target_port, deadline=deadline,
                        )
                    else:
                        addresses = resolve_validated_addresses(
                            target_host, target_port, deadline=deadline,
                        )
                last_error = None
                for family, socktype, proto, _canonname, sockaddr in addresses:
                    if not proxy_hop:
                        _ensure_connect_address(
                            *_sockaddr_host(sockaddr), resolved=True,
                        )
                    sock = None
                    try:
                        sock = socket.socket(family, socktype, proto)
                        sock.settimeout(_remaining(deadline))
                        if source_address:
                            sock.bind(source_address)
                        sock.connect(sockaddr)
                        sock.settimeout(_remaining(deadline))
                        return sock
                    except OSError as exc:
                        last_error = exc
                        if sock is not None:
                            sock.close()
                if last_error is not None:
                    raise last_error
                raise OSError("HTTP DNS resolution returned no addresses")

            def connect_tunnel():
                tunnel()
                try:
                    conn.sock.settimeout(_remaining(deadline))
                except BaseException:
                    conn.close()
                    raise

            # Leave stdlib connect/TLS/SNI handling intact; deduct TCP and
            # proxy CONNECT time before that flow starts the TLS handshake.
            conn._create_connection = connect_socket
            conn._tunnel = connect_tunnel
        return conn

    return handler.do_open(connection, req, **connection_options)


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return _open_with_deadline(self, http.client.HTTPConnection, req)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return _open_with_deadline(self, http.client.HTTPSConnection, req, context=self._context)


class _SafeHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, resolver=None):
        super().__init__()
        self._resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            deadline = getattr(req, "_multi_search_deadline", None)
            answers = []

            def capture(host):
                found = list((self._resolver or _resolve_host_ips)(host))
                answers.extend(found)
                return found

            validate_redirect_target(
                newurl, resolver=capture, deadline=deadline,
                allow_fake_ip=allow_fake_ip_default(),
            )
            pinned = _pin_redirect_addresses(newurl, deadline, lambda host: answers)
            old_origin, new_origin = _origin(req.full_url), _origin(newurl)
            if old_origin[0] == "https" and new_origin[0] == "http":
                raise UrlSecurityError("HTTPS redirect must not downgrade to HTTP")
            has_credentials = any(name.lower() in _CREDENTIAL_HEADERS for name, _ in req.header_items())
            if old_origin != new_origin and has_credentials:
                raise UrlSecurityError("cross-origin redirect must not forward credentials")
            redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
            if redirected is not None and deadline is not None:
                redirected._multi_search_deadline = deadline
                if pinned:
                    redirected._multi_search_pinned_addresses = pinned
                # urllib follows the redirect with the original request's timeout.
                req.timeout = redirected.timeout = _remaining(deadline)
            return redirected
        except Exception:
            fp.close()
            raise


def _pin_redirect_addresses(url: str, deadline: float | None, resolver=None) -> dict:
    """Resolve a redirect target once; connect to exactly the checked answers."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or _is_ip_literal(host):
        return {}
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())
    if port is None:
        return {}
    if resolver is not None:
        # Caller-supplied resolver (tests/offline) is authoritative; build
        # sockaddrs locally instead of issuing an implicit real DNS query.
        addresses = []
        for answer in resolver(host):
            ip = str(answer).strip("[]")
            try:
                parsed = ipaddress.ip_address(ip)
            except ValueError:
                raise UrlSecurityError("redirect target resolved to a non-IP value")
            ensure_public_ip(
                ip, label="redirect target", resolved=True,
                allow_fake_ip=allow_fake_ip_default(),
            )
            if isinstance(parsed, ipaddress.IPv4Address):
                addresses.append(
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                )
            else:
                addresses.append(
                    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))
                )
        return {(host, port): addresses} if addresses else {}
    try:
        addresses = resolve_validated_addresses(host, port, deadline=deadline)
    except UrlSecurityError:
        raise
    except OSError:
        # Resolution failures surface later in connect with a clearer error.
        return {}
    return {(host, port): addresses}


def _build_safe_opener(
    *,
    redirect_resolver=None,
    extra_handlers: Iterable[urllib.request.BaseHandler] = (),
):
    return urllib.request.build_opener(
        _SafeHTTPRedirectHandler(resolver=redirect_resolver),
        _DeadlineHTTPHandler(),
        _DeadlineHTTPSHandler(context=_ssl_ctx),
        *extra_handlers,
    )


_shared_opener = _build_safe_opener()


def urlopen_retry(
    req_or_url,
    timeout: int | float,
    retries: int = 2,
    *,
    deadline: float | None = None,
    redirect_resolver=None,
    extra_handlers: Iterable[urllib.request.BaseHandler] = (),
):
    """Keep SSL retries, redirects and response reads within one time budget.

    Returns the standard HTTPResponse protocol, including HTTPError bodies.
    """
    call_started = time.monotonic()
    deadline = min(
        call_started + float(timeout), float(deadline)
    ) if deadline is not None else call_started + float(timeout)
    request = req_or_url if isinstance(req_or_url, urllib.request.Request) else urllib.request.Request(req_or_url)
    request._multi_search_deadline = deadline
    last_exc = None
    handlers = tuple(extra_handlers)
    opener = (
        _shared_opener
        if redirect_resolver is None and not handlers
        else _build_safe_opener(
            redirect_resolver=redirect_resolver,
            extra_handlers=handlers,
        )
    )
    for _ in range(retries + 1):
        try:
            return opener.open(request, timeout=_remaining(deadline))
        except (ssl.SSLEOFError, ssl.SSLError) as e:
            # Retrying a POST-like request may duplicate a paid or mutating
            # operation whose first attempt actually reached the server.
            if request.get_method().upper() not in _RETRYABLE_METHODS:
                raise
            last_exc = e
            continue
        except OSError as e:
            msg = str(e)
            if "EOF" in msg or "SSL" in msg:
                if request.get_method().upper() not in _RETRYABLE_METHODS:
                    raise
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]
