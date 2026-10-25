import email.message
import io
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import urllib.response
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.scrape.scrapers.reddit import scrape_url_reddit
from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor
from multi_search_mcp.src.support.url_security import UrlSecurityError


PUBLIC_IP = "93.184.216.34"


class DnsDeadlineTests(unittest.TestCase):
    def setUp(self):
        # Slow resolvers block on this event instead of sleeping, so "late"
        # means "after the caller has already returned", not "after N ms".
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def _slow_resolver(self, finished: threading.Event, result=None):
        def resolve(_host):
            try:
                self.release.wait(timeout=5)
                return list(result or [PUBLIC_IP])
            finally:
                finished.set()

        return resolve

    def _finish_late_resolution(self, finished: threading.Event):
        self.release.set()
        self.assertTrue(finished.wait(timeout=5))

    @staticmethod
    def _redirect_response(url: str, location: str):
        headers = email.message.Message()
        headers["Location"] = location
        response = urllib.response.addinfourl(io.BytesIO(b""), headers, url, 302)
        response.msg = "Found"
        return response

    def test_http_dns_timeout_returns_before_late_resolution_can_connect(self):
        finished = threading.Event()

        def delayed_dns(_host, port, *args, **kwargs):
            try:
                self.release.wait(timeout=5)
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port))]
            finally:
                finished.set()

        start = time.monotonic()
        with mock.patch("socket.getaddrinfo", side_effect=delayed_dns), mock.patch(
            "socket.socket.connect", side_effect=AssertionError("TCP must not start after DNS deadline"),
        ):
            with self.assertRaises((TimeoutError, urllib.error.URLError)) as error:
                http.urlopen_retry(
                    "http://slow.example/path",
                    timeout=0.01,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)
        self.assertIn("DNS", str(error.exception))
        self._finish_late_resolution(finished)

    def test_url_security_dns_timeout_returns_before_late_resolver_result(self):
        finished = threading.Event()
        start = time.monotonic()

        with self.assertRaises(UrlSecurityError) as error:
            url_security.validate_public_http_url(
                "https://slow.example/path",
                resolver=self._slow_resolver(finished),
                deadline=time.monotonic() + 0.01,
            )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)
        self.assertIn("DNS", str(error.exception))
        self.assertIn("deadline", str(error.exception))
        self._finish_late_resolution(finished)

    def test_scrape_core_does_not_resolve_delegated_urls_locally(self):
        # A delegated backend fetches the URL from the provider's network, so a
        # local DNS preflight adds no SSRF protection and wrongly rejects
        # fake-IP/TUN routing. The resolver must not even be consulted.
        for backend in ("firecrawl", "jina", "exa", "tavily"):
            with self.subTest(backend=backend):
                resolver = mock.Mock(side_effect=AssertionError("delegated URL resolved locally"))
                with mock.patch(
                    "multi_search_mcp.src.scrape.scrape._jina_anonymous_cooling_down",
                    return_value=False,
                ), mock.patch(
                    f"multi_search_mcp.src.scrape.scrape.scrape_url_{backend}",
                    return_value={"url": "https://slow.example/path", "error": "delegated backend error"},
                ) as scraper:
                    result = scrape_url_smart(
                        "https://slow.example/path",
                        primary=backend,
                        backends=(backend,),
                        **({f"{backend}_keys": ["synthetic-key"]} if backend in {"exa", "tavily"} else {}),
                        deadline=time.monotonic() + 5,
                        url_resolver=resolver,
                    )

                resolver.assert_not_called()
                scraper.assert_called_once()
                self.assertEqual(result["via"], backend)
                self.assertIn("delegated backend error", result["error"])

    def test_delegated_url_still_rejects_local_targets_without_dns(self):
        resolver = mock.Mock(side_effect=AssertionError("unsafe URL must fail before DNS"))
        for url, reason in (
            ("http://127.0.0.1/admin", "loopback"),
            ("http://[::1]/admin", "loopback"),
            ("http://10.0.0.5/admin", "private"),
            ("http://192.168.1.1/admin", "private"),
            ("http://169.254.169.254/latest/meta-data", "link-local"),
            ("http://0.0.0.0/", "unspecified"),
            ("http://localhost/admin", "localhost"),
            ("http://api.localhost/admin", "localhost"),
            ("ftp://example.com/file", "unsupported URL scheme"),
            ("file:///etc/passwd", "unsupported URL scheme"),
            ("https://user:secret@example.com/", "credentials"),
            # Non-canonical numeric IPv4 forms (inet_aton semantics) that
            # platform resolvers map to local addresses.
            ("http://2130706433/admin", "loopback"),
            ("http://0x7f.0.0.1/admin", "loopback"),
            ("http://0x7f000001/", "loopback"),
            ("http://127.1/", "loopback"),
            ("http://127.0.1/", "loopback"),
            # Leading-zero labels are octal to glibc/WHATWG but decimal to
            # BSD libc: rejected as ambiguous instead of guessing a base.
            ("http://017700000001/", "non-canonical numeric"),
            ("http://127.000.000.001/", "non-canonical numeric"),
            ("http://0/", "unspecified"),
            ("http://2852039166/latest/meta-data/", "link-local"),
            ("http://0xa9fea9fe/", "link-local"),
            ("http://0251.0376.0251.0376/", "non-canonical numeric"),
            ("http://169.254.43518/", "link-local"),
            ("http://167772165/", "private"),
            ("http://0x0a.0.0.5/", "private"),
            # Numeric-looking hosts that are not a valid address fail closed.
            ("http://1.2.3.999/", "numeric"),
            ("http://08/", "numeric"),
            # Hosts that normalize (NFKC, IDNA dots, percent-decoding) to local
            # targets.
            ("http://\u24db\u24de\u24d2\u24d0\u24db\u24d7\u24de\u24e2\u24e3/", "localhost"),
            ("http://\uff11\uff12\uff17.\uff10.\uff10.\uff11/", "loopback"),
            ("http://127\u30020\u30020\u30021/", "loopback"),
            ("http://127\uff0e0\uff0e0\uff0e1/", "loopback"),
            ("http://127\uff610\uff610\uff611/", "loopback"),
            ("http://127.0.0.%31/", "loopback"),
            ("http://%6cocalhost/", "localhost"),
            # Credentials stay out of the error even for an unsafe host.
            ("http://user:secret@2130706433/", "credentials"),
            # A backslash ends the authority for WHATWG parsers (the provider
            # side), so these would fetch the local host after the backslash.
            ("http://127.0.0.1\\admin", "not a valid hostname"),
            ("http://127.0.0.1\\.evil.com/", "not a valid hostname"),
            ("http://169.254.169.254\\latest\\meta-data", "not a valid hostname"),
            ("http://localhost\\admin", "not a valid hostname"),
            ("http://LOCALHOST\\admin", "not a valid hostname"),
            ("http://10.0.0.5\\admin", "not a valid hostname"),
            ("http://2130706433\\admin", "not a valid hostname"),
            ("http://\\127.0.0.1/", "not a valid hostname"),
            ("http://evil.com\\@127.0.0.1/", "credentials"),
            ("http://user:secret@evil.com\\@127.0.0.1/", "credentials"),
            # Tab/CR/LF are silently dropped by WHATWG parsers.
            ("http://127.0.0.1\t/", "control characters"),
            ("http://127.0.0\n.1/", "control characters"),
            # Ambiguous leading-zero labels (decimal on BSD libc, octal elsewhere).
            ("http://010.0.0.05/", "non-canonical numeric"),
            ("http://010.0.0.01/", "non-canonical numeric"),
            ("http://0010.0.0.5/", "non-canonical numeric"),
            ("http://0127.0.0.1/", "non-canonical numeric"),
            ("http://0177.0.0.1/", "non-canonical numeric"),
            ("http://012.0.0.1/", "non-canonical numeric"),
            # Characters outside the hostname set fail closed.
            ("http://127.0.0.1%00/", "not a valid hostname"),
            ("http://127.0.0.1%1f/", "not a valid hostname"),
            ("http://exa^mple.com/", "not a valid hostname"),
            ("http://exa|mple.com/", "not a valid hostname"),
            ("http://exa<mple.com/", "not a valid hostname"),
            ("http://exa mple.com/", "not a valid hostname"),
            ("http://[fe80::1%25eth0]/", "not a valid hostname"),
        ):
            with self.subTest(url=url), \
                 mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl") as scraper:
                result = scrape_url_smart(
                    url, primary="firecrawl", backends=("firecrawl",),
                    deadline=time.monotonic() + 5, url_resolver=resolver,
                )
                self.assertIn(reason, result["error"])
                self.assertNotIn("secret", result["error"])
                scraper.assert_not_called()
        resolver.assert_not_called()

    def test_delegated_url_accepts_public_and_fake_ip_domains_without_dns(self):
        # Fake-IP/TUN routing only shows up in DNS answers, which the delegated
        # path never requests. Real domains (including numeric labels before
        # the TLD and IDNs) and public literals still dispatch.
        resolver = mock.Mock(side_effect=AssertionError("delegated URL resolved locally"))
        for url in (
            "https://fake-ip.tun.example/article",
            "https://163.com/news",
            "https://1password.com/",
            "https://123.example.com/",
            "https://0x.example.com/",
            "https://exa_mple.com/",
            "https://m\u00fcnchen.de/",
            "https://93.184.216.34/",
            "https://134744072/",
        ):
            with self.subTest(url=url), mock.patch(
                "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl",
                return_value={"url": url, "markdown": "body", "via": "firecrawl"},
            ) as scraper:
                result = scrape_url_smart(
                    url, primary="firecrawl", backends=("firecrawl",),
                    deadline=time.monotonic() + 5, url_resolver=resolver,
                )
                self.assertNotIn("error", result)
                self.assertEqual(result["via"], "firecrawl")
                scraper.assert_called_once()
        resolver.assert_not_called()

    def test_delegated_backend_receives_the_rebuilt_url_not_the_raw_string(self):
        # The provider parses the URL itself; it must receive the components
        # that were validated, never the raw input another parser may read
        # differently.
        resolver = mock.Mock(side_effect=AssertionError("delegated URL resolved locally"))
        for raw, rebuilt in (
            ("HTTPS://Example.COM:8443/a\\b c?q=1 2#frag",
             "https://example.com:8443/a%5Cb%20c?q=1%202#frag"),
            ("https://m\u00fcnchen.de/stra\u00dfe?x=\u00fc",
             "https://xn--mnchen-3ya.de/stra%C3%9Fe?x=%C3%BC"),
            ("https://134744072/path", "https://8.8.8.8/path"),
            ("https://[2606:4700:0:0::1111]/p", "https://[2606:4700::1111]/p"),
            ("https://example.com/%E4%B8%AD?a=%20b", "https://example.com/%E4%B8%AD?a=%20b"),
        ):
            with self.subTest(url=raw), mock.patch(
                "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl",
                return_value={"url": rebuilt, "markdown": "body", "via": "firecrawl"},
            ) as scraper:
                result = scrape_url_smart(
                    raw, primary="firecrawl", backends=("firecrawl",),
                    deadline=time.monotonic() + 5, url_resolver=resolver,
                )
                self.assertNotIn("error", result)
                scraper.assert_called_once()
                self.assertEqual(scraper.call_args.args[0], rebuilt)
                self.assertEqual(result["url"], rebuilt)
        resolver.assert_not_called()

    def test_delegated_scrape_does_not_dispatch_after_deadline(self):
        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl") as scraper:
            result = scrape_url_smart(
                "https://slow.example/path",
                primary="firecrawl",
                backends=("firecrawl",),
                deadline=time.monotonic() - 1,
                url_resolver=mock.Mock(side_effect=AssertionError("no DNS")),
            )

        self.assertIn("deadline", result["error"])
        scraper.assert_not_called()

    def test_scrape_core_does_not_dispatch_after_url_preflight_deadline(self):
        # Reddit is fetched locally, so its URL preflight still resolves the
        # host under the request deadline and never dispatches after it.
        finished = threading.Event()
        start = time.monotonic()

        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_reddit") as scraper:
            result = scrape_url_smart(
                "https://www.reddit.com/r/test/comments/abc123/title",
                deadline=time.monotonic() + 0.01,
                url_resolver=self._slow_resolver(finished),
            )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)
        self.assertIn("DNS", result["error"])
        self.assertEqual(result["via"], "reddit")
        scraper.assert_not_called()
        self._finish_late_resolution(finished)

    def test_http_hostname_uses_resolved_address_for_normal_connection(self):
        class SocketProbe:
            def __init__(self):
                self.addresses = []
                self.timeout = None
                self.closed = False

            def settimeout(self, value):
                self.timeout = value

            def setsockopt(self, *args):
                pass

            def bind(self, address):
                pass

            def connect(self, address):
                self.addresses.append(address)

            def sendall(self, data):
                pass

            def makefile(self, mode):
                return io.BufferedReader(io.BytesIO(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
                ))

            def close(self):
                self.closed = True

        sock = SocketProbe()
        with mock.patch.object(url_security.socket, "getaddrinfo", return_value=[(
            socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 80),
        )]) as resolved, mock.patch.object(http.socket, "socket", return_value=sock):
            with http.urlopen_retry(
                "http://normal.example/path",
                timeout=1,
                extra_handlers=(urllib.request.ProxyHandler({}),),
            ) as response:
                self.assertEqual(response.read(), b"ok")

        resolved.assert_called_once_with(
            "normal.example", 80, type=socket.SOCK_STREAM,
        )
        self.assertEqual(sock.addresses, [(PUBLIC_IP, 80)])
        self.assertTrue(sock.closed)

    def test_http_dns_failure_is_explicit_without_connection_attempt(self):
        with mock.patch.object(
            url_security.socket,
            "getaddrinfo",
            side_effect=socket.gaierror(-2, "name not known"),
        ), mock.patch.object(http.socket, "socket") as socket_factory:
            with self.assertRaises(urllib.error.URLError) as error:
                http.urlopen_retry(
                    "http://missing.example/path",
                    timeout=1,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                )

        self.assertIsInstance(error.exception.reason, socket.gaierror)
        socket_factory.assert_not_called()

    def test_fetch_core_passes_supplied_deadline_to_url_preflight(self):
        finished = threading.Event()
        scraper = mock.Mock(return_value={"markdown": "late", "via": "fixture"})
        start = time.monotonic()

        with self.assertRaises(UrlSecurityError) as error:
            service.run_fetch_source(
                service.FetchSourceRequest(url="https://slow.example/path", use_state=False),
                scraper=scraper,
                keys={},
                config={},
                url_resolver=self._slow_resolver(finished),
                deadline=time.monotonic() + 0.01,
            )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)
        self.assertIn("DNS", str(error.exception))
        scraper.assert_not_called()
        self._finish_late_resolution(finished)

    def test_fetch_core_starts_timeout_budget_before_url_preflight(self):
        scraper = mock.Mock(return_value={"markdown": "ok", "via": "fixture"})
        resolved_at = []

        def recording_resolver(_host):
            resolved_at.append(time.monotonic())
            return [PUBLIC_IP]

        start = time.monotonic()
        result = service.run_fetch_source(
            service.FetchSourceRequest(
                url="https://slow.example/path", timeout=1, use_state=False,
            ),
            scraper=scraper,
            keys={},
            config={},
            url_resolver=recording_resolver,
        )

        self.assertEqual(result["body"], "ok")
        scraper.assert_called_once()
        scrape_deadline = scraper.call_args.kwargs["deadline"]
        self.assertGreater(scrape_deadline, time.monotonic())
        # The 1s budget started before the URL preflight resolved the host.
        self.assertEqual(len(resolved_at), 1)
        self.assertGreaterEqual(scrape_deadline - 1, start)
        self.assertLessEqual(scrape_deadline - 1, resolved_at[0])

    def test_fetch_core_timeout_bounds_slow_url_preflight_without_explicit_deadline(self):
        started = threading.Event()
        released = threading.Event()
        finished = threading.Event()

        def blocking_resolver(_host):
            started.set()
            try:
                released.wait(timeout=2)
                return [PUBLIC_IP]
            finally:
                finished.set()

        start = time.monotonic()
        try:
            with self.assertRaises(UrlSecurityError) as error:
                service.run_fetch_source(
                    service.FetchSourceRequest(
                        url="https://slow.example/path", timeout=1, use_state=False,
                    ),
                    scraper=mock.Mock(return_value={"markdown": "late"}),
                    keys={},
                    config={},
                    url_resolver=blocking_resolver,
                )
        finally:
            released.set()

        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.6)
        self.assertTrue(started.is_set())
        self.assertIn("deadline", str(error.exception))
        self._finish_late_resolution(finished)

    def test_fetch_core_config_timeout_bounds_slow_url_preflight(self):
        started = threading.Event()
        released = threading.Event()
        finished = threading.Event()

        def blocking_resolver(_host):
            started.set()
            try:
                released.wait(timeout=2)
                return [PUBLIC_IP]
            finally:
                finished.set()

        start = time.monotonic()
        try:
            with self.assertRaises(UrlSecurityError) as error:
                service.run_fetch_source(
                    service.FetchSourceRequest(
                        url="https://slow.example/path", use_state=False,
                    ),
                    scraper=mock.Mock(return_value={"markdown": "late"}),
                    keys={},
                    config={"scrape_timeout": 1},
                    url_resolver=blocking_resolver,
                )
        finally:
            released.set()

        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.6)
        self.assertTrue(started.is_set())
        self.assertIn("deadline", str(error.exception))
        self._finish_late_resolution(finished)

    def test_direct_reddit_scraper_timeout_bounds_second_url_preflight(self):
        finished = threading.Event()
        start = time.monotonic()

        result = scrape_url_reddit(
            "https://www.reddit.com/r/test/comments/abc123/title",
            timeout=0.01,
            url_resolver=self._slow_resolver(finished),
        )

        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0)
        self.assertIn("DNS", result["error"])
        self._finish_late_resolution(finished)

    def test_redirect_dns_preflight_uses_original_http_deadline(self):
        finished = threading.Event()
        requests_seen = []

        class RedirectHandler(urllib.request.BaseHandler):
            def default_open(self, request):
                requests_seen.append(request.full_url)
                return DnsDeadlineTests._redirect_response(
                    request.full_url, "https://slow.example/next",
                )

        start = time.monotonic()
        with self.assertRaises(UrlSecurityError) as error:
            http.urlopen_retry(
                "http://" + PUBLIC_IP + "/start",
                timeout=0.01,
                redirect_resolver=self._slow_resolver(finished),
                extra_handlers=(RedirectHandler(),),
            )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)
        self.assertIn("DNS", str(error.exception))
        self.assertEqual(requests_seen, ["http://" + PUBLIC_IP + "/start"])
        self._finish_late_resolution(finished)

    def test_timed_out_resolution_frees_its_slot_for_the_next_lookup(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-r3-dns-detach")
        released = threading.Event()
        finished = threading.Event()

        def blocking_resolver(_host):
            try:
                released.wait(timeout=2)
                return [PUBLIC_IP]
            finally:
                finished.set()

        try:
            with mock.patch.object(url_security, "_DNS_POOL", pool):
                with self.assertRaises(UrlSecurityError) as first:
                    url_security.validate_public_http_url(
                        "https://blocked.example/path",
                        resolver=blocking_resolver,
                        deadline=time.monotonic() + 0.02,
                    )
                self.assertIn("deadline", str(first.exception))
                self.assertFalse(finished.is_set())
                self.assertEqual(pool.detached_count, 1)
                # The stuck resolver no longer blocks an unrelated lookup.
                self.assertEqual(
                    url_security.validate_public_http_url(
                        "https://next.example/path",
                        resolver=lambda _host: [PUBLIC_IP],
                        deadline=time.monotonic() + 1,
                    ),
                    "https://next.example/path",
                )
                # The detached budget (1) is spent: a second stuck lookup keeps
                # its slot and further work reports capacity, not a timeout.
                with self.assertRaises(UrlSecurityError):
                    url_security.validate_public_http_url(
                        "https://blocked-again.example/path",
                        resolver=lambda _host: released.wait(timeout=2) and [PUBLIC_IP],
                        deadline=time.monotonic() + 0.02,
                    )
                with self.assertRaises(UrlSecurityError) as saturated:
                    url_security.validate_public_http_url(
                        "https://full.example/path",
                        resolver=lambda _host: [PUBLIC_IP],
                        deadline=time.monotonic() + 1,
                    )
                self.assertIn("capacity", str(saturated.exception))
                self.assertNotIn("deadline", str(saturated.exception))
        finally:
            released.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_dns_capacity_is_retained_when_no_detached_budget_remains(self):
        pool = BoundedDaemonExecutor(
            max_workers=1, thread_name_prefix="test-r3-dns", max_detached=0,
        )
        started = threading.Event()
        released = threading.Event()
        finished = threading.Event()

        def blocking_resolver(_host):
            started.set()
            try:
                released.wait(timeout=2)
                return [PUBLIC_IP]
            finally:
                finished.set()

        try:
            with mock.patch.object(url_security, "_DNS_POOL", pool):
                with self.assertRaises(UrlSecurityError) as first:
                    url_security.validate_public_http_url(
                        "https://blocked.example/path",
                        resolver=blocking_resolver,
                        deadline=time.monotonic() + 0.02,
                    )
                self.assertIn("deadline", str(first.exception))
                self.assertTrue(started.wait(timeout=1))
                self.assertFalse(finished.is_set())

                for _ in range(4):
                    with self.assertRaises(UrlSecurityError) as saturated:
                        url_security.validate_public_http_url(
                            "https://full.example/path",
                            resolver=lambda _host: [PUBLIC_IP],
                            deadline=time.monotonic() + 1,
                        )
                    self.assertIn("capacity", str(saturated.exception))

                released.set()
                self._finish_late_resolution(finished)
                self.assertEqual(
                    url_security.validate_public_http_url(
                        "https://reusable.example/path",
                        resolver=lambda _host: [PUBLIC_IP],
                        deadline=time.monotonic() + 1,
                    ),
                    "https://reusable.example/path",
                )
        finally:
            released.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_dns_timeout_worker_does_not_hold_process_exit(self):
        script = """
import socket
import threading
import urllib.request
from multi_search_mcp.src.support import http

def slow_dns(*_args, **_kwargs):
    threading.Event().wait()  # never released: only process exit ends it
    return []

socket.getaddrinfo = slow_dns
try:
    http.urlopen_retry(
        "http://slow.example/path", timeout=0.01,
        extra_handlers=(urllib.request.ProxyHandler({}),),
    )
except Exception:
    pass
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
