"""HTTP requests with safe redirects and a shared retry/read deadline.

Trust model: every outbound target is a provider address fixed in code (search
APIs, scrape backends, the Reddit API, the X API), while externally supplied
URLs are only handed to those providers as parameters. The HTTP layer therefore
never resolves a target name itself and never checks resolved addresses: name
resolution and dialing are left to the standard library socket connect, so a
TUN fake-IP proxy works exactly as it does for a browser or curl. Only checks
that need no DNS remain: http/https, a valid host, no credentials, no
``localhost`` and no non-public IP literal (including numeric aliases and
embedded IPv4 forms).

If a future scraper connects to an external URL from this machine, it must add
resolved-address checks back before calling :func:`urlopen_retry`.
"""
import http.client
import io
import socket
import ssl
import time
from collections.abc import Iterable
from functools import partial
import urllib.parse
import urllib.request

from .url_security import (
    UrlSecurityError,
    check_host_is_not_local,
    http_target,
    numeric_host,
)


# Default verification and strict EOF handling: a TLS stream that ends without
# close_notify is a truncation and must fail, not read as a complete body.
_ssl_ctx = ssl.create_default_context()

# Only these methods are safe to retry after SSL/EOF. POST-like requests may
# charge money or mutate remote state on the first, apparently failed attempt.
_RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _is_certificate_failure(exc: BaseException) -> bool:
    """True for TLS verification failures, which no retry can fix."""
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        # urllib wraps handshake errors as URLError(reason=<SSLError>).
        reason = getattr(current, "reason", None)
        current = reason if isinstance(reason, BaseException) else current.__cause__ or current.__context__
    return False


def _origin(url: str) -> tuple[str, str, int]:
    parts, host, port = http_target(url)
    return parts.scheme.lower(), host, port


# One size bound for every provider response body (search and scrape APIs,
# including HTTP error bodies). Real provider JSON is far smaller; the cap only
# stops an abnormal or hostile upstream from filling memory inside the deadline.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Error bodies are only used for a short diagnostic message.
ERROR_BODY_LIMIT = 4096


class ResponseTooLargeError(ValueError):
    """A provider response body (raw or decompressed) exceeded its size bound.

    A ValueError, not an OSError, so the SSL/EOF retry loop never repeats it.
    The message deliberately avoids words key classification treats as auth,
    quota, rate-limit, timeout or network failures.
    """

    def __init__(self, what: str, limit: int):
        super().__init__(f"{what} is larger than the {limit}-byte size cap")
        self.limit = limit


