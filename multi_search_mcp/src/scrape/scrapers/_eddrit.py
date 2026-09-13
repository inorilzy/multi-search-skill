"""Anonymous Reddit transport adapted from eddrit 0.19.0.

Source: corenting/eddrit, df1bcc3cb3815adf043e750e54cd309cd484fed1,
eddrit/utils/oauth.py and eddrit/utils/httpx.py. The Android identity and
LOID exchange are reused; this adapter uses curl_cffi directly and a bounded,
process-local cache instead of eddrit's frontend/Valkey dependencies.

MIT License
Copyright (c) 2020 corenting

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

from base64 import standard_b64encode
import math
import os
import random
import threading
import time
from urllib.request import getproxies, proxy_bypass
from uuid import uuid4

from ...support.url_security import validate_public_http_url


TOKEN_URL = "https://www.reddit.com/auth/v2/oauth/access-token/loid"
API_ORIGIN = "https://oauth.reddit.com"
ANDROID_CLIENT_ID = "ohXpoqrZYub1kg"
APP_VERSIONS = (
    "Version 2024.35.0/Build 1857451", "Version 2024.34.0/Build 1837909",
    "Version 2024.33.0/Build 1819908", "Version 2024.32.1/Build 1813258",
    "Version 2024.32.0/Build 1809095", "Version 2024.31.0/Build 1786202",
    "Version 2024.30.0/Build 1770787", "Version 2024.29.0/Build 1747562",
    "Version 2024.28.1/Build 1741165", "Version 2024.28.0/Build 1737665",
    "Version 2024.26.1/Build 1717435", "Version 2024.26.1/Build 1717435",
    "Version 2024.26.0/Build 1710470",
)


class EddritError(ValueError):
    """A public error that never embeds response bodies or credentials."""


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Reddit scrape deadline exceeded")
    return seconds


def _android_headers() -> dict[str, str]:
    device_id = str(uuid4())
    codecs = "available-codecs=video/avc, video/hevc"
    if random.choice((0, 1)):
        codecs += ", video/x-vnd.on2.vp9"
    return {
        "User-Agent": f"Reddit/{random.choice(APP_VERSIONS)}/Android {random.choice(range(9, 15))}",
        "x-reddit-retry": "algo=no-retries",
        "x-reddit-compression": "1",
        "x-reddit-qos": f"{random.uniform(1.0, 100):.3f}",
        "x-reddit-media-codecs": codecs,
        "Client-Vendor-Id": device_id,
        "X-Reddit-Device-Id": device_id,
    }


def _json_response(response):
    if response.status_code != 200:
        raise EddritError(f"Reddit returned HTTP {response.status_code}")
    if "application/json" not in response.headers.get("content-type", "").lower():
        raise EddritError("Reddit returned a non-JSON response (possibly a block page)")
    try:
        return response.json()
    except (ValueError, TypeError):
        raise EddritError("Reddit returned invalid JSON") from None


class AnonymousAuth:
    def __init__(self):
        self._lock = threading.Lock()
        self._headers: dict[str, str] = {}
        self._expires_at = 0.0
        self._proxy: str | None = None

    def headers(self, session, deadline: float, proxy: str | None) -> dict[str, str]:
        if not self._lock.acquire(timeout=remaining(deadline)):
            raise TimeoutError("Reddit authentication deadline exceeded")
        try:
            if self._headers and self._proxy == proxy and time.monotonic() < self._expires_at:
                return dict(self._headers)
            common = _android_headers()
            basic = standard_b64encode(f"{ANDROID_CLIENT_ID}:".encode()).decode()
            response = session.post(
                TOKEN_URL, headers={**common, "Authorization": f"Basic {basic}"},
                json={"scopes": ["*", "email", "pii"]}, timeout=remaining(deadline),
            )
            data = _json_response(response)
            try:
                token = data["access_token"]
                ttl = float(data["expires_in"])
                loid, session_id = response.headers["x-reddit-loid"], response.headers["x-reddit-session"]
                if not isinstance(token, str) or not token or not math.isfinite(ttl) or ttl <= 0:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise EddritError("Reddit returned invalid anonymous credentials") from None
            self._headers = {**common, "Authorization": f"Bearer {token}",
                             "x-reddit-loid": loid, "x-reddit-session": session_id}
            self._expires_at = time.monotonic() + max(0.0, ttl - 300)
            self._proxy = proxy
            return dict(self._headers)
        finally:
            self._lock.release()

    def invalidate(self, headers: dict[str, str], deadline: float) -> None:
        if not self._lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return
        try:
            if self._headers.get("Authorization") == headers.get("Authorization"):
                self._headers = {}
        finally:
            self._lock.release()


_auth = AnonymousAuth()


def get_post_json(post_id: str, params: dict, deadline: float, *, resolver=None):
    # All requests go to fixed Reddit endpoints; redirects never carry the token.
    api_url = f"{API_ORIGIN}/comments/{post_id}.json"
    validate_public_http_url(TOKEN_URL, resolver=resolver, deadline=deadline)
    validate_public_http_url(api_url, resolver=resolver, deadline=deadline)
    from curl_cffi.requests import Session

    proxies = getproxies()
    proxy = os.environ.get("PROXY") or proxies.get("https") or proxies.get("all")
    if not os.environ.get("PROXY") and proxy_bypass("oauth.reddit.com"):
        proxy = None
    with Session(impersonate="chrome131_android", proxy=proxy, trust_env=False,
                 allow_redirects=False, timeout=remaining(deadline)) as session:
        headers = _auth.headers(session, deadline, proxy)
        headers.update({"Content-Type": "application/json; charset=UTF-8",
                        "Accept-Encoding": "gzip", "Cookie": "", "Host": "oauth.reddit.com"})
        items = list(headers.items())
        random.shuffle(items)
        response = session.get(api_url, params=params, headers=dict(items), timeout=remaining(deadline))
        if response.status_code == 401:
            _auth.invalidate(headers, deadline)
        return _json_response(response)
