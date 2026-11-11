"""Regressions for one shared URL/numeric-host parsing implementation."""
import unittest
from pathlib import Path

from multi_search_mcp.src.scrape.scrape import validate_delegated_url
from multi_search_mcp.src.support.url_security import (
    UrlSecurityError,
    validate_public_http_url,
)


class SharedNumericHostParsingTests(unittest.TestCase):
    def test_delegated_url_accepts_leading_zero_labels_in_domain_names(self):
        # A leading-zero label only looks numeric; when the last label is not a
        # number the host is an ordinary domain name, exactly as the URL
        # preflight already decides.
        for url in (
            "https://01.example.com/article",
            "https://08.example.com/",
            "https://1.01.example.com/",
        ):
            with self.subTest(url=url):
                self.assertEqual(validate_delegated_url(url), url)
                self.assertEqual(validate_public_http_url(url), url)

    def test_delegated_url_rejects_host_with_empty_label_like_url_preflight(self):
        # A double trailing dot is not a valid hostname under the WHATWG parser
        # the delegated provider uses, so delegated validation must not accept
        # it as "example.com".
        for url in ("http://example.com../", "http://a../"):
            with self.subTest(url=url):
                with self.assertRaises(UrlSecurityError):
                    validate_delegated_url(url)
                with self.assertRaises(UrlSecurityError):
                    validate_public_http_url(url)

    def test_delegated_url_rejects_the_same_non_canonical_numeric_spellings(self):
        for url in (
            "http://017700000001/",
            "http://010.0.0.05/",
            "http://1.2.3.999/",
            "http://08/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(UrlSecurityError) as delegated:
                    validate_delegated_url(url)
                with self.assertRaises(UrlSecurityError) as preflight:
                    validate_public_http_url(url)
                self.assertIn("non-canonical numeric", str(delegated.exception))
                self.assertIn("non-canonical numeric", str(preflight.exception))


class SingleImplementationTests(unittest.TestCase):
    def test_scrape_chain_no_longer_defines_its_own_numeric_host_parser(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "multi_search_mcp"
            / "src"
            / "scrape"
            / "scrape.py"
        ).read_text(encoding="utf-8")
        duplicates = [
            helper
            for helper in ("_normalize_delegated_host", "_parse_inet_aton", "_literal_ip")
            if f"def {helper}(" in source
        ]
        self.assertEqual(duplicates, [])


if __name__ == "__main__":
    unittest.main()
