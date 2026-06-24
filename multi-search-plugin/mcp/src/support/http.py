"""HTTP utilities: tolerant SSL context + urlopen with retry."""
import ssl
import urllib.request


_ssl_ctx = ssl.create_default_context()
if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
    _ssl_ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF  # type: ignore[attr-defined]

_https_handler = urllib.request.HTTPSHandler(context=_ssl_ctx)
urllib.request.install_opener(urllib.request.build_opener(_https_handler))


def urlopen_retry(req_or_url, timeout: int, retries: int = 2):
    """urlopen with up to 2 retries on SSL EOF errors (Python 3.12 + parallel TLS issue)."""
    last_exc = None
    for _ in range(retries + 1):
        try:
            return urllib.request.urlopen(req_or_url, timeout=timeout, context=_ssl_ctx)
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
