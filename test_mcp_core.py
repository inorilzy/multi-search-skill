"""Pure-logic and key/state tests for the multi-search MCP runtime.

These exercise the packaged MCP modules under multi_search_mcp/src (dedup, scrape planner,
routes, capabilities, models, secrets, cache, keys). The companion
test_mcp_architecture.py covers the MCP/service wiring and the C' architecture
fixes; this file covers the provider-agnostic core logic.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MCP_ROOT = Path(__file__).resolve().parent / "multi_search_mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from src.search.capabilities import (
    PROVIDER_CAPABILITIES,
    ProviderKind,
    ScrapePolicy,
    capability_table_rows,
    get_capability,
)
from src.search.search_runner import ROUTE_PROFILES, available_routes, resolve_route
from src.scrape.scrape_planner import plan_scrapes
from src.scrape.scrape import KNOWN_BACKENDS
from src.state.keys import (
    count_jina_keys,
    jina_config_keys,
    key_pool,
    load_keys,
    pick_key,
)
from src.state.mark_exhausted import _mark_config_exhausted
from src.support.cache import JsonCache, make_scrape_cache_key
from src.support.dedup import _norm_url, deduplicate, split_by_content
from src.support.models import ProviderError, ScrapeResult, SearchResult
from src.support.secrets import scrub_secrets
from src.search.searchers import baidu as baidu_searcher
from src.search.searchers import brave as brave_searcher
from src.search.searchers import exa as exa_searcher
from src.search.searchers import firecrawl as firecrawl_searcher
from src.search.searchers import serpapi as serpapi_searcher
from src.search.searchers import tavily as tavily_searcher


class SecretTests(unittest.TestCase):
    def test_scrub_secrets_redacts_common_credentials_and_nested_values(self):
        message = (
            "GET /search?api_key=abc123&token=tok456 "
            "Authorization: Bearer bearer-secret "
            "x-api-key: header-secret "
            "direct nested-secret and list-secret"
        )
        output = scrub_secrets(
            message,
            {"provider": {"key": "nested-secret"}, "pool": ["list-secret"]},
        )

        for secret in ("abc123", "tok456", "bearer-secret", "header-secret", "nested-secret", "list-secret"):
            self.assertNotIn(secret, output)
        self.assertIn("api_key=<redacted>", output)
        self.assertIn("token=<redacted>", output)
        self.assertIn("Authorization: <redacted>", output)
        self.assertIn("x-api-key: <redacted>", output)

    def test_scrub_secrets_tolerates_empty_secret_values(self):
        self.assertEqual(scrub_secrets("plain error", None), "plain error")


class ModelTests(unittest.TestCase):
    def test_search_result_round_trip_preserves_unknown_metadata(self):
        row = {
            "source": "brave",
            "title": "Doc",
            "url": "https://example.com",
            "description": "snippet",
            "also_from": ["exa"],
            "stars": 3,
            "custom": {"rank": 1},
        }

        result = SearchResult.from_dict(row).to_dict()

        self.assertEqual(result["source"], "brave")
        self.assertEqual(result["also_from"], ["exa"])
        self.assertEqual(result["custom"], {"rank": 1})

    def test_scrape_result_round_trip_preserves_length_and_raw(self):
        row = {
            "url": "https://example.com",
            "title": "Doc",
            "markdown": "body",
            "length": 99,
            "via": "jina",
            "cache": "hit",
        }

        result = ScrapeResult.from_dict(row).to_dict()

        self.assertEqual(result["length"], 99)
        self.assertEqual(result["via"], "jina")
        self.assertEqual(result["cache"], "hit")

    def test_provider_error_round_trip_keeps_source_error_and_raw(self):
        row = {"source": "exa", "error": "quota", "retryable": True}

        result = ProviderError.from_dict(row).to_dict()

        self.assertEqual(result["source"], "exa")
        self.assertEqual(result["error"], "quota")
        self.assertTrue(result["retryable"])


class RouteTests(unittest.TestCase):
    """Route assertions reflect the semantic-profile redesign.

    The legacy single-provider aliases (github/youtube/v2ex ...) were
    intentionally removed; routes are now multi-provider profiles.
    """

    def test_named_routes_resolve_to_expected_profiles(self):
        self.assertEqual(
            resolve_route("default"),
            {"brave", "exa", "tavily", "serpapi", "firecrawl", "baidu", "glm_web", "deepseek_web"},
        )
        self.assertEqual(resolve_route("dev"), {"stackoverflow", "hackernews", "github_repos"})
        self.assertEqual(resolve_route("social"), {"twitter", "reddit_oauth"})
        self.assertEqual(resolve_route("video"), {"bilibili", "youtube"})
        self.assertEqual(resolve_route("cn-community"), {"zhihu", "v2ex", "linuxdo"})
        self.assertNotIn("youtube", resolve_route("all"))
        self.assertNotIn("bilibili", resolve_route("all"))
        self.assertTrue({"brave", "baidu", "github_repos", "zhihu"} <= resolve_route("all"))

    def test_fast_route_resolves_to_inline_content_providers(self):
        # ``fast`` is a route whose providers return body content inline.
        self.assertEqual(resolve_route("fast"), {"baidu", "tavily", "firecrawl", "exa"})
        # ``normal`` is no longer a route or a level.
        self.assertEqual(resolve_route("normal"), set())

    def test_unknown_route_resolves_empty_for_validation(self):
        self.assertEqual(resolve_route("not-a-route"), set())
        self.assertEqual(resolve_route(""), set())

    def test_removed_single_provider_aliases_no_longer_resolve(self):
        for alias in ("github", "youtube", "bilibili", "v2ex", "zhihu", "reddit", "hackernews", "stackoverflow", "lite", "discussion"):
            self.assertEqual(resolve_route(alias), set(), alias)

    def test_available_routes_lists_semantic_profiles(self):
        routes = available_routes()
        for name in ("default", "fast", "all", "dev", "social", "video", "cn-community"):
            self.assertIn(name, routes)
        self.assertNotIn("normal", routes)
        self.assertNotIn("web", routes)


class CapabilityTests(unittest.TestCase):
    def test_capabilities_cover_all_route_sources(self):
        route_sources = set().union(*ROUTE_PROFILES.values())

        self.assertFalse(route_sources - set(PROVIDER_CAPABILITIES))

    def test_capabilities_cover_all_scraper_backends(self):
        for name in KNOWN_BACKENDS:
            self.assertIn(name, PROVIDER_CAPABILITIES)
            self.assertTrue(PROVIDER_CAPABILITIES[name].scrape.can_scrape)

    def test_video_sources_are_marked_skip_for_scraping(self):
        for name in ("youtube", "bilibili"):
            capability = PROVIDER_CAPABILITIES[name]
            self.assertEqual(capability.kind, ProviderKind.VIDEO_SEARCHER)
            self.assertEqual(capability.scrape_policy, ScrapePolicy.SKIP)

    def test_content_searchers_return_content_and_prefetch(self):
        for name in ("tavily", "exa", "twitter"):
            capability = PROVIDER_CAPABILITIES[name]
            self.assertTrue(capability.output.returns_content)
            self.assertEqual(capability.scrape_policy, ScrapePolicy.PREFETCH)

    def test_capability_table_rows_are_flat_for_markdown_rendering(self):
        rows = capability_table_rows(["brave", "tavily"])

        self.assertEqual(rows[0]["provider"], "brave")
        self.assertEqual(rows[0]["can_search"], True)
        self.assertEqual(rows[1]["returns_content"], True)
        self.assertIn("auth_mode", rows[0])

    def test_capability_table_exposes_normalized_result_fields(self):
        rows = {row["name"]: row for row in capability_table_rows(["baidu", "brave", "tavily"])}

        self.assertTrue(rows["baidu"]["returns_summary"])
        self.assertTrue(rows["baidu"]["returns_result_content"])
        self.assertTrue(rows["baidu"]["returns_title"])
        self.assertTrue(rows["baidu"]["returns_url"])
        self.assertTrue(rows["baidu"]["returns_prefetched_body"])

        self.assertFalse(rows["brave"]["returns_summary"])
        self.assertTrue(rows["brave"]["returns_result_content"])
        self.assertTrue(rows["brave"]["returns_title"])
        self.assertTrue(rows["brave"]["returns_url"])
        self.assertFalse(rows["brave"]["returns_prefetched_body"])

        self.assertTrue(rows["tavily"]["returns_summary"])
        self.assertTrue(rows["tavily"]["returns_prefetched_body"])

    def test_get_capability_resolves_public_name(self):
        self.assertEqual(get_capability("brave").public_name, "brave")

    def test_baidu_capability_is_available_as_answer_searcher(self):
        capability = get_capability("baidu")

        self.assertEqual(capability.kind, ProviderKind.ANSWER_SEARCHER)
        self.assertTrue(capability.output.returns_answer)
        self.assertTrue(capability.output.returns_scores)


class BaiduSearcherTests(unittest.TestCase):
    class _FakeResp:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def test_baidu_uses_web_summary_endpoint(self):
        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            return self._FakeResp({
                "request_id": "rid",
                "choices": [{"message": {"content": "answer"}}],
                "references": [{
                    "id": 1,
                    "title": "Doc",
                    "url": "https://example.com",
                    "snippet": "short",
                    "content": "full",
                    "rerank_score": 0.9,
                    "authority_score": 0.7,
                }],
            })

        with mock.patch.object(baidu_searcher, "urlopen_retry", side_effect=fake_urlopen):
            rows = baidu_searcher.search_baidu("q", "key", count=3)

        self.assertIn("/v2/ai_search/web_summary", calls[0])
        self.assertEqual(rows[0]["source"], "baidu_answer")
        self.assertEqual(rows[1]["source"], "baidu")
        self.assertEqual(rows[1]["description"], "short")
        self.assertEqual(rows[1]["authority_score"], 0.7)
        # Reference rows must not carry the full raw payload (output bloat).
        self.assertNotIn("raw_reference", rows[1])

class GeneralSearchDepthTests(unittest.TestCase):
    class _FakeResp:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def test_tavily_want_content_maps_to_raw_content(self):
        captured = []

        def fake_urlopen(req, timeout=0):
            captured.append(json.loads(req.data.decode("utf-8")))
            return self._FakeResp({"results": [], "answer": "a"})

        with mock.patch.object(tavily_searcher, "urlopen_retry", side_effect=fake_urlopen):
            tavily_searcher.search_tavily("q", "key", want_content=True)
            tavily_searcher.search_tavily("q", "key", want_content=False)

        self.assertEqual(captured[0]["search_depth"], "basic")
        self.assertEqual(captured[0]["include_raw_content"], "markdown")
        self.assertEqual(captured[1]["search_depth"], "basic")
        self.assertFalse(captured[1]["include_raw_content"])

    def test_exa_want_content_maps_to_text_contents(self):
        captured = []

        def fake_urlopen(req, timeout=0):
            captured.append(json.loads(req.data.decode("utf-8")))
            return self._FakeResp({"results": [{"title": "Doc", "url": "https://example.com", "highlights": ["h"]}]})

        with mock.patch.object(exa_searcher, "urlopen_retry", side_effect=fake_urlopen):
            rows = exa_searcher.search_exa("q", "key", want_content=False)
            exa_searcher.search_exa("q", "key", want_content=True)

        self.assertEqual(captured[0]["type"], "auto")
        self.assertEqual(captured[1]["type"], "auto")
        self.assertIn("highlights", captured[0]["contents"])
        self.assertIn("text", captured[1]["contents"])
        self.assertEqual(rows[0]["scraped_content"], "h")

    def test_brave_fast_disables_extra_snippets(self):
        urls = []

        def fake_urlopen(req, timeout=0):
            urls.append(req.full_url)
            return self._FakeResp({"web": {"results": []}})

        with mock.patch.object(brave_searcher, "urlopen_retry", side_effect=fake_urlopen):
            brave_searcher.search_brave("q", "key", search_depth="fast")
            brave_searcher.search_brave("q", "key", search_depth="normal")

        self.assertIn("extra_snippets=false", urls[0])
        self.assertIn("extra_snippets=true", urls[1])

    def test_serpapi_fast_forces_google_light(self):
        urls = []

        def fake_urlopen(url, timeout=0):
            urls.append(url)
            return self._FakeResp({"organic_results": []})

        with mock.patch.object(serpapi_searcher, "urlopen_retry", side_effect=fake_urlopen):
            serpapi_searcher.search_serpapi("q", "key", engine="google", search_depth="fast")
            serpapi_searcher.search_serpapi("q", "key", engine="google", search_depth="normal")

        self.assertIn("engine=google_light", urls[0])
        self.assertIn("engine=google", urls[1])

    def test_serpapi_maps_answer_box_to_answer_row(self):
        def fake_urlopen(url, timeout=0):
            return self._FakeResp({
                "answer_box": {"title": "Coffee", "answer": "A brewed drink."},
                "organic_results": [{"title": "Doc", "link": "https://example.com", "snippet": "organic snippet"}],
            })

        with mock.patch.object(serpapi_searcher, "urlopen_retry", side_effect=fake_urlopen):
            rows = serpapi_searcher.search_serpapi("coffee", "key", search_depth="fast")

        self.assertEqual(rows[0]["source"], "serpapi_answer")
        self.assertEqual(rows[0]["answer_type"], "answer_box")
        self.assertIn("A brewed drink", rows[0]["answer"])
        self.assertEqual(rows[1]["description"], "organic snippet")


class DedupTests(unittest.TestCase):
    def test_tracking_params_are_removed_for_consensus(self):
        self.assertEqual(
            _norm_url("http://Example.com/path/?utm_source=x&keep=1#frag"),
            "https://example.com/path?keep=1",
        )

    def test_duplicate_urls_merge_sources_and_richer_fields(self):
        results = [
            {"source": "brave", "title": "A", "url": "https://example.com/a", "description": "short"},
            {
                "source": "tavily",
                "title": "Longer title",
                "url": "https://example.com/a?utm_campaign=x",
                "description": "a longer description",
                "scraped_content": "full text",
            },
        ]
        deduped, raw_counts = deduplicate(results)
        self.assertEqual(raw_counts, {"brave": 1, "tavily": 1})
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["also_from"], ["tavily"])
        self.assertEqual(deduped[0]["title"], "Longer title")
        self.assertEqual(deduped[0]["scraped_content"], "full text")

    def test_split_by_content_keeps_summarized_url_rows_when_skipping(self):
        # An answer row's source uses underscores (``glm_web_answer``) while its
        # matching URL row uses hyphens (``glm-web``); skip_summarized_sources
        # must fold both so the URL row is accepted as content-bearing (not
        # scraped), while a URL-only source (github) still needs scraping.
        rows = [
            {"source": "glm_web_answer", "answer": "synthesized summary"},
            {"source": "glm-web", "title": "A", "url": "https://example.com/a"},
            {"source": "github-repos", "title": "Y", "url": "https://github.com/x/y"},
        ]

        with_content, without_content, _passthrough, _raw = split_by_content(
            rows, skip_summarized_sources=True
        )
        self.assertIn(
            "https://example.com/a", {item.get("url") for item in with_content}
        )
        self.assertIn(
            "https://github.com/x/y", {item.get("url") for item in without_content}
        )

    def test_split_by_content_scrapes_summarized_url_rows_by_default(self):
        # Without skip_summarized_sources (normal level), a summarized source's
        # URL row is still a scrape candidate.
        rows = [
            {"source": "glm_web_answer", "answer": "synthesized summary"},
            {"source": "glm-web", "title": "A", "url": "https://example.com/a"},
        ]

        _with, without_content, _pass, _raw = split_by_content(rows)
        self.assertIn(
            "https://example.com/a", {item.get("url") for item in without_content}
        )


class ScrapePlannerTests(unittest.TestCase):
    def test_prefetched_content_does_not_enter_scrape_items(self):
        rows = [
            {"source": "tavily", "title": "Full", "url": "https://example.com/full", "scraped_content": "x" * 400},
            {"source": "brave", "title": "Needs", "url": "https://example.com/needs", "description": "snippet"},
        ]

        plan = plan_scrapes(rows, keys={}, scrape_top=2, scrape_per_source=6)

        self.assertEqual([item["url"] for item in plan.items_to_scrape], ["https://example.com/needs"])
        self.assertIn("https://example.com/full", {row["url"] for row in plan.content_pool.values()})

    def test_video_results_are_not_scrape_candidates(self):
        rows = [
            {"source": "youtube", "title": "Video", "url": "https://youtube.com/watch?v=1"},
            {"source": "brave", "title": "Doc", "url": "https://example.com/doc"},
        ]

        plan = plan_scrapes(rows, keys={}, scrape_top=5, scrape_per_source=6)

        self.assertEqual([item["url"] for item in plan.items_to_scrape], ["https://example.com/doc"])

    def test_skip_summarized_sources_skips_scraping_sources_with_a_summary(self):
        rows = [
            {"source": "tavily_answer", "answer": "synthesized summary"},
            {"source": "tavily", "title": "A", "url": "https://example.com/a", "description": "snippet"},
            {"source": "github-repos", "title": "Y", "url": "https://github.com/x/y", "description": "snippet"},
        ]

        normal = plan_scrapes(rows, keys={}, scrape_top=5, scrape_per_source=6)
        self.assertEqual(
            {item["url"] for item in normal.items_to_scrape},
            {"https://example.com/a", "https://github.com/x/y"},
        )

        skipped = plan_scrapes(
            rows, keys={}, scrape_top=5, scrape_per_source=6, skip_summarized_sources=True
        )
        # tavily provided a summary -> its URL is not scraped; github (URL-only) is.
        self.assertEqual(
            [item["url"] for item in skipped.items_to_scrape], ["https://github.com/x/y"]
        )

    def test_preferred_sources_and_source_quota_are_applied(self):
        rows = [
            {"source": "exa", "title": "Generic", "url": "https://example.com/generic"},
            {"source": "brave", "title": "Preferred 1", "url": "https://example.com/p1"},
            {"source": "brave", "title": "Preferred 2", "url": "https://example.com/p2"},
        ]

        plan = plan_scrapes(rows, keys={}, scrape_top=5, scrape_per_source=1)

        self.assertEqual(
            [item["url"] for item in plan.items_to_scrape],
            ["https://example.com/p1", "https://example.com/generic"],
        )
        self.assertEqual(plan.source_quota, {"brave": 1, "exa": 1})

    def test_key_pools_rotate_per_url(self):
        rows = [
            {"source": "brave", "title": f"Doc {idx}", "url": f"https://example.com/{idx}"}
            for idx in range(3)
        ]

        with mock.patch("src.state.keys.random.shuffle", side_effect=lambda xs: None):
            plan = plan_scrapes(
                rows,
                keys={"exa": ["e1", "e2"], "tavily": ["t1", "t2"]},
                scrape_top=3,
                scrape_per_source=6,
            )

        self.assertEqual(
            [tuple(item.key_pools.exa) for item in plan.plan_items],
            [("e1", "e2"), ("e2", "e1"), ("e1", "e2")],
        )
        self.assertEqual(
            [item.primary_backend for item in plan.plan_items],
            ["jina", "exa", "tavily"],
        )


class CacheTests(unittest.TestCase):
    def test_json_cache_hit_miss_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = make_scrape_cache_key("https://example.com", ["jina"], {"primary": "jina"})
            disabled = JsonCache(tmp, enabled=False)
            self.assertFalse(disabled.set("scrape", key, {"url": "https://example.com"}))
            self.assertIsNone(disabled.get("scrape", key))

            cache = JsonCache(tmp, ttl_seconds=60, enabled=True)
            self.assertTrue(cache.set("scrape", key, {"url": "https://example.com", "via": "jina"}))
            self.assertEqual(cache.get("scrape", key)["via"], "jina")

    def test_json_cache_ignores_corrupt_and_expired_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonCache(tmp, ttl_seconds=0, enabled=True)
            key = "abc"
            path = cache.path_for("scrape", key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(cache.get("scrape", key))
            path.write_text(json.dumps({"created": 1, "value": {"url": "x"}}), encoding="utf-8")
            self.assertIsNone(cache.get("scrape", key))


class KeyTests(unittest.TestCase):
    def test_pick_key_supports_key_pool_arrays(self):
        with mock.patch("src.state.keys.random.choice", return_value="k2") as choice:
            self.assertEqual(pick_key(["k1", "k2", ""]), "k2")
        choice.assert_called_once_with(["k1", "k2"])

    def test_key_pool_shuffles_non_empty_candidates(self):
        with mock.patch("src.state.keys.random.shuffle") as shuffle:
            pool = key_pool(["k1", "", "k2"])
        self.assertEqual(pool, ["k1", "k2"])
        shuffle.assert_called_once_with(pool)

    def test_load_keys_preserves_json_key_pool_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys_path = Path(tmp) / ".search-keys.json"
            keys_path.write_text(
                json.dumps({"serpapi": ["s1", "s2"], "exa": ["e1", "e2"]}),
                encoding="utf-8",
            )
            with mock.patch("pathlib.Path.home", return_value=Path(tmp)):
                keys = load_keys()

        self.assertEqual(keys["serpapi"], ["s1", "s2"])
        self.assertEqual(keys["exa"], ["e1", "e2"])

    def test_load_keys_ignores_non_object_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys_path = Path(tmp) / ".search-keys.json"
            keys_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            with mock.patch("pathlib.Path.home", return_value=Path(tmp)):
                with mock.patch.dict(os.environ, {"EXA_API_KEY": "env-exa"}, clear=False):
                    keys = load_keys()

        self.assertEqual(keys["exa"], "env-exa")

    def test_twitter_cookies_path_env_overrides_json_twitter_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_path = Path(tmpdir) / ".search-keys.json"
            keys_path.write_text(
                json.dumps({"twitter": {"auth_token": "json-token", "ct0": "json-ct0"}}),
                encoding="utf-8",
            )
            env_path = str(Path(tmpdir) / "cookies.json")
            with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with mock.patch.dict(os.environ, {"TWITTER_COOKIES_PATH": env_path}, clear=False):
                    keys = load_keys()

        self.assertEqual(keys["twitter"], env_path)
        self.assertEqual(keys["twitter_cookies"], env_path)

    def test_jina_env_key_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with mock.patch.dict(os.environ, {"JINA_API_KEY": "jina-env-key"}, clear=False):
                    keys = load_keys()

        self.assertEqual(keys["jina"], "jina-env-key")

    def test_zhihu_access_secret_env_key_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with mock.patch.dict(os.environ, {"ZHIHU_ACCESS_SECRET": "zhihu-secret"}, clear=False):
                    keys = load_keys()

        self.assertEqual(keys["zhihu"], "zhihu-secret")

    def test_jina_config_keys_filter_statically_exhausted_without_shuffle(self):
        cfg = [
            {"key": "active"},
            {"key": "config-dead", "exhausted": True},
            {"key": "second-active"},
        ]

        active = jina_config_keys(cfg)

        # Only the config-level ``exhausted: true`` flag is honored, and the
        # order is preserved (no shuffling — live rotation is owned by the
        # SQLite key manager).
        self.assertEqual(active, ["active", "second-active"])
        self.assertEqual(count_jina_keys(cfg), (2, 3))

    def test_mark_config_exhausted_updates_key_pool_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_path = Path(tmpdir) / ".search-keys.json"
            keys_path.write_text(
                json.dumps({"jina": [{"key": "j1"}, {"key": "j2", "exhausted": False}]}),
                encoding="utf-8",
            )

            with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                changed = _mark_config_exhausted("j2")

            saved = json.loads(keys_path.read_text(encoding="utf-8"))

        self.assertTrue(changed)
        self.assertFalse(saved["jina"][0].get("exhausted", False))
        self.assertTrue(saved["jina"][1]["exhausted"])


if __name__ == "__main__":
    unittest.main()
