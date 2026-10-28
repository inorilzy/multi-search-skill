"""Data-driven check that every searchable source reaches its own searcher.

Each source gets a controlled fake searcher patched on the registry module, returning a row
shaped like the real searcher output. No network call is made, and no real key or config is
read: the keys file and the environment are isolated per test. Key requirements come from the
capability metadata, not from a hardcoded list.
"""
import unittest
from unittest import mock

from multi_search_mcp.src.search.capabilities import get_capability
from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES

# (public source name, registry searcher attribute)
MATRIX = [
    ("baidu", "search_baidu"),
    ("brave", "search_brave"),
    ("exa", "search_exa"),
    ("firecrawl", "search_firecrawl"),
    ("github_repos", "search_github_repos"),
    ("hackernews", "search_hackernews"),
    ("parallel", "search_parallel"),
    ("serpapi", "search_serpapi"),
    ("sov2ex", "search_sov2ex"),
    ("stackoverflow", "search_stackoverflow"),
    ("tavily", "search_tavily"),
    ("twitter", "search_twitter"),
]

def _requires_key(name: str) -> bool:
    return bool(get_capability(name).operation.requires_api_key)

def _key_pool_name(name: str) -> str | None:
    operation = get_capability(name).operation
    return operation.key_name if operation.uses_api_key_pool else None

def _fake_row(name: str) -> dict:
    return {
        "source": name,
        "title": f"{name}-hit",
        "url": f"https://example.invalid/{name}",
        "snippet": "fixture",
        "content_kind": "snippet",
    }

def _scraper(url: str, **_kwargs) -> dict:
    """Return a synthetic body for the fetch stage without touching the network."""

    return {"url": url, "markdown": "fixture body", "via": "fixture"}

def _search(request: dict, keys: dict) -> dict:
    from multi_search_mcp.src.service import run_search_web

    return run_search_web(
        request, keys=keys, config={}, scraper=_scraper,
    )

class SearchSourceMatrixTests(unittest.TestCase):
    def test_matrix_covers_every_searchable_source(self):
        self.assertEqual(sorted(name for name, _ in MATRIX), sorted(ALL_SOURCE_NAMES))
        self.assertEqual(len(MATRIX), 12)

    def test_every_source_reaches_its_own_searcher_with_controlled_fake(self):
        for name, searcher in MATRIX:
            with self.subTest(source=name):
                calls: list[str] = []

                def fake(*args, __name=name, __calls=calls, **kwargs):
                    __calls.append(__name)
                    return [_fake_row(__name)]

                # Give each key-requiring source a synthetic key so the searcher is reached.
                keys = {}
                if _requires_key(name) and _key_pool_name(name):
                    keys[_key_pool_name(name)] = "synthetic-matrix-key"
                with mock.patch(f"multi_search_mcp.src.search.registry.{searcher}", fake):
                    response = _search(
                        {"query": "fixture", "sources": [name], "count": 1, "use_state": False},
                        keys,
                    )
                self.assertEqual(calls, [name], "the source must call its own searcher exactly once")
                titles = [hit.get("title") for hit in response.get("results", [])]
                self.assertIn(f"{name}-hit", titles)

    def test_fixture_flow_resolves_nothing_and_runs_no_real_scraper(self):
        """Regression for the isolation violations: the fetch stage stays injected."""

        calls: list[str] = []

        def fake(*_args, **_kwargs):
            calls.append("hackernews")
            return [_fake_row("hackernews")]

        with mock.patch(
            "multi_search_mcp.src.search.registry.search_hackernews", fake,
        ), mock.patch(
            "socket.getaddrinfo",
            side_effect=AssertionError("the matrix fixture must not resolve any host"),
        ), mock.patch(
            "multi_search_mcp.src.scrape.service.scrape_url_smart",
            side_effect=AssertionError("the matrix fixture must not scrape the internet"),
        ):
            response = _search(
                {"query": "fixture", "sources": ["hackernews"], "count": 1, "use_state": False},
                {},
            )

        self.assertEqual(calls, ["hackernews"])
        self.assertEqual(response["diagnostics"]["body_failures"], [])
        self.assertEqual([row["markdown"] for row in response["scrapes"]], ["fixture body"])

    def test_key_required_source_without_key_is_not_called(self):
        for name, searcher in MATRIX:
            if not _requires_key(name) or not _key_pool_name(name):
                continue
            with self.subTest(source=name):
                calls: list[str] = []

                def fake(*args, __calls=calls, **kwargs):
                    __calls.append(True)
                    return []

                with mock.patch(f"multi_search_mcp.src.search.registry.{searcher}", fake):
                    _search(
                        {"query": "fixture", "sources": [name], "count": 1, "use_state": False},
                        {},
                    )
                self.assertEqual(calls, [], "a key-required source with no key must not reach its searcher")

if __name__ == "__main__":
    unittest.main()
