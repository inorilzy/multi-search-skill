import unittest
from unittest import mock

from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.support.url_security import (
    UrlSecurityError,
    validate_public_http_url,
    validate_redirect_target,
)


class UrlSecurityTests(unittest.TestCase):
    @staticmethod
    def _resolver(mapping):
        def resolve(hostname: str) -> list[str]:
            return list(mapping.get(hostname.lower(), []))

        return resolve

    def test_accepts_public_http_urls_with_case_insensitive_host_lookup(self):
        resolver = self._resolver({"example.com": ["93.184.216.34"]})

        validated = validate_public_http_url(" HTTPS://Example.com/path?q=1 ", resolver=resolver)

        self.assertEqual(validated, "HTTPS://Example.com/path?q=1")

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

    def test_rejects_unsafe_direct_ip_targets(self):
        cases = {
            "http://127.0.0.1/": "loopback",
            "http://10.0.0.8/": "private",
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

    def test_rejects_domain_resolving_to_unsafe_ip(self):
        resolver = self._resolver({"internal.example": ["192.168.1.20"]})

        with self.assertRaises(UrlSecurityError) as ctx:
            validate_public_http_url("https://internal.example/data", resolver=resolver)

        self.assertIn("resolved to private IP", str(ctx.exception))

    def test_documentation_domains_do_not_bypass_dns_safety(self):
        resolver = self._resolver({"example.com": ["127.0.0.1"]})

        with self.assertRaises(UrlSecurityError) as ctx:
            validate_public_http_url("https://example.com/data", resolver=resolver)

        self.assertIn("resolved to loopback IP", str(ctx.exception))

    def test_redirect_target_uses_same_policy(self):
        resolver = self._resolver({"redirect.example": ["fe80::1"]})

        with self.assertRaises(UrlSecurityError) as ctx:
            validate_redirect_target("https://redirect.example/next", resolver=resolver)

        self.assertIn("unsafe redirect target", str(ctx.exception))
        self.assertIn("link-local", str(ctx.exception))

    def test_scrape_url_smart_rejects_unsafe_input_before_backend_dispatch(self):
        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl") as backend:
            result = scrape_url_smart(
                "http://127.0.0.1/admin",
                primary="firecrawl",
                backends=("firecrawl",),
            )

        self.assertIn("unsafe scrape URL", result["error"])
        backend.assert_not_called()

    def test_scrape_url_smart_validates_rewritten_target_before_backend_dispatch(self):
        resolver = self._resolver({"example.com": ["93.184.216.34"], "metadata.local": ["169.254.169.254"]})

        with mock.patch(
            "multi_search_mcp.src.scrape.scrape._rewrite_for_clean_scrape",
            return_value="http://metadata.local/latest/meta-data",
        ), mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_jina") as backend:
            result = scrape_url_smart(
                "https://example.com/rewrite-me",
                primary="jina",
                backends=("jina",),
                url_resolver=resolver,
            )

        self.assertIn("unsafe redirect target", result["error"])
        backend.assert_not_called()

    def test_scrape_url_smart_allows_public_rewrite_and_dispatches_backend(self):
        resolver = self._resolver({
            "github.com": ["140.82.112.3"],
            "raw.githubusercontent.com": ["185.199.108.133"],
        })

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
            "https://raw.githubusercontent.com/openai/example/HEAD/README.md",
        )


if __name__ == "__main__":
    unittest.main()
