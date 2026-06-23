import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_MCP = Path(__file__).resolve().parent / "multi-search-plugin" / "mcp"
if str(PLUGIN_MCP) not in sys.path:
    sys.path.insert(0, str(PLUGIN_MCP))

from src.scrape.scrape import scrape_url_smart
from src.search.search_runner import ROUTE_PROFILES, resolve_route, route_meta
from src.service import MultiSearchRequest, ScrapeRequest, doctor_data, list_sources, run_multi_search, run_scrape
from src.state.key_state import COOLDOWN, SQLiteKeyManager, key_id_for
from src.state.state_store import StateStore
from src.support.format import format_results
import tools
from src.support import config as config_module


class PluginRouteRedesignTests(unittest.TestCase):
    def test_routes_are_semantic_profiles_not_single_provider_aliases(self):
        self.assertEqual(resolve_route("default"), {"brave", "tavily", "exa", "serpapi"})
        self.assertEqual(resolve_route("web"), {"brave", "tavily", "exa", "serpapi"})
        self.assertEqual(resolve_route("fast"), {"deepseek_web", "glm_web", "tavily", "exa"})
        self.assertEqual(resolve_route("expert"), {"brave", "tavily", "exa", "serpapi", "firecrawl"})
        self.assertEqual(resolve_route("social"), {"twitter", "reddit_oauth"})
        self.assertEqual(resolve_route("dev"), {"stackoverflow", "github_repos", "hackernews"})
        self.assertEqual(resolve_route("cn-community"), {"zhihu", "v2ex", "linuxdo"})
        self.assertEqual(resolve_route("video"), {"youtube", "bilibili"})
        self.assertEqual(resolve_route("brave"), set())
        self.assertNotIn("lite", ROUTE_PROFILES)
        self.assertEqual(resolve_route("ignored", lite=True), resolve_route("fast"))

    def test_route_meta_carries_behavior_not_just_sources(self):
        self.assertEqual(route_meta("fast")["scrape_top"], 0)
        self.assertTrue(route_meta("fast")["show_answer"])
        self.assertEqual(route_meta("expert")["scrape_top"], 20)
        self.assertFalse(route_meta("expert")["show_answer"])
        self.assertTrue(route_meta("video")["title_url_only"])

    def test_list_sources_exposes_all_sources_after_single_provider_routes_removed(self):
        data = list_sources()
        self.assertIn("fast", data["routes"])
        self.assertIn("brave", data["sources"])
        self.assertIn("github_repos", data["sources"])
        self.assertNotIn("brave", data["routes"])

    def test_formatter_shows_answers_and_degradation_when_route_requests_it(self):
        output = format_results(
            [
                {"source": "deepseek_web_answer", "answer": "直接总结"},
                {"source": "exa", "title": "Example", "url": "https://example.com", "description": "摘要"},
            ],
            "q",
            show_answer=True,
            degradation={"message": "fast degraded to tavily, exa"},
        )
        self.assertIn("DeepSeek Web Answer", output)
        self.assertIn("直接总结", output)
        self.assertIn("fast degraded to tavily, exa", output)
        self.assertIn("摘要", output)

    def test_formatter_can_hide_snippets_by_route(self):
        output = format_results(
            [{"source": "exa", "title": "Example", "url": "https://example.com", "description": "摘要"}],
            "q",
            show_snippet=False,
        )
        self.assertNotIn("摘要", output)


