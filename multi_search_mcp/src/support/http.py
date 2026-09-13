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
    resolve_host_addresses,
    validate_redirect_target,
)


_ssl_ctx = ssl.create_default_context()
if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
    _ssl_ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF  # type: ignore[attr-defined]


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
                if _is_ip_literal(target_host):
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

                addresses = resolve_host_addresses(
                    target_host, target_port, deadline=deadline,
                )
                last_error = None
                for family, socktype, proto, _canonname, sockaddr in addresses:
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
            validate_redirect_target(
                newurl, resolver=self._resolver, deadline=deadline,
            )
            old_origin, new_origin = _origin(req.full_url), _origin(newurl)
            if old_origin[0] == "https" and new_origin[0] == "http":
                raise UrlSecurityError("HTTPS redirect must not downgrade to HTTP")
            has_credentials = any(name.lower() in _CREDENTIAL_HEADERS for name, _ in req.header_items())
            if old_origin != new_origin and has_credentials:
                raise UrlSecurityError("cross-origin redirect must not forward credentials")
            redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
            if redirected is not None and deadline is not None:
                redirected._multi_search_deadline = deadline
                # urllib follows the redirect with the original request's timeout.
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
urllib.request.install_opener(_shared_opener)


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
            last_exc = e
            continue
        except OSError as e:
            msg = str(e)
            if "EOF" in msg or "SSL" in msg:
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]
