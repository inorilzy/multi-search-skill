import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import DEFAULT_MAX_OBJECT_BYTES, max_acquisition_chars
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://evidence.example/long-article"
BODY = "# Long article\n" + "正文 with context. " * 3000 + "\nEND_OF_ARTICLE"


def resolver(_host):
    return ["93.184.216.34"]


class FullContentFlowTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        temporary = stack.enter_context(TemporaryDirectory(prefix="full-content-"))
        self.store = StateStore(Path(temporary) / "state.sqlite")
        stack.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected network")))
        self.scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": BODY[:kwargs["scrape_chars"]], "via": "fixture",
        })

    def fetch(self, **request):
        return service.run_fetch_source(
            service.FetchSourceRequest(**request), state_store=self.store,
            scraper=self.scraper, keys={}, config={}, url_resolver=resolver,
        )

    def assert_full_body(self, response):
        self.assertEqual(response["body"], BODY)
        self.assertGreater(len(response["body"]), 20_000)
        self.assertEqual(response["content_length"], len(BODY))
        self.assertFalse(response["truncated"])
        self.assertTrue(response["untrusted_content"])

    def test_full_content_expands_cached_preview_without_another_scrape(self):
        preview = self.fetch(url=URL, max_chars=1200)
        self.assertEqual(preview["body"], BODY[:1200])
        self.assertTrue(preview["truncated"])
        expanded = self.fetch(source_id=preview["source_id"], full_content=True, max_chars=10)
        self.assert_full_body(expanded)
        self.assertTrue(expanded["cache_hit"])
        self.assertEqual(expanded["content_hash"], preview["content_hash"])
        self.assertEqual(self.scraper.call_count, 1)

    def test_full_content_on_fresh_fetch_returns_and_caches_the_whole_acquisition(self):
        fetched = self.fetch(url=URL, full_content=True)
        self.assert_full_body(fetched)
        self.assertFalse(fetched["cache_hit"])
        self.assertTrue(fetched["persisted"])
        self.assertEqual(self.scraper.call_args.kwargs["scrape_chars"], DEFAULT_MAX_OBJECT_BYTES)
        cached = self.fetch(source_id=fetched["source_id"], full_content=True)
        self.assert_full_body(cached)
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(self.scraper.call_count, 1)

    def test_default_and_explicit_preview_limits_remain_compatible(self):
        default = self.fetch(url=URL)
        self.assertEqual(default["body"], BODY[:20_000])
        self.assertTrue(default["truncated"])
        for requested, expected in ((1200, 1200), (40_000, 20_000)):
            with self.subTest(requested=requested):
                preview = self.fetch(
                    source_id=default["source_id"], max_chars=requested, full_content=False,
                )
                self.assertEqual(preview["body"], BODY[:expected])
                self.assertTrue(preview["truncated"])

    def test_selected_three_or_five_sources_expand_fully_after_fifteen_previews(self):
        rows = [{
            "source": "brave", "title": f"Article {i}", "url": f"{URL}/{i}",
            "description": f"Evidence angle {i}", "content_kind": "excerpt",
        } for i in range(15)]
        provider = ProviderSpec(name="brave", public_name="brave", call=lambda *_args: rows)
        response = service.run_search_web(
            service.SearchWebRequest(query="evidence", sources=["brave"], count=15),
            providers={"brave": provider}, keys={}, config={}, state_store=self.store,
            scraper=self.scraper, url_resolver=resolver,
        )
        self.assertEqual(response["errors"], [])
        self.assertEqual(len(response["scrapes"]), 15)
        self.assertTrue(all(len(page["markdown"]) == 1200 for page in response["scrapes"]))
        self.assertEqual(self.scraper.call_count, 15)
        # Selection belongs to the caller; these subsets exercise both batch sizes.
        for selected in ((0, 3, 7), (1, 3, 6, 8, 14)):
            with self.subTest(selected=selected):
                expanded = [self.fetch(
                    source_id=response["scrapes"][i]["source_id"], full_content=True,
                ) for i in selected]
                self.assertEqual(len(expanded), len(selected))
                for i, page in zip(selected, expanded):
                    self.assert_full_body(page)
                    self.assertEqual(page["source_id"], response["scrapes"][i]["source_id"])
                    self.assertTrue(page["cache_hit"])
                self.assertEqual(self.scraper.call_count, 15)

    def test_full_content_does_not_bypass_existing_cache_capacity(self):
        self.scraper.side_effect = None
        body = "x" * (DEFAULT_MAX_OBJECT_BYTES + 1)
        self.scraper.return_value = {"url": URL, "markdown": body, "via": "fixture"}
        fetched = self.fetch(url=URL, full_content=True)
        self.assertEqual(fetched["body"], body)
        self.assertFalse(fetched["persisted"])
        self.assertIn("exceeds max object bytes", fetched["persist_error"]["message"])
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])


# 100,000 CJK characters: ~100K characters (well under the character
# acquisition bound) but 300,000 UTF-8 bytes (over the 256 KiB cache bound).
LARGE_CJK_BODY = "# 大型中文页面\n" + "中文正文内容" * 16_666 + "\n文章结束"


class LargeCjkFetchTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        temporary = stack.enter_context(TemporaryDirectory(prefix="large-cjk-"))
        self.store = StateStore(Path(temporary) / "state.sqlite")
        stack.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected network")))
        self.scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": LARGE_CJK_BODY[:kwargs["scrape_chars"]], "via": "fixture",
        })

    def fetch(self, **request):
        return service.run_fetch_source(
            service.FetchSourceRequest(**request), state_store=self.store,
            scraper=self.scraper, keys={}, config={}, url_resolver=resolver,
        )

    def test_fixture_exceeds_the_byte_limit_but_not_the_character_limit(self):
        self.assertGreater(len(LARGE_CJK_BODY.encode("utf-8")), 256 * 1024)
        self.assertLess(len(LARGE_CJK_BODY), max_acquisition_chars())

    def test_character_acquisition_limit_is_aligned_with_the_byte_limit(self):
        # No body longer than the byte bound in characters can ever be stored,
        # so the acquisition bound must not exceed it, and must not drop below
        # the largest storable (pure ASCII) body either.
        self.assertEqual(max_acquisition_chars(), DEFAULT_MAX_OBJECT_BYTES)
        self.assertEqual(max_acquisition_chars(1000), 1000)
        self.fetch(url=URL, full_content=True)
        self.assertEqual(self.scraper.call_args.kwargs["scrape_chars"], max_acquisition_chars())

    def test_large_cjk_full_content_fetch_returns_the_body_unpersisted(self):
        fetched = self.fetch(url=URL, full_content=True)
        self.assertEqual(fetched["body"], LARGE_CJK_BODY)
        self.assertEqual(fetched["content_length"], len(LARGE_CJK_BODY))
        self.assertTrue(fetched["body"].endswith("文章结束"))
        self.assertFalse(fetched["truncated"])
        self.assertFalse(fetched["persisted"])
        self.assertFalse(fetched["cache_hit"])
        self.assertIsNone(fetched["content_hash"])
        self.assertIsNone(fetched["expires_at"])
        error = fetched["persist_error"]
        self.assertEqual(error["reason"], "content_too_large")
        self.assertEqual(error["content_bytes"], len(LARGE_CJK_BODY.encode("utf-8")))
        self.assertEqual(error["limit_bytes"], DEFAULT_MAX_OBJECT_BYTES)
        self.assertIn("not cached", error["message"])
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])
        self.assertEqual(self.store.rows("SELECT * FROM content_sources"), [])
        with self.assertRaisesRegex(ValueError, "missing or expired"):
            service.run_read_source(
                service.ReadSourceRequest(source_id=fetched["source_id"]), state_store=self.store,
            )

    def test_large_cjk_preview_fetch_returns_the_preview_unpersisted(self):
        fetched = self.fetch(url=URL, max_chars=1200)
        self.assertEqual(fetched["body"], LARGE_CJK_BODY[:1200])
        self.assertTrue(fetched["truncated"])
        self.assertFalse(fetched["persisted"])
        self.assertEqual(fetched["persist_error"]["reason"], "content_too_large")

    def test_small_cjk_page_is_still_persisted_without_persist_error(self):
        small = "中文" * 1000
        self.scraper.side_effect = None
        self.scraper.return_value = {"url": URL, "markdown": small, "via": "fixture"}
        fetched = self.fetch(url=URL, full_content=True)
        self.assertTrue(fetched["persisted"])
        self.assertNotIn("persist_error", fetched)
        self.assertTrue(self.fetch(source_id=fetched["source_id"], full_content=True)["cache_hit"])

    def test_search_keeps_large_cjk_preview_and_reports_it_was_not_cached(self):
        rows = [{
            "source": "brave", "title": "大型中文页面", "url": URL,
            "description": "中文摘要", "content_kind": "excerpt",
        }]
        provider = ProviderSpec(name="brave", public_name="brave", call=lambda *_args: rows)
        response = service.run_search_web(
            service.SearchWebRequest(query="中文", sources=["brave"], count=1),
            providers={"brave": provider}, keys={}, config={}, state_store=self.store,
            scraper=self.scraper, url_resolver=resolver,
        )
        self.assertEqual(response["errors"], [])
        page = response["scrapes"][0]
        self.assertNotIn("error", page)
        self.assertTrue(page["markdown"])
        self.assertEqual(page["length"], len(LARGE_CJK_BODY))
        self.assertFalse(page["persisted"])
        hit = response["results"][0]
        self.assertTrue(hit["body_available"])
        self.assertFalse(hit["body_persisted"])
        failure, = response["diagnostics"]["body_persist_failures"]
        self.assertEqual(failure["source_id"], hit["source_id"])
        self.assertEqual(failure["reason"], "content_too_large")
        self.assertEqual(response["diagnostics"]["body_success_count"], 1)


if __name__ == "__main__":
    unittest.main()