class PluginKeyStateTests(unittest.TestCase):
    def test_sqlite_key_manager_uses_unused_then_lru_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))
            keys = ["k1", "k2", "k3"]

            first = manager.candidates("exa", keys)
            self.assertEqual([candidate.key for candidate in first], keys)

            manager.record_use("exa", first[0])
            second = manager.candidates("exa", keys)
            self.assertEqual([candidate.key for candidate in second], ["k2", "k3", "k1"])

            manager.record_use("exa", second[0])
            third = manager.candidates("exa", keys)
            self.assertEqual([candidate.key for candidate in third], ["k3", "k1", "k2"])

    def test_scrape_records_key_use_and_result_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))

            def fake_exa(url, key, timeout):
                if key == "bad":
                    return {"url": url, "error": "HTTP 429 rate limit"}
                return {"url": url, "markdown": "ok", "via": "exa"}

            with mock.patch("src.scrape.scrape.scrape_url_exa", side_effect=fake_exa):
                result = scrape_url_smart(
                    "https://example.com",
                    primary="exa",
                    backends=("exa",),
                    exa_keys=["bad", "good"],
                    key_manager=manager,
                )

            self.assertNotIn("error", result)
            rows = {row["key_id"]: row for row in manager.status_rows("exa")}
            bad = rows[key_id_for("exa", "bad")]
            good = rows[key_id_for("exa", "good")]
            self.assertEqual(bad["status"], COOLDOWN)
            self.assertEqual(bad["use_count"], 1)
            self.assertEqual(good["status"], "active")
            self.assertEqual(good["success_count"], 1)
            self.assertEqual(good["use_count"], 1)


