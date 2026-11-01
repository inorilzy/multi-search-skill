"""GitHub code search source (``github_code`` / ``github-code``)."""
import io
import json
import unittest
import urllib.parse
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp.src.search.capabilities import get_capability
from multi_search_mcp.src.search.catalog import build_source_catalog
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.resolve import COUNT_CAPS, build_counts
from multi_search_mcp.src.search.search_runner import (
    ALL_SOURCE_NAMES,
    ROUTE_PROFILES,
    SOURCE_ALIASES,
    SearchRunner,
    SearchRunnerConfig,
    default_routes_config,
)
from multi_search_mcp.src.search.searchers import github


TOKEN = "fixture-github-code-token"


def code_item(full_name, path="README.md", fragment="", html_url=None):
    item = {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "sha": "abc",
        "url": f"https://api.github.com/repos/{full_name}/contents/{path}",
        "git_url": f"https://api.github.com/repos/{full_name}/git/blobs/abc",
        "html_url": f"https://github.com/{full_name}/blob/main/{path}",
        "repository": {
            "full_name": full_name,
            "html_url": html_url or f"https://github.com/{full_name}",
        },
        "score": 1.0,
    }
    if fragment is not None:
        item["text_matches"] = [{"property": "content", "fragment": fragment, "matches": []}]
    return item


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def http_error(status, body, headers=None):
    return HTTPError("https://api.github.com/search/code", status, "err", headers or {}, body)


