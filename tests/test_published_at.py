"""Publication timestamps from upstream search results survive fusion."""
import json
import unittest
from unittest import mock

from multi_search_mcp.src.search.candidates import run_search_candidates
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search.searchers import brave, exa, hackernews, tavily


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return json.dumps(self._payload).encode("utf-8")


HACKERNEWS_PAYLOAD = {
    "hits": [{
        "objectID": "42",
        "title": "Launch",
        "url": "https://example.com/hackernews",
        "created_at": "2026-08-27T00:00:00Z",
    }],
}

EXA_PAYLOAD = {
    "results": [{
        "title": "Exa result",
        "url": "https://example.com/exa",
        "publishedDate": "2025-04-14T00:00:00.000Z",
        "highlights": ["excerpt"],
    }],
}

TAVILY_PAYLOAD = {
    "results": [{
        "title": "Tavily result",
        "url": "https://example.com/tavily",
        "content": "snippet",
        "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
    }],
}

BRAVE_PAYLOAD = {
    "web": {
        "results": [{
            "title": "Brave result",
            "url": "https://example.com/brave",
            "description": "snippet",
            "page_age": "2025-04-12T14:22:41",
        }],
    },
}


class PublishedAtMappingTests(unittest.TestCase):
    def test_hackernews_maps_created_at_to_published_at(self):
        with mock.patch.object(
            hackernews, "urlopen_retry", return_value=_FakeResponse(HACKERNEWS_PAYLOAD),
        ):
            rows = hackernews.search_hackernews("publish-time", count=1)

        self.assertEqual(rows[0]["published_at"], "2026-08-27T00:00:00Z")

    def test_exa_maps_published_date_to_published_at(self):
        with mock.patch.object(
            exa, "urlopen_retry", return_value=_FakeResponse(EXA_PAYLOAD),
        ):
            rows = exa.search_exa("publish-time", "fixture-exa-key", count=1)

        self.assertEqual(rows[0]["published_at"], "2025-04-14T00:00:00.000Z")

    def test_tavily_maps_published_date_to_published_at(self):
        with mock.patch.object(
            tavily, "urlopen_retry", return_value=_FakeResponse(TAVILY_PAYLOAD),
        ):
            rows = tavily.search_tavily("publish-time", "fixture-tavily-key", max_results=1)

        self.assertEqual(rows[0]["published_at"], "Tue, 11 Mar 2025 17:00:00 GMT")

    def test_tavily_requests_published_date_in_search_payload(self):
        with mock.patch.object(
            tavily, "urlopen_retry", return_value=_FakeResponse(TAVILY_PAYLOAD),
        ) as fetch:
            tavily.search_tavily("publish-time", "fixture-tavily-key", max_results=1)

        request = fetch.call_args.args[0]
        self.assertIs(json.loads(request.data)["include_published_date"], True)

    def test_brave_maps_page_age_to_published_at(self):
        with mock.patch.object(
            brave, "urlopen_retry", return_value=_FakeResponse(BRAVE_PAYLOAD),
        ):
            rows = brave.search_brave("publish-time", "fixture-brave-key", count=1)

        self.assertEqual(rows[0]["published_at"], "2025-04-12T14:22:41")

    def _rows(self, source: str) -> list[dict]:
        if source == "hackernews":
            with mock.patch.object(
                hackernews, "urlopen_retry", return_value=_FakeResponse(HACKERNEWS_PAYLOAD),
            ):
                return hackernews.search_hackernews("publish-time", count=1)
        if source == "exa":
            with mock.patch.object(exa, "urlopen_retry", return_value=_FakeResponse(EXA_PAYLOAD)):
                return exa.search_exa("publish-time", "fixture-exa-key", count=1)
        if source == "tavily":
            with mock.patch.object(
                tavily, "urlopen_retry", return_value=_FakeResponse(TAVILY_PAYLOAD),
            ):
                return tavily.search_tavily("publish-time", "fixture-tavily-key", max_results=1)
        with mock.patch.object(brave, "urlopen_retry", return_value=_FakeResponse(BRAVE_PAYLOAD)):
            return brave.search_brave("publish-time", "fixture-brave-key", count=1)

    def test_fused_search_hit_carries_published_at(self):
        expected = {
            "hackernews": "2026-08-27T00:00:00Z",
            "exa": "2025-04-14T00:00:00.000Z",
            "tavily": "Tue, 11 Mar 2025 17:00:00 GMT",
            "brave": "2025-04-12T14:22:41",
        }
        for source, published_at in expected.items():
            with self.subTest(source=source):
                rows = self._rows(source)
                providers = {
                    source: ProviderSpec(source, source, lambda *_args, rows=rows, **_kwargs: rows),
                }
                response = run_search_candidates(
                    {"query": "publish-time", "sources": [source], "count": 1, "use_state": False},
                    providers=providers, keys={}, config={},
                )
                self.assertEqual(response["results"][0]["published_at"], published_at)


if __name__ == "__main__":
    unittest.main()