class PluginServiceConfigTests(unittest.TestCase):
    def _fake_scrape_stage(self, all_results, **kwargs):
        return {
            "with_content": [],
            "final_without_content": list(all_results),
            "passthrough": [],
            "raw_counts": {},
            "items_to_scrape": [],
            "scrape_errors": [],
            "scrapes": [],
        }

    def test_route_meta_supplies_scrape_count_timeout_and_formatter_defaults(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["timeout"] = config.timeout
                captured["counts"] = config.counts

            def run(self, query, lite=False):
                return [{"source": "deepseek_web_answer", "answer": "fast answer"}]

        def fake_scrape_stage(all_results, **kwargs):
            captured["scrape_top"] = kwargs["scrape_top"]
            return self._fake_scrape_stage(all_results, **kwargs)

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", use_state=False))

        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(captured["counts"]["tavily"], 5)
        self.assertEqual(captured["scrape_top"], 0)
        self.assertIn("DeepSeek Web Answer", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_meta"]["scrape_top"], 0)

    def test_config_and_request_still_override_route_meta(self):
        captured = []

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured.append({"timeout": config.timeout, "counts": config.counts})

            def run(self, query, lite=False):
                return []

        def fake_scrape_stage(all_results, **kwargs):
            captured[-1]["scrape_top"] = kwargs["scrape_top"]
            return self._fake_scrape_stage(all_results, **kwargs)

        with mock.patch("src.service._load_config_safe", return_value={"type": "fast", "timeout": 11, "scrape_top": 2, "count": 4}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage):
            run_multi_search(MultiSearchRequest(query="q", use_state=False))
            run_multi_search(MultiSearchRequest(query="q", scrape_top=3, timeout=12, count=6, use_state=False))

        self.assertEqual(captured[0]["timeout"], 11)
        self.assertEqual(captured[0]["counts"]["tavily"], 4)
        self.assertEqual(captured[0]["scrape_top"], 2)
        self.assertEqual(captured[1]["timeout"], 12)
        self.assertEqual(captured[1]["counts"]["tavily"], 6)
        self.assertEqual(captured[1]["scrape_top"], 3)

    def test_expert_route_uses_route_count_default(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["counts"] = config.counts

            def run(self, query, lite=False):
                return []

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            run_multi_search(MultiSearchRequest(query="q", route="expert", use_state=False))

        self.assertEqual(captured["counts"]["brave"], 12)
        self.assertEqual(captured["counts"]["firecrawl"], 12)

    def test_sources_aliases_bypass_route_without_reintroducing_single_source_routes(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.route_resolver = route_resolver

            def run(self, query, lite=False):
                captured["sources"] = self.route_resolver("default", lite=lite)
                return []

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            run_multi_search(MultiSearchRequest(query="q", sources=["github", "deepseek-web"], use_state=False))

        self.assertEqual(captured["sources"], {"github_repos", "deepseek_web"})

    def test_fast_degradation_is_explicit_when_answer_providers_fail(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "deepseek-web", "error": "missing session"},
                    {"source": "glm-web", "error": "service unavailable"},
                    {"source": "exa", "title": "Fallback", "url": "https://example.com", "description": "fallback summary"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", use_state=False))

        self.assertIn("fast degraded to exa, tavily", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_degradation"]["fallback_sources"], ["exa", "tavily"])

    def test_config_no_scrape_applies_until_request_overrides_it(self):
        captured = []

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.config = config

            def run(self, query, lite=False):
                return []

        def fake_scrape_stage(all_results, **kwargs):
            captured.append(kwargs)
            return {
                "with_content": [],
                "final_without_content": [],
                "passthrough": [],
                "raw_counts": {},
                "items_to_scrape": [],
                "scrape_errors": [],
                "scrapes": [],
            }

        patches = [
            mock.patch("src.service._load_config_safe", return_value={"type": "default", "timeout": 7, "no_scrape": True, "scrape_top": 9}),
            mock.patch("src.service.load_keys", return_value={}),
            mock.patch("src.service.SearchRunner", FakeRunner),
            mock.patch("src.search.registry.build_provider_registry", return_value={}),
            mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            run_multi_search(MultiSearchRequest(query="q", use_state=False))
            run_multi_search(MultiSearchRequest(query="q", scrape_top=3, use_state=False))

        self.assertEqual(captured[0]["scrape_top"], 0)
        self.assertEqual(captured[1]["scrape_top"], 3)

    def test_direct_scrape_passes_configured_jina_keys(self):
        captured = {}

        def fake_scrape(url, **kwargs):
            captured.update(kwargs)
            return {"url": url, "markdown": "ok", "via": "jina"}

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={"jina": ["j1"]}), \
             mock.patch("src.service.scrape_url_smart", side_effect=fake_scrape):
            run_scrape(ScrapeRequest(url="https://example.com", use_state=False))

        self.assertEqual(captured["jina_keys"], ["j1"])

    def test_doctor_reports_config_key_and_state_boundaries(self):
        data = doctor_data(include_keys=False)

        self.assertIn("config_path", data)
        self.assertEqual(data["key_sources"]["file"], "~/.search-keys.json")
        self.assertIn("TAVILY_API_KEY", data["key_sources"]["env"])
        self.assertEqual(data["key_sources"]["state"], data["state_path"])


class PluginEntryLayerTests(unittest.TestCase):
    def test_multi_search_unknown_route_returns_structured_error(self):
        result = tools.multi_search_tool("q", route="discussion", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("valid routes", result["error"])
        self.assertNotIn("markdown", result)

    def test_multi_search_empty_query_returns_structured_error(self):
        result = tools.multi_search_tool("", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertEqual(result["error"], "query is required")

    def test_invalid_output_mode_is_rejected_at_tool_boundary(self):
        result = tools.multi_search_tool("q", output="markdwon", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("both", result["valid_output"])

    def test_set_site_scraper_preference_rejects_unknown_backend(self):
        result = tools.set_site_scraper_preference_tool("example.com", "not-a-backend")
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("jina", result["valid_scrapers"])

    def test_multi_search_use_state_false_skips_state_store(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["key_manager"] = type(key_manager).__name__

            def run(self, query, lite=False):
                return []

        def fake_scrape_stage(all_results, **kwargs):
            return {
                "with_content": [], "final_without_content": [], "passthrough": [],
                "raw_counts": {}, "items_to_scrape": [], "scrape_errors": [], "scrapes": [],
            }

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage):
            tools.multi_search_tool("q", use_state=False)

        self.assertEqual(captured["key_manager"], "BasicKeyManager")

    def test_config_path_prefers_env_then_user_then_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "cfg.json"
            cfg.write_text("{}", encoding="utf-8")
            with mock.patch.dict("os.environ", {config_module.CONFIG_ENV_VAR: str(cfg)}):
                self.assertEqual(config_module.resolve_config_path(), cfg)

    def test_load_config_missing_default_returns_empty_without_raising(self):
        missing = Path(tempfile.gettempdir()) / "definitely-missing-multi-search-config.json"
        with mock.patch.object(config_module, "resolve_config_path", return_value=missing):
            self.assertEqual(config_module.load_config(), {})


if __name__ == "__main__":
    unittest.main()
