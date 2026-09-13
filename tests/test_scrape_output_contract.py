import asyncio
import copy
import io
import json
import unittest
from contextlib import ExitStack
from unittest import mock

from pydantic_core import to_json

from multi_search_mcp import cli
from multi_search_mcp.server import mcp
from multi_search_mcp.src import service
from multi_search_mcp.src.scrape import scrape


URL = "https://example.com/post"
MARKER = "UNIQUE_SCRAPED_PASSAGE"
BODY = MARKER + " actual source text" * 20
FIELDS = {"url", "title", "markdown", "length", "via", "truncated"}


def candidates(count=1):
    return {
        "query": "contract probe", "route": "default", "response_id": "probe",
        "results": [{
            "source_id": f"source_{i}", "url": f"{URL}/{i}",
            "canonical_url": f"{URL}/{i}", "title": f"Post {i}",
            "content": "Search excerpt", "source": "brave", "providers": ["brave"],
            "rrf_rank": i + 1, "rrf_score": 1 / (40 + i + 1),
        } for i in range(count)],
        "errors": [], "diagnostics": {},
    }


class SingleMarkdownResponseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(service, "load_keys", return_value={}))
        self.stack.enter_context(mock.patch.object(service, "load_config", return_value={}))
        self.stack.enter_context(mock.patch.object(
            service, "_run_search_candidates", side_effect=lambda *a, **k: candidates(),
        ))
        self.stack.enter_context(mock.patch.object(service, "run_fetch_source", return_value={
            "body": BODY, "content_length": len(BODY), "backend": "fixture",
            "truncated": False,
        }))

    def test_search_returns_each_body_only_once_as_markdown(self):
        result = service.run_search_web(
            service.SearchWebRequest(query="probe", use_state=False), keys={}, config={},
        )
        self.assertEqual(json.dumps(result).count(MARKER), 1)
        self.assertNotIn("body", result["results"][0])
        self.assertEqual(result["scrapes"][0]["markdown"], BODY)

    def test_compat_search_never_repeats_bodies_in_any_output_mode(self):
        for mode in ("json", "markdown", "both"):
            with self.subTest(mode=mode):
                result = service.run_multi_search(service.MultiSearchRequest(
                    query="probe", use_state=False, output=mode,
                ))
                self.assertEqual(to_json(result).decode().count(MARKER), 1)
                if mode == "json":
                    self.assertEqual(result["scrapes"][0]["markdown"], BODY)
                else:
                    self.assertIn(MARKER, result["markdown"])
                    self.assertNotIn("markdown", result["scrapes"][0])
                    self.assertIn("source_0", result["markdown"])

    def test_direct_scrape_never_repeats_body_in_any_output_mode(self):
        for mode in ("json", "markdown", "both"):
            with self.subTest(mode=mode):
                result = service.run_scrape(
                    service.ScrapeRequest(url=URL, output=mode, use_state=False),
                    scraper=lambda *_a, **_k: {"url": URL, "markdown": BODY, "via": "fixture"},
                    keys={}, config={},
                )
                self.assertEqual(json.dumps(result).count(MARKER), 1)

    def test_cli_renders_the_single_markdown_body_and_source_reference(self):
        result = service.run_search_web(
            service.SearchWebRequest(query="probe", use_state=False), keys={}, config={},
        )
        for mode in ("json", "human", "markdown"):
            with self.subTest(mode=mode):
                output = io.StringIO()
                cli._write_payload(result, mode, output)
                self.assertEqual(output.getvalue().count(MARKER), 1)
                self.assertIn("source_0", output.getvalue())

    def test_failed_search_retains_reference_and_error_in_the_same_order(self):
        with mock.patch.object(service, "run_fetch_source", side_effect=ValueError("unavailable")):
            result = service.run_search_web(
                service.SearchWebRequest(query="probe", use_state=False), keys={}, config={},
            )
        page = result["scrapes"][0]
        self.assertTrue(FIELDS <= page.keys())
        self.assertEqual(page["source_id"], result["results"][0]["source_id"])
        self.assertEqual(page["error"], result["results"][0]["body_error"])
        self.assertEqual(page["markdown"], "")

    def test_invalid_fetch_body_cannot_be_marked_as_success(self):
        with mock.patch.object(service, "run_fetch_source", return_value={"body": []}):
            result = service.run_search_web(
                service.SearchWebRequest(query="probe", use_state=False), keys={}, config={},
            )
        self.assertFalse(result["results"][0]["body_available"])
        self.assertIn("invalid scrape response", result["results"][0]["body_error"])
        self.assertEqual(result["diagnostics"]["body_success_count"], 0)
        self.assertEqual(len(result["diagnostics"]["body_failures"]), 1)

    def test_registered_mcp_tools_emit_one_body_in_the_text_response(self):
        for tool in ("search_web", "multi_search"):
            with self.subTest(tool=tool):
                result = asyncio.run(mcp.call_tool(tool, {"query": "probe", "use_state": False}))
                texts = [item.text for item in result if getattr(item, "type", None) == "text"]
                self.assertEqual(len(texts), 1)
                self.assertEqual(texts[0].count(MARKER), 1)
                self.assertIn("source_0", texts[0])


