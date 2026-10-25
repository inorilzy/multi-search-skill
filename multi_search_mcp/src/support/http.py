"""HTTP requests with safe redirects and a shared retry/read deadline."""
import http.client
import ipaddress
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
    _ensure_public_ip,
    _resolve_host_ips,
    allow_fake_ip_default,
    ensure_public_ip,
    numeric_host,
    normalize_http_host,
    http_target,
    resolve_host_addresses,
    resolve_validated_addresses,
    validate_redirect_target,
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


_CREDENTIAL_HEADERS = {
    "authorization", "proxy-authorization", "cookie",
    "x-api-key", "x-subscription-token", "x-appbuilder-authorization",
}


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port if parts.port is not None else {"http": 80, "https": 443}.get(scheme)
    return scheme, (parts.hostname or "").lower(), port


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


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _configured_proxy_addresses() -> set[tuple[str, int]]:
    """Exact endpoints explicitly configured as this process's proxies."""
    targets: set[tuple[str, int]] = set()
    defaults = {"http": 80, "https": 443, "socks": 1080, "socks5": 1080, "socks4": 1080}
    for proxy_url in urllib.request.getproxies().values():
        target = _proxy_host_port(str(proxy_url), defaults=defaults)
        if target is not None:
            targets.add(target)
    return targets


