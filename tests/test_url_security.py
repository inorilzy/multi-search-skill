import email.message
import io
import unittest
import urllib.request
import urllib.response
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.support.http import urlopen_retry
from multi_search_mcp.src.support.url_security import (
    UrlSecurityError,
    validate_public_http_url,
    validate_redirect_target,
    validate_scrape_url,
)


class UrlSecurityTests(unittest.TestCase):
    @staticmethod
    def _resolver(mapping):
        def resolve(hostname: str) -> list[str]:
            return list(mapping.get(hostname.lower(), []))

        return resolve

    @staticmethod
    def _redirect_response(url: str, location: str):
        headers = email.message.Message()
        headers["Location"] = location
        response = urllib.response.addinfourl(io.BytesIO(b""), headers, url, 302)
        response.msg = "Found"
        return response

    @staticmethod
    def _ok_response(url: str, body: bytes = b"ok"):
        headers = email.message.Message()
        response = urllib.response.addinfourl(io.BytesIO(body), headers, url, 200)
        response.msg = "OK"
        return response

    def test_accepts_public_http_urls_without_a_local_dns_lookup(self):
        resolver = mock.Mock(return_value=["93.184.216.34"])

        validated = validate_public_http_url(" HTTPS://Example.com/path?q=1 ", resolver=resolver)

        self.assertEqual(validated, "HTTPS://Example.com/path?q=1")
        resolver.assert_not_called()

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(UrlSecurityError) as ctx:
            validate_public_http_url("file:///etc/passwd", resolver=self._resolver({}))

        self.assertIn("unsupported URL scheme", str(ctx.exception))

    def test_rejects_missing_host_and_credentials(self):
        with self.assertRaises(UrlSecurityError) as missing_host:
            validate_public_http_url("https:///path-only", resolver=self._resolver({}))
        self.assertIn("missing host", str(missing_host.exception))

        with self.assertRaises(UrlSecurityError) as credentials:
            validate_public_http_url("https://user:pass@example.com/private", resolver=self._resolver({}))
        self.assertIn("must not include credentials", str(credentials.exception))

    def test_rejects_localhost_targets(self):
        for url in ("http://localhost/", "https://api.localhost/", "http://LOCALHOST./"):
            with self.subTest(url=url):
                with self.assertRaises(UrlSecurityError) as ctx:
                    validate_public_http_url(url, resolver=self._resolver({}))
                self.assertIn("localhost is not allowed", str(ctx.exception))

    def test_rejects_unsafe_direct_ip_targets(self):
        cases = {
            "http://127.0.0.1/": "loopback",
            "http://127.1/": "loopback",
            "http://2130706433/": "loopback",
            "http://0x7f000001/": "loopback",
            "http://010.0.0.05/": "non-canonical numeric",
            "http://[::ffff:127.0.0.1]/": "loopback",
            "http://[64:ff9b::a00:1]/": "private",
            "http://[2002:0a00:0001::]/": "private",
            "http://10.0.0.8/": "private",
            "http://100.64.0.8/": "shared",
            "http://169.254.169.254/": "link-local",
            "http://224.0.0.1/": "multicast",
            "http://0.0.0.0/": "unspecified",
            "http://240.0.0.9/": "reserved",
            "https://[::1]/": "loopback",
        }

        for url, expected_reason in cases.items():
            with self.subTest(url=url):
                with self.assertRaises(UrlSecurityError) as ctx:
                    validate_public_http_url(url, resolver=self._resolver({}))
                self.assertIn(expected_reason, str(ctx.exception))

    def test_domain_urls_pass_regardless_of_dns_answers(self):
        # The URL is never dialed locally (provider fetch or post-id parsing),
        # so no DNS answer may reject it and the resolver must not be consulted.
        for answers in (
            ["192.168.1.20"],
            ["198.18.1.241"],
            ["127.0.0.1"],
            ["fe80::1"],
            [],
            ["not-an-ip"],
        ):
            with self.subTest(answers=answers):
                resolver = mock.Mock(return_value=answers)
                self.assertEqual(
                    validate_public_http_url("https://internal.example/data", resolver=resolver),
                    "https://internal.example/data",
                )
                resolver.assert_not_called()

    def test_scrape_url_preflight_never_resolves_the_host(self):
        resolver = mock.Mock(side_effect=AssertionError("scrape preflight must not use DNS"))

        for url in (
            "https://www.reddit.com/r/python/comments/abc123/example/",
            "https://evidence.example/article",
        ):
            with self.subTest(url=url):
                self.assertEqual(validate_scrape_url(url, resolver=resolver), url)
        resolver.assert_not_called()

    def test_redirect_target_uses_same_policy(self):
        resolver = self._resolver({"redirect.example": ["fe80::1"]})

        with self.assertRaises(UrlSecurityError) as ctx:
            validate_redirect_target("https://redirect.example/next", resolver=resolver)

        self.assertIn("unsafe redirect target", str(ctx.exception))
        self.assertIn("link-local", str(ctx.exception))
        self.assertNotIn("redirect.example", str(ctx.exception))
        self.assertNotIn("fe80::1", str(ctx.exception))

    def test_urlopen_retry_rejects_unsafe_redirect_target_without_following(self):
        requests_seen: list[str] = []

        class FakeHandler(urllib.request.BaseHandler):
            def default_open(self, req):
                requests_seen.append(req.full_url)
                if req.full_url == "https://93.184.216.34/start":
                    return UrlSecurityTests._redirect_response(
                        req.full_url,
                        "http://127.0.0.1/admin?token=secret",
                    )
                raise AssertionError(f"unexpected request: {req.full_url}")

        with self.assertRaises(UrlSecurityError) as ctx:
            urlopen_retry(
                "https://93.184.216.34/start",
                timeout=1,
                extra_handlers=(FakeHandler(),),
            )

        self.assertEqual(requests_seen, ["https://93.184.216.34/start"])
        self.assertIn("unsafe redirect target", str(ctx.exception))
        self.assertIn("loopback", str(ctx.exception))
        self.assertNotIn("127.0.0.1", str(ctx.exception))
        self.assertNotIn("token=secret", str(ctx.exception))

    def test_urlopen_retry_follows_safe_redirect_chain(self):
        requests_seen: list[str] = []

        class FakeHandler(urllib.request.BaseHandler):
            def default_open(self, req):
                requests_seen.append(req.full_url)
                if req.full_url == "https://93.184.216.34/start":
                    return UrlSecurityTests._redirect_response(
                        req.full_url,
                        "https://151.101.1.69/next",
                    )
                if req.full_url == "https://151.101.1.69/next":
                    return UrlSecurityTests._redirect_response(
                        req.full_url,
                        "https://151.101.65.69/result",
                    )
                if req.full_url == "https://151.101.65.69/result":
                    return UrlSecurityTests._ok_response(req.full_url, body=b"safe")
                raise AssertionError(f"unexpected request: {req.full_url}")

        with urlopen_retry(
            "https://93.184.216.34/start",
            timeout=1,
            extra_handlers=(FakeHandler(),),
        ) as resp:
            body = resp.read()

        self.assertEqual(body, b"safe")
        self.assertEqual(
            requests_seen,
            [
                "https://93.184.216.34/start",
                "https://151.101.1.69/next",
                "https://151.101.65.69/result",
            ],
        )

    def test_scrape_url_smart_rejects_unsafe_input_before_backend_dispatch(self):
        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl") as backend:
            result = scrape_url_smart(
                "http://127.0.0.1/admin",
                primary="firecrawl",
                backends=("firecrawl",),
            )

        self.assertIn("unsafe scrape URL", result["error"])
        backend.assert_not_called()

    def test_scrape_url_smart_preserves_github_repository_url(self):
        resolver = self._resolver({"github.com": ["140.82.112.3"]})

        def fake_jina(url, key, timeout=0, **kwargs):
            return {"url": url, "markdown": "ok", "via": "jina"}

        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_jina", side_effect=fake_jina) as backend:
            result = scrape_url_smart(
                "https://github.com/openai/example",
                primary="jina",
                backends=("jina",),
                url_resolver=resolver,
            )

        self.assertEqual(result["via"], "jina")
        self.assertEqual(
            backend.call_args.args[0],
            "https://github.com/openai/example",
        )


if __name__ == "__main__":
    unittest.main()
