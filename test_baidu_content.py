import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search.searchers.baidu import _rows_from_response
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://example.com/taskgroup"
SUMMARY = "TaskGroup cancels sibling tasks when one fails."


def rows(reference):
    return _rows_from_response(
        {"references": [{"title": "TaskGroup", "url": URL, **reference}]},
        endpoint="/v2/ai_search/web_summary", max_references=1,
    )


class BaiduContentTests(unittest.TestCase):
    def test_summary_content_is_excerpt_even_when_longer_than_preview(self):
        for reference in (
            {"content": SUMMARY, "snippet": SUMMARY},
            {"content": SUMMARY * 100},
            {"snippet": SUMMARY},
        ):
            with self.subTest(fields=list(reference), length=len(reference.get("content", ""))):
                row = rows(reference)[0]
                self.assertEqual(row["content_kind"], "excerpt")
                self.assertNotIn("scraped_content", row)
                self.assertEqual(row["description"], (reference.get("snippet") or reference["content"])[:300])

    def test_explicit_markdown_keeps_its_body_contract(self):
        row = rows({"content": SUMMARY, "snippet": SUMMARY, "markdown_text": "# Full page\nBody text."})[0]
        self.assertEqual(row["content_kind"], "body")
        self.assertEqual(row["scraped_content"], "# Full page\nBody text.")

    def test_summary_requires_fetch_and_only_fetched_body_is_cached(self):
        body = "# TaskGroup\n\nThe full article includes examples omitted from the summary."
        scraper = mock.Mock(return_value={"url": URL, "markdown": body, "via": "fixture"})
        provider = ProviderSpec(
            name="baidu", public_name="baidu",
            call=lambda *_: rows({"content": SUMMARY, "snippet": SUMMARY}),
        )
        with TemporaryDirectory() as temp:
            store = StateStore(Path(temp) / "state.sqlite")
            response = service.run_search_web(
                service.SearchWebRequest(query="TaskGroup", sources=["baidu"], count=1),
                providers={"baidu": provider}, keys={}, config={}, state_store=store,
                scraper=scraper, url_resolver=lambda _: ["93.184.216.34"],
            )
            scraper.assert_called_once()
            page = response["scrapes"][0]
            self.assertEqual(page["markdown"], body)
            self.assertEqual(page["via"], "fixture")
            fetched = service.run_fetch_source(
                service.FetchSourceRequest(source_id=page["source_id"], full_content=True),
                state_store=store, url_resolver=lambda _: ["93.184.216.34"],
            )
            self.assertTrue(fetched["cache_hit"])
            self.assertFalse(fetched["truncated"])
            self.assertEqual(fetched["body"], body)


if __name__ == "__main__":
    unittest.main()
