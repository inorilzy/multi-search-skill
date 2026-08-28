"""HTTP utilities: tolerant SSL context + urlopen with retry."""
import ssl
from collections.abc import Iterable
import urllib.request

from .url_security import validate_redirect_target


_ssl_ctx = ssl.create_default_context()
if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
    _ssl_ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF  # type: ignore[attr-defined]


class _SafeHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, resolver=None):
        super().__init__()
        self._resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            validate_redirect_target(newurl, resolver=self._resolver)
        except Exception:
            fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_safe_opener(
    *,
    redirect_resolver=None,
    extra_handlers: Iterable[urllib.request.BaseHandler] = (),
):
    return urllib.request.build_opener(
        _SafeHTTPRedirectHandler(resolver=redirect_resolver),
        urllib.request.HTTPSHandler(context=_ssl_ctx),
        *extra_handlers,
    )


_shared_opener = _build_safe_opener()
urllib.request.install_opener(_shared_opener)


def urlopen_retry(
    req_or_url,
    timeout: int,
    retries: int = 2,
    *,
    redirect_resolver=None,
    extra_handlers: Iterable[urllib.request.BaseHandler] = (),
):
    """urlopen with up to 2 retries on SSL EOF errors (Python 3.12 + parallel TLS issue)."""
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
            return opener.open(req_or_url, timeout=timeout)
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
