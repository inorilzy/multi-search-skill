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
    @staticmethod
    def _slow_resolver(finished: threading.Event, result=None):
        def resolve(_host):
            try:
                time.sleep(0.08)
                return list(result or [PUBLIC_IP])
            finally:
                finished.set()

        return resolve

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
                time.sleep(0.08)
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

        self.assertLess(elapsed, 0.06)
        self.assertIn("DNS", str(error.exception))
        self.assertTrue(finished.wait(timeout=1))

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

        self.assertLess(elapsed, 0.06)
        self.assertIn("DNS", str(error.exception))
        self.assertIn("deadline", str(error.exception))
        self.assertTrue(finished.wait(timeout=1))

    def test_scrape_core_does_not_dispatch_after_url_preflight_deadline(self):
        finished = threading.Event()
        start = time.monotonic()

        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl") as scraper:
            result = scrape_url_smart(
                "https://slow.example/path",
                primary="firecrawl",
                backends=("firecrawl",),
                deadline=time.monotonic() + 0.01,
                url_resolver=self._slow_resolver(finished),
            )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 0.06)
        self.assertIn("DNS", result["error"])
        scraper.assert_not_called()
        self.assertTrue(finished.wait(timeout=1))

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

        self.assertLess(elapsed, 0.06)
        self.assertIn("DNS", str(error.exception))
        scraper.assert_not_called()
        self.assertTrue(finished.wait(timeout=1))

    def test_fetch_core_starts_timeout_budget_before_url_preflight(self):
        finished = threading.Event()
        scraper = mock.Mock(return_value={"markdown": "ok", "via": "fixture"})
        start = time.monotonic()

        result = service.run_fetch_source(
            service.FetchSourceRequest(
                url="https://slow.example/path", timeout=1, use_state=False,
            ),
            scraper=scraper,
            keys={},
            config={},
            url_resolver=self._slow_resolver(finished),
        )

        self.assertEqual(result["body"], "ok")
        scraper.assert_called_once()
        scrape_deadline = scraper.call_args.kwargs["deadline"]
        self.assertGreater(scrape_deadline, time.monotonic())
        self.assertLessEqual(scrape_deadline, start + 1.04)
        self.assertTrue(finished.is_set())

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
        self.assertTrue(finished.wait(timeout=1))

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
        self.assertTrue(finished.wait(timeout=1))

    def test_direct_reddit_scraper_timeout_bounds_second_url_preflight(self):
        finished = threading.Event()
        start = time.monotonic()

        result = scrape_url_reddit(
            "https://www.reddit.com/r/test/comments/abc123/title",
            timeout=0.01,
            url_resolver=self._slow_resolver(finished),
        )

        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.06)
        self.assertIn("DNS", result["error"])
        self.assertTrue(finished.wait(timeout=1))

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

        self.assertLess(elapsed, 0.06)
        self.assertIn("DNS", str(error.exception))
        self.assertEqual(requests_seen, ["http://" + PUBLIC_IP + "/start"])
        self.assertTrue(finished.wait(timeout=1))

    def test_dns_capacity_is_retained_until_running_resolution_finishes(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-r3-dns")
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
                self.assertTrue(finished.wait(timeout=1))
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
import time
import urllib.request
from multi_search_mcp.src.support import http

def slow_dns(*_args, **_kwargs):
    time.sleep(5)
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
