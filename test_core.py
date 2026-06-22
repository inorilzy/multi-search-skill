import unittest
import base64
import io
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

import search as search_shim

from scripts.dedup import _norm_url, deduplicate, split_by_content
from scripts.format import format_results, format_scrapes
from scripts.cache import JsonCache, make_scrape_cache_key
from scripts.auth import is_key_retryable_error
from scripts.keys import (
    _JINA_EXHAUSTED,
    count_jina_keys,
    get_active_jina_keys,
    key_pool,
    load_keys,
    mark_jina_exhausted_persistent,
    pick_key,
)
from scripts.main import _has_preferred_scrape_source, available_routes, main, resolve_route
from scripts.capabilities import PROVIDER_CAPABILITIES, ProviderKind, ScrapePolicy, capability_table_rows
from scripts.models import ProviderError, ScrapeResult, SearchResult
from scripts.search_runner import ROUTE_PROFILES, ProviderSpec, SearchRunner, SearchRunnerConfig, call_optional_timeout
from scripts.scrape_planner import plan_scrapes
from scripts.scrapers.registry import SCRAPER_REGISTRY, ScrapeContext, ScraperSpec, call_scraper
from scripts import scrape
from scripts.scrape import _resolve_scrape_policy
from scripts.secrets import scrub_secrets
from scripts.searchers.brave import search_brave
from scripts.searchers.bilibili import search_bilibili
from scripts.searchers.exa import search_exa
from scripts.searchers.firecrawl import (
    REDDIT_DOMAINS,
    V2EX_DOMAINS,
    ZHIHU_DOMAINS,
    search_firecrawl,
    search_reddit,
    search_v2ex,
    search_zhihu as search_zhihu_firecrawl,
)
from scripts.searchers.github import search_github_repos
from scripts.searchers import deepseek_web as deepseek_source
from scripts.searchers.hackernews import search_hackernews
from scripts.searchers.serpapi import search_serpapi
from scripts.searchers.stackoverflow import search_stackoverflow
from scripts.searchers.tavily import search_tavily
from scripts.searchers import twitter as twitter_source
from scripts.searchers.youtube import search_youtube
from scripts.searchers.zhihu import search_zhihu
from scripts.scrapers import reddit as reddit_scraper


