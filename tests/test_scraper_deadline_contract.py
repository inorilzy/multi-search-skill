"""Per-call deadlines reach real provider adapters, not only dispatcher fakes."""
import io
import json
import unittest
from unittest import mock

from multi_search_mcp.src.scrape.scrapers import exa, firecrawl, jina, tavily


class ScraperDeadlineContractTests(unittest.TestCase):
    def test_each_adapter_caps_its_http_budget_to_the_remaining_deadline(self):
        fixtures = (
            (exa, exa.scrape_url_exa, {"results": [{"text": "body"}]}),
            (firecrawl, firecrawl.scrape_url_firecrawl, {"success": True, "data": {"markdown": "body"}}),
            (jina, jina.scrape_url_jina, {"data": {"content": "body"}}),
            (tavily, tavily.scrape_url_tavily, {"results": [{"raw_content": "body"}]}),
        )
        for module, call, payload in fixtures:
            with self.subTest(backend=module.__name__), mock.patch("time.monotonic", return_value=100), mock.patch.object(
                module, "urlopen_retry", return_value=io.BytesIO(json.dumps(payload).encode()),
            ) as request:
                result = call("https://example.com/article", "synthetic-key", timeout=20, deadline=103)
                self.assertNotIn("error", result)
                self.assertEqual(result["markdown"], "body")
                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs["timeout"], 3)


if __name__ == "__main__":
    unittest.main()