class ScraperContractTests(unittest.TestCase):
    def _scrape(self, backend, payload):
        url = "https://www.reddit.com/r/test/comments/abc123/post/" if backend == "reddit" else URL
        with mock.patch.object(scrape, f"scrape_url_{backend}", return_value=copy.deepcopy(payload)):
            return scrape.scrape_url_smart(
                url, backends=None if backend == "reddit" else [backend],
                exa_keys=["fixture-key"], tavily_keys=["fixture-key"],
                url_resolver=lambda _host: ["93.184.216.34"],
            )

    def test_all_five_backends_share_success_fields_and_preserve_markdown(self):
        for backend in ("jina", "exa", "tavily", "firecrawl", "reddit"):
            with self.subTest(backend=backend):
                markdown = "# Title\n\n`literal &amp;`\n\n正文 **bold**"
                result = self._scrape(backend, {"markdown": markdown, "raw_provider_dump": "not public"})
                self.assertTrue(FIELDS <= result.keys())
                self.assertEqual(result["markdown"], markdown)
                self.assertEqual(result["length"], len(markdown))
                self.assertEqual(result["via"], backend)
                self.assertFalse(result["truncated"])
                self.assertNotIn("error", result)
                self.assertNotIn("raw_provider_dump", result)

    def test_all_five_backends_share_error_fields(self):
        for backend in ("jina", "exa", "tavily", "firecrawl", "reddit"):
            with self.subTest(backend=backend):
                result = self._scrape(backend, {"error": "unavailable"})
                self.assertTrue(FIELDS <= result.keys())
                self.assertEqual(result["error"], "unavailable")
                self.assertEqual(result["markdown"], "")
                self.assertEqual(result["length"], 0)
                self.assertEqual(result["via"], backend)

    def test_invalid_payload_and_empty_markdown_are_explicit_errors(self):
        for value in (None, [], {"markdown": ["bad"]}, {"markdown": "  "}, {"body": "wrong field"}):
            with self.subTest(payload=value):
                result = self._scrape("reddit", value)
                self.assertTrue(FIELDS <= result.keys())
                self.assertIn("error", result)
                self.assertEqual(result["markdown"], "")

    def test_direct_preview_has_original_length_and_truncation_marker(self):
        result = service.run_scrape(
            service.ScrapeRequest(url=URL, output="json", scrape_chars=8, use_state=False),
            scraper=lambda *_a, **_k: {"url": URL, "markdown": BODY, "via": "fixture"},
            keys={}, config={},
        )["result"]
        self.assertTrue(FIELDS <= result.keys())
        self.assertEqual(result["markdown"], BODY[:8])
        self.assertEqual(result["length"], len(BODY))
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
