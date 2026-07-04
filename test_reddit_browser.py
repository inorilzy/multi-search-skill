"""Tests for the browser-backed Reddit content searcher and its helpers.

Mirrors the sys.path convention used by test_mcp_core.py so the packaged
modules under multi_search_mcp/src import cleanly.
"""
import json
import os
import tempfile
import threading
import time as _time
import sys
import unittest
from pathlib import Path
from unittest import mock


MCP_ROOT = Path(__file__).resolve().parent / "multi_search_mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from src.browser.cookie_export import load_cookie_export, to_playwright_cookies
from src.search.capabilities import PROVIDER_CAPABILITIES, ProviderKind, ScrapePolicy
from src.search.search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_PROFILES,
    normalize_source_name,
)
from src.search.searchers.reddit_browser import (
    build_search_url,
    is_blocked_text,
    resolve_reddit_config,
    search_reddit_browser,
    shape_result,
)


class CookieExportConversionTests(unittest.TestCase):
    def test_no_restriction_same_site_maps_to_none_and_keeps_expiry(self):
        raw = [{
            "name": "reddit_session",
            "value": "abc",
            "domain": ".reddit.com",
            "path": "/",
            "sameSite": "no_restriction",
            "expirationDate": 1810945777.5,
            "httpOnly": True,
        }]

        cookies = to_playwright_cookies(raw)

        self.assertEqual(len(cookies), 1)
        cookie = cookies[0]
        self.assertEqual(cookie["name"], "reddit_session")
        self.assertEqual(cookie["value"], "abc")
        self.assertEqual(cookie["domain"], ".reddit.com")
        self.assertEqual(cookie["path"], "/")
        self.assertEqual(cookie["sameSite"], "None")
        self.assertEqual(cookie["expires"], 1810945777.5)
        self.assertTrue(cookie["httpOnly"])