def _proxy_host_port(
    target: str, *, defaults: dict[str, int] | None = None,
) -> tuple[str, int] | None:
    text = str(target or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "//" + text
    try:
        parts = urllib.parse.urlsplit(text)
        host = normalize_http_host(parts.hostname or "")
        port = parts.port
        if port is None:
            port = (defaults or {"http": 80, "https": 443}).get(parts.scheme.lower(), 80)
        return host, int(port)
    except (ValueError, UnicodeError):
        return None


def _trusted_proxy_targets(req) -> set[tuple[str, int]]:
    """Configured proxy hops only; request destinations never grant trust."""
    targets = set(_configured_proxy_addresses())
    if getattr(req, "has_proxy", lambda: False)() or bool(getattr(req, "_tunnel_host", None)):
        request_proxy = _proxy_host_port(getattr(req, "host", ""))
        if request_proxy is not None:
            targets.add(request_proxy)
    return targets


def _is_trusted_proxy_hop(req, host: str, port: int) -> bool:
    has_proxy = getattr(req, "has_proxy", lambda: False)
    if not (has_proxy() or bool(getattr(req, "_tunnel_host", None))):
        return False
    normalized = str(host or "").strip("[]").lower()
    return (normalized, int(port)) in _trusted_proxy_targets(req)


def _ensure_connect_address(raw_address: str, port=None, *, resolved: bool = False) -> None:
    ensure_public_ip(
        str(raw_address).strip("[]"), label="HTTP connection", resolved=resolved,
        allow_fake_ip=allow_fake_ip_default() if resolved else False,
    )


def _sockaddr_host(sockaddr) -> str:
    return str(sockaddr[0]).strip("[]")


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
    # Validate the logical URL separately from the socket hop. Parse before
    # urllib sends HTTP absolute-form GET or HTTPS CONNECT to a trusted proxy.
    parts = None
    if getattr(req, "full_url", None):
        parts, logical_host, logical_port = http_target(req.full_url)
        literal = numeric_host(logical_host)
        if literal is not None:
            _ensure_connect_address(str(literal))
    proxy_target = None
    proxy_hop_target = _proxy_host_port(req.host) if (
        getattr(req, "has_proxy", lambda: False)() or getattr(req, "_tunnel_host", None)
    ) else None
    original_selector = getattr(req, "selector", None)
    if proxy_hop_target is not None:
        if parts is None:
            raise UrlSecurityError("proxy request is missing its logical target")
        pinned = getattr(req, "_multi_search_pinned_addresses", {})
        answers = pinned.get((logical_host, logical_port))
        if answers is None:
            answers = resolve_validated_addresses(logical_host, logical_port, deadline=deadline)
        for answer in answers:
            _ensure_connect_address(answer[4][0], resolved=literal is None)
        if not answers:
            raise UrlSecurityError("URL host did not resolve to any IP")
        # Reuse the checked destination even across idempotent retry attempts.
        req._multi_search_pinned_addresses = {**pinned, (logical_host, logical_port): answers}
        proxy_target = answers[0][4][0]
        if not getattr(req, "_tunnel_host", None):
            authority = f"[{proxy_target}]" if ":" in proxy_target else proxy_target
            origin = f"[{logical_host}]" if ":" in logical_host else logical_host
            if parts.port is not None:
                origin += f":{logical_port}"
            req.add_unredirected_header("Host", origin)
            # Only the routing authority changes. The origin Host stays intact.
            req.selector = urllib.parse.urlunsplit((
                parts.scheme, f"{authority}:{logical_port}", parts.path or "/", parts.query, "",
            ))

    def connection(host, **options):
        if deadline is not None:
            options["timeout"] = _socket_budget(deadline, options.get("timeout", socket._GLOBAL_DEFAULT_TIMEOUT))
        conn = connection_type(host, **options)
        create_connection = conn._create_connection
        tunnel = conn._tunnel

        def connect_socket(address, timeout=None, source_address=None, **socket_options):
            remaining = _socket_budget(deadline, timeout)
            target_host, target_port = address
            target_host = normalize_http_host(target_host)
            proxy_hop = proxy_hop_target == (target_host, int(target_port))
            pinned = getattr(req, "_multi_search_pinned_addresses", None) or {}
            addresses = pinned.get((str(target_host).lower(), int(target_port)))
            literal = numeric_host(target_host)
            if literal is not None and not proxy_hop:
                _ensure_connect_address(str(literal))
                target_host = str(literal)
                address = (target_host, target_port)
            if addresses is None and _is_ip_literal(target_host):
                if not proxy_hop:
                    _ensure_connect_address(str(target_host))
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

            if addresses is None:
                # Validate the exact answers used for connect; a second lookup
                # is a DNS-rebinding window. Proxy hops resolve without inheriting
                # the destination's public-address requirement.
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
                    _ensure_connect_address(_sockaddr_host(sockaddr), resolved=True)
                sock = None
                try:
                    sock = socket.socket(family, socktype, proto)
                    sock.settimeout(_socket_budget(deadline, timeout))
                    if source_address:
                        sock.bind(source_address)
                    sock.connect(sockaddr)
                    sock.settimeout(_socket_budget(deadline, timeout))
                    return sock
                except OSError as exc:
                    last_error = exc
                    if sock is not None:
                        sock.close()
            if last_error is not None:
                raise last_error
            raise OSError("HTTP DNS resolution returned no addresses")

        def connect_tunnel():
            original_host = conn._tunnel_host
            original_headers = conn._tunnel_headers.copy()
            try:
                if proxy_target is not None:
                    conn._tunnel_host = proxy_target
                    authority = f"[{proxy_target}]" if ":" in proxy_target else proxy_target
                    conn._tunnel_headers["Host"] = f"{authority}:{conn._tunnel_port}"
                tunnel()
                conn.sock.settimeout(_socket_budget(deadline, conn.timeout))
            except BaseException:
                conn.close()
                raise
            finally:
                # HTTPSConnection uses this after CONNECT for SNI/certificate
                # identity. Only CONNECT's routing address is replaced.
                conn._tunnel_host = original_host
                conn._tunnel_headers = original_headers

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

    try:
        return handler.do_open(connection, req, **connection_options)
    finally:
        # has_proxy() depends on selector == full_url; preserve urllib's proxy
        # state for retries while never forwarding the unchecked selector.
        if original_selector is not None:
            req.selector = original_selector


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return _open_with_deadline(self, http.client.HTTPConnection, req)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return _open_with_deadline(self, http.client.HTTPSConnection, req, context=self._context)


def _pin_redirect_addresses(url: str, deadline: float | None, answers) -> dict:
    """Resolve a redirect target once; connect to exactly the checked answers.

    ``validate_redirect_target`` checks every answer, but urllib would resolve
    the host again for the connect call, leaving a DNS-rebinding window. Pinning
    the validated answers closes it.
    """
    _parts, host, port = http_target(url, label="redirect target")
    literal = numeric_host(host)
    if literal is not None:
        _ensure_connect_address(str(literal))
        return {}
    if not answers:
        # Validation must supply the exact DNS answers; never silently perform
        # a second lookup when pinning the connection.
        raise UrlSecurityError("redirect target host did not resolve to any IP")
    addresses = []
    for answer in answers:
        try:
            parsed = ipaddress.ip_address(str(answer).strip("[]"))
        except ValueError:
            raise UrlSecurityError("redirect target resolved to a non-IP value")
        _ensure_public_ip(parsed, label="redirect target", resolved=True,
                          allow_fake_ip=allow_fake_ip_default())
        ip = str(parsed)
        if isinstance(parsed, ipaddress.IPv4Address):
            addresses.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)))
        else:
            addresses.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0)))
    return {(host, port): addresses} if addresses else {}


class _SafeHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, resolver=None):
        super().__init__()
        self._resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            deadline = getattr(req, "_multi_search_deadline", None)
            answers: list[str] = []

            def capture(host):
                found = list((self._resolver or _resolve_host_ips)(host))
                answers.extend(found)
                return found

            validate_redirect_target(
                newurl, resolver=capture, deadline=deadline,
            )
            pinned = _pin_redirect_addresses(newurl, deadline, answers or None)
            old_origin, new_origin = _origin(req.full_url), _origin(newurl)
            if old_origin[0] == "https" and new_origin[0] == "http":
                raise UrlSecurityError("HTTPS redirect must not downgrade to HTTP")
            has_credentials = any(name.lower() in _CREDENTIAL_HEADERS for name, _ in req.header_items())
            if old_origin != new_origin and has_credentials:
                raise UrlSecurityError("cross-origin redirect must not forward credentials")
            redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
            if redirected is not None:
                if pinned:
                    redirected._multi_search_pinned_addresses = pinned
                if deadline is not None:
                    redirected._multi_search_deadline = deadline
                    req.timeout = redirected.timeout = _remaining(deadline)
            return redirected
        except Exception:
            fp.close()
            raise


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