class _FakeResponse:
    def __init__(self, payload: dict, headers: dict | None = None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _BytesResponse:
    def __init__(self, payload: bytes, headers: dict | None = None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def _headers(req) -> dict:
    return {name.lower(): value for name, value in req.header_items()}


def _json_body(req) -> dict:
    return json.loads(req.data.decode("utf-8"))


def _query(url: str) -> dict:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


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


class SearchShimTests(unittest.TestCase):
    def test_scrape_url_legacy_alias_is_exported(self):
        self.assertIs(search_shim.scrape_url, search_shim.scrape_url_smart)
        self.assertIn("scrape_url", search_shim.__all__)

    def test_new_architecture_symbols_are_exported(self):
        self.assertIs(search_shim.SearchResult, SearchResult)
        self.assertIs(search_shim.SearchRunner, SearchRunner)
        self.assertIs(search_shim.SCRAPER_REGISTRY, SCRAPER_REGISTRY)
        self.assertIn("plan_scrapes", search_shim.__all__)

    def test_capability_symbols_are_exported(self):
        self.assertIs(search_shim.PROVIDER_CAPABILITIES, PROVIDER_CAPABILITIES)
        self.assertEqual(search_shim.get_capability("brave").public_name, "brave")
        self.assertIn("capability_table_rows", search_shim.__all__)


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
        row = {"url": "https://example.com", "title": "Doc", "markdown": "body", "length": 99, "via": "jina", "cache": "hit"}

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
    def test_named_routes_resolve_to_expected_profiles(self):
        self.assertEqual(resolve_route("default"), {
            "brave", "tavily", "exa", "firecrawl", "serpapi",
            "github_repos", "twitter",
        })
        self.assertEqual(resolve_route("lite"), {"tavily", "exa"})
        self.assertEqual(resolve_route("discussion"), {"twitter"})
        self.assertEqual(resolve_route("video"), {"youtube", "bilibili"})
        self.assertEqual(resolve_route("github"), {"github_repos"})
        self.assertEqual(resolve_route("firecrawl"), {"firecrawl"})
        self.assertEqual(resolve_route("youtube"), {"youtube"})
        self.assertEqual(resolve_route("bilibili"), {"bilibili"})
        self.assertEqual(resolve_route("v2ex"), {"v2ex"})
        self.assertEqual(resolve_route("zhihu"), {"zhihu"})
        self.assertEqual(resolve_route("reddit"), {"reddit"})
        self.assertEqual(resolve_route("hackernews"), {"hackernews"})
        self.assertEqual(resolve_route("stackoverflow"), {"stackoverflow"})
        self.assertEqual(resolve_route("glm-web"), {"glm_web"})
        self.assertEqual(resolve_route("glm_web"), {"glm_web"})
        self.assertEqual(resolve_route("deepseek-web"), {"deepseek_web"})
        self.assertEqual(resolve_route("deepseek_web"), {"deepseek_web"})

    def test_removed_aliases_do_not_resolve(self):
        self.assertEqual(resolve_route("all"), set())
        self.assertEqual(resolve_route("balanced"), set())
        self.assertEqual(resolve_route("social+community"), set())
        self.assertEqual(resolve_route("community"), set())
        self.assertEqual(resolve_route("repos"), set())
        self.assertEqual(resolve_route("google"), set())
        self.assertEqual(resolve_route("x"), set())
        self.assertEqual(resolve_route("hac" + "knews"), set())
        self.assertEqual(resolve_route("h" + "n"), set())
        self.assertEqual(resolve_route("s" + "o"), set())

    def test_unknown_route_resolves_empty_for_validation(self):
        self.assertEqual(resolve_route("not-a-route"), set())
        self.assertIn("default", available_routes())
        self.assertIn("lite", available_routes())
        self.assertIn("discussion", available_routes())
        self.assertIn("video", available_routes())
        self.assertIn("youtube", available_routes())
        self.assertIn("bilibili", available_routes())
        self.assertIn("v2ex", available_routes())
        self.assertIn("zhihu", available_routes())
        self.assertIn("reddit", available_routes())
        self.assertIn("hackernews", available_routes())
        self.assertIn("stackoverflow", available_routes())
        self.assertIn("glm-web", available_routes())
        self.assertIn("deepseek-web", available_routes())


class CapabilityTests(unittest.TestCase):
    def test_capabilities_cover_all_route_sources(self):
        route_sources = set().union(*ROUTE_PROFILES.values())

        self.assertFalse(route_sources - set(PROVIDER_CAPABILITIES))

    def test_capabilities_cover_all_scraper_backends(self):
        for name in SCRAPER_REGISTRY:
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


class SearchRunnerTests(unittest.TestCase):
    def test_keyed_provider_success_and_dataclass_rows(self):
        cfg = SearchRunnerConfig(
            route="custom",
            counts={"custom": 1},
            timeout=5,
            serpapi_engine="google_light",
            keys={"custom": "key"},
        )
        providers = {
            "custom": ProviderSpec(
                name="custom",
                public_name="custom",
                key_name="custom",
                call=lambda q, cfg, ctx, key: [SearchResult(source="custom", title=q, url="https://example.com")],
            )
        }
        runner = SearchRunner(cfg, providers, route_resolver=lambda route, lite=False: {"custom"})

        rows = runner.run("query")

        self.assertEqual(rows[0]["source"], "custom")
        self.assertEqual(rows[0]["title"], "query")

    def test_missing_key_reports_public_source_name(self):
        cfg = SearchRunnerConfig("custom", {}, 5, "google_light", {})
        providers = {
            "custom": ProviderSpec(
                name="custom",
                public_name="public-source",
                key_name="custom",
                missing_message="missing CUSTOM_KEY",
                call=lambda *args: [],
            )
        }
        runner = SearchRunner(cfg, providers, route_resolver=lambda route, lite=False: {"custom"})

        rows = runner.run("query")

        self.assertEqual(rows, [{"source": "public-source", "error": "skipped: missing CUSTOM_KEY"}])

    def test_key_pool_falls_back_from_retryable_error(self):
        calls = []
        cfg = SearchRunnerConfig("custom", {}, 5, "google_light", {"custom": ["bad", "good"]})

        def call(q, cfg, ctx, key):
            calls.append(key)
            if key == "bad":
                return [{"source": "custom", "error": "HTTP 429 quota exceeded"}]
            return [{"source": "custom", "title": "ok", "url": "https://example.com"}]

        providers = {"custom": ProviderSpec("custom", "custom", call, key_name="custom")}
        runner = SearchRunner(cfg, providers, route_resolver=lambda route, lite=False: {"custom"})
        with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
            rows = runner.run("query")

        self.assertEqual(calls, ["bad", "good"])
        self.assertEqual(rows[0]["title"], "ok")

    def test_timeout_returns_without_waiting_for_slow_provider(self):
        cfg = SearchRunnerConfig("custom", {}, 1, "google_light", {})

        def slow(q, cfg, ctx, key):
            time.sleep(3)
            return [{"source": "public-source", "title": "late", "url": "https://late.example"}]

        providers = {"custom": ProviderSpec("custom", "public-source", slow)}
        runner = SearchRunner(cfg, providers, route_resolver=lambda route, lite=False: {"custom"})
        started = time.monotonic()
        rows = runner.run("query")

        self.assertLess(time.monotonic() - started, 2.2)
        self.assertEqual(rows, [{"source": "public-source", "error": "timeout after 1s"}])

    def test_retry_helper_recognizes_quota_and_rate_errors(self):
        for message in ("HTTP 401", "HTTP 403", "HTTP 429", "quota exceeded", "rate limit", "credits exhausted"):
            self.assertTrue(is_key_retryable_error([{"source": "x", "error": message}]))
        self.assertFalse(is_key_retryable_error([{"source": "x", "error": "DNS failed"}]))


class DeepSeekWebTests(unittest.TestCase):
    def test_deepseek_hash_v1_matches_reference_vectors(self):
        vectors = {
            b"": "e594808bc5b7151ac160c6d39a02e0a8e261ed588578403099e3561dc40c26b3",
            b"testsalt_1700000000_42": "d4a2ea58c89e40887c933484868380c6f803eaa8dc53a3b9df8e431b921a4f09",
            b"testsalt_1700000000_100000": "abea2f35796b65486e9be1b36f7878c66cab021e96faa473fdf4decd31f9ba30",
            b"abc123salt_1700000000_12345": "74b3b7452745b70e85eb32ee7f0a9ec0381d42dd5137b695da915e104fc390e1",
        }

        for raw, expected in vectors.items():
            self.assertEqual(deepseek_source._deepseek_hash_v1(raw).hex(), expected)

    def test_deepseek_pow_header_contains_answer(self):
        target = deepseek_source._deepseek_hash_v1(b"testsalt_1700000000_42").hex()
        header = deepseek_source._solve_pow({
            "algorithm": "DeepSeekHashV1",
            "challenge": target,
            "salt": "testsalt",
            "expire_at": 1700000000,
            "difficulty": 1000,
            "signature": "sig",
            "target_path": "/api/v0/chat/completion",
        })

        payload = json.loads(base64.b64decode(header).decode("utf-8"))
        self.assertEqual(payload["answer"], 42)
        self.assertEqual(payload["target_path"], "/api/v0/chat/completion")

    def test_deepseek_auth_export_parses_token_and_cookie(self):
        export = {
            "cookies": [
                {"name": "ds_session_id", "value": "sid"},
                {"name": "smidV2", "value": "smid"},
            ],
            "localStorage": {"userToken": json.dumps({"value": "tok"})},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(export, f)
            path = f.name
        try:
            token, cookie = deepseek_source._resolve_auth(export_path=path)
        finally:
            os.unlink(path)

        self.assertEqual(token, "tok")
        self.assertIn("ds_session_id=sid", cookie)
        self.assertIn("smidV2=smid", cookie)

    def test_deepseek_sse_parser_extracts_answer_and_results(self):
        payload = "\n".join([
            "event: update_session",
            'data: {"p":"response/content","v":"答案"}',
            'data: {"p":"response/search/results","v":[{"title":"Doc","url":"https://example.com","snippet":"body","cite_index":1}]}',
            'data: {"v":{"response":{"message_id":"msg1","content":"补充"}}}',
        ]).encode("utf-8")

        answer, results, message_id = deepseek_source._parse_sse(payload, max_results=10)

        self.assertEqual(answer, "答案补充")
        self.assertEqual(message_id, "msg1")
        self.assertEqual(results[0]["source"], "deepseek-web")
        self.assertEqual(results[0]["url"], "https://example.com")


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

    def test_preferred_sources_and_source_quota_are_applied(self):
        rows = [
            {"source": "exa", "title": "Generic", "url": "https://example.com/generic"},
            {"source": "brave", "title": "Preferred 1", "url": "https://example.com/p1"},
            {"source": "brave", "title": "Preferred 2", "url": "https://example.com/p2"},
        ]

        plan = plan_scrapes(rows, keys={}, scrape_top=5, scrape_per_source=1)

        self.assertEqual([item["url"] for item in plan.items_to_scrape], ["https://example.com/p1", "https://example.com/generic"])
        self.assertEqual(plan.source_quota, {"brave": 1, "exa": 1})

    def test_key_pools_rotate_per_url(self):
        rows = [
            {"source": "brave", "title": f"Doc {idx}", "url": f"https://example.com/{idx}"}
            for idx in range(3)
        ]

        with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
            plan = plan_scrapes(
                rows,
                keys={"exa": ["e1", "e2"], "tavily": ["t1", "t2"]},
                scrape_top=3,
                scrape_per_source=6,
            )

        self.assertEqual([tuple(item.key_pools.exa) for item in plan.plan_items], [("e1", "e2"), ("e2", "e1"), ("e1", "e2")])
        self.assertEqual([item.primary_backend for item in plan.plan_items], ["jina", "exa", "tavily"])


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


class ScraperRegistryTests(unittest.TestCase):
    def test_registry_contains_standard_backends(self):
        self.assertIn("jina", SCRAPER_REGISTRY)
        self.assertIn("exa", SCRAPER_REGISTRY)
        self.assertIn("tavily", SCRAPER_REGISTRY)
        self.assertIn("firecrawl", SCRAPER_REGISTRY)
        self.assertIn("reddit", SCRAPER_REGISTRY)

    def test_adapter_accepts_dataclass_return(self):
        spec = ScraperSpec(
            name="custom",
            public_name="custom",
            call=lambda url, ctx, key: ScrapeResult(url=url, markdown="body", via=ctx.backend),
        )

        row = call_scraper(spec, "https://example.com", ScrapeContext(backend="custom"))

        self.assertEqual(row["url"], "https://example.com")
        self.assertEqual(row["via"], "custom")

    def test_adapter_accepts_dict_return(self):
        spec = ScraperSpec(
            name="custom",
            public_name="custom",
            call=lambda url, ctx, key: {"url": url, "markdown": "body", "via": "custom"},
        )

        row = call_scraper(spec, "https://example.com", ScrapeContext(backend="custom"))

        self.assertEqual(row["markdown"], "body")


class ScrapeRoutingTests(unittest.TestCase):
    def setUp(self):
        scrape._reset_jina_anonymous_rate_limit()

    def tearDown(self):
        scrape._reset_jina_anonymous_rate_limit()

    def test_default_scrape_policy_keeps_markdown_backends(self):
        policy = _resolve_scrape_policy("https://example.com/doc")

        self.assertEqual(policy["name"], "default")
        self.assertEqual(policy["backends"], ["jina", "exa", "tavily", "firecrawl"])
        self.assertEqual(policy["jina"], {})
        self.assertEqual(policy["tavily"], {})
        self.assertIsNone(policy["blocked"])

    def test_zhihu_scrape_policy_overrides_only_needed_formats(self):
        policy = _resolve_scrape_policy("https://zhuanlan.zhihu.com/p/1999526177337992365")

        self.assertEqual(policy["name"], "zhihu")
        self.assertEqual(policy["backends"], ["jina", "exa", "tavily", "firecrawl"])
        self.assertEqual(policy["jina"], {"respond_with": "text"})
        self.assertEqual(policy["tavily"], {"content_format": "text"})
        self.assertIs(policy["blocked"], scrape.is_zhihu_blocked_text)

    def test_reddit_scrape_policy_prefers_remote_scrapers_before_local_fallback(self):
        policy = _resolve_scrape_policy("https://www.reddit.com/r/OpenAI/comments/abc/example/")

        self.assertEqual(policy["name"], "reddit")
        self.assertEqual(policy["backends"], ["jina", "tavily", "exa", "firecrawl", "reddit"])
        self.assertEqual(policy["jina"], {})
        self.assertEqual(policy["tavily"], {})
        self.assertIs(policy["blocked"], scrape.is_reddit_blocked_text)

    def test_old_reddit_scrape_policy_prefers_tavily_before_jina(self):
        policy = _resolve_scrape_policy("https://old.reddit.com/r/OpenAI/comments/abc/example/")

        self.assertEqual(policy["name"], "old-reddit")
        self.assertEqual(policy["backends"], ["tavily", "jina", "exa", "firecrawl", "reddit"])
        self.assertEqual(policy["jina"], {})
        self.assertEqual(policy["tavily"], {})
        self.assertIs(policy["blocked"], scrape.is_reddit_blocked_text)

    def test_scrape_rewrites_github_repo_root_to_raw_readme(self):
        """GitHub repo root URL should be rewritten to raw README before fetching,
        but the result should preserve the original URL."""
        called_with = []
        originals = (scrape.scrape_url_jina, scrape.scrape_url_tavily, scrape.scrape_url_exa)
        def capture_tavily(url, *a, **kw):
            called_with.append(url)
            return {"url": url, "title": "README", "markdown": "# Hello", "length": 8, "via": "tavily"}
        try:
            scrape.scrape_url_jina = lambda *a, **kw: None
            scrape.scrape_url_tavily = capture_tavily
            scrape.scrape_url_exa = lambda *a, **kw: None
            result = scrape.scrape_url_smart(
                "https://github.com/fastapi/fastapi",
                exa_key="exa", tavily_key="tavily", primary="tavily",
            )
        finally:
            scrape.scrape_url_jina, scrape.scrape_url_tavily, scrape.scrape_url_exa = originals
        self.assertEqual(called_with, ["https://raw.githubusercontent.com/fastapi/fastapi/HEAD/README.md"])
        self.assertEqual(result["url"], "https://github.com/fastapi/fastapi")

    def test_short_tavily_content_goes_to_without_content(self):
        """Short scraped_content (< 300 chars) should not satisfy 'has content'
        for web sources, so the URL remains eligible for richer scraping."""
        short = "x" * 100
        with_content, without_content, passthrough, raw_counts = split_by_content([
            {"source": "tavily", "title": "doc", "url": "https://example.com/short", "scraped_content": short},
        ])
        self.assertEqual([item["source"] for item in with_content], [])
        self.assertEqual([item["source"] for item in without_content], ["tavily"])

    def test_long_tavily_content_stays_in_with_content(self):
        """Long scraped_content (>= 300 chars) is substantial; stays in with_content."""
        long = "x" * 400
        with_content, without_content, _, _ = split_by_content([
            {"source": "tavily", "title": "doc", "url": "https://example.com/long", "scraped_content": long},
        ])
        self.assertEqual([item["source"] for item in with_content], ["tavily"])
        self.assertEqual(without_content, [])

    def test_twitter_short_content_stays_in_with_content(self):
        """Twitter discussion content is independent; even short text counts."""
        short = "x" * 50
        with_content, without_content, _, _ = split_by_content([
            {"source": "twitter", "title": "tweet", "url": "https://x.com/a/status/1", "scraped_content": short},
        ])
        self.assertEqual([item["source"] for item in with_content], ["twitter"])
        self.assertEqual(without_content, [])

    def test_preferred_scrape_source_checks_also_from(self):
        item = {"source": "exa", "also_from": ["brave"]}

        self.assertTrue(_has_preferred_scrape_source(item))
        self.assertFalse(_has_preferred_scrape_source({"source": "exa", "also_from": ["tavily"]}))

    def test_scrape_respects_primary_backend_before_fallbacks(self):
        calls = []
        originals = (
            scrape.scrape_url_jina,
            scrape.scrape_url_tavily,
            scrape.scrape_url_exa,
        )

        def fail(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                return {"url": "https://example.com", "error": f"{name} failed"}
            return _inner

        try:
            scrape.scrape_url_jina = fail("jina")
            scrape.scrape_url_tavily = fail("tavily")
            scrape.scrape_url_exa = fail("exa")
            result = scrape.scrape_url_smart(
                "https://example.com",
                exa_key="exa-key",
                tavily_key="tavily-key",
                primary="tavily",
            )
        finally:
            (
                scrape.scrape_url_jina,
                scrape.scrape_url_tavily,
                scrape.scrape_url_exa,
            ) = originals

        self.assertEqual(calls, ["tavily", "jina", "exa"])
        self.assertIn("exa failed", result["error"])

    def test_scrape_url_smart_accepts_legacy_positional_signature(self):
        calls = []
        originals = (
            scrape.scrape_url_jina,
            scrape.scrape_url_tavily,
            scrape.scrape_url_exa,
        )

        def capture_tavily(url, api_key, timeout=25):
            calls.append(("tavily", api_key, timeout))
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "tavily"}

        try:
            scrape.scrape_url_jina = lambda *a, **kw: None
            scrape.scrape_url_tavily = capture_tavily
            scrape.scrape_url_exa = lambda *a, **kw: None
            result = scrape.scrape_url_smart(
                "https://example.com/doc",
                "legacy-firecrawl-key",
                17,
                "exa-key",
                "tavily-key",
                "tavily",
            )
        finally:
            (
                scrape.scrape_url_jina,
                scrape.scrape_url_tavily,
                scrape.scrape_url_exa,
            ) = originals

        self.assertEqual(calls, [("tavily", "tavily-key", 17)])
        self.assertEqual(result["via"], "tavily")

    def test_scrape_default_fallback_order_prefers_exa_before_tavily(self):
        calls = []
        originals = (
            scrape.scrape_url_jina,
            scrape.scrape_url_tavily,
            scrape.scrape_url_exa,
        )

        def fail(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                return {"url": "https://example.com", "error": f"{name} failed"}
            return _inner

        try:
            scrape.scrape_url_jina = fail("jina")
            scrape.scrape_url_tavily = fail("tavily")
            scrape.scrape_url_exa = fail("exa")
            result = scrape.scrape_url_smart(
                "https://example.com",
                exa_key="exa-key",
                tavily_key="tavily-key",
            )
        finally:
            (
                scrape.scrape_url_jina,
                scrape.scrape_url_tavily,
                scrape.scrape_url_exa,
            ) = originals

        self.assertEqual(calls, ["jina", "exa", "tavily"])
        self.assertIn("tavily failed", result["error"])

    def test_scrape_url_smart_uses_remote_reddit_scraper_before_local_fallback(self):
        calls = []
        originals = (scrape.scrape_url_reddit, scrape.scrape_url_jina)
        url = "https://www.reddit.com/r/OpenAI/comments/abc/example/"

        def fake_reddit(scrape_url, timeout=30):
            calls.append(("reddit", scrape_url))
            return {"url": scrape_url, "title": "Post", "markdown": "reddit body", "length": 11, "via": "reddit-old"}

        def fake_jina(*args, **kwargs):
            calls.append(("jina", args[0]))
            return {"url": args[0], "title": "Post", "markdown": "remote body", "length": 11, "via": "jina"}

        try:
            scrape.scrape_url_reddit = fake_reddit
            scrape.scrape_url_jina = fake_jina
            result = scrape.scrape_url_smart(url, primary="jina")
        finally:
            scrape.scrape_url_reddit, scrape.scrape_url_jina = originals

        self.assertEqual(calls, [("jina", url)])
        self.assertEqual(result["via"], "jina")

    def test_scrape_url_smart_falls_back_to_local_reddit_after_blocked_remote(self):
        calls = []
        originals = (scrape.scrape_url_reddit, scrape.scrape_url_jina)
        url = "https://www.reddit.com/r/OpenAI/comments/abc/example/"

        def fake_jina(*args, **kwargs):
            calls.append(("jina", args[0]))
            return {
                "url": args[0],
                "title": "Blocked",
                "markdown": "You've been blocked by network security.",
                "length": 39,
                "via": "jina",
            }

        def fake_reddit(scrape_url, timeout=30):
            calls.append(("reddit", scrape_url))
            return {"url": scrape_url, "title": "Post", "markdown": "reddit body", "length": 11, "via": "reddit-old"}

        try:
            scrape.scrape_url_jina = fake_jina
            scrape.scrape_url_reddit = fake_reddit
            result = scrape.scrape_url_smart(url, primary="jina")
        finally:
            scrape.scrape_url_reddit, scrape.scrape_url_jina = originals

        self.assertEqual(calls, [("jina", url), ("reddit", url)])
        self.assertEqual(result["via"], "reddit-old")

    def test_scrape_url_smart_does_not_add_reddit_backend_for_other_urls(self):
        calls = []
        originals = (scrape.scrape_url_reddit, scrape.scrape_url_jina)

        def fake_reddit(*args, **kwargs):
            calls.append("reddit")
            return {"url": args[0], "error": "Reddit should not run"}

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            calls.append("jina")
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "jina"}

        try:
            scrape.scrape_url_reddit = fake_reddit
            scrape.scrape_url_jina = fake_jina
            result = scrape.scrape_url_smart("https://example.com/doc", primary="jina", backends=("jina",))
        finally:
            scrape.scrape_url_reddit, scrape.scrape_url_jina = originals

        self.assertEqual(calls, ["jina"])
        self.assertEqual(result["via"], "jina")

    def test_scrape_url_smart_rejects_reddit_block_page_from_fallback(self):
        originals = (scrape.scrape_url_reddit, scrape.scrape_url_jina)

        def fake_reddit(url, timeout=30):
            return {"url": url, "error": "Reddit: blocked by Reddit network policy"}

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            return {
                "url": url,
                "title": "Blocked",
                "markdown": "You've been blocked by network security. To continue, log in to your Reddit account.",
                "length": 88,
                "via": "jina",
            }

        try:
            scrape.scrape_url_reddit = fake_reddit
            scrape.scrape_url_jina = fake_jina
            result = scrape.scrape_url_smart(
                "https://www.reddit.com/r/OpenAI/comments/abc/example/",
                primary="jina",
                backends=("jina",),
            )
        finally:
            scrape.scrape_url_reddit, scrape.scrape_url_jina = originals

        self.assertIn("Reddit blocked content fetch", result["error"])
        self.assertNotIn("markdown", result)

    def test_scrape_url_smart_rejects_zhihu_block_page_from_fallback(self):
        original = scrape.scrape_url_jina

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            return {
                "url": url,
                "title": "Blocked",
                "markdown": (
                    "# 你似乎来到了没有知识存在的荒原 - 知乎\n\n"
                    "1 秒后自动跳转至知乎首页\n\n"
                    "打开知乎App\n\n登录/注册\n\n验证码登录"
                ),
                "length": 72,
                "via": "jina",
            }

        try:
            scrape.scrape_url_jina = fake_jina
            result = scrape.scrape_url_smart(
                "https://www.zhihu.com/question/497594623",
                primary="jina",
                backends=("jina",),
            )
        finally:
            scrape.scrape_url_jina = original

        self.assertIn("Zhihu blocked content fetch", result["error"])
        self.assertNotIn("markdown", result)

    def test_zhihu_jina_uses_text_browser_options_and_keeps_real_content(self):
        original = scrape.scrape_url_jina
        calls = []

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            calls.append(kwargs)
            return {
                "url": url,
                "title": "Zhihu article",
                "markdown": (
                    "登录/注册\n"
                    "452 人赞同了该文章\n\n"
                    "对于大模型应用开发工程师而言，学习 AI Agent 不是一个可选项。"
                ),
                "length": 80,
                "via": "jina",
            }

        try:
            scrape.scrape_url_jina = fake_jina
            result = scrape.scrape_url_smart(
                "https://zhuanlan.zhihu.com/p/1999526177337992365",
                primary="jina",
                backends=("jina",),
            )
        finally:
            scrape.scrape_url_jina = original

        self.assertNotIn("error", result)
        self.assertEqual(calls[0]["respond_with"], "text")
        self.assertNotIn("extra_headers", calls[0])
        self.assertIn("对于大模型应用开发工程师而言", result["markdown"])

    def test_zhihu_tavily_uses_text_format_and_keeps_real_content(self):
        original = scrape.scrape_url_tavily
        calls = []

        def fake_tavily(url, api_key, timeout=25, content_format="markdown"):
            calls.append(content_format)
            body = "对于大模型应用开发工程师而言，学习 AI Agent 不是一个可选项。" * 30
            return {
                "url": url,
                "title": "Zhihu article",
                "markdown": (
                    "登录/注册\n打开知乎App\n验证码登录\n其他方式登录\n"
                    "452 人赞同了该文章\n\n"
                    f"{body}"
                ),
                "length": 120,
                "via": "tavily",
            }

        try:
            scrape.scrape_url_tavily = fake_tavily
            result = scrape.scrape_url_smart(
                "https://zhuanlan.zhihu.com/p/1999526177337992365",
                tavily_key="tvly-key",
                primary="tavily",
                backends=("tavily",),
            )
        finally:
            scrape.scrape_url_tavily = original

        self.assertNotIn("error", result)
        self.assertEqual(calls, ["text"])
        self.assertIn("452 人赞同", result["markdown"])

    def test_reddit_scraper_extracts_old_reddit_post_and_comments(self):
        seen_urls = []
        html = b"""
        <html><head><title>Example : subreddit</title></head><body>
          <div class="thing link">
            <a class="title" href="/r/OpenAI/comments/abc/example/">Example post title</a>
            <span class="score unvoted">42 points</span>
            <a class="author">poster</a>
            <a class="comments">7 comments</a>
            <div class="usertext-body"><div class="md"><p>Post body from old reddit.</p></div></div>
          </div>
          <div class="comment">
            <a class="author">alice</a>
            <span class="score unvoted">9 points</span>
            <div class="usertext-body"><div class="md"><p>First useful comment.</p></div></div>
          </div>
          <div class="comment">
            <a class="author">bob</a>
            <span class="score unvoted">3 points</span>
            <div class="usertext-body"><div class="md"><p>Second useful comment.</p></div></div>
          </div>
        </body></html>
        """

        def fake_urlopen(req, timeout=30):
            seen_urls.append(req.full_url)
            return _BytesResponse(html)

        with mock.patch("scripts.scrapers.reddit.urlopen_retry", side_effect=fake_urlopen):
            result = reddit_scraper.scrape_url_reddit(
                "https://www.reddit.com/r/OpenAI/comments/abc/example/",
            )

        self.assertEqual(seen_urls, ["https://old.reddit.com/r/OpenAI/comments/abc/example/"])
        self.assertEqual(result["via"], "reddit-old")
        self.assertIn("Example post title", result["markdown"])
        self.assertIn("Post body from old reddit.", result["markdown"])
        self.assertIn("First useful comment.", result["markdown"])

    def test_scrape_url_smart_falls_back_after_exa_empty_content(self):
        calls = []
        originals = (scrape.scrape_url_exa, scrape.scrape_url_tavily)

        def fake_exa(url, api_key, timeout=25):
            calls.append("exa")
            return {"url": url, "error": "Exa: empty content"}

        def fake_tavily(url, api_key, timeout=25):
            calls.append("tavily")
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "tavily"}

        try:
            scrape.scrape_url_exa = fake_exa
            scrape.scrape_url_tavily = fake_tavily
            result = scrape.scrape_url_smart(
                "https://example.com",
                exa_key="exa-key",
                tavily_key="tavily-key",
                primary="exa",
                backends=("exa", "tavily"),
            )
        finally:
            scrape.scrape_url_exa, scrape.scrape_url_tavily = originals

        self.assertEqual(calls, ["exa", "tavily"])
        self.assertEqual(result["via"], "tavily")

    def test_scrape_url_smart_rotates_and_soft_deletes_exhausted_jina_keys(self):
        _JINA_EXHAUSTED.clear()
        calls = []
        original = scrape.scrape_url_jina

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            calls.append((api_key, skip_anonymous))
            if not api_key:
                return {"url": url, "error": "Jina: HTTP 429", "rate_limited": True}
            if api_key == "jina-k1":
                return {
                    "url": url,
                    "error": "Jina: quota exhausted",
                    "rate_limited": True,
                    "key_exhausted": True,
                    "exhausted": True,
                }
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "jina"}

        with tempfile.TemporaryDirectory() as tmpdir:
            keys_path = Path(tmpdir) / ".search-keys.json"
            keys_path.write_text(
                json.dumps({"jina": [{"key": "jina-k1"}, {"key": "jina-k2"}]}),
                encoding="utf-8",
            )
            try:
                scrape.scrape_url_jina = fake_jina
                with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                    result = scrape.scrape_url_smart(
                        "https://example.com/doc",
                        primary="jina",
                        backends=("jina",),
                        jina_keys=["jina-k1", "jina-k2"],
                    )
            finally:
                scrape.scrape_url_jina = original

            saved = json.loads(keys_path.read_text(encoding="utf-8"))

        self.assertEqual(result["via"], "jina")
        self.assertEqual(calls, [("", False), ("jina-k1", True), ("jina-k2", True)])
        self.assertIn("jina-k1", _JINA_EXHAUSTED)
        self.assertTrue(saved["jina"][0]["exhausted"])
        self.assertFalse(saved["jina"][1].get("exhausted", False))
        _JINA_EXHAUSTED.clear()

    def test_scrape_url_smart_rotates_jina_key_on_temporary_rate_limit_without_soft_delete(self):
        _JINA_EXHAUSTED.clear()
        calls = []
        original = scrape.scrape_url_jina

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            calls.append((api_key, skip_anonymous))
            if not api_key:
                return {"url": url, "error": "Jina: HTTP 429", "rate_limited": True}
            if api_key == "jina-k1":
                return {
                    "url": url,
                    "error": "Jina: HTTP 429: Per key RPM exceeded",
                    "rate_limited": True,
                }
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "jina"}

        with tempfile.TemporaryDirectory() as tmpdir:
            keys_path = Path(tmpdir) / ".search-keys.json"
            keys_path.write_text(
                json.dumps({"jina": [{"key": "jina-k1"}, {"key": "jina-k2"}]}),
                encoding="utf-8",
            )
            try:
                scrape.scrape_url_jina = fake_jina
                with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                    result = scrape.scrape_url_smart(
                        "https://example.com/doc",
                        primary="jina",
                        backends=("jina",),
                        jina_keys=["jina-k1", "jina-k2"],
                    )
            finally:
                scrape.scrape_url_jina = original

            saved = json.loads(keys_path.read_text(encoding="utf-8"))

        self.assertEqual(result["via"], "jina")
        self.assertEqual(calls, [("", False), ("jina-k1", True), ("jina-k2", True)])
        self.assertNotIn("jina-k1", _JINA_EXHAUSTED)
        self.assertFalse(saved["jina"][0].get("exhausted", False))
        self.assertFalse(saved["jina"][1].get("exhausted", False))
        _JINA_EXHAUSTED.clear()

    def test_scrape_url_smart_falls_back_after_jina_key_rate_limits_without_soft_delete(self):
        _JINA_EXHAUSTED.clear()
        calls = []
        originals = (scrape.scrape_url_jina, scrape.scrape_url_exa, scrape.scrape_url_tavily)

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            calls.append(("jina", api_key, skip_anonymous))
            return {"url": url, "error": "Jina: HTTP 429: Per key RPM exceeded", "rate_limited": True}

        def fake_exa(url, api_key, timeout=25):
            calls.append(("exa", api_key, False))
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "exa"}

        try:
            scrape.scrape_url_jina = fake_jina
            scrape.scrape_url_exa = fake_exa
            scrape.scrape_url_tavily = lambda *a, **kw: None
            with mock.patch("scripts.scrape.mark_jina_exhausted_persistent") as persistent:
                result = scrape.scrape_url_smart(
                    "https://example.com/doc",
                    primary="jina",
                    jina_keys=["jina-k1"],
                    exa_key="exa-key",
                    tavily_key="tavily-key",
                )
        finally:
            scrape.scrape_url_jina, scrape.scrape_url_exa, scrape.scrape_url_tavily = originals

        self.assertEqual(result["via"], "exa")
        self.assertEqual(calls, [("jina", "", False), ("jina", "jina-k1", True), ("exa", "exa-key", False)])
        persistent.assert_not_called()
        self.assertNotIn("jina-k1", _JINA_EXHAUSTED)
        _JINA_EXHAUSTED.clear()

    def test_jina_anonymous_rate_limit_cooldown_skips_anonymous_for_next_url(self):
        calls = []
        original = scrape.scrape_url_jina

        def fake_jina(url, api_key="", timeout=25, skip_anonymous=False, **kwargs):
            calls.append((api_key, skip_anonymous))
            if not api_key:
                return {"url": url, "error": "Jina: HTTP 429", "rate_limited": True}
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "jina"}

        try:
            scrape.scrape_url_jina = fake_jina
            first = scrape.scrape_url_smart(
                "https://example.com/one",
                primary="jina",
                backends=("jina",),
                jina_keys=["jina-k1"],
            )
            second = scrape.scrape_url_smart(
                "https://example.com/two",
                primary="jina",
                backends=("jina",),
                jina_keys=["jina-k1"],
            )
        finally:
            scrape.scrape_url_jina = original

        self.assertEqual(first["via"], "jina")
        self.assertEqual(second["via"], "jina")
        self.assertEqual(calls, [("", False), ("jina-k1", True), ("jina-k1", True)])

    def test_jina_anonymous_cooldown_without_key_falls_back_to_exa(self):
        calls = []
        originals = (scrape.scrape_url_jina, scrape.scrape_url_exa)

        def fake_jina(*args, **kwargs):
            calls.append("jina")
            return {"url": args[0], "error": "should not call anonymous Jina"}

        def fake_exa(url, api_key, timeout=25):
            calls.append("exa")
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "exa"}

        try:
            scrape._record_jina_anonymous_rate_limit()
            scrape.scrape_url_jina = fake_jina
            scrape.scrape_url_exa = fake_exa
            result = scrape.scrape_url_smart(
                "https://example.com/doc",
                primary="jina",
                backends=("jina", "exa"),
                exa_key="exa-key",
            )
        finally:
            scrape.scrape_url_jina, scrape.scrape_url_exa = originals

        self.assertEqual(result["via"], "exa")
        self.assertEqual(calls, ["exa"])

    def test_scrape_url_smart_rotates_exa_scrape_key_pool_without_soft_delete(self):
        calls = []
        original = scrape.scrape_url_exa

        def fake_exa(url, api_key, timeout=25):
            calls.append(api_key)
            if api_key == "exa-k1":
                return {"url": url, "error": "Exa: HTTP 429 quota exceeded"}
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "exa"}

        try:
            scrape.scrape_url_exa = fake_exa
            result = scrape.scrape_url_smart(
                "https://example.com/doc",
                primary="exa",
                backends=("exa",),
                exa_keys=["exa-k1", "exa-k2"],
            )
        finally:
            scrape.scrape_url_exa = original

        self.assertEqual(calls, ["exa-k1", "exa-k2"])
        self.assertEqual(result["via"], "exa")

    def test_scrape_url_smart_rotates_tavily_scrape_key_pool_without_soft_delete(self):
        calls = []
        original = scrape.scrape_url_tavily

        def fake_tavily(url, api_key, timeout=25):
            calls.append(api_key)
            if api_key == "tvly-k1":
                return {"url": url, "error": "Tavily: HTTP 429 rate limit"}
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "tavily"}

        try:
            scrape.scrape_url_tavily = fake_tavily
            result = scrape.scrape_url_smart(
                "https://example.com/doc",
                primary="tavily",
                backends=("tavily",),
                tavily_keys=["tvly-k1", "tvly-k2"],
            )
        finally:
            scrape.scrape_url_tavily = original

        self.assertEqual(calls, ["tvly-k1", "tvly-k2"])
        self.assertEqual(result["via"], "tavily")

    def test_scrape_url_smart_rotates_firecrawl_scrape_key_pool_without_soft_delete(self):
        calls = []
        original = scrape.scrape_url_firecrawl

        def fake_firecrawl(url, api_key, timeout=30):
            calls.append(api_key)
            if api_key == "fc-k1":
                return {"url": url, "error": "Firecrawl: HTTP 429 rate limit"}
            return {"url": url, "title": "Doc", "markdown": "body", "length": 4, "via": "firecrawl"}

        try:
            scrape.scrape_url_firecrawl = fake_firecrawl
            result = scrape.scrape_url_smart(
                "https://example.com/doc",
                primary="firecrawl",
                backends=("firecrawl",),
                firecrawl_keys=["fc-k1", "fc-k2"],
            )
        finally:
            scrape.scrape_url_firecrawl = original

        self.assertEqual(calls, ["fc-k1", "fc-k2"])
        self.assertEqual(result["via"], "firecrawl")

    def test_unknown_scrape_backend_is_ignored(self):
        calls = []
        originals = (
            scrape.scrape_url_jina,
            scrape.scrape_url_tavily,
            scrape.scrape_url_exa,
        )

        def fail(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                return {"url": "https://example.com", "error": f"{name} failed"}
            return _inner

        try:
            scrape.scrape_url_jina = fail("jina")
            scrape.scrape_url_tavily = fail("tavily")
            scrape.scrape_url_exa = fail("exa")
            result = scrape.scrape_url_smart(
                "https://example.com",
                exa_key="exa-key",
                tavily_key="tavily-key",
                primary="tavily",
                backends=("tavily", "exa", "removed-backend"),
            )
        finally:
            (
                scrape.scrape_url_jina,
                scrape.scrape_url_tavily,
                scrape.scrape_url_exa,
            ) = originals

        self.assertEqual(calls, ["tavily", "exa"])
        self.assertIn("exa failed", result["error"])

    def test_split_by_content_puts_twitter_in_content_side(self):
        long_text = "x" * 400
        with_content, without_content, passthrough, raw_counts = split_by_content([
            {"source": "twitter", "title": "tweet", "url": "https://x.com/a/status/1", "scraped_content": long_text},
            {"source": "tavily", "title": "doc", "url": "https://example.com/doc", "scraped_content": long_text},
            {"source": "brave", "title": "snippet", "url": "https://example.com/snippet", "description": "only snippet"},
        ])

        self.assertEqual([item["source"] for item in with_content], ["twitter", "tavily"])
        self.assertEqual([item["source"] for item in without_content], ["brave"])
        self.assertEqual(passthrough, [])
        self.assertEqual(raw_counts, {"twitter": 1, "tavily": 1, "brave": 1})


class KeyTests(unittest.TestCase):
    def test_pick_key_supports_key_pool_arrays(self):
        with mock.patch("scripts.keys.random.choice", return_value="k2") as choice:
            self.assertEqual(pick_key(["k1", "k2", ""]), "k2")
        choice.assert_called_once_with(["k1", "k2"])

    def test_load_keys_preserves_json_key_pool_arrays(self):
        cfg = {"serpapi": ["s1", "s2"], "exa": ["e1", "e2"]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            keys_path = f.name

        try:
            with mock.patch("pathlib.Path.home", return_value=type("Home", (), {
                "__truediv__": lambda self, name: __import__("pathlib").Path(keys_path)
            })()):
                keys = load_keys()
        finally:
            try:
                os.unlink(keys_path)
            except OSError:
                pass

        self.assertEqual(keys["serpapi"], ["s1", "s2"])
        self.assertEqual(keys["exa"], ["e1", "e2"])

    def test_load_keys_ignores_non_object_json_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(["not", "an", "object"], f)
            keys_path = f.name

        try:
            with mock.patch("pathlib.Path.home", return_value=type("Home", (), {
                "__truediv__": lambda self, name: __import__("pathlib").Path(keys_path)
            })()):
                with mock.patch.dict(os.environ, {"EXA_API_KEY": "env-exa"}, clear=False):
                    keys = load_keys()
        finally:
            try:
                os.unlink(keys_path)
            except OSError:
                pass

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

    def test_key_pool_shuffles_non_empty_candidates(self):
        with mock.patch("scripts.keys.random.shuffle") as shuffle:
            pool = key_pool(["k1", "", "k2"])
        self.assertEqual(pool, ["k1", "k2"])
        shuffle.assert_called_once_with(pool)

    def test_active_jina_keys_filter_exhausted_config_and_runtime_keys(self):
        _JINA_EXHAUSTED.clear()
        _JINA_EXHAUSTED.add("runtime-dead")
        cfg = [
            {"key": "active"},
            {"key": "config-dead", "exhausted": True},
            {"key": "runtime-dead"},
        ]

        with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
            active = get_active_jina_keys(cfg)

        self.assertEqual(active, ["active"])
        self.assertEqual(count_jina_keys(cfg), (1, 3))
        _JINA_EXHAUSTED.clear()

    def test_mark_jina_exhausted_persistent_updates_key_pool_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_path = Path(tmpdir) / ".search-keys.json"
            keys_path.write_text(
                json.dumps({"jina": [{"key": "j1"}, {"key": "j2", "exhausted": False}]}),
                encoding="utf-8",
            )

            with mock.patch("pathlib.Path.home", return_value=Path(tmpdir)):
                changed = mark_jina_exhausted_persistent("j2")

            saved = json.loads(keys_path.read_text(encoding="utf-8"))

        self.assertTrue(changed)
        self.assertFalse(saved["jina"][0].get("exhausted", False))
        self.assertTrue(saved["jina"][1]["exhausted"])


class ProviderContractTests(unittest.TestCase):
    def test_brave_search_uses_subscription_token_and_extra_snippets(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "web": {"results": [{
                    "title": "Doc",
                    "url": "https://example.com/doc",
                    "description": "main snippet",
                    "extra_snippets": ["extra snippet", "main snippet"],
                }]}
            })

        with mock.patch("scripts.searchers.brave.urlopen_retry", side_effect=fake_urlopen):
            results = search_brave("hello world", "brave-key", 2)

        headers = _headers(captured[0])
        qs = _query(captured[0].full_url)
        self.assertEqual(headers["x-subscription-token"], "brave-key")
        self.assertEqual(qs["q"], ["hello world"])
        self.assertEqual(qs["count"], ["2"])
        self.assertEqual(qs["extra_snippets"], ["true"])
        self.assertEqual(results[0]["description"], "main snippet · extra snippet")

    def test_exa_search_nests_text_under_contents(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "results": [{
                    "title": "Doc",
                    "url": "https://example.com/doc",
                    "text": "full text",
                }]
            })

        with mock.patch("scripts.searchers.exa.urlopen_retry", side_effect=fake_urlopen):
            results = search_exa("query", "exa-key", 4)

        body = _json_body(captured[0])
        headers = _headers(captured[0])
        self.assertEqual(captured[0].full_url, "https://api.exa.ai/search")
        self.assertEqual(headers["x-api-key"], "exa-key")
        self.assertEqual(body["query"], "query")
        self.assertEqual(body["numResults"], 4)
        self.assertEqual(body["type"], "auto")
        self.assertEqual(body["contents"], {"text": {"maxCharacters": 8000}})
        self.assertEqual(results[0]["scraped_content"], "full text")

    def test_exa_contents_uses_top_level_text_not_nested_contents(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "statuses": [{"status": "success"}],
                "results": [{"title": "Doc", "text": "page text"}],
            })

        with mock.patch("scripts.scrapers.exa.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_exa("https://example.com/doc", "exa-key")

        body = _json_body(captured[0])
        headers = _headers(captured[0])
        self.assertEqual(captured[0].full_url, "https://api.exa.ai/contents")
        self.assertEqual(headers["x-api-key"], "exa-key")
        self.assertEqual(body["urls"], ["https://example.com/doc"])
        self.assertEqual(body["text"], {"maxCharacters": 8000})
        self.assertEqual(body["maxAgeHours"], 0)
        self.assertEqual(body["livecrawlTimeout"], 30000)
        self.assertNotIn("contents", body)
        self.assertEqual(result["markdown"], "page text")

    def test_exa_contents_empty_text_is_error_for_fallback(self):
        def fake_urlopen(req, timeout):
            return _FakeResponse({
                "statuses": [{"status": "success"}],
                "results": [{"title": "Doc", "text": ""}],
            })

        with mock.patch("scripts.scrapers.exa.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_exa("https://example.com/doc", "exa-key")

        self.assertIn("error", result)
        self.assertIn("empty content", result["error"])

    def test_exa_contents_reports_status_error_detail(self):
        def fake_urlopen(req, timeout):
            return _FakeResponse({
                "statuses": [{
                    "status": "error",
                    "error": {"tag": "SOURCE_NOT_AVAILABLE", "httpStatusCode": 403},
                }],
                "results": [],
            })

        with mock.patch("scripts.scrapers.exa.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_exa("https://example.com/doc", "exa-key")

        self.assertIn("Exa status: error", result["error"])
        self.assertIn("SOURCE_NOT_AVAILABLE", result["error"])
        self.assertIn("403", result["error"])

    def test_firecrawl_scrape_uses_v2_main_markdown(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "success": True,
                "data": {
                    "markdown": "# main",
                    "metadata": {"title": "Doc"},
                },
            })

        with mock.patch("scripts.scrapers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_firecrawl("https://example.com/doc", "fc-key")

        body = _json_body(captured[0])
        headers = _headers(captured[0])
        self.assertEqual(captured[0].full_url, "https://api.firecrawl.dev/v2/scrape")
        self.assertEqual(headers["authorization"], "Bearer fc-key")
        self.assertEqual(body["url"], "https://example.com/doc")
        self.assertEqual(body["formats"], ["markdown"])
        self.assertTrue(body["onlyMainContent"])
        self.assertEqual(body["timeout"], 30000)
        self.assertEqual(result["markdown"], "# main")
        self.assertEqual(result["via"], "firecrawl")

    def test_jina_reader_uses_anonymous_json_markdown_request(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "code": 200,
                "status": 20000,
                "data": {
                    "title": "Doc",
                    "url": "https://example.com/doc",
                    "content": "# markdown",
                },
            })

        with mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_jina("https://example.com/doc")

        headers = _headers(captured[0])
        self.assertEqual(captured[0].full_url, "https://r.jina.ai/https%3A%2F%2Fexample.com%2Fdoc")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["x-respond-with"], "markdown")
        self.assertEqual(headers["x-timeout"], "30")
        self.assertIn("nav", headers["x-remove-selector"])
        self.assertEqual(headers["x-retain-images"], "none")
        self.assertEqual(headers["x-retain-media"], "none")
        self.assertIn("user-agent", headers)
        self.assertNotIn("authorization", headers)
        self.assertEqual(result["markdown"], "# markdown")
        self.assertEqual(result["via"], "jina")

    def test_jina_reader_retries_with_key_after_anonymous_rate_limit(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            if len(captured) == 1:
                body = json.dumps({"message": "Per IP rate limit exceeded"}).encode("utf-8")
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))
            return _FakeResponse({
                "code": 200,
                "status": 20000,
                "data": {"title": "Doc", "content": "with key"},
            })

        with mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_jina("https://example.com/doc", "jina-key")

        self.assertNotIn("authorization", _headers(captured[0]))
        self.assertEqual(_headers(captured[1])["authorization"], "Bearer jina-key")
        self.assertEqual(result["markdown"], "with key")

    def test_jina_reader_marks_anonymous_rate_limit(self):
        def fake_urlopen(req, timeout):
            body = json.dumps({"message": "Per IP rate limit exceeded"}).encode("utf-8")
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))

        with mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_jina("https://example.com/doc")

        self.assertTrue(result["rate_limited"])
        self.assertNotIn("key_exhausted", result)
        self.assertNotIn("exhausted", result)

    def test_jina_reader_keeps_key_active_on_key_rate_limit_when_balance_positive(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            if "dash.jina.ai/api/v1/api_key/fe_user" in req.full_url:
                return _FakeResponse({"wallet": {"total_balance": 12345}})
            body = json.dumps({"message": "Per key RPM exceeded"}).encode("utf-8")
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))

        with mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_jina(
                "https://example.com/doc",
                "jina-key",
                skip_anonymous=True,
            )

        self.assertEqual(len(captured), 2)
        self.assertEqual(_headers(captured[0])["authorization"], "Bearer jina-key")
        self.assertEqual(_query(captured[1].full_url)["api_key"], ["jina-key"])
        self.assertTrue(result["rate_limited"])
        self.assertNotIn("key_exhausted", result)
        self.assertNotIn("exhausted", result)

    def test_jina_reader_marks_key_exhausted_when_balance_is_zero(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            if "dash.jina.ai/api/v1/api_key/fe_user" in req.full_url:
                return _FakeResponse({"wallet": {"total_balance": 0}})
            body = json.dumps({"message": "quota exhausted"}).encode("utf-8")
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))

        with mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_jina(
                "https://example.com/doc",
                "jina-key",
                skip_anonymous=True,
            )

        self.assertEqual(len(captured), 2)
        self.assertEqual(_headers(captured[0])["authorization"], "Bearer jina-key")
        self.assertEqual(_query(captured[1].full_url)["api_key"], ["jina-key"])
        self.assertTrue(result["rate_limited"])
        self.assertTrue(result["key_exhausted"])
        self.assertTrue(result["exhausted"])

    def test_jina_reader_checks_balance_for_authz_insufficient_balance(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            if "dash.jina.ai/api/v1/api_key/fe_user" in req.full_url:
                return _FakeResponse({"wallet": {"total_balance": 0}})
            body = json.dumps({"message": "AUTHZ_INSUFFICIENT_BALANCE"}).encode("utf-8")
            raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(body))

        with mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_jina(
                "https://example.com/doc",
                "jina-key",
                skip_anonymous=True,
            )

        self.assertEqual(len(captured), 2)
        self.assertEqual(_query(captured[1].full_url)["api_key"], ["jina-key"])
        self.assertTrue(result["rate_limited"])
        self.assertTrue(result["key_exhausted"])
        self.assertTrue(result["exhausted"])

    def test_firecrawl_search_uses_v2_search_bearer_auth_and_data_web(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "data": {"web": [{
                    "title": "Doc",
                    "url": "https://example.com/doc",
                    "description": "desc",
                }]}
            })

        with mock.patch("scripts.searchers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            results = search_firecrawl("query", "fc-key", 5)

        body = _json_body(captured[0])
        headers = _headers(captured[0])
        self.assertEqual(captured[0].full_url, "https://api.firecrawl.dev/v2/search")
        self.assertEqual(headers["authorization"], "Bearer fc-key")
        self.assertEqual(body, {"query": "query", "limit": 5})
        self.assertEqual(results[0]["source"], "firecrawl")
        self.assertEqual(results[0]["url"], "https://example.com/doc")

    def test_v2ex_search_uses_firecrawl_include_domains(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "data": {"web": [{
                    "title": "V2EX Topic",
                    "url": "https://www.v2ex.com/t/123",
                    "description": "desc",
                }]}
            })

        with mock.patch("scripts.searchers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            results = search_v2ex("claude code", "fc-key", 5)

        body = _json_body(captured[0])
        self.assertEqual(body["query"], "claude code")
        self.assertEqual(body["limit"], 5)
        self.assertEqual(tuple(body["includeDomains"]), V2EX_DOMAINS)
        self.assertEqual(results[0]["source"], "v2ex")
        self.assertEqual(results[0]["url"], "https://www.v2ex.com/t/123")

    def test_reddit_search_uses_firecrawl_include_domains(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "data": {"web": [{
                    "title": "Reddit thread",
                    "url": "https://www.reddit.com/r/LocalLLaMA/comments/abc/agent_memory/",
                    "description": "desc",
                }]}
            })

        with mock.patch("scripts.searchers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            results = search_reddit("agent memory", "fc-key", 5)

        body = _json_body(captured[0])
        self.assertEqual(body["query"], "agent memory")
        self.assertEqual(body["limit"], 5)
        self.assertEqual(tuple(body["includeDomains"]), REDDIT_DOMAINS)
        self.assertEqual(results[0]["source"], "reddit")
        self.assertEqual(results[0]["url"], "https://www.reddit.com/r/LocalLLaMA/comments/abc/agent_memory/")

    def test_zhihu_firecrawl_fallback_uses_include_domains(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "data": {"web": [{
                    "title": "知乎回答",
                    "url": "https://www.zhihu.com/question/497594623/answer/3489550674",
                    "description": "desc",
                }]}
            })

        with mock.patch("scripts.searchers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            results = search_zhihu_firecrawl("AI Agent", "fc-key", 5)

        body = _json_body(captured[0])
        self.assertEqual(body["query"], "AI Agent")
        self.assertEqual(body["limit"], 5)
        self.assertEqual(tuple(body["includeDomains"]), ZHIHU_DOMAINS)
        self.assertEqual(results[0]["source"], "zhihu")
        self.assertEqual(results[0]["url"], "https://www.zhihu.com/question/497594623/answer/3489550674")

    def test_zhihu_openapi_search_uses_bearer_timestamp_and_normalizes_items(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append((req, timeout))
            return _FakeResponse({
                "Code": 0,
                "Message": "success",
                "Data": {"Items": [{
                    "Title": "RAG 评测方法综述",
                    "Url": "https://zhuanlan.zhihu.com/p/123456789",
                    "ContentText": "本文介绍了主流 RAG 评测框架",
                    "AuthorName": "张三",
                    "VoteUpCount": 128,
                    "CommentCount": 15,
                    "EditTime": 1710000000,
                    "ContentType": "Article",
                    "ContentID": "123456789",
                    "AuthorityLevel": "2",
                    "RankingScore": 0.98,
                }]}
            })

        with mock.patch("scripts.searchers.zhihu.urlopen_retry", side_effect=fake_urlopen):
            with mock.patch("scripts.searchers.zhihu.time.time", return_value=1742822400):
                results = search_zhihu("RAG", "zhihu-secret", 50)

        req, timeout = captured[0]
        headers = _headers(req)
        query = _query(req.full_url)
        self.assertEqual(req.full_url.split("?")[0], "https://developer.zhihu.com/api/v1/content/zhihu_search")
        self.assertEqual(query["Query"], ["RAG"])
        self.assertEqual(query["Count"], ["10"])
        self.assertEqual(headers["authorization"], "Bearer zhihu-secret")
        self.assertEqual(headers["x-request-timestamp"], "1742822400")
        self.assertEqual(timeout, 5)
        self.assertEqual(results[0]["source"], "zhihu")
        self.assertEqual(results[0]["title"], "RAG 评测方法综述")
        self.assertEqual(results[0]["author_name"], "张三")
        self.assertEqual(results[0]["vote_up_count"], 128)

    def test_hackernews_search_uses_algolia_story_search(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "hits": [{
                    "title": "Uv: Python packaging in Rust",
                    "url": "https://astral.sh/blog/uv",
                    "objectID": "39387641",
                    "points": 647,
                    "num_comments": 210,
                    "author": "samwho",
                    "created_at": "2024-02-15T19:50:27Z",
                }]
            })

        with mock.patch("scripts.searchers.hackernews.urlopen_retry", side_effect=fake_urlopen):
            results = search_hackernews("python uv", 5)

        qs = _query(captured[0].full_url)
        self.assertEqual(captured[0].full_url.split("?", 1)[0], "https://hn.algolia.com/api/v1/search")
        self.assertEqual(qs["query"], ["python uv"])
        self.assertEqual(qs["tags"], ["story"])
        self.assertEqual(qs["hitsPerPage"], ["5"])
        self.assertEqual(results[0]["source"], "hackernews")
        self.assertEqual(results[0]["url"], "https://astral.sh/blog/uv")
        self.assertIn("647 points", results[0]["description"])

    def test_hackernews_search_falls_back_to_hackernews_item_url(self):
        def fake_urlopen(req, timeout):
            return _FakeResponse({
                "hits": [{
                    "story_title": "Ask Hacker News: Python uv?",
                    "objectID": "123",
                }]
            })

        with mock.patch("scripts.searchers.hackernews.urlopen_retry", side_effect=fake_urlopen):
            results = search_hackernews("python uv", 1)

        self.assertEqual(results[0]["url"], "https://news.ycombinator.com/item?id=123")

    def test_stackoverflow_search_uses_stackexchange_advanced_search(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({
                "items": [{
                    "title": "Python uv module: confusing behaviour",
                    "link": "https://stackoverflow.com/questions/79314812/python-uv-module-confusing-behaviour",
                    "tags": ["python", "uv"],
                    "score": 1,
                    "answer_count": 1,
                    "view_count": 7581,
                    "is_answered": True,
                }]
            })

        with mock.patch("scripts.searchers.stackoverflow.urlopen_retry", side_effect=fake_urlopen):
            results = search_stackoverflow("python uv", 5)

        qs = _query(captured[0].full_url)
        self.assertEqual(captured[0].full_url.split("?", 1)[0], "https://api.stackexchange.com/2.3/search/advanced")
        self.assertEqual(qs["q"], ["python uv"])
        self.assertEqual(qs["site"], ["stackoverflow"])
        self.assertEqual(qs["pagesize"], ["5"])
        self.assertEqual(qs["sort"], ["relevance"])
        self.assertEqual(results[0]["source"], "stackoverflow")
        self.assertEqual(results[0]["url"], "https://stackoverflow.com/questions/79314812/python-uv-module-confusing-behaviour")
        self.assertIn("1 answers", results[0]["description"])

    def test_youtube_search_uses_data_api_video_search(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append((req, timeout))
            return _FakeResponse({
                "items": [{
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "Agent Memory Tutorial",
                        "channelTitle": "Example Channel",
                        "publishedAt": "2026-01-02T03:04:05Z",
                        "description": "Video description",
                    },
                }]
            })

        with mock.patch("scripts.searchers.youtube.urlopen_retry", side_effect=fake_urlopen):
            results = search_youtube("agent memory", "youtube-key", 60)

        req, timeout = captured[0]
        qs = _query(req.full_url)
        self.assertEqual(req.full_url.split("?", 1)[0], "https://www.googleapis.com/youtube/v3/search")
        self.assertEqual(qs["part"], ["snippet"])
        self.assertEqual(qs["q"], ["agent memory"])
        self.assertEqual(qs["type"], ["video"])
        self.assertEqual(qs["maxResults"], ["50"])
        self.assertEqual(qs["key"], ["youtube-key"])
        self.assertEqual(timeout, 20)
        self.assertEqual(results[0]["source"], "youtube")
        self.assertEqual(results[0]["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertIn("Example Channel", results[0]["description"])

    def test_bilibili_search_uses_video_search_api(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append((req, timeout))
            return _FakeResponse({
                "code": 0,
                "data": {
                    "result": [{
                        "title": "<em class=\"keyword\">Agent</em> Memory 教程",
                        "bvid": "BV1xx411c7mD",
                        "arcurl": "https://www.bilibili.com/video/BV1xx411c7mD",
                        "author": "作者",
                        "duration": "12:34",
                        "play": 1234,
                        "danmaku": 56,
                    }]
                },
            })

        with mock.patch("scripts.searchers.bilibili.urlopen_retry", side_effect=fake_urlopen):
            results = search_bilibili("agent memory", "SESSDATA=abc", 60)

        req, timeout = captured[0]
        qs = _query(req.full_url)
        headers = _headers(req)
        self.assertEqual(req.full_url.split("?", 1)[0], "https://api.bilibili.com/x/web-interface/search/type")
        self.assertEqual(qs["search_type"], ["video"])
        self.assertEqual(qs["keyword"], ["agent memory"])
        self.assertEqual(qs["page_size"], ["50"])
        self.assertEqual(headers["cookie"], "SESSDATA=abc")
        self.assertEqual(timeout, 20)
        self.assertEqual(results[0]["source"], "bilibili")
        self.assertEqual(results[0]["title"], "Agent Memory 教程")
        self.assertEqual(results[0]["url"], "https://www.bilibili.com/video/BV1xx411c7mD")

    def test_bilibili_search_falls_back_to_html_on_request_ban(self):
        calls = []
        html_body = b'''
        <a href="//www.bilibili.com/video/BV1html12345/" target="_blank">
          <img src="//example.invalid/cover.jpg" alt="HTML Fallback Video">
        </a>
        '''

        def fake_urlopen(req, timeout):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 412, "request was banned", {}, None)
            return _BytesResponse(html_body)

        with mock.patch("scripts.searchers.bilibili.urlopen_retry", side_effect=fake_urlopen):
            results = search_bilibili("agent memory", "", 5)

        self.assertEqual(len(calls), 2)
        self.assertIn("api.bilibili.com/x/web-interface/search/type", calls[0])
        self.assertIn("search.bilibili.com/all", calls[1])
        self.assertEqual(results[0]["source"], "bilibili")
        self.assertEqual(results[0]["title"], "HTML Fallback Video")
        self.assertEqual(results[0]["url"], "https://www.bilibili.com/video/BV1html12345")

    def test_firecrawl_empty_grouped_web_returns_no_blank_result(self):
        def fake_urlopen(req, timeout):
            return _FakeResponse({"data": {"web": []}})

        with mock.patch("scripts.searchers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            results = search_firecrawl("query", "fc-key", 5)

        self.assertEqual(results, [])

    def test_firecrawl_success_false_returns_error(self):
        def fake_urlopen(req, timeout):
            return _FakeResponse({"success": False, "error": "quota fc-secret exceeded"})

        with mock.patch("scripts.searchers.firecrawl.urlopen_retry", side_effect=fake_urlopen):
            results = search_firecrawl("query", "fc-secret", 5)

        self.assertEqual(results[0]["source"], "firecrawl")
        self.assertIn("quota", results[0]["error"])
        self.assertNotIn("fc-secret", results[0]["error"])

    def test_serpapi_uses_google_light_query_params_and_parses_organic_results(self):
        captured = []

        def fake_urlopen(url, timeout):
            captured.append(url)
            return _FakeResponse({
                "organic_results": [{
                    "title": "Doc",
                    "link": "https://example.com/doc",
                    "snippet": "snippet",
                }]
            })

        with mock.patch("scripts.searchers.serpapi.urlopen_retry", side_effect=fake_urlopen):
            results = search_serpapi("query", "serp-key", 7, "google_light")

        qs = _query(captured[0])
        self.assertEqual(qs["engine"], ["google_light"])
        self.assertEqual(qs["q"], ["query"])
        self.assertNotIn("num", qs)
        self.assertNotIn("start", qs)
        self.assertEqual(qs["output"], ["json"])
        self.assertEqual(qs["api_key"], ["serp-key"])
        self.assertEqual(qs["hl"], ["en"])
        self.assertEqual(qs["gl"], ["us"])
        self.assertEqual(results[0]["url"], "https://example.com/doc")

    def test_serpapi_count_above_first_page_uses_start_pagination(self):
        captured = []

        def fake_urlopen(url, timeout):
            captured.append(url)
            page = len(captured)
            return _FakeResponse({
                "organic_results": [
                    {
                        "title": f"Doc {page}-{idx}",
                        "link": f"https://example.com/{page}-{idx}",
                        "snippet": "snippet",
                    }
                    for idx in range(10)
                ]
            })

        with mock.patch("scripts.searchers.serpapi.urlopen_retry", side_effect=fake_urlopen):
            results = search_serpapi("query", "serp-key", 12, "google_light")

        first_qs = _query(captured[0])
        second_qs = _query(captured[1])
        self.assertNotIn("num", first_qs)
        self.assertNotIn("start", first_qs)
        self.assertEqual(second_qs["start"], ["10"])
        self.assertNotIn("num", second_qs)
        self.assertEqual(len(results), 12)

    def test_serpapi_api_error_scrubs_key_like_query_params(self):
        def fake_urlopen(url, timeout):
            return _FakeResponse({"error": "bad request: api_key=serp-secret&foo=bar"})

        with mock.patch("scripts.searchers.serpapi.urlopen_retry", side_effect=fake_urlopen):
            results = search_serpapi("query", "serp-secret", 3, "google_light")

        self.assertEqual(results[0]["source"], "serpapi")
        self.assertNotIn("serp-secret", results[0]["error"])
        self.assertIn("api_key=<redacted>", results[0]["error"])

    def test_serpapi_api_error_scrubs_direct_key_value(self):
        def fake_urlopen(url, timeout):
            return _FakeResponse({"error": "invalid key serp-direct-secret"})

        with mock.patch("scripts.searchers.serpapi.urlopen_retry", side_effect=fake_urlopen):
            results = search_serpapi("query", "serp-direct-secret", 3, "google_light")

        self.assertNotIn("serp-direct-secret", results[0]["error"])
        self.assertIn("<redacted>", results[0]["error"])

    def test_serpapi_partial_page_error_is_returned_with_results(self):
        captured = []

        def fake_urlopen(url, timeout):
            captured.append(url)
            if len(captured) == 1:
                return _FakeResponse({
                    "organic_results": [
                        {
                            "title": f"Doc {idx}",
                            "link": f"https://example.com/{idx}",
                            "snippet": "snippet",
                        }
                        for idx in range(10)
                    ],
                })
            return _FakeResponse({"error": "HTTP 429 quota exceeded for serp-partial-secret"})

        with mock.patch("scripts.searchers.serpapi.urlopen_retry", side_effect=fake_urlopen):
            results = search_serpapi("query", "serp-partial-secret", 12, "google_light")

        self.assertEqual(len(captured), 2)
        self.assertEqual(len([r for r in results if r.get("source") == "serpapi" and "error" not in r]), 10)
        self.assertIn("HTTP 429", results[-1]["error"])
        self.assertNotIn("serp-partial-secret", results[-1]["error"])

    def test_search_provider_exceptions_scrub_api_keys(self):
        cases = [
            ("scripts.searchers.brave.urlopen_retry", lambda: search_brave("q", "brave-secret", 1), "brave-secret"),
            ("scripts.searchers.tavily.urlopen_retry", lambda: search_tavily("q", "tvly-secret", 1), "tvly-secret"),
            ("scripts.searchers.exa.urlopen_retry", lambda: search_exa("q", "exa-secret", 1), "exa-secret"),
            ("scripts.searchers.firecrawl.urlopen_retry", lambda: search_firecrawl("q", "fc-secret", 1), "fc-secret"),
        ]

        for patch_target, call, secret in cases:
            with self.subTest(patch_target=patch_target):
                with mock.patch(patch_target, side_effect=RuntimeError(f"failed with token {secret}")):
                    results = call()
                self.assertNotIn(secret, results[0]["error"])
                self.assertIn("<redacted>", results[0]["error"])

    def test_scrape_provider_exceptions_scrub_api_keys(self):
        cases = [
            (lambda: scrape.scrape_url_exa("https://example.com", "exa-secret"), "exa-secret", "Exa:"),
            (lambda: scrape.scrape_url_tavily("https://example.com", "tvly-secret"), "tvly-secret", "Tavily:"),
            (lambda: scrape.scrape_url_jina("https://example.com", "jina-secret"), "jina-secret", "Jina:"),
        ]

        for call, secret, prefix in cases:
            with self.subTest(prefix=prefix):
                with mock.patch("scripts.scrapers.exa.urlopen_retry", side_effect=RuntimeError(f"bad header x-api-key: {secret}")), \
                     mock.patch("scripts.scrapers.tavily.urlopen_retry", side_effect=RuntimeError(f"bad header x-api-key: {secret}")), \
                     mock.patch("scripts.scrapers.jina.urlopen_retry", side_effect=RuntimeError(f"bad header x-api-key: {secret}")):
                    result = call()
                self.assertIn(prefix, result["error"])
                self.assertNotIn(secret, result["error"])
                self.assertIn("<redacted>", result["error"])

    def test_tavily_failed_extract_result_scrubs_api_key(self):
        def fake_urlopen(req, timeout):
            return _FakeResponse({"failed_results": [{"error": "denied tvly-secret"}]})

        with mock.patch("scripts.scrapers.tavily.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_tavily("https://example.com", "tvly-secret")

        self.assertNotIn("tvly-secret", result["error"])
        self.assertIn("<redacted>", result["error"])

    def test_github_direct_api_exception_scrubs_token(self):
        with mock.patch("scripts.searchers.github.urlopen_retry", side_effect=RuntimeError("bad gh-direct-secret")):
            results = search_github_repos("query", 2, "gh-direct-secret")

        self.assertEqual(results[0]["source"], "github-repos")
        self.assertNotIn("gh-direct-secret", results[0]["error"])
        self.assertIn("<redacted>", results[0]["error"])

    def test_twitter_scrub_redacts_direct_cookie_values(self):
        output = twitter_source._scrub(
            "auth failed auth_token=cookie-param and direct-cookie-secret",
            {"auth_token": "direct-cookie-secret", "ct0": "ct0-secret"},
        )

        self.assertNotIn("cookie-param", output)
        self.assertNotIn("direct-cookie-secret", output)
        self.assertIn("auth_token=<redacted>", output)

    def test_tavily_extract_uses_bearer_auth_and_markdown_format(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({"results": [{"raw_content": "# markdown"}]})

        with mock.patch("scripts.scrapers.tavily.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_tavily("https://example.com/doc", "tvly-key")

        body = _json_body(captured[0])
        headers = _headers(captured[0])
        self.assertEqual(captured[0].full_url, "https://api.tavily.com/extract")
        self.assertEqual(headers["authorization"], "Bearer tvly-key")
        self.assertNotIn("api_key", body)
        self.assertEqual(body["urls"], ["https://example.com/doc"])
        self.assertEqual(body["extract_depth"], "advanced")
        self.assertEqual(body["format"], "markdown")
        self.assertEqual(body["timeout"], 30.0)
        self.assertEqual(result["markdown"], "# markdown")

    def test_tavily_extract_falls_back_to_basic_after_advanced_failure(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            body = _json_body(req)
            if body["extract_depth"] == "advanced":
                return _FakeResponse({"failed_results": [{"error": "Failed to fetch url"}]})
            return _FakeResponse({"results": [{"raw_content": "# basic"}]})

        with mock.patch("scripts.scrapers.tavily.urlopen_retry", side_effect=fake_urlopen):
            result = scrape.scrape_url_tavily("https://example.com/doc", "tvly-key")

        self.assertEqual([_json_body(req)["extract_depth"] for req in captured], ["advanced", "basic"])
        self.assertEqual(result["markdown"], "# basic")

    def test_tavily_search_uses_bearer_auth_not_body_api_key(self):
        captured = []

        def fake_urlopen(req, timeout):
            captured.append(req)
            return _FakeResponse({"results": []})

        with mock.patch("scripts.searchers.tavily.urlopen_retry", side_effect=fake_urlopen):
            self.assertEqual(search_tavily("query", "tvly-test", 3), [])

        self.assertEqual(captured[0].headers["Authorization"], "Bearer tvly-test")
        body = json.loads(captured[0].data.decode("utf-8"))
        self.assertNotIn("api_key", body)
        self.assertEqual(body["query"], "query")
        self.assertEqual(body["max_results"], 3)


class FormatTests(unittest.TestCase):
    def test_default_output_hides_ai_answer_and_regular_snippets(self):
        output = format_results([
            {"source": "tavily_answer", "answer": "provider summary"},
            {"source": "brave", "title": "Doc", "url": "https://example.com/doc", "description": "regular snippet"},
            {"source": "twitter", "title": "Discussion", "url": "https://x.com/example/status/1", "description": "💬5 ♥2 🔁1"},
        ], "query")

        self.assertNotIn("Tavily AI Answer", output)
        self.assertNotIn("regular snippet", output)
        self.assertIn("💬5 ♥2 🔁1", output)

    def test_output_includes_required_skill_markers(self):
        output = format_results([
            {"source": "brave", "title": "Doc", "url": "https://example.com/doc"},
        ], "query")

        self.assertIn("multi-search", output)
        self.assertRegex(output, r"\b1 results\b")
        self.assertIn("### Top:", output)

    def test_verbose_output_shows_ai_answer_and_regular_snippets(self):
        output = format_results([
            {"source": "tavily_answer", "answer": "provider summary"},
            {"source": "brave", "title": "Doc", "url": "https://example.com/doc", "description": "regular snippet"},
        ], "query", verbose=True)

        self.assertIn("Tavily AI Answer", output)
        self.assertIn("regular snippet", output)

    def test_markdown_output_escapes_tables_and_links(self):
        output = format_results([
            {
                "source": "brave",
                "title": "Doc [alpha] | beta",
                "url": "https://example.com/a(b)?x=1|2",
                "description": "snippet",
            },
        ], "query")

        self.assertIn("Doc [alpha] ｜ beta", output)
        self.assertIn("https://example.com/a(b)?x=1｜2", output)
        self.assertIn("[Doc \\[alpha\\] ｜ beta](https://example.com/a\\(b\\)?x=1|2)", output)

    def test_scrape_summary_sanitizes_untrusted_markdown(self):
        output = format_scrapes([
            {
                "url": "https://example.com/doc",
                "title": "Doc",
                "via": "exa",
                "length": 200,
                "markdown": (
                    "This scraped line is deliberately long with "
                    "<script>alert(1)</script> and image "
                    "![leak](https://img.example/pixel.png) plus fence ``` break.\n"
                    "More body text."
                ),
            }
        ])

        self.assertNotIn("<script>", output)
        self.assertNotIn("</script>", output)
        self.assertNotIn("alert(1)", output)
        self.assertNotIn("![leak]", output)
        self.assertIn("[image: leak — https://img.example/pixel.png]", output)
        self.assertNotIn("fence ``` break", output)
        self.assertIn("fence ʼʼʼ break", output)

    def test_error_rows_are_single_line_and_table_safe(self):
        output = format_results([
            {"source": "serpapi", "error": "bad | thing\nsecond line"},
        ], "query")

        self.assertIn("bad ｜ thing second line", output)
        self.assertNotIn("bad | thing\nsecond line", output)

    def test_sources_summary_is_explicit_when_all_sources_error(self):
        output = format_results([
            {"source": "brave", "error": "missing API key"},
        ], "query")

        self.assertIn("**Sources (raw hits):** none", output)
        self.assertIn("| 🔍 brave | 0 | ERROR | missing API key |", output)

    def test_zero_hit_source_status_is_ok_not_error(self):
        output = format_results([
            {"source": "exa", "status": "ok", "raw_hits": 0},
        ], "query")

        self.assertIn("**Sources (raw hits):** ✨ **exa**: 0", output)
        self.assertIn("| ✨ exa | 0 | OK |  |", output)


class CliTests(unittest.TestCase):
    def test_unknown_option_exits_with_error(self):
        with mock.patch("sys.argv", ["search.py", "query", "--unknown-option"]):
            with self.assertRaises(SystemExit) as cm:
                main()
        self.assertEqual(cm.exception.code, 2)

    def test_invalid_integer_option_exits_before_search(self):
        with mock.patch("sys.argv", ["search.py", "query", "--count", "nope"]):
            with mock.patch("scripts.main.load_keys") as load_keys_mock:
                with self.assertRaises(SystemExit) as cm:
                    main()
        self.assertEqual(cm.exception.code, 2)
        load_keys_mock.assert_not_called()

    def test_missing_option_value_exits_before_search(self):
        with mock.patch("sys.argv", ["search.py", "query", "--config"]):
            with mock.patch("scripts.main.load_keys") as load_keys_mock:
                with self.assertRaises(SystemExit) as cm:
                    main()
        self.assertEqual(cm.exception.code, 2)
        load_keys_mock.assert_not_called()

    def test_explicit_missing_config_file_exits_before_search(self):
        missing_path = str(Path(tempfile.gettempdir()) / "multi-search-missing-config.json")
        try:
            os.unlink(missing_path)
        except OSError:
            pass

        with mock.patch("sys.argv", ["search.py", "query", "--config", missing_path]):
            with mock.patch("scripts.main.load_keys") as load_keys_mock:
                with self.assertRaises(SystemExit) as cm:
                    main()

        self.assertEqual(cm.exception.code, 2)
        load_keys_mock.assert_not_called()

    def test_invalid_config_file_shape_exits_before_search(self):
        cases = [
            "{not json",
            json.dumps(["not", "an", "object"]),
        ]

        for content in cases:
            with self.subTest(content=content):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    f.write(content)
                    config_path = f.name

                try:
                    with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                        with mock.patch("scripts.main.load_keys") as load_keys_mock:
                            with self.assertRaises(SystemExit) as cm:
                                main()
                finally:
                    try:
                        os.unlink(config_path)
                    except OSError:
                        pass

                self.assertEqual(cm.exception.code, 2)
                load_keys_mock.assert_not_called()

    def test_invalid_scrape_numeric_options_exit_before_search(self):
        cases = [
            ["search.py", "query", "--scrape-chars", "0"],
            ["search.py", "query", "--scrape-top", "-1"],
            ["search.py", "query", "--scrape-per-source", "0"],
            ["search.py", "query", "--scrape-timeout", "-1"],
            ["search.py", "query", "--scrape-concurrency", "0"],
            ["search.py", "query", "--timeout", "-1"],
            ["search.py", "query", "--count", "0"],
            ["search.py", "query", "--count", "-1"],
            ["search.py", "query", "--brave-count", "0"],
            ["search.py", "query", "--brave-count", "-1"],
            ["search.py", "query", "--serpapi-engine", "bing"],
        ]

        for argv in cases:
            with self.subTest(argv=argv):
                with mock.patch("sys.argv", argv):
                    with mock.patch("scripts.main.load_keys") as load_keys_mock:
                        with self.assertRaises(SystemExit) as cm:
                            main()
                self.assertEqual(cm.exception.code, 2)
                load_keys_mock.assert_not_called()

    def test_invalid_config_non_numeric_values_exit_before_search(self):
        cases = [
            {"type": "brave", "no_scrape": []},
            {"type": "brave", "brief": "sometimes"},
            {"type": "brave", "verbose": {"yes": True}},
            {"type": "brave", "expand": "one query"},
            {"type": "brave", "expand": ["ok", 2]},
            {"type": "brave", "expand": ["ok", None]},
            {"type": "brave", "expand_queries": [True]},
            {"type": "brave", "serpapi_engine": "bing"},
        ]

        for cfg in cases:
            with self.subTest(cfg=cfg):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    json.dump(cfg, f)
                    config_path = f.name

                try:
                    with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                        with mock.patch("scripts.main.load_keys") as load_keys_mock:
                            with self.assertRaises(SystemExit) as cm:
                                main()
                finally:
                    try:
                        os.unlink(config_path)
                    except OSError:
                        pass

                self.assertEqual(cm.exception.code, 2)
                load_keys_mock.assert_not_called()

    def test_invalid_config_runtime_numeric_values_exit_before_search(self):
        cases = [
            {"type": "brave", "timeout": -1},
            {"type": "brave", "timeout": "5"},
            {"type": "brave", "timeout": "nope"},
            {"type": "brave", "timeout": 1.5},
            {"type": "brave", "timeout": True},
            {"type": "brave", "scrape_top": -1},
            {"type": "brave", "scrape_top": "nope"},
            {"type": "brave", "scrape_top": False},
            {"type": "brave", "scrape_chars": 0},
            {"type": "brave", "scrape_chars": -20},
            {"type": "brave", "scrape_chars": 1.5},
            {"type": "brave", "scrape_per_source": 0},
            {"type": "brave", "scrape_per_source": -3},
            {"type": "brave", "scrape_per_source": []},
            {"type": "brave", "scrape_timeout": -1},
            {"type": "brave", "scrape_timeout": "5"},
            {"type": "brave", "scrape_timeout": True},
            {"type": "brave", "scrape_concurrency": 0},
            {"type": "brave", "scrape_concurrency": -1},
            {"type": "brave", "scrape_concurrency": "5"},
            {"type": "brave", "scrape_concurrency": False},
        ]

        for cfg in cases:
            with self.subTest(cfg=cfg):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    json.dump(cfg, f)
                    config_path = f.name

                try:
                    with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                        with mock.patch("scripts.main.load_keys") as load_keys_mock:
                            with self.assertRaises(SystemExit) as cm:
                                main()
                finally:
                    try:
                        import os
                        os.unlink(config_path)
                    except OSError:
                        pass

                self.assertEqual(cm.exception.code, 2)
                load_keys_mock.assert_not_called()

    def test_valid_config_scrape_values_are_used(self):
        scrape_calls = []
        cfg = {
            "type": "brave",
            "counts": {"brave": 1},
            "timeout": 5,
            "scrape_top": 1,
            "scrape_chars": 3,
            "scrape_per_source": 1,
        }

        def fake_scrape(url, *args, **kwargs):
            scrape_calls.append(url)
            return {"url": url, "title": "Fetched", "markdown": "abcdef", "length": 6, "via": "tavily"}

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tvly-key"}):
                    with mock.patch("scripts.main.search_brave", return_value=[{
                        "source": "brave",
                        "title": "Needs content",
                        "url": "https://example.com/needs-content",
                        "description": "snippet",
                    }]):
                        with mock.patch("scripts.main.scrape_url_smart", side_effect=fake_scrape):
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(scrape_calls, ["https://example.com/needs-content"])
        self.assertIn("```untrusted\nabc\n```", stdout.getvalue())

    def test_invalid_config_count_values_exit_before_search(self):
        cases = [
            {"type": "brave", "count": 0},
            {"type": "brave", "count": "5"},
            {"type": "brave", "count": "nope"},
            {"type": "brave", "count": 1.5},
            {"type": "brave", "counts": []},
            {"type": "brave", "counts": "brave=1"},
            {"type": "brave", "counts": {"brave": 0}},
            {"type": "brave", "counts": {"brave": "nope"}},
            {"type": "brave", "counts": {"brave": True}},
            {"type": "brave", "brave_count": "nope"},
        ]

        for cfg in cases:
            with self.subTest(cfg=cfg):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    json.dump(cfg, f)
                    config_path = f.name

                try:
                    with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                        with mock.patch("scripts.main.load_keys") as load_keys_mock:
                            with self.assertRaises(SystemExit) as cm:
                                main()
                finally:
                    try:
                        import os
                        os.unlink(config_path)
                    except OSError:
                        pass

                self.assertEqual(cm.exception.code, 2)
                load_keys_mock.assert_not_called()

    def test_expand_same_text_uses_lite_route_for_expanded_query(self):
        calls = []
        cfg = {"type": "brave", "counts": {"brave": 1, "tavily": 1, "exa": 1}, "timeout": 5, "no_scrape": True}

        def fake_brave(query, api_key, count):
            calls.append(("brave", query))
            return [{"source": "brave", "title": "brave", "url": "https://example.com/brave", "description": ""}]

        def fake_tavily(query, api_key, count):
            calls.append(("tavily", query))
            return [{"source": "tavily", "title": "tavily", "url": "https://example.com/tavily", "description": "", "scraped_content": "x" * 400}]

        def fake_exa(query, api_key, count):
            calls.append(("exa", query))
            return [{"source": "exa", "title": "exa", "url": "https://example.com/exa", "description": "", "scraped_content": "x" * 400}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "same", "--config", config_path, "--expand", "same"]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tvly-key", "exa": "exa-key"}):
                    with mock.patch("scripts.main.search_brave", side_effect=fake_brave):
                        with mock.patch("scripts.main.search_tavily", side_effect=fake_tavily):
                            with mock.patch("scripts.main.search_exa", side_effect=fake_exa):
                                with mock.patch("sys.stdout", new_callable=io.StringIO):
                                    with mock.patch("sys.stderr", new_callable=io.StringIO):
                                        main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(calls.count(("brave", "same")), 1)
        self.assertEqual(calls.count(("tavily", "same")), 1)
        self.assertEqual(calls.count(("exa", "same")), 1)

    def test_cli_expand_overrides_config_expand(self):
        calls = []
        cfg = {
            "type": "brave",
            "counts": {"brave": 1, "tavily": 1, "exa": 1},
            "timeout": 5,
            "no_scrape": True,
            "expand": ["from-config"],
        }

        def fake_brave(query, api_key, count):
            calls.append(("brave", query))
            return []

        def fake_tavily(query, api_key, count):
            calls.append(("tavily", query))
            return []

        def fake_exa(query, api_key, count):
            calls.append(("exa", query))
            return []

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "main", "--config", config_path, "--expand", "from-cli"]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tvly-key", "exa": "exa-key"}):
                    with mock.patch("scripts.main.search_brave", side_effect=fake_brave):
                        with mock.patch("scripts.main.search_tavily", side_effect=fake_tavily):
                            with mock.patch("scripts.main.search_exa", side_effect=fake_exa):
                                with mock.patch("sys.stdout", new_callable=io.StringIO):
                                    with mock.patch("sys.stderr", new_callable=io.StringIO):
                                        main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        called_queries = {query for _, query in calls}
        self.assertIn("main", called_queries)
        self.assertIn("from-cli", called_queries)
        self.assertNotIn("from-config", called_queries)

    def test_expand_outer_future_exception_is_reported_and_scrubbed(self):
        cfg = {"type": "brave", "counts": {"brave": 1}, "timeout": 5, "no_scrape": True}

        def fake_resolve(search_type, lite=False):
            if lite:
                raise RuntimeError("boom tvly-secret")
            return {"brave"}

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "main", "--config", config_path, "--expand", "extra"]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tvly-secret", "exa": "exa-key"}):
                    with mock.patch("scripts.main.resolve_route", side_effect=fake_resolve):
                        with mock.patch("scripts.main.search_brave", return_value=[]):
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        output = stdout.getvalue()
        self.assertIn("multi-search", output)
        self.assertIn("query 'extra' failed", output)
        self.assertNotIn("tvly-secret", output)

    def test_cli_count_overrides_config_source_count(self):
        calls = []
        cfg = {
            "type": "brave",
            "count": None,
            "counts": {"brave": 9},
            "timeout": 5,
        }

        def fake_brave(query, api_key, count):
            calls.append((query, api_key, count))
            return []

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path, "--count", "3"]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "key"}):
                    with mock.patch("scripts.main.search_brave", side_effect=fake_brave):
                        with mock.patch("sys.stdout", new_callable=io.StringIO):
                            with mock.patch("sys.stderr", new_callable=io.StringIO):
                                main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(calls, [("query", "key", 3)])

    def test_global_count_50_propagates_to_serpapi(self):
        """--count 50 --type serpapi should pass 50 (not 20) to search_serpapi."""
        calls = []
        cfg = {"type": "serpapi", "counts": {}, "timeout": 5, "no_scrape": True}

        def fake_serpapi(query, api_key, count, engine):
            calls.append(count)
            return [{"source": "serpapi", "title": "ok", "url": "https://example.com", "description": ""}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name
        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path, "--count", "50"]):
                with mock.patch("scripts.main.load_keys", return_value={"serpapi": "key"}):
                    with mock.patch("scripts.main.search_serpapi", side_effect=fake_serpapi):
                        with mock.patch("sys.stdout", new_callable=io.StringIO):
                            with mock.patch("sys.stderr", new_callable=io.StringIO):
                                main()
        finally:
            try:
                import os; os.unlink(config_path)
            except OSError:
                pass
        self.assertEqual(calls, [50])

    def test_firecrawl_cli_count_resolution(self):
        cases = [
            {
                "label": "route default count",
                "argv": ["search.py", "query", "--type", "firecrawl", "--no-scrape"],
                "cfg": None,
                "expected": 10,
            },
            {
                "label": "global count passthrough",
                "argv": ["search.py", "query", "--type", "firecrawl", "--count", "50", "--no-scrape"],
                "cfg": None,
                "expected": 50,
            },
            {
                "label": "global count clamp",
                "argv": ["search.py", "query", "--type", "firecrawl", "--count", "500", "--no-scrape"],
                "cfg": None,
                "expected": 100,
            },
            {
                "label": "source count override",
                "argv": ["search.py", "query", "--type", "firecrawl", "--firecrawl-count", "12", "--no-scrape"],
                "cfg": None,
                "expected": 12,
            },
            {
                "label": "config counts override",
                "argv": ["search.py", "query"],
                "cfg": {"type": "firecrawl", "counts": {"firecrawl": 17}, "no_scrape": True},
                "expected": 17,
            },
        ]

        for case in cases:
            calls = []
            config_path = None

            def fake_firecrawl(query, api_key, count):
                calls.append((query, api_key, count))
                return []

            argv = list(case["argv"])
            if case["cfg"] is not None:
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    json.dump(case["cfg"], f)
                    config_path = f.name
                argv.extend(["--config", config_path])

            try:
                with self.subTest(case=case["label"]):
                    with mock.patch("sys.argv", argv):
                        with mock.patch("scripts.main.load_keys", return_value={"firecrawl": "fc-key"}):
                            with mock.patch("scripts.main.search_firecrawl", side_effect=fake_firecrawl):
                                with mock.patch("sys.stdout", new_callable=io.StringIO):
                                    with mock.patch("sys.stderr", new_callable=io.StringIO):
                                        main()
            finally:
                if config_path:
                    try:
                        os.unlink(config_path)
                    except OSError:
                        pass

            self.assertEqual(calls, [("query", "fc-key", case["expected"])])

    def test_v2ex_route_uses_firecrawl_key_and_count(self):
        calls = []

        def fake_v2ex(query, api_key, count):
            calls.append((query, api_key, count))
            return [{
                "source": "v2ex",
                "title": "V2EX Topic",
                "url": "https://www.v2ex.com/t/123",
                "description": "",
            }]

        with mock.patch("sys.argv", ["search.py", "claude", "--type", "v2ex", "--count", "7", "--no-scrape"]):
            with mock.patch("scripts.main.load_keys", return_value={"firecrawl": "fc-key"}):
                with mock.patch("scripts.main.search_v2ex", side_effect=fake_v2ex):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            main()

        self.assertEqual(calls, [("claude", "fc-key", 7)])
        self.assertIn("V2EX Topic", stdout.getvalue())

    def test_reddit_route_uses_firecrawl_key_and_count(self):
        calls = []

        def fake_reddit(query, api_key, count):
            calls.append((query, api_key, count))
            return [{
                "source": "reddit",
                "title": "Reddit thread",
                "url": "https://www.reddit.com/r/example/comments/1/thread/",
                "description": "",
            }]

        with mock.patch("sys.argv", ["search.py", "agent memory", "--type", "reddit", "--count", "7", "--no-scrape"]):
            with mock.patch("scripts.main.load_keys", return_value={"firecrawl": "fc-key"}):
                with mock.patch("scripts.main.search_reddit", side_effect=fake_reddit):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            main()

        self.assertEqual(calls, [("agent memory", "fc-key", 7)])
        self.assertIn("Reddit thread", stdout.getvalue())

    def test_zhihu_route_prefers_openapi_key_and_count(self):
        calls = []

        def fake_zhihu(query, api_key, count):
            calls.append((query, api_key, count))
            return [{
                "source": "zhihu",
                "title": "知乎问题",
                "url": "https://www.zhihu.com/question/497594623",
                "description": "",
            }]

        with mock.patch("sys.argv", ["search.py", "AI Agent", "--type", "zhihu", "--count", "50", "--no-scrape"]):
            with mock.patch("scripts.main.load_keys", return_value={"zhihu": "zhihu-secret", "firecrawl": "fc-key"}):
                with mock.patch("scripts.main.search_zhihu", side_effect=fake_zhihu):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            main()

        self.assertEqual(calls, [("AI Agent", "zhihu-secret", 10)])
        self.assertIn("知乎问题", stdout.getvalue())

    def test_zhihu_route_falls_back_to_firecrawl_key(self):
        calls = []

        def fake_zhihu_firecrawl(query, api_key, count):
            calls.append((query, api_key, count))
            return [{
                "source": "zhihu",
                "title": "知乎问题",
                "url": "https://www.zhihu.com/question/497594623",
                "description": "",
            }]

        with mock.patch("sys.argv", ["search.py", "AI Agent", "--type", "zhihu", "--count", "7", "--no-scrape"]):
            with mock.patch("scripts.main.load_keys", return_value={"firecrawl": "fc-key"}):
                with mock.patch("scripts.main.search_zhihu_firecrawl", side_effect=fake_zhihu_firecrawl):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            main()

        self.assertEqual(calls, [("AI Agent", "fc-key", 7)])
        self.assertIn("知乎问题", stdout.getvalue())

    def test_hackernews_route_uses_hackernews_count(self):
        calls = []

        def fake_hackernews(query, count):
            calls.append((query, count))
            return [{
                "source": "hackernews",
                "title": "Hacker News Story",
                "url": "https://news.ycombinator.com/item?id=123",
                "description": "",
            }]

        with mock.patch("sys.argv", ["search.py", "python uv", "--type", "hackernews", "--hackernews-count", "6", "--no-scrape"]):
            with mock.patch("scripts.main.load_keys", return_value={}):
                with mock.patch("scripts.main.search_hackernews", side_effect=fake_hackernews):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            main()

        self.assertEqual(calls, [("python uv", 6)])
        self.assertIn("Hacker News Story", stdout.getvalue())

    def test_stackoverflow_route_uses_stackoverflow_count(self):
        calls = []

        def fake_stackoverflow(query, count):
            calls.append((query, count))
            return [{
                "source": "stackoverflow",
                "title": "Stack Overflow Question",
                "url": "https://stackoverflow.com/questions/1/example",
                "description": "",
            }]

        with mock.patch("sys.argv", ["search.py", "python uv", "--type", "stackoverflow", "--stackoverflow-count", "6", "--no-scrape"]):
            with mock.patch("scripts.main.load_keys", return_value={}):
                with mock.patch("scripts.main.search_stackoverflow", side_effect=fake_stackoverflow):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            main()

        self.assertEqual(calls, [("python uv", 6)])
        self.assertIn("Stack Overflow Question", stdout.getvalue())

    def test_video_route_uses_video_sources_and_does_not_scrape(self):
        youtube_calls = []
        bilibili_calls = []

        def fake_youtube(query, api_key, count):
            youtube_calls.append((query, api_key, count))
            return [{
                "source": "youtube",
                "title": "YouTube Agent Memory",
                "url": "https://www.youtube.com/watch?v=abc123",
                "description": "should not be shown in title-url-only output",
            }]

        def fake_bilibili(query, cookie, count):
            bilibili_calls.append((query, cookie, count))
            return [{
                "source": "bilibili",
                "title": "Bilibili Agent Memory",
                "url": "https://www.bilibili.com/video/BV1xx411c7mD",
                "description": "should not be shown in title-url-only output",
            }]

        with mock.patch(
            "sys.argv",
            ["search.py", "agent memory", "--type", "video", "--count", "7"],
        ):
            with mock.patch("scripts.main.load_keys", return_value={"youtube": "yt-key", "bilibili": "SESSDATA=abc"}):
                with mock.patch("scripts.main.search_youtube", side_effect=fake_youtube):
                    with mock.patch("scripts.main.search_bilibili", side_effect=fake_bilibili):
                        with mock.patch("scripts.main.scrape_url_smart") as scrape_mock:
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()

        output = stdout.getvalue()
        self.assertEqual(youtube_calls, [("agent memory", "yt-key", 7)])
        self.assertEqual(bilibili_calls, [("agent memory", "SESSDATA=abc", 7)])
        scrape_mock.assert_not_called()
        self.assertIn("YouTube Agent Memory", output)
        self.assertIn("https://www.youtube.com/watch?v=abc123", output)
        self.assertIn("Bilibili Agent Memory", output)
        self.assertIn("https://www.bilibili.com/video/BV1xx411c7mD", output)
        self.assertNotIn("should not be shown", output)
        self.assertNotIn("Scraped Content", output)

    def test_firecrawl_metadata_scrape_includes_firecrawl_backend(self):
        scrape_calls = []

        def fake_firecrawl(query, api_key, count):
            return [{
                "source": "firecrawl",
                "title": "Metadata only",
                "url": "https://example.com/firecrawl-result",
                "description": "snippet only",
            }]

        def fake_scrape(url, *args, **kwargs):
            scrape_calls.append((
                url,
                tuple(kwargs.get("backends") or ()),
                tuple(kwargs.get("firecrawl_keys") or ()),
            ))
            return {"url": url, "title": "Fetched", "markdown": "body", "length": 4, "via": "exa"}

        with mock.patch("sys.argv", ["search.py", "query", "--type", "firecrawl"]):
            with mock.patch(
                "scripts.main.load_keys",
                return_value={"firecrawl": "fc-key", "exa": "exa-key", "tavily": "tvly-key"},
            ):
                with mock.patch("scripts.main.search_firecrawl", side_effect=fake_firecrawl):
                    with mock.patch("scripts.main.scrape_url_smart", side_effect=fake_scrape):
                        with mock.patch("sys.stdout", new_callable=io.StringIO):
                            with mock.patch("sys.stderr", new_callable=io.StringIO):
                                main()

        self.assertEqual(
            scrape_calls,
            [("https://example.com/firecrawl-result", ("jina", "exa", "tavily", "firecrawl"), ("fc-key",))],
        )

    def test_serpapi_key_pool_falls_back_on_auth_error(self):
        calls = []
        cfg = {
            "type": "serpapi",
            "counts": {"serpapi": 3},
            "timeout": 5,
            "no_scrape": True,
        }

        def fake_serpapi(query, api_key, count, engine):
            calls.append(api_key)
            if api_key == "bad":
                return [{"source": "serpapi", "error": "HTTP Error 401: Unauthorized"}]
            return [{"source": "serpapi", "title": "ok", "url": "https://example.com", "description": ""}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"serpapi": ["bad", "good"]}):
                    with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
                        with mock.patch("scripts.main.search_serpapi", side_effect=fake_serpapi):
                            with mock.patch("sys.stdout", new_callable=io.StringIO):
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(calls, ["bad", "good"])

    def test_serpapi_key_pool_falls_back_on_partial_retryable_error(self):
        calls = []
        cfg = {
            "type": "serpapi",
            "counts": {"serpapi": 12},
            "timeout": 5,
            "no_scrape": True,
        }

        def fake_serpapi(query, api_key, count, engine):
            calls.append(api_key)
            if api_key == "bad":
                return [
                    {
                        "source": "serpapi",
                        "title": "partial",
                        "url": "https://example.com/partial",
                        "description": "",
                    },
                    {"source": "serpapi", "error": "HTTP 429 quota exceeded"},
                ]
            return [{"source": "serpapi", "title": "ok", "url": "https://example.com/good", "description": ""}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"serpapi": ["bad", "good"]}):
                    with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
                        with mock.patch("scripts.main.search_serpapi", side_effect=fake_serpapi):
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(calls, ["bad", "good"])
        output = stdout.getvalue()
        self.assertIn("https://example.com/good", output)
        self.assertNotIn("https://example.com/partial", output)

    def test_key_pool_preserves_partial_results_when_all_keys_fail(self):
        calls = []
        cfg = {
            "type": "serpapi",
            "counts": {"serpapi": 12},
            "timeout": 5,
            "no_scrape": True,
        }

        def fake_serpapi(query, api_key, count, engine):
            calls.append(api_key)
            return [
                {
                    "source": "serpapi",
                    "title": f"partial {api_key}",
                    "url": f"https://example.com/{api_key}",
                    "description": "",
                },
                {"source": "serpapi", "error": f"HTTP 429 quota exceeded for {api_key}"},
            ]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"serpapi": ["k1", "k2"]}):
                    with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
                        with mock.patch("scripts.main.search_serpapi", side_effect=fake_serpapi):
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(calls, ["k1", "k2"])
        output = stdout.getvalue()
        self.assertIn("https://example.com/k1", output)
        self.assertIn("https://example.com/k2", output)
        self.assertIn("key pool exhausted after 2 key(s)", output)

    def test_batch_timeout_returns_without_waiting_for_slow_source(self):
        cfg = {
            "type": "lite",
            "timeout": 1,
            "no_scrape": True,
        }

        def slow_tavily(query, api_key, count):
            time.sleep(3)
            return [{"source": "tavily", "title": "late", "url": "https://late.example"}]

        def fast_exa(query, api_key, count):
            return [{"source": "exa", "title": "fast", "url": "https://fast.example"}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            started = time.monotonic()
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"tavily": "tvly", "exa": "exa"}):
                    with mock.patch("scripts.main.search_tavily", side_effect=slow_tavily):
                        with mock.patch("scripts.main.search_exa", side_effect=fast_exa):
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
            elapsed = time.monotonic() - started
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertLess(elapsed, 2.2)
        output = stdout.getvalue()
        self.assertIn("https://fast.example", output)
        self.assertIn("timeout after 1s", output)

    def test_scrape_timeout_returns_without_waiting_for_slow_scrape(self):
        cfg = {
            "type": "brave",
            "counts": {"brave": 2},
            "timeout": 5,
            "scrape_top": 2,
            "scrape_timeout": 1,
            "scrape_concurrency": 1,
        }

        def slow_scrape(url, *args, **kwargs):
            time.sleep(3)
            return {"url": url, "title": "late", "markdown": "late body", "length": 9, "via": "jina"}

        brave_results = [
            {
                "source": "brave",
                "title": f"Needs content {idx}",
                "url": f"https://example.com/needs-content-{idx}",
                "description": "snippet",
            }
            for idx in range(2)
        ]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            started = time.monotonic()
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key"}):
                    with mock.patch("scripts.main.search_brave", return_value=brave_results):
                        with mock.patch("scripts.main.scrape_url_smart", side_effect=slow_scrape):
                            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with mock.patch("sys.stderr", new_callable=io.StringIO):
                                    main()
            elapsed = time.monotonic() - started
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertLess(elapsed, 2.2)
        output = stdout.getvalue()
        self.assertIn("scrape timeout after 1s", output)
        self.assertIn("https://example.com/needs-content-0", output)
        self.assertIn("https://example.com/needs-content-1", output)

    def test_scrape_key_pools_are_rotated_per_url(self):
        seen = []
        cfg = {
            "type": "brave",
            "counts": {"brave": 4},
            "timeout": 5,
            "scrape_top": 4,
            "scrape_concurrency": 1,
        }

        brave_results = [
            {
                "source": "brave",
                "title": f"Needs content {idx}",
                "url": f"https://example.com/needs-content-{idx}",
                "description": "snippet",
            }
            for idx in range(4)
        ]

        def fake_scrape(url, *args, **kwargs):
            seen.append((
                url,
                tuple(kwargs.get("exa_keys") or ()),
                tuple(kwargs.get("tavily_keys") or ()),
            ))
            return {"url": url, "title": "Fetched", "markdown": "body", "length": 4, "via": "exa"}

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch(
                    "scripts.main.load_keys",
                    return_value={"brave": "brave-key", "exa": ["e1", "e2"], "tavily": ["t1", "t2"]},
                ):
                    with mock.patch("scripts.keys.random.shuffle", side_effect=lambda xs: None):
                        with mock.patch("scripts.main.search_brave", return_value=brave_results):
                            with mock.patch("scripts.main.scrape_url_smart", side_effect=fake_scrape):
                                with mock.patch("sys.stdout", new_callable=io.StringIO):
                                    with mock.patch("sys.stderr", new_callable=io.StringIO):
                                        main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(
            [exa_keys for _, exa_keys, _ in seen],
            [("e1", "e2"), ("e2", "e1"), ("e1", "e2"), ("e2", "e1")],
        )
        self.assertEqual(
            [tavily_keys for _, _, tavily_keys in seen],
            [("t1", "t2"), ("t2", "t1"), ("t1", "t2"), ("t2", "t1")],
        )

    def test_github_timeout_reports_public_source_name(self):
        cfg = {
            "type": "github",
            "timeout": 1,
            "no_scrape": True,
        }

        def slow_github(query, count, token):
            time.sleep(3)
            return [{"source": "github-repos", "title": "late", "url": "https://github.com/example/late"}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            started = time.monotonic()
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={}):
                    with mock.patch("scripts.main.search_github_repos", side_effect=slow_github):
                        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                            with mock.patch("sys.stderr", new_callable=io.StringIO):
                                main()
            elapsed = time.monotonic() - started
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertLess(elapsed, 2.2)
        output = stdout.getvalue()
        self.assertIn("github-repos", output)
        self.assertIn("timeout after 1s", output)
        self.assertNotIn("github_repos", output)

    def test_prefetched_content_does_not_consume_scrape_top(self):
        scrape_calls = []
        cfg = {
            "type": "default",
            "counts": {"brave": 1, "tavily": 1},
            "timeout": 5,
            "scrape_top": 1,
        }

        def fake_scrape(url, *args, **kwargs):
            scrape_calls.append(url)
            return {"url": url, "title": "Needs content", "markdown": "fetched body", "length": 12, "via": "tavily"}

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tavily-key"}):
                    with mock.patch("scripts.main.search_brave", return_value=[{
                        "source": "brave",
                        "title": "Needs content",
                        "url": "https://example.com/needs-content",
                        "description": "snippet",
                    }]):
                        with mock.patch("scripts.main.search_tavily", return_value=[{
                            "source": "tavily",
                            "title": "Already has content",
                            "url": "https://example.com/already-has-content",
                            "description": "body",
                            "scraped_content": "x" * 400,
                        }]):
                            with mock.patch("scripts.main.search_github_repos", return_value=[]):
                                with mock.patch("scripts.main.search_twitter", return_value=[]):
                                    with mock.patch("scripts.main.scrape_url_smart", side_effect=fake_scrape):
                                        with mock.patch("sys.stdout", new_callable=io.StringIO):
                                            with mock.patch("sys.stderr", new_callable=io.StringIO):
                                                main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(scrape_calls, ["https://example.com/needs-content"])

    def test_prefetched_duplicate_keeps_consensus_without_extra_scrape(self):
        scrape_calls = []
        cfg = {
            "type": "default",
            "counts": {"brave": 1, "tavily": 1},
            "timeout": 5,
            "scrape_top": 1,
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tavily-key"}):
                    with mock.patch("scripts.main.search_brave", return_value=[{
                        "source": "brave",
                        "title": "Snippet result",
                        "url": "https://example.com/same?utm_source=brave",
                        "description": "snippet",
                    }]):
                        with mock.patch("scripts.main.search_tavily", return_value=[{
                            "source": "tavily",
                            "title": "Full result",
                            "url": "https://example.com/same",
                            "description": "body",
                            "scraped_content": "x" * 400,
                        }]):
                            with mock.patch("scripts.main.search_exa", return_value=[]):
                                with mock.patch("scripts.main.search_firecrawl", return_value=[]):
                                    with mock.patch("scripts.main.search_serpapi", return_value=[]):
                                        with mock.patch("scripts.main.search_github_repos", return_value=[]):
                                            with mock.patch("scripts.main.search_twitter", return_value=[]):
                                                with mock.patch("scripts.main.scrape_url_smart", side_effect=lambda url, *a, **k: scrape_calls.append(url)):
                                                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                                                            main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        output = stdout.getvalue()
        self.assertEqual(scrape_calls, [])
        self.assertIn("**【×2】**", output)
        self.assertIn("_from: tavily, brave_", output)

    def test_twitter_content_does_not_block_webpage_scrape_for_same_url(self):
        scrape_calls = []
        cfg = {
            "type": "default",
            "counts": {"brave": 1, "tavily": 1, "twitter": 1},
            "timeout": 5,
            "scrape_top": 1,
        }

        def fake_scrape(url, *args, **kwargs):
            scrape_calls.append(url)
            return {"url": url, "title": "Fetched", "markdown": "body", "length": 4, "via": "tavily"}

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["search.py", "query", "--config", config_path]):
                with mock.patch("scripts.main.load_keys", return_value={"brave": "brave-key", "tavily": "tavily-key"}):
                    with mock.patch("scripts.main.search_brave", return_value=[{
                        "source": "brave",
                        "title": "Article",
                        "url": "https://example.com/article",
                        "description": "snippet",
                    }]):
                        with mock.patch("scripts.main.search_tavily", return_value=[]):
                            with mock.patch("scripts.main.search_github_repos", return_value=[]):
                                with mock.patch("scripts.main.search_twitter", return_value=[{
                                    "source": "twitter",
                                    "title": "Discussion",
                                    "url": "https://example.com/article",
                                    "description": "social signal",
                                    "scraped_content": "tweet text",
                                }]):
                                    with mock.patch("scripts.main.scrape_url_smart", side_effect=fake_scrape):
                                        with mock.patch("sys.stdout", new_callable=io.StringIO):
                                            with mock.patch("sys.stderr", new_callable=io.StringIO):
                                                main()
        finally:
            try:
                import os
                os.unlink(config_path)
            except OSError:
                pass

        self.assertEqual(scrape_calls, ["https://example.com/article"])


if __name__ == "__main__":
    unittest.main()