def _content_length(resp) -> int | None:
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Content-Length")
    except Exception:  # noqa: BLE001 - only an optional early check
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def read_limited(resp, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a whole response body, refusing anything over ``max_bytes``.

    A declared oversize Content-Length is rejected before reading; otherwise at
    most ``max_bytes + 1`` bytes are ever pulled into memory.
    """
    declared = _content_length(resp)
    if declared is not None and declared > max_bytes:
        raise ResponseTooLargeError("provider response body", max_bytes)
    body = resp.read(max_bytes + 1)
    if isinstance(body, str):
        body = body.encode("utf-8")
    body = bytes(body or b"")
    if len(body) > max_bytes:
        raise ResponseTooLargeError("provider response body", max_bytes)
    return body


def read_error_body(exc, limit: int = ERROR_BODY_LIMIT) -> bytes:
    """Read at most ``limit`` bytes of an HTTP error body for diagnostics."""
    body = exc.read(limit)
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    return bytes(body or b"")[:limit]


def decompress_limited(data: bytes, encoding: str, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Decompress gzip/deflate bounded by the *decompressed* size (no bombs)."""
    import zlib

    encoding = (encoding or "").strip().lower()
    if encoding == "gzip":
        candidates = (16 + zlib.MAX_WBITS,)
    elif encoding == "deflate":
        # RFC "deflate" is zlib-wrapped; some servers send raw deflate.
        candidates = (zlib.MAX_WBITS, -zlib.MAX_WBITS)
    else:
        raise ValueError(f"unsupported Content-Encoding: {encoding}")
    last_error = None
    for wbits in candidates:
        decompressor = zlib.decompressobj(wbits)
        try:
            output = decompressor.decompress(data, max_bytes + 1)
        except zlib.error as exc:
            last_error = exc
            continue
        if len(output) > max_bytes or decompressor.unconsumed_tail:
            raise ResponseTooLargeError("decompressed provider response", max_bytes)
        if not decompressor.eof:
            last_error = zlib.error("incomplete compressed response")
            continue
        return output
    raise ValueError(f"invalid {encoding} response: {last_error}")


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("HTTP request deadline exceeded")
    return remaining


def _ensure_connect_address(raw_address: str) -> None:
    """Refuse a literal connect target that is not public, before any socket."""
    check_host_is_not_local(str(raw_address).strip("[]"), label="HTTP connection")


class _DeadlineReader(io.RawIOBase):
    """Refresh the socket budget before each individual buffered-stream read.

    A single HTTPResponse.read() can perform many socket reads, so setting the
    timeout just once still lets a slow, continuously arriving body run forever.
    read1 performs at most one underlying read, including for chunked bodies.
    """

    def __init__(self, stream, sock, deadline: float, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        self.stream, self.sock, self.deadline = stream, sock, deadline
        self.timeout = timeout

    def readable(self):
        return True

    def readinto(self, target):
        if not target:
            return 0
        try:
            self.sock.settimeout(_socket_budget(self.deadline, self.timeout))
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
    def __init__(self, sock, *args, deadline: float, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs):
        super().__init__(sock, *args, **kwargs)
        self.fp = io.BufferedReader(_DeadlineReader(self.fp, sock, deadline, timeout))

    def read(self, amt=None):
        # Central size ceiling: every urlopen_retry response is bounded here, so
        # no call site can accidentally buffer an unbounded provider body. A
        # declared oversize Content-Length is refused before reading it.
        if amt is None:
            declared = _content_length(self)
            if declared is not None and declared > MAX_RESPONSE_BYTES:
                raise ResponseTooLargeError("provider response body", MAX_RESPONSE_BYTES)
            body = super().read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ResponseTooLargeError("provider response body", MAX_RESPONSE_BYTES)
            return body
        return super().read(amt)


def _socket_budget(deadline, timeout):
    if timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
        timeout = socket.getdefaulttimeout()
    if deadline is None:
        return timeout
    remaining = _remaining(deadline)
    return remaining if timeout is None else min(remaining, timeout)


def _open_with_deadline(handler, connection_type, req, **connection_options):
    deadline = getattr(req, "_multi_search_deadline", None)
    # Validate the logical URL, not the socket hop. With an explicit proxy the
    # socket hop is the user's proxy (loopback is normal) and urllib hands the
    # hostname to the proxy, so the destination is checked here instead.
    if getattr(req, "full_url", None):
        _parts, logical_host, _logical_port = http_target(req.full_url)
        check_host_is_not_local(logical_host, label="HTTP connection")
    proxy_hop = bool(
        getattr(req, "has_proxy", lambda: False)()
        or getattr(req, "_tunnel_host", None)
    )

    def connection(host, **options):
        if deadline is not None:
            options["timeout"] = _socket_budget(deadline, options.get("timeout", socket._GLOBAL_DEFAULT_TIMEOUT))
        conn = connection_type(host, **options)
        create_connection = conn._create_connection
        tunnel = conn._tunnel

        def connect_socket(address, timeout=None, source_address=None, **socket_options):
            remaining = _socket_budget(deadline, timeout)
            target_host, target_port = address
            if not proxy_hop:
                # Re-check the exact host handed to the dialer, and canonicalise
                # a numeric alias so getaddrinfo cannot read it another way.
                literal = numeric_host(target_host)
                if literal is not None:
                    _ensure_connect_address(str(literal))
                    address = (str(literal), target_port)
            # Hostnames are resolved and dialed by socket.create_connection; the
            # resolved address is not checked here.
            sock = create_connection(
                address, timeout=remaining,
                source_address=source_address, **socket_options,
            )
            try:
                sock.settimeout(_socket_budget(deadline, timeout))
            except BaseException:
                sock.close()
                raise
            return sock

        def connect_tunnel():
            try:
                tunnel()
                conn.sock.settimeout(_socket_budget(deadline, conn.timeout))
            except BaseException:
                conn.close()
                raise

        if deadline is not None:
            conn.response_class = partial(
                _DeadlineHTTPResponse, deadline=deadline,
                timeout=options.get("timeout", socket._GLOBAL_DEFAULT_TIMEOUT),
            )
        # Always replace the dial path, even without a deadline. Deadline only
        # changes the timeout accounting, not the address safety checks.
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


def _has_explicit_port(url: str) -> bool:
    try:
        return urllib.parse.urlsplit(url).port is not None
    except ValueError:
        return False


class _SafeHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirects by rules that need no DNS.

    Allowed: the same scheme, host and port, and an http -> https upgrade on
    the same host to the default https port or the port the original URL
    named. Cross-host targets, https -> http downgrades, other port changes
    and non-public IP-literal targets fail; the error names the reason without
    echoing the full target URL. Because cross-host redirects never follow, no
    credential header can be forwarded to another host.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            deadline = getattr(req, "_multi_search_deadline", None)
            old_scheme, old_host, old_port = _origin(req.full_url)
            _parts, new_host, new_port = http_target(newurl, label="redirect target")
            check_host_is_not_local(new_host, label="redirect target")
            new_scheme = urllib.parse.urlsplit(newurl).scheme.lower()
            if old_scheme == "https" and new_scheme == "http":
                raise UrlSecurityError("unsafe redirect target: HTTPS must not downgrade to HTTP")
            if new_host != old_host:
                raise UrlSecurityError("unsafe redirect target: cross-host redirect is not allowed")
            if old_scheme == "http" and new_scheme == "https":
                # An upgrade may only reach the default https port, or the port the
                # original URL named explicitly. Any other port is a different service.
                allowed_ports = {443} | ({old_port} if _has_explicit_port(req.full_url) else set())
                if new_port not in allowed_ports:
                    raise UrlSecurityError(
                        "unsafe redirect target: upgrade may only keep the default or original port"
                    )
            elif (new_scheme, new_port) != (old_scheme, old_port):
                raise UrlSecurityError(
                    "unsafe redirect target: redirect must keep the same scheme and port"
                )
            redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
            if redirected is not None and deadline is not None:
                redirected._multi_search_deadline = deadline
                req.timeout = redirected.timeout = _remaining(deadline)
            return redirected
        except Exception:
            fp.close()
            raise


def _build_safe_opener(
    *,
    extra_handlers: Iterable[urllib.request.BaseHandler] = (),
):
    return urllib.request.build_opener(
        _SafeHTTPRedirectHandler(),
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
        if not handlers
        else _build_safe_opener(extra_handlers=handlers)
    )
    retryable = request.get_method().upper() in _RETRYABLE_METHODS
    for _ in range(retries + 1):
        try:
            return opener.open(request, timeout=_remaining(deadline))
        except (ssl.SSLEOFError, ssl.SSLError) as e:
            # A certificate failure no retry can fix; a POST-like request may
            # already have reached the server, so retrying could duplicate it.
            if _is_certificate_failure(e) or not retryable:
                raise
            last_exc = e
            continue
        except OSError as e:
            if _is_certificate_failure(e):
                raise
            msg = str(e)
            if "EOF" in msg or "SSL" in msg:
                if not retryable:
                    raise
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]
