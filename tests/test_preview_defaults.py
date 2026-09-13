import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from pydantic_core import to_json

from multi_search_mcp.src import service
from multi_search_mcp.src.search.resolve import resolve_search_plan
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state import state_store
from multi_search_mcp.src.state.content_store import DEFAULT_MAX_OBJECT_BYTES
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.config import load_config


URL = "https://evidence.example/preview"
MARKER = "UNIQUE_PREVIEW_BODY"
BODY = MARKER + "正文abc0123;" * 1000
ROOT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "multi-search-config.json"


def _resolver(_host):
    return ["93.184.216.34"]


class PreviewDefaultTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        temporary = stack.enter_context(TemporaryDirectory(prefix="preview-defaults-"))
        self.state_path = Path(temporary) / "state.sqlite"
        stack.enter_context(mock.patch.object(state_store, "DEFAULT_STATE_PATH", self.state_path))
        stack.enter_context(mock.patch.object(service, "load_config", return_value={}))
        stack.enter_context(mock.patch.object(service, "load_keys", return_value={}))
        stack.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")))
        self.providers = {"brave": ProviderSpec(
            name="brave", public_name="brave",
            call=lambda *_args: [{
                "source": "brave", "title": "Preview document", "url": URL,
                "description": "Search excerpt", "content_kind": "excerpt",
            }],
        )}
        self.scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": BODY[:kwargs["scrape_chars"]], "via": "fixture",
        })

    def test_empty_and_repo_config_use_1200_character_default(self):
        for config in ({}, load_config(str(ROOT_CONFIG_PATH))):
            with self.subTest(configured=bool(config)):
                plan = resolve_search_plan(service.MultiSearchRequest(query="preview"), config)
                self.assertEqual(plan.scrape_chars, 1200)

    def test_preview_request_overrides_config_and_config_overrides_default(self):
        for requested, config, expected in (
            (None, {}, 1200),
            (None, {"scrape_chars": 2400}, 2400),
            (3600, {"scrape_chars": 2400}, 3600),
        ):
            with self.subTest(requested=requested, config=config):
                plan = resolve_search_plan(
                    service.MultiSearchRequest(query="preview", scrape_chars=requested), config,
                )
                self.assertEqual(plan.scrape_chars, expected)

    def test_search_default_preview_preserves_full_acquisition_and_cached_continuation(self):
        store = StateStore(self.state_path)
        response = service.run_search_web(
            service.SearchWebRequest(query="preview", sources=["brave"]),
            providers=self.providers, keys={}, config={}, state_store=store,
            scraper=self.scraper, url_resolver=_resolver,
        )
        self.assertEqual(response["errors"], [])
        page = response["scrapes"][0]
        self.assertEqual(len(page["markdown"]), 1200)
        self.assertEqual(page["markdown"], BODY[:1200])
        self.assertGreater(len(page["markdown"].encode("utf-8")), 1200)
        self.assertEqual(page["length"], len(BODY))
        self.assertTrue(page["truncated"])
        self.assertEqual(self.scraper.call_args.kwargs["scrape_chars"], DEFAULT_MAX_OBJECT_BYTES)

        continuation = service.run_read_source(
            service.ReadSourceRequest(source_id=page["source_id"], offset=1400, limit=80),
            state_store=store,
        )
        self.assertEqual(continuation["content"], BODY[1400:1480])
        self.assertEqual(continuation["content_length"], len(BODY))
        self.assertEqual(self.scraper.call_count, 1)

    def test_multi_search_default_matches_search_web_in_every_output_mode(self):
        current = service.run_search_web(
            service.SearchWebRequest(query="preview", sources=["brave"], use_state=False),
            providers=self.providers, keys={}, config={}, scraper=self.scraper,
            url_resolver=_resolver,
        )
        self.assertEqual(current["errors"], [])
        expected = current["scrapes"][0]["markdown"]
        self.assertEqual(len(expected), 1200)
        self.assertEqual(expected, BODY[:1200])
        with (
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry", return_value=self.providers),
            mock.patch.object(service, "scrape_url_smart", self.scraper),
            mock.patch("multi_search_mcp.src.support.url_security._resolve_host_ips", side_effect=_resolver),
        ):
            for mode in ("json", "markdown", "both"):
                with self.subTest(mode=mode):
                    response = service.run_multi_search(service.MultiSearchRequest(
                        query="preview", sources=["brave"], use_state=False, output=mode,
                    ))
                    self.assertEqual(response["errors"], [])
                    self.assertEqual(response["scrapes"][0]["length"], len(BODY))
                    self.assertTrue(response["scrapes"][0]["truncated"])
                    self.assertEqual(to_json(response).decode().count(MARKER), 1)
                    if mode == "json":
                        self.assertEqual(response["scrapes"][0]["markdown"], expected)
                    else:
                        self.assertNotIn("markdown", response["scrapes"][0])
                        self.assertIn(f"```untrusted\n{expected}\n```", response["markdown"])
                        self.assertNotIn(BODY[:1201], response["markdown"])
        self.assertEqual(self.scraper.call_count, 4)

    def test_direct_scrape_default_and_larger_overrides_in_every_output_mode(self):
        # These backends return the acquired body; run_scrape owns its public projection.
        scraper = mock.Mock(return_value={"url": URL, "markdown": BODY, "via": "fixture"})
        for requested, size in ((None, 1200), (2400, 2400), (len(BODY), len(BODY))):
            for mode in ("json", "markdown", "both"):
                with self.subTest(requested=requested, mode=mode):
                    response = service.run_scrape(
                        service.ScrapeRequest(
                            url=URL, scrape_chars=requested, output=mode, use_state=False,
                        ),
                        scraper=scraper, keys={}, config={},
                    )
                    page = response["result"]
                    self.assertEqual(page["length"], len(BODY))
                    self.assertEqual(page["truncated"], size < len(BODY))
                    self.assertEqual(to_json(response).decode().count(MARKER), 1)
                    if mode == "json":
                        self.assertEqual(len(page["markdown"]), size)
                        self.assertEqual(page["markdown"], BODY[:size])
                    else:
                        self.assertNotIn("markdown", page)
                        rendered_body = response["markdown"].split("```untrusted\n", 1)[1].split("\n```", 1)[0]
                        self.assertEqual(len(rendered_body), size)
                        self.assertEqual(rendered_body, BODY[:size])
                        self.assertEqual("_...truncated (" in response["markdown"], size < len(BODY))
                        if size < len(BODY):
                            self.assertNotIn(BODY[:size + 1], response["markdown"])


if __name__ == "__main__":
    unittest.main()
