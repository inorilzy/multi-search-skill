import functools
import io
import socket
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrape import scrape_url_smart
from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.url_security import UrlSecurityError

PUBLIC_IP = "93.184.216.34"


def _no_local_dns(test):
    """Fail the test if URL preflight performs any local DNS lookup."""
    def wrapper(self, *args, **kwargs):
        with mock.patch(
            "socket.getaddrinfo",
            side_effect=AssertionError("URL preflight used local DNS"),
        ):
            return test(self, *args, **kwargs)

    return functools.wraps(test)(wrapper)

class DnsDeadlineTests(unittest.TestCase):
    @_no_local_dns
    def test_scrape_core_does_not_resolve_delegated_urls_locally(self):
        # A delegated backend fetches the URL from the provider's network, so a
        # local DNS preflight adds no SSRF protection and wrongly rejects
        # fake-IP/TUN routing. No local DNS lookup may run.
        for backend in ("firecrawl", "jina", "exa", "tavily"):
            with self.subTest(backend=backend):
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

                    )

                scraper.assert_called_once()
                self.assertEqual(result["via"], backend)
                self.assertIn("delegated backend error", result["error"])

    @_no_local_dns
    def test_delegated_url_still_rejects_local_targets_without_dns(self):
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
                    deadline=time.monotonic() + 5,
                )
                self.assertIn(reason, result["error"])
                self.assertNotIn("secret", result["error"])
                scraper.assert_not_called()

    @_no_local_dns
    def test_delegated_url_accepts_public_and_fake_ip_domains_without_dns(self):
        # Fake-IP/TUN routing only shows up in DNS answers, which the delegated
        # path never requests. Real domains (including numeric labels before
        # the TLD and IDNs) and public literals still dispatch.
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
                    deadline=time.monotonic() + 5,
                )
                self.assertNotIn("error", result)
                self.assertEqual(result["via"], "firecrawl")
                scraper.assert_called_once()

    @_no_local_dns
    def test_delegated_backend_receives_the_rebuilt_url_not_the_raw_string(self):
        # The provider parses the URL itself; it must receive the components
        # that were validated, never the raw input another parser may read
        # differently.
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
                    deadline=time.monotonic() + 5,
                )
                self.assertNotIn("error", result)
                scraper.assert_called_once()
                self.assertEqual(scraper.call_args.args[0], rebuilt)
                self.assertEqual(result["url"], rebuilt)

    @_no_local_dns
    def test_delegated_scrape_does_not_dispatch_after_deadline(self):
        with mock.patch("multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl") as scraper:
            result = scrape_url_smart(
                "https://slow.example/path",
                primary="firecrawl",
                backends=("firecrawl",),
                deadline=time.monotonic() - 1,

            )

        self.assertIn("deadline", result["error"])
        scraper.assert_not_called()

    @_no_local_dns
    def test_scrape_core_does_not_resolve_reddit_url_locally(self):
        # Reddit post URLs are parsed for an id; the request goes to fixed
        # endpoints, so the preflight must never consult local DNS.
        reddit_result = {
            "url": "https://www.reddit.com/r/test/comments/abc123/title",
            "markdown": "post body", "via": "reddit",
        }
        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_reddit",
            return_value=reddit_result,
        ) as scraper:
            result = scrape_url_smart(
                "https://www.reddit.com/r/test/comments/abc123/title",
                deadline=time.monotonic() + 5,

            )

        scraper.assert_called_once()
        self.assertEqual(result["via"], "reddit")
        self.assertEqual(result["markdown"], "post body")

    def test_http_dns_failure_surfaces_as_a_url_error(self):
        with mock.patch.object(
            socket,
            "create_connection",
            side_effect=socket.gaierror(-2, "name not known"),
        ):
            with self.assertRaises(urllib.error.URLError) as error:
                http.urlopen_retry(
                    "http://missing.example/path",
                    timeout=1,
                    extra_handlers=(urllib.request.ProxyHandler({}),),
                )

        self.assertIsInstance(error.exception.reason, socket.gaierror)

    @_no_local_dns
    def test_fetch_delegated_backends_bypass_tun_dns_for_urls_and_sources(self):
        url = "https://tun.example/article"
        for backend in ("jina", "exa", "tavily", "firecrawl"):
            for by_source in (False, True):
                for scraper in (None, scrape_url_smart):
                    with self.subTest(backend=backend, by_source=by_source, explicit_scraper=scraper is not None):
                        source = {"source_id": "src-fixture", "url": url, "providers": ["brave"]}
                        request = {"source_id": source["source_id"]} if by_source else {"url": url}
                        with mock.patch(
                            f"multi_search_mcp.src.scrape.scrape.scrape_url_{backend}",
                            return_value={"markdown": "fetched via provider", "via": backend},
                        ) as fetch, mock.patch(
                            "multi_search_mcp.src.scrape.scrape._jina_anonymous_cooling_down", return_value=False,
                        ):
                            response = service.run_fetch_source(
                                {**request, "backends": [backend], "use_state": False},
                                scraper=scraper, keys={backend: "synthetic-key"}, config={},
                                source_record=source if by_source else None,
                            )
                        self.assertEqual(response["body"], "fetched via provider")
                        self.assertEqual(response["backend"], backend)
                        fetch.assert_called_once()
                        self.assertEqual(fetch.call_args.args[0], url)

    @_no_local_dns
    def test_fetch_uses_the_same_configured_chain_as_dispatch(self):
        from multi_search_mcp.src.scrape import service as scrape_service

        for config in ({}, {"scrape_backends": None}, {"scrape_backends": ["firecrawl", "exa", "firecrawl"]}):
            with self.subTest(config=config):
                chain = scrape_service.configured_scrape_backends(config)
                expected = "firecrawl" if config.get("scrape_backends") else "jina"
                with mock.patch(
                    "multi_search_mcp.src.scrape.scrape._jina_anonymous_cooling_down", return_value=False,
                ), mock.patch(
                    f"multi_search_mcp.src.scrape.scrape.scrape_url_{expected}",
                    return_value={"markdown": "configured body"},
                ) as backend:
                    result = service.run_fetch_source(
                        {"url": "https://tun.example/config", "use_state": False},
                        keys={}, config=config,
                    )
                self.assertEqual(result["backend"], expected)
                self.assertEqual(chain[0], expected)
                self.assertEqual(len(chain), len(set(chain)))
                backend.assert_called_once()

    @_no_local_dns
    def test_fetch_delegated_config_file_load_and_explicit_backend_precedence(self):
        for backends, expected in ((None, "firecrawl"), (["jina"], "jina")):
            with self.subTest(backends=backends):
                with mock.patch(
                    "multi_search_mcp.src.scrape.fetch.runtime.load_config_safe",
                    return_value={"scrape_backends": ["firecrawl"]},
                ) as load, mock.patch(
                    "multi_search_mcp.src.scrape.scrape._jina_anonymous_cooling_down", return_value=False,
                ), mock.patch(
                    f"multi_search_mcp.src.scrape.scrape.scrape_url_{expected}",
                    return_value={"markdown": "configured body"},
                ) as backend:
                    result = service.run_fetch_source(
                        {"url": "https://tun.example/config", "use_state": False,
                         "config_path": "fixture.json", "timeout": 2, "backends": backends},
                        keys={},
                    )
                load.assert_called_once_with("fixture.json")
                backend.assert_called_once()
                self.assertEqual(result["backend"], expected)

    @_no_local_dns
    def test_fetch_delegated_rejects_unsafe_urls_before_acquisition(self):
        for url in (
            "http://127.0.0.1/", "http://[::1]/", "http://10.0.0.5/",
            "http://169.254.169.254/", "http://198.18.0.93/",
            "http://localhost/", "http://api.localhost/",
            "file:///etc/passwd", "ftp://example.com/", "https://user:secret@example.com/",
            "http://2130706433/", "http://0x7f000001/", "http://010.0.0.05/",
            "http://127\u30020\u30020\u30021/", "http://127.0.0.1%00/",
            "http://127.0.0.1\\admin", "http://exa^mple.com/",
        ):
            with self.subTest(url=url), mock.patch(
                "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl",
            ) as backend:
                with self.assertRaises(UrlSecurityError) as error:
                    service.run_fetch_source(
                        {"url": url, "backends": ["firecrawl"], "use_state": False},
                        keys={}, config={},
                    )
                self.assertNotIn("secret", str(error.exception))
                backend.assert_not_called()

    @_no_local_dns
    def test_fetch_delegated_dispatches_rebuilt_url_under_original_deadline(self):
        raw = "HTTPS://Example.COM:8443/a\\b c?q=1 2"
        rebuilt = "https://example.com:8443/a%5Cb%20c?q=1%202"
        deadline = time.monotonic() + 2
        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl", return_value={"markdown": "body"},
        ) as backend:
            result = service.run_fetch_source(
                {"url": raw, "backends": ["firecrawl"], "use_state": False},
                keys={}, config={}, deadline=deadline,
            )
            backend.assert_called_once()
            self.assertEqual(backend.call_args.args[0], rebuilt)
            self.assertLessEqual(backend.call_args.kwargs["timeout"], 2)
            self.assertEqual(result["url"], rebuilt)
            backend.reset_mock()
            with self.assertRaisesRegex(UrlSecurityError, "deadline"):
                service.run_fetch_source(
                    {"url": raw, "backends": ["firecrawl"], "use_state": False},
                    keys={}, config={}, deadline=time.monotonic() - 1,
                )
            backend.assert_not_called()

    @_no_local_dns
    def test_search_to_fetch_delegates_without_tun_dns(self):
        from multi_search_mcp.src.search.search_runner import ProviderSpec

        provider = ProviderSpec(name="hackernews", public_name="hackernews", call=lambda *_: [{
            "source": "hackernews", "url": "https://tun.example/article", "title": "Fixture",
            "description": "candidate only", "content_kind": "excerpt",
        }])
        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl", return_value={"markdown": "body"},
        ) as backend:
            result = service.run_search_web(
                {"query": "fixture", "sources": ["hackernews"], "use_state": False},
                providers={"hackernews": provider}, keys={},
                config={"scrape_backends": ["firecrawl"]},
            )
        self.assertEqual(result["diagnostics"]["body_success_count"], 1)
        backend.assert_called_once()

    @_no_local_dns
    def test_fetch_custom_and_local_paths_use_format_checks_only(self):
        # A caller-supplied scraper, a prefetched body and Reddit never resolve
        # the URL locally: fake-IP DNS answers must not block them.

        custom = mock.Mock(return_value={"markdown": "custom body", "via": "custom"})
        response = service.run_fetch_source(
            {"url": "https://local.example/path", "backends": ["firecrawl"],
             "use_state": False},
            keys={}, config={}, scraper=custom,
        )
        self.assertEqual(response["body"], "custom body")
        custom.assert_called_once()

        response = service.run_fetch_source(
            {"url": "https://local.example/path", "use_state": False},
            keys={}, config={},
            prefetched_body="already fetched",
        )
        self.assertEqual(response["body"], "already fetched")

        reddit_result = {"markdown": "reddit body", "via": "reddit"}
        with mock.patch(
            "multi_search_mcp.src.scrape.scrape.scrape_url_reddit",
            return_value=reddit_result,
        ) as reddit:
            response = service.run_fetch_source(
                {"url": "https://www.reddit.com/r/test/comments/abc123/title",
                 "use_state": False},
                keys={}, config={},
            )
        self.assertEqual(response["body"], "reddit body")
        reddit.assert_called_once()

        # Unknown chains pass the format check too; the configuration error is
        # raised later and the DNS answer is never consulted.
        with self.assertRaisesRegex(ValueError, "unknown scrape backend"):
            service.run_fetch_source(
                {"url": "https://local.example/path", "backends": ["typo"],
                 "use_state": False},
                keys={}, config={},
            )

        # Literal local destinations are still rejected by those checks, again
        # without ever consulting DNS.
        for url, reason in (
            ("https://10.0.0.5/article", "private"),
            ("http://127.0.0.1/", "loopback"),
            ("http://localhost/", "localhost"),
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(UrlSecurityError, reason):
                    service.run_fetch_source(
                        {"url": url, "use_state": False},
                        keys={}, config={}, scraper=custom,
                    )

    @_no_local_dns
    def test_fetch_rejects_invalid_configured_chains_before_dispatch(self):
        for chain in ([], ["unknown"], ["firecrawl", "direct"], "firecrawl"):
            with self.subTest(chain=chain), mock.patch(
                "multi_search_mcp.src.scrape.scrape.scrape_url_firecrawl",
            ) as backend:
                with self.assertRaises(ValueError):
                    service.run_fetch_source(
                        {"url": "https://tun.example/path", "use_state": False},
                        keys={}, config={"scrape_backends": chain},
                    )
                backend.assert_not_called()

    @_no_local_dns
    def test_fetch_core_never_resolves_the_url_and_keeps_its_deadline(self):
        # The URL preflight no longer resolves, so a supplied deadline reaches
        # the acquisition unchanged and no DNS lookup runs.
        scraper = mock.Mock(return_value={"markdown": "ok", "via": "fixture"})
        deadline = time.monotonic() + 5

        result = service.run_fetch_source(
            service.FetchSourceRequest(url="https://slow.example/path", use_state=False),
            scraper=scraper,
            keys={},
            config={},

            deadline=deadline,
        )

        self.assertEqual(result["body"], "ok")
        self.assertEqual(scraper.call_args.kwargs["deadline"], deadline)

    def test_redirect_keeps_the_deadline_without_a_local_dns_lookup(self):
        deadline = time.monotonic() + 5
        request = urllib.request.Request("http://origin.example/start")
        request._multi_search_deadline = deadline

        with mock.patch(
            "socket.getaddrinfo",
            side_effect=AssertionError("redirect targets must not be resolved"),
        ) as dns:
            redirected = http._SafeHTTPRedirectHandler().redirect_request(
                request, io.BytesIO(), 302, "Found", {},
                "https://origin.example/next",
            )

        dns.assert_not_called()
        self.assertEqual(redirected._multi_search_deadline, deadline)
        self.assertGreater(redirected.timeout, 0)
        self.assertLessEqual(redirected.timeout, 5)


if __name__ == "__main__":
    unittest.main()