class CookieExportLoadTests(unittest.TestCase):
    def test_load_returns_playwright_cookies_and_local_storage(self):
        export = {
            "cookies": [
                {"name": "reddit_session", "value": "abc", "domain": ".reddit.com",
                 "sameSite": "no_restriction", "expirationDate": 111.0},
            ],
            "localStorage": {"theme": "dark", "count": 3},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reddit-export.json"
            path.write_text(json.dumps(export), encoding="utf-8")

            cookies, local_storage = load_cookie_export(path)

        self.assertEqual(cookies[0]["name"], "reddit_session")
        self.assertEqual(cookies[0]["sameSite"], "None")
        # localStorage values are coerced to strings for page.evaluate setItem.
        self.assertEqual(local_storage, {"theme": "dark", "count": "3"})

    def test_load_tolerates_utf8_bom(self):
        export = {"cookies": [{"name": "csv", "value": "x"}], "localStorage": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.json"
            path.write_text(json.dumps(export), encoding="utf-8-sig")

            cookies, local_storage = load_cookie_export(path)

        self.assertEqual(cookies[0]["name"], "csv")
        self.assertEqual(local_storage, {})


class RedditSearchUrlTests(unittest.TestCase):
    def test_build_search_url_uses_relevance_all_time(self):
        url = build_search_url("playwright")
        self.assertEqual(
            url,
            "https://www.reddit.com/search/?q=playwright&sort=relevance&t=all",
        )

    def test_build_search_url_encodes_spaces_and_unicode(self):
        url = build_search_url("北京 咖啡")
        self.assertIn("q=%E5%8C%97%E4%BA%AC+%E5%92%96%E5%95%A1", url)
        self.assertNotIn(" ", url)


class RedditBlockDetectionTests(unittest.TestCase):
    def test_detects_network_security_block(self):
        self.assertTrue(is_blocked_text(
            "You've been blocked by network security."
        ))

    def test_detects_humanity_challenge(self):
        self.assertTrue(is_blocked_text("Prove your humanity"))

    def test_normal_results_text_is_not_blocked(self):
        self.assertFalse(is_blocked_text(
            "playwright - Reddit Search! Posts Communities"
        ))

    def test_post_body_mentioning_blocker_word_is_not_a_block(self):
        # A post whose body merely contains the word "blocked" must not be
        # misclassified as a network-security block.
        self.assertFalse(is_blocked_text(
            "My ISP blocked this site, here is how I fixed routing"
        ))


class RedditResultShapeTests(unittest.TestCase):
    def _raw(self):
        return {
            "title": "Why you should never use waitForTimeout",
            "url": "https://www.reddit.com/r/programming/comments/1j4/abc/",
            "subreddit": "programming",
            "post_text": "The post body explaining the problem.",
            "comments": ["first comment", "second comment"],
        }

    def test_with_content_inlines_post_and_comments_as_scraped_content(self):
        row = shape_result(self._raw(), want_content=True)

        self.assertEqual(row["source"], "reddit-browser")
        self.assertEqual(row["title"], "Why you should never use waitForTimeout")
        self.assertEqual(row["url"], "https://www.reddit.com/r/programming/comments/1j4/abc/")
        self.assertEqual(row["subreddit"], "programming")
        # Inline body -> split_by_content keeps it out of the scrape stage.
        self.assertIn("The post body explaining the problem.", row["scraped_content"])
        self.assertIn("first comment", row["scraped_content"])
        self.assertTrue(row["scraped"])
        self.assertEqual(row["scrape_via"], "reddit-browser")

    def test_without_content_returns_card_without_scraped_content(self):
        row = shape_result(self._raw(), want_content=False)

        self.assertEqual(row["source"], "reddit-browser")
        self.assertEqual(row["url"], "https://www.reddit.com/r/programming/comments/1j4/abc/")
        self.assertNotIn("scraped_content", row)
        self.assertNotIn("scraped", row)
        # A short description preview is still useful on cards.
        self.assertIn("programming", row["description"])


class RedditConfigResolutionTests(unittest.TestCase):
    def test_dict_value_supplies_cookie_export_and_profile(self):
        cfg = resolve_reddit_config({
            "cookie_export": "C:/auth/reddit.json",
            "profile": "C:/profiles/reddit",
            "concurrency": 4,
            "max_comments": 5,
        })
        self.assertEqual(cfg["cookie_export"], "C:/auth/reddit.json")
        self.assertEqual(cfg["profile"], "C:/profiles/reddit")
        self.assertEqual(cfg["concurrency"], 4)
        self.assertEqual(cfg["max_comments"], 5)

    def test_string_value_is_treated_as_cookie_export_path(self):
        cfg = resolve_reddit_config("C:/auth/reddit.json")
        self.assertEqual(cfg["cookie_export"], "C:/auth/reddit.json")

    def test_defaults_applied_when_missing(self):
        cfg = resolve_reddit_config({"cookie_export": "x.json"})
        # Sensible defaults so the provider can run without extra config.
        self.assertGreaterEqual(cfg["concurrency"], 1)
        self.assertGreaterEqual(cfg["max_comments"], 1)
        self.assertTrue(cfg["profile"])

    def test_empty_value_has_no_cookie_export(self):
        cfg = resolve_reddit_config(None)
        self.assertEqual(cfg["cookie_export"], "")


class RedditSearchOrchestrationTests(unittest.TestCase):
    def _raw_post(self):
        return {
            "title": "Thoughts on Playwright?",
            "url": "https://www.reddit.com/r/QA/comments/1/abc/",
            "subreddit": "QA",
            "post_text": "Body text",
            "comments": ["c1"],
        }

    def test_missing_cookie_export_returns_structured_error(self):
        rows = search_reddit_browser("playwright", 10, {}, want_content=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "reddit-browser")
        self.assertIn("error", rows[0])
        self.assertIn("cookie", rows[0]["error"].lower())

    def test_happy_path_shapes_rows_and_passes_count_through(self):
        seen = {}

        def fake_fetch(query, *, count, config, want_content, deadline):
            seen["query"] = query
            seen["count"] = count
            seen["want_content"] = want_content
            return {"posts": [self._raw_post()]}

        rows = search_reddit_browser(
            "playwright", 7, {"cookie_export": "x.json"},
            want_content=True, fetch=fake_fetch,
        )

        self.assertEqual(seen["query"], "playwright")
        self.assertEqual(seen["count"], 7)
        self.assertTrue(seen["want_content"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "reddit-browser")
        self.assertEqual(rows[0]["url"], "https://www.reddit.com/r/QA/comments/1/abc/")
        self.assertIn("Body text", rows[0]["scraped_content"])

    def test_blocked_fetch_returns_cookie_expired_error(self):
        def blocked_fetch(query, *, count, config, want_content, deadline):
            return {"posts": [], "error": "blocked"}

        rows = search_reddit_browser(
            "playwright", 10, {"cookie_export": "x.json"},
            want_content=True, fetch=blocked_fetch,
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("error", rows[0])
        self.assertIn("cookie", rows[0]["error"].lower())

    def test_fetch_exception_is_scrubbed_into_error_row(self):
        def boom_fetch(query, *, count, config, want_content, deadline):
            raise RuntimeError("token=supersecret failed")

        rows = search_reddit_browser(
            "playwright", 10, {"cookie_export": "x.json"},
            want_content=True, fetch=boom_fetch,
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("error", rows[0])
        self.assertNotIn("supersecret", rows[0]["error"])

    def test_links_found_but_all_posts_filtered_returns_error_not_empty(self):
        # Search saw posts but every post page was blocked/empty. Returning an
        # empty list would look like "no results"; surface a retryable error.
        def fetch(query, *, count, config, want_content, deadline):
            return {"posts": [], "links_found": 12}

        rows = search_reddit_browser(
            "playwright", 10, {"cookie_export": "x.json"},
            want_content=True, fetch=fetch,
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("error", rows[0])

    def test_no_links_found_returns_empty_results(self):
        # A genuine zero-result query (no links seen) is not an error.
        def fetch(query, *, count, config, want_content, deadline):
            return {"posts": [], "links_found": 0}

        rows = search_reddit_browser(
            "obscurequerywithnoresults", 10, {"cookie_export": "x.json"},
            want_content=True, fetch=fetch,
        )

        self.assertEqual(rows, [])


class RedditWiringTests(unittest.TestCase):
    def test_source_is_registered_in_all_source_names(self):
        self.assertIn("reddit_browser", ALL_SOURCE_NAMES)

    def test_public_alias_normalizes_to_internal_name(self):
        self.assertEqual(normalize_source_name("reddit-browser"), "reddit_browser")

    def test_capability_is_cookie_content_searcher(self):
        cap = PROVIDER_CAPABILITIES["reddit_browser"]
        self.assertEqual(cap.public_name, "reddit-browser")
        self.assertEqual(cap.kind, ProviderKind.CONTENT_SEARCHER)
        self.assertTrue(cap.search.can_search)
        self.assertTrue(cap.output.returns_content)
        self.assertEqual(cap.scrape_policy, ScrapePolicy.PREFETCH)
        self.assertEqual(cap.count_key, "reddit_browser")
        self.assertEqual(cap.timeout_default, 45)
        self.assertEqual(cap.search.max_count, 25)

    def test_registry_has_provider_with_matching_timeout(self):
        from src.search.registry import build_provider_registry
        registry = build_provider_registry()
        self.assertIn("reddit_browser", registry)
        self.assertEqual(registry["reddit_browser"].public_name, "reddit-browser")
        self.assertEqual(registry["reddit_browser"].timeout_default, 45)

    def test_vertical_route_includes_reddit_browser_but_default_does_not(self):
        self.assertIn("reddit_browser", ROUTE_PROFILES["vertical"])
        self.assertNotIn("reddit_browser", ROUTE_PROFILES["default"])


class RedditKeysLoadingTests(unittest.TestCase):
    def test_env_cookie_export_populates_reddit_browser_key(self):
        from src.state.keys import load_keys
        with mock.patch.dict(os.environ, {
            "REDDIT_COOKIE_EXPORT": "C:/auth/reddit.json",
            "REDDIT_BROWSER_PROFILE": "C:/profiles/reddit",
        }, clear=False), mock.patch("src.state.keys.Path.home", return_value=Path("/no/such/home")):
            keys = load_keys()

        self.assertIsInstance(keys["reddit_browser"], dict)
        self.assertEqual(keys["reddit_browser"]["cookie_export"], "C:/auth/reddit.json")
        self.assertEqual(keys["reddit_browser"]["profile"], "C:/profiles/reddit")


class CloakRuntimeConcurrencyTests(unittest.TestCase):
    def test_fetch_reddit_serializes_access_to_shared_profile(self):
        from src.browser import cloak_runtime

        active = {"now": 0, "max": 0}
        lock = threading.Lock()

        def fake_run(query, *, count, config, want_content, deadline):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            _time.sleep(0.05)
            with lock:
                active["now"] -= 1
            return {"posts": []}

        def worker():
            cloak_runtime.fetch_reddit(
                "q", count=5, config={"profile": "p"},
                want_content=True, deadline=None, _run=fake_run,
            )

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Shared persistent profile => at most one browser session at a time.
        self.assertEqual(active["max"], 1)


class DoctorCloakHealthTests(unittest.TestCase):
    def test_doctor_reports_cloak_section(self):
        from src.service import doctor_data
        data = doctor_data(include_keys=False, include_network=False)
        self.assertIn("cloak", data)
        self.assertIn("cloakbrowser_installed", data["cloak"])
        self.assertIsInstance(data["cloak"]["cloakbrowser_installed"], bool)


class OldRedditScraperRemovalTests(unittest.TestCase):
    def test_reddit_is_not_a_scrape_backend(self):
        from src.scrape.scrape import KNOWN_BACKENDS
        self.assertNotIn("reddit", KNOWN_BACKENDS)

    def test_reddit_scraper_module_is_removed(self):
        import importlib.util
        self.assertIsNone(
            importlib.util.find_spec("src.scrape.scrapers.reddit"),
            "old reddit scraper module should be deleted",
        )

    def test_reddit_scraper_capability_is_removed(self):
        from src.search.capabilities import PROVIDER_CAPABILITIES
        self.assertNotIn("reddit", PROVIDER_CAPABILITIES)


if __name__ == "__main__":
    unittest.main()