class GitHubCodeSearchTests(unittest.TestCase):
    def setUp(self):
        guard = mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("unexpected real HTTP request"),
        )
        guard.start()
        self.addCleanup(guard.stop)

    def run_code(self, payload=None, *, error=None, query="fixture", count=10, token=TOKEN):
        captured = {}

        def fake(req, timeout=None):
            captured["request"] = req
            if error is not None:
                raise error
            return response(payload if payload is not None else {"incomplete_results": False, "items": []})

        with mock.patch.object(github, "urlopen_retry", side_effect=fake):
            rows = github.search_github_code(query, count=count, token=token, timeout=1)
        return rows, captured.get("request")

    def test_request_url_and_headers(self):
        _, req = self.run_code(query="yazi_plugin preview", count=250)
        parsed = urllib.parse.urlsplit(req.full_url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://api.github.com/search/code")
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(params["q"], ["yazi_plugin preview"])
        self.assertEqual(params["per_page"], ["100"])
        self.assertNotIn("filename:README.md", params["q"][0])
        self.assertNotIn("sort", params)
        headers = {name.lower(): value for name, value in req.header_items()}
        self.assertEqual(headers["accept"], "application/vnd.github.text-match+json")
        self.assertEqual(headers["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(headers["x-github-api-version"], "2022-11-28")
        self.assertEqual(headers["user-agent"], "multi-search/1.0")

    def test_per_page_follows_count(self):
        _, req = self.run_code(count=5)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        self.assertEqual(params["per_page"], ["5"])

    def test_dedupes_by_repository_preserving_api_order(self):
        rows, _ = self.run_code({
            "incomplete_results": False,
            "items": [
                code_item("b/two", "src/a.lua", "first b"),
                code_item("a/one", "README.md", "first a"),
                code_item("b/two", "src/c.lua", "second b"),
                code_item("c/three", "init.lua", "first c"),
            ],
        })
        self.assertEqual([row["title"] for row in rows], ["b/two", "a/one", "c/three"])
        self.assertEqual(rows[0]["url"], "https://github.com/b/two")
        self.assertEqual(rows[0]["path"], "src/a.lua")
        self.assertTrue(all(row["source"] == "github-code" for row in rows))
        self.assertFalse(any("error" in row for row in rows))

    def test_fragment_description_collapses_whitespace_and_caps_length(self):
        rows, _ = self.run_code({
            "incomplete_results": False,
            "items": [
                code_item("a/one", "README.md", "  yazi_plugin\n\n   preview\tdemo  "),
                code_item("b/two", "docs/long.md", "x " * 400),
                code_item("c/three", "empty.md", None),
            ],
        })
        self.assertEqual(rows[0]["description"], "README.md: yazi_plugin preview demo")
        self.assertEqual(rows[0]["content_kind"], "excerpt")
        self.assertTrue(rows[1]["description"].startswith("docs/long.md: x x"))
        self.assertLessEqual(len(rows[1]["description"]), 300)
        self.assertEqual(rows[2]["description"], "")
        self.assertEqual(rows[2]["content_kind"], "metadata")
        self.assertEqual(rows[2]["path"], "empty.md")

    def test_incomplete_results_appends_target_warning(self):
        rows, _ = self.run_code({
            "incomplete_results": True,
            "items": [code_item("a/one", "README.md", "hit")],
        })
        self.assertEqual(rows[0]["title"], "a/one")
        self.assertEqual(rows[-1], {
            "source": "github-code",
            "error": "GitHub search timed out; results may be incomplete",
            "error_type": "target",
        })

    def test_repos_incomplete_results_appends_target_warning(self):
        payload = {
            "incomplete_results": True,
            "items": [{"full_name": "a/one", "html_url": "https://github.com/a/one", "description": "d"}],
        }
        with mock.patch.object(github, "urlopen_retry", return_value=response(payload)):
            rows = github.search_github_repos("fixture", token=TOKEN, timeout=1)
        self.assertEqual(rows[0]["title"], "a/one")
        self.assertEqual(rows[-1]["source"], "github-repos")
        self.assertEqual(rows[-1]["error_type"], "target")

    def test_query_truncated_to_github_limits(self):
        long_query = " ".join(["word"] * 80) + " language:lua"
        rows, req = self.run_code(query=long_query)
        sent = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)["q"][0]
        self.assertIn("language:lua", sent)
        text = " ".join(token for token in sent.split() if ":" not in token)
        self.assertLessEqual(len(text), 256)
        self.assertEqual(rows[-1], {
            "source": "github-code",
            "error": "query truncated to GitHub's 256-character / 5-operator limit",
            "error_type": "target",
        })

    def test_operators_beyond_fifth_are_dropped(self):
        query = " OR ".join(f"t{i}" for i in range(8))
        limited, truncated = github.limit_github_query(query)
        self.assertTrue(truncated)
        self.assertEqual(limited.split().count("OR"), 5)
        self.assertEqual(github.limit_github_query("a AND b"), ("a AND b", False))

    def test_missing_token_is_skipped_without_gh_fallback(self):
        with mock.patch.object(github, "_run_gh", side_effect=AssertionError("gh must not run")), \
                mock.patch.object(github, "urlopen_retry", side_effect=AssertionError("no HTTP")):
            rows = github.search_github_code("fixture", token="")
        self.assertEqual(rows[0]["error_type"], "missing_key")
        self.assertEqual(rows[0]["source"], "github-code")

    def test_runner_without_token_emits_missing_key_row(self):
        registry = build_provider_registry()
        self.assertTrue(registry["github_code"].key_required)
        self.assertEqual(registry["github_code"].key_name, "github")
        config = SearchRunnerConfig(
            route="custom", counts=build_counts({}), timeout=5, serpapi_engine="google", keys={},
        )
        with mock.patch(
            "multi_search_mcp.src.search.registry.search_github_code",
            side_effect=AssertionError("must not be called"),
        ):
            rows = SearchRunner(config, registry, route_resolver=lambda _r: {"github_code"}).run("q")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "github-code")
        self.assertEqual(rows[0]["error_type"], "missing_key")
        self.assertIn("GITHUB_TOKEN", rows[0]["error"])

    def test_403_rate_limit_carries_retry_after_from_reset(self):
        error = http_error(
            403,
            io.BytesIO(b'{"message":"API rate limit exceeded"}'),
            {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1000060"},
        )
        with mock.patch.object(github.time, "time", return_value=1000000.0):
            rows, _ = self.run_code(error=error)
        row = rows[0]
        self.assertEqual(row["source"], "github-code")
        self.assertEqual(row["error_type"], "rate_limit")
        self.assertTrue(row["rate_limited"])
        self.assertEqual(row["retry_after"], 60)
        self.assertNotIn(TOKEN, json.dumps(row))

    def test_retry_after_header_wins_and_applies_to_repos(self):
        error = http_error(
            403,
            io.BytesIO(b'{"message":"You have exceeded a secondary rate limit."}'),
            {"retry-after": "42", "x-ratelimit-reset": "1"},
        )
        with mock.patch.object(github, "urlopen_retry", side_effect=error):
            row = github.search_github_repos("fixture", token=TOKEN, timeout=1)[0]
        self.assertEqual(row["error_type"], "rate_limit")
        self.assertEqual(row["retry_after"], 42)

    def test_non_rate_limit_errors_have_no_retry_after(self):
        rows, _ = self.run_code(error=http_error(
            401, io.BytesIO(b'{"message":"Bad credentials"}'), {"x-ratelimit-reset": "1"},
        ))
        self.assertEqual(rows[0]["error_type"], "invalid")
        self.assertNotIn("retry_after", rows[0])


class GitHubCodeRegistrationTests(unittest.TestCase):
    def test_registered_with_own_count_key_and_shared_token(self):
        self.assertIn("github_code", ALL_SOURCE_NAMES)
        self.assertEqual(SOURCE_ALIASES["github-code"], "github_code")
        cap = get_capability("github_code")
        self.assertEqual(cap.public_name, "github-code")
        self.assertEqual(cap.count_key, "github_code")
        self.assertEqual(cap.search.max_count, 100)
        self.assertFalse(cap.search.supports_pagination)
        self.assertEqual(cap.operation.key_name, "github")
        self.assertTrue(cap.operation.requires_api_key)
        self.assertEqual(COUNT_CAPS["github_code"], 100)
        self.assertEqual(build_counts({"counts": {"github_code": 7}})["github_code"], 7)

    def test_not_in_any_builtin_route(self):
        for route, sources in ROUTE_PROFILES.items():
            with self.subTest(route=route):
                self.assertNotIn("github_code", sources)
        for route, definition in default_routes_config().items():
            with self.subTest(default_route=route):
                self.assertNotIn("github_code", definition["sources"])
        entry = next(s for s in build_source_catalog()["sources"] if s["name"] == "github_code")
        self.assertEqual(entry["routes"], [])
        self.assertEqual(entry["key_provider"], "github")
        self.assertTrue(entry["keyed"])
        self.assertEqual(entry["env"], ["GITHUB_TOKEN", "GH_TOKEN"])
        self.assertEqual(entry["label"], "GitHub 代码")


if __name__ == "__main__":
    unittest.main()
