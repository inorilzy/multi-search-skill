import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_MCP = Path(__file__).resolve().parent / "multi-search-plugin" / "mcp"
if str(PLUGIN_MCP) not in sys.path:
    sys.path.insert(0, str(PLUGIN_MCP))

from src.scrape.scrape import scrape_url_smart
from src.search.search_runner import (
    ROUTE_PROFILES,
    available_levels,
    level_meta,
    resolve_route,
    route_meta,
)
from src.service import MultiSearchRequest, ScrapeRequest, doctor_data, list_sources, run_multi_search, run_scrape
from src.state.key_state import (
    COOLDOWN,
    INVALID,
    INVALID_STRIKE_LIMIT,
    TRANSIENT_INVALID,
    KeyCandidate,
    KeyOutcome,
    SQLiteKeyManager,
    key_fingerprint,
    key_id_for,
)
from src.state.state_store import StateStore
from src.support.format import format_results
import tools
from src.support import config as config_module
from src.support.dedup import _norm_url, apply_scraped_content, deduplicate, rank_results
from src import service as service_module


class PluginRouteRedesignTests(unittest.TestCase):
    def test_routes_are_semantic_profiles_not_single_provider_aliases(self):
        self.assertEqual(
            resolve_route("default"),
            {"brave", "tavily", "exa", "serpapi", "firecrawl", "baidu", "glm_web", "deepseek_web"},
        )
        self.assertEqual(resolve_route("social"), {"twitter", "reddit_oauth"})
        self.assertEqual(resolve_route("dev"), {"stackoverflow", "github_repos", "hackernews"})
        self.assertEqual(resolve_route("cn-community"), {"zhihu", "v2ex", "linuxdo"})
        self.assertEqual(resolve_route("video"), {"youtube", "bilibili"})
        self.assertEqual(resolve_route("brave"), set())
        self.assertNotIn("lite", ROUTE_PROFILES)
        # fast/expert are now levels (search depth), not routes (source selection).
        self.assertNotIn("fast", ROUTE_PROFILES)
        self.assertNotIn("expert", ROUTE_PROFILES)
        self.assertEqual(resolve_route("ignored", lite=True), resolve_route("default"))

    def test_route_meta_carries_source_shaped_behavior(self):
        # Routes only carry source-shaped defaults; depth/answer live on levels.
        self.assertTrue(route_meta("video")["title_url_only"])
        self.assertEqual(route_meta("default")["scrape_top"], 8)
        self.assertNotIn("search_depth", route_meta("default"))

    def test_level_meta_carries_search_depth_and_answer_behavior(self):
        self.assertEqual(set(available_levels()), {"fast", "normal", "expert"})
        self.assertEqual(level_meta("fast")["search_depth"], "fast")
        self.assertTrue(level_meta("fast")["show_answer"])
        self.assertEqual(level_meta("fast")["scrape_top"], 0)
        self.assertEqual(level_meta("normal")["search_depth"], "normal")
        self.assertFalse(level_meta("normal")["show_answer"])
        self.assertEqual(level_meta("expert")["search_depth"], "deep")
        self.assertEqual(level_meta("expert")["scrape_top"], 20)

    def test_list_sources_exposes_all_sources_after_single_provider_routes_removed(self):
        data = list_sources()
        self.assertIn("default", data["routes"])
        self.assertNotIn("fast", data["routes"])
        self.assertEqual(set(data["levels"]), {"fast", "normal", "expert"})
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


class PluginScrapeReviewFixTests(unittest.TestCase):
    """Covers the adversarial-review scrape-layer fixes (P0-A, P1-B/C, P2-F/G/I)."""

    @staticmethod
    def _candidate(provider, key):
        return KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))

    def test_invalid_401_is_transient_until_strike_limit_then_permanent(self):
        # P0-A: a single 401/403 must NOT permanently kill a key. It cools down
        # and only escalates to a permanent INVALID after repeated strikes.
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))
            cand = self._candidate("exa", "k1")
            outcome = KeyOutcome(success=False, retryable=True, error_type="invalid", error_message="HTTP 401 unauthorized")

            for strike in range(1, INVALID_STRIKE_LIMIT):
                manager.record_result("exa", cand, outcome)
                row = {r["key_id"]: r for r in manager.status_rows("exa")}[cand.key_id]
                self.assertEqual(row["status"], TRANSIENT_INVALID)
                self.assertEqual(row["invalid_strikes"], strike)
                self.assertIsNotNone(row["cooldown_until"])

            # Final strike escalates to permanent INVALID.
            manager.record_result("exa", cand, outcome)
            row = {r["key_id"]: r for r in manager.status_rows("exa")}[cand.key_id]
            self.assertEqual(row["status"], INVALID)
            self.assertEqual(row["invalid_strikes"], INVALID_STRIKE_LIMIT)

    def test_invalid_strikes_reset_on_success_and_other_failures(self):
        # P0-A: the consecutive-invalid streak must reset, otherwise a key
        # accumulates strikes across unrelated, recoverable errors.
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))
            cand = self._candidate("exa", "k1")
            invalid = KeyOutcome(False, True, "invalid", "HTTP 403 forbidden")
            timeout = KeyOutcome(False, True, "timeout", "request timed out")
            success = KeyOutcome(True, False)

            manager.record_result("exa", cand, invalid)
            manager.record_result("exa", cand, timeout)  # breaks streak
            row = {r["key_id"]: r for r in manager.status_rows("exa")}[cand.key_id]
            self.assertEqual(row["invalid_strikes"], 0)

            manager.record_result("exa", cand, invalid)
            manager.record_result("exa", cand, success)  # also resets
            row = {r["key_id"]: r for r in manager.status_rows("exa")}[cand.key_id]
            self.assertEqual(row["invalid_strikes"], 0)
            self.assertEqual(row["status"], "active")

    def test_transient_invalid_key_returns_to_pool_after_cooldown(self):
        # P0-A: a transiently-invalid key with an expired cooldown is usable.
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            manager = SQLiteKeyManager(store)
            cand = self._candidate("exa", "k1")
            manager.record_result("exa", cand, KeyOutcome(False, True, "invalid", "401"))
            # Cooldown still active -> excluded.
            self.assertEqual(manager.candidates("exa", ["k1"]), [])
            # Force the cooldown into the past.
            store.execute(
                "UPDATE key_state SET cooldown_until = ? WHERE provider = ? AND key_id = ?",
                ("2000-01-01T00:00:00+00:00", "exa", cand.key_id),
            )
            self.assertEqual([c.key for c in manager.candidates("exa", ["k1"])], ["k1"])

    def test_explicit_backends_still_append_reddit_fallback(self):
        # P1-B: an explicit backend order from the orchestrator must not drop the
        # policy-mandated reddit fallback for reddit URLs.
        from src.scrape.scrape import _resolve_scrape_policy

        policy = _resolve_scrape_policy(
            "https://www.reddit.com/r/python/comments/abc/title/",
            backends=["jina", "tavily"],
        )
        self.assertEqual(policy["name"], "reddit")
        self.assertEqual(policy["backends"][:2], ["jina", "tavily"])
        self.assertIn("reddit", policy["backends"])

    def test_unknown_and_missing_key_backends_error_eagerly(self):
        # P2-I: forcing an unknown or unconfigured keyed backend yields a clear
        # structured error instead of a generic "no backend available".
        unknown = scrape_url_smart("https://example.com", backends=("does-not-exist",))
        self.assertEqual(unknown["error"], "unknown scrape backend: does-not-exist")

        missing = scrape_url_smart("https://example.com", backends=("exa",))
        self.assertEqual(missing["error"], "missing key for backend: exa")

    def test_jina_routes_through_state_aware_manager_without_shuffle(self):
        # P1-C: Jina key selection now flows through the SQLite key manager LRU
        # order (no random shuffle), shared with the other providers.
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))
            used: list[str] = []

            def fake_jina(url, key, timeout=0, **kwargs):
                used.append(key)
                if key == "":
                    return {"url": url, "error": "Jina: anonymous blocked"}
                return {"url": url, "markdown": "ok", "via": "jina"}

            with mock.patch("src.scrape.scrape.scrape_url_jina", side_effect=fake_jina):
                result = scrape_url_smart(
                    "https://example.com",
                    primary="jina",
                    backends=("jina",),
                    jina_keys=["jk1", "jk2"],
                    jina_prefer_keyed=True,
                    key_manager=manager,
                )

            self.assertNotIn("error", result)
            self.assertEqual(used[0], "jk1")
            rows = {r["key_id"]: r for r in manager.status_rows("jina")}
            self.assertEqual(rows[key_id_for("jina", "jk1")]["use_count"], 1)

    def test_tavily_skips_basic_fallback_once_deadline_passed(self):
        # P2-F: the internal advanced->basic fallback must respect the stage
        # deadline instead of issuing a second blind HTTP round-trip.
        from src.scrape.scrapers import tavily as tavily_mod

        calls: list[str] = []

        def fake_extract(self_depth):  # placeholder, replaced below
            return {}

        class _FakeResp:
            def __init__(self, payload):
                self._payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self):
                import json as _json
                return _json.dumps(self._payload).encode()

        def fake_urlopen(req, timeout=0):
            import json as _json
            depth = _json.loads(req.data).get("extract_depth")
            calls.append(depth)
            # advanced returns an error so a fallback would normally be tried.
            return _FakeResp({"results": [], "failed_results": [{"error": "boom"}]})

        with mock.patch.object(tavily_mod, "urlopen_retry", side_effect=fake_urlopen):
            # deadline already in the past -> only the advanced call runs.
            out = tavily_mod.scrape_url_tavily(
                "https://example.com", "tk", timeout=30, deadline=time.monotonic() - 1,
            )

        self.assertIn("error", out)
        self.assertEqual(calls, ["advanced"])


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

    def test_level_meta_supplies_scrape_and_formatter_defaults(self):
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
            response = run_multi_search(MultiSearchRequest(query="q", level="fast", use_state=False))

        # route defaults to "default" (timeout 60, count 8); level=fast pins scrape_top=0.
        self.assertEqual(captured["timeout"], 60)
        self.assertEqual(captured["counts"]["tavily"], 8)
        self.assertEqual(captured["scrape_top"], 0)
        self.assertIn("DeepSeek Web Answer", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_meta"]["scrape_top"], 0)

    def test_level_is_echoed_in_response_and_diagnostics(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [{"source": "tavily", "title": "t", "url": "https://e.com"}]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", level="expert", use_state=False))

        self.assertEqual(response["level"], "expert")
        level_meta_out = response["diagnostics"]["level_meta"]
        self.assertEqual(level_meta_out["level"], "expert")
        self.assertEqual(level_meta_out["search_depth"], "deep")
        self.assertEqual(level_meta_out["scrape_top"], 20)

    def test_level_defaults_to_normal_and_uses_route_scrape_top(self):
        # normal does not pin scrape_top, so it falls back to the route default (8).
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [{"source": "tavily", "title": "t", "url": "https://e.com"}]

        def fake_scrape_stage(all_results, **kwargs):
            captured["scrape_top"] = kwargs["scrape_top"]
            return self._fake_scrape_stage(all_results, **kwargs)

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", use_state=False))

        self.assertEqual(response["level"], "normal")
        self.assertEqual(captured["scrape_top"], 8)

    def test_expert_level_wires_skip_summarized_into_scrape_stage(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [{"source": "tavily", "title": "t", "url": "https://e.com"}]

        def fake_scrape_stage(all_results, **kwargs):
            captured["skip_summarized_sources"] = kwargs["skip_summarized_sources"]
            return self._fake_scrape_stage(all_results, **kwargs)

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage):
            run_multi_search(MultiSearchRequest(query="q", level="expert", use_state=False))
            self.assertTrue(captured["skip_summarized_sources"])
            run_multi_search(MultiSearchRequest(query="q", level="normal", use_state=False))
            self.assertFalse(captured["skip_summarized_sources"])

    def test_config_supplies_level_when_request_omits_it(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["search_depth"] = config.search_depth

            def run(self, query, lite=False):
                return [{"source": "tavily", "title": "t", "url": "https://e.com"}]

        with mock.patch("src.service._load_config_safe", return_value={"level": "fast"}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", use_state=False))

        # config-provided level drives both the echoed level and the depth.
        self.assertEqual(response["level"], "fast")
        self.assertEqual(captured["search_depth"], "fast")

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

        with mock.patch("src.service._load_config_safe", return_value={"type": "default", "timeout": 11, "scrape_top": 2, "count": 4}), \
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

    def test_search_depth_flows_to_runner_and_diagnostics(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["search_depth"] = config.search_depth

            def run(self, query, lite=False):
                return [{"source": "baidu_answer", "answer": "summary"}]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(
                query="q", sources=["baidu"], search_depth="deep", use_state=False,
            ))

        self.assertEqual(captured["search_depth"], "deep")
        self.assertEqual(response["diagnostics"]["route_meta"]["search_depth"], "deep")

    def test_auto_search_depth_classifies_prompt_complexity(self):
        captured = []

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.config = config

            def run(self, query, lite=False):
                captured.append(self.config.search_depth)
                return [{"source": "baidu_answer", "answer": self.config.search_depth}]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            fast_response = run_multi_search(MultiSearchRequest(
                query="Vue 官网链接", sources=["baidu"], search_depth="auto", use_state=False,
            ))
            deep_response = run_multi_search(MultiSearchRequest(
                query="对比 Codex 和 Claude Code 的优缺点，需要多来源证据", sources=["baidu"], search_depth="auto", use_state=False,
            ))

        self.assertEqual(captured, ["fast", "deep"])
        self.assertEqual(fast_response["diagnostics"]["route_meta"]["search_depth"], "fast")
        self.assertEqual(deep_response["diagnostics"]["route_meta"]["search_depth"], "deep")
        self.assertIn("auto:", deep_response["diagnostics"]["route_meta"]["search_depth_reason"])

    def test_level_pinned_depth_beats_config_auto(self):
        # Config says "auto" but a level that pins a concrete depth (fast/expert)
        # must keep that depth regardless of how the query would classify.
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.config = config

            def run(self, query, lite=False):
                return [{"source": "tavily", "title": "t", "url": "https://e.com"}]

        with mock.patch("src.service._load_config_safe", return_value={"search_depth": "auto"}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            # level=expert + a simple "fast-looking" query must stay deep.
            expert_response = run_multi_search(MultiSearchRequest(
                query="Vue 官网链接", level="expert", use_state=False,
            ))
            # level=fast + a complex "deep-looking" query must stay fast.
            fast_response = run_multi_search(MultiSearchRequest(
                query="对比 Codex 和 Claude Code 的优缺点，需要多来源证据", level="fast", use_state=False,
            ))
            # explicit request value still wins over the level's pinned depth.
            override_response = run_multi_search(MultiSearchRequest(
                query="x", level="expert", search_depth="fast", use_state=False,
            ))

        self.assertEqual(expert_response["diagnostics"]["route_meta"]["search_depth"], "deep")
        self.assertEqual(expert_response["diagnostics"]["route_meta"]["search_depth_reason"], "level")
        self.assertEqual(fast_response["diagnostics"]["route_meta"]["search_depth"], "fast")
        self.assertEqual(override_response["diagnostics"]["route_meta"]["search_depth"], "fast")
        self.assertEqual(override_response["diagnostics"]["route_meta"]["search_depth_reason"], "explicit")

    def test_status_ok_is_reserved_for_provider_status_meta_rows(self):
        # Contract guard: `status == "ok"` marks a ProviderStatus *meta* row
        # (raw_hits accounting), NOT a real search result. The result-counting
        # and degradation logic excludes such rows. If a future searcher emits
        # `status: "ok"` on a genuine result row, that result would be silently
        # dropped from counts and could trigger a false degradation. This test
        # pins the convention so such a regression is caught early.
        real_result = {"source": "tavily", "title": "t", "url": "https://e.com"}
        meta_row = {"source": "tavily", "status": "ok", "raw_hits": 0}

        self.assertEqual(service_module._valid_result_count([real_result, meta_row]), 1)

        # A meta-only result set (no real results) for a route with primary
        # sources must report degradation; adding a real primary result clears it.
        meta = route_meta("social")
        only_meta = [{"source": "twitter", "status": "ok", "raw_hits": 0}]
        self.assertIsNotNone(service_module._route_degradation("social", only_meta, None, meta))
        with_real = only_meta + [{"source": "twitter", "title": "t", "url": "https://e.com"}]
        self.assertIsNone(service_module._route_degradation("social", with_real, None, meta))

    def test_classify_search_depth_is_script_aware_for_short_queries(self):
        classify = service_module._classify_search_depth
        # A short, space-free Chinese query without strong terms is no longer
        # mis-judged as "fast" purely because of its low character count.
        self.assertEqual(classify("Vue和React哪个好")[0], "normal")
        # Chinese research/comparison intent still upgrades to deep.
        self.assertEqual(classify("比较一下Vue和React的SSR方案")[0], "deep")
        # Genuinely tiny lookups still classify as fast.
        self.assertEqual(classify("python")[0], "fast")
        self.assertEqual(classify("Vue 官网链接")[0], "fast")
        # Whitespace-only / empty input is handled gracefully.
        self.assertEqual(classify("   ")[0], "normal")

    def test_route_uses_route_count_default(self):
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
            run_multi_search(MultiSearchRequest(query="q", route="default", use_state=False))

        self.assertEqual(captured["counts"]["brave"], 8)
        self.assertEqual(captured["counts"]["firecrawl"], 8)

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

    def test_social_degradation_is_explicit_when_primary_providers_fail(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "twitter", "error": "missing session"},
                    {"source": "reddit-oauth", "error": "service unavailable"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="social", use_state=False))

        self.assertIn("social primary providers unavailable", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_degradation"]["fallback_sources"], [])

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
        self.assertEqual(set(data["levels"]), {"fast", "normal", "expert"})


class PluginEntryLayerTests(unittest.TestCase):
    def test_multi_search_unknown_route_returns_structured_error(self):
        result = tools.multi_search_tool("q", route="discussion", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("valid routes", result["error"])
        self.assertNotIn("markdown", result)

    def test_multi_search_unknown_level_returns_structured_error(self):
        result = tools.multi_search_tool("q", level="turbo", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("unknown level", result["error"])
        self.assertIn("valid levels", result["error"])
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


class PluginNormUrlTests(unittest.TestCase):
    def test_drops_tracking_params(self):
        norm = _norm_url("https://x.com/a?utm_source=g&fbclid=1&gclid=2&ref=partner&q=hi")
        self.assertIn("q=hi", norm)
        for token in ("utm_source", "fbclid", "gclid", "ref="):
            self.assertNotIn(token, norm)

    def test_keeps_business_params_with_tracking_like_prefixes(self):
        # ref_id / reference / referrer / source_id must NOT be stripped: they
        # identify distinct resources, and dropping them merges separate URLs.
        norm = _norm_url("https://x.com/a?ref_id=99&reference=abc&referrer=g&source_id=7&q=hi")
        for token in ("ref_id=99", "reference=abc", "referrer=g", "source_id=7", "q=hi"):
            self.assertIn(token, norm)

    def test_distinct_ref_id_not_merged(self):
        deduped, _ = deduplicate([
            {"source": "brave", "url": "https://x.com/a?ref_id=1", "title": "A"},
            {"source": "tavily", "url": "https://x.com/a?ref_id=2", "title": "B"},
        ])
        urls = {row["url"] for row in deduped}
        self.assertEqual(len(urls), 2)


class PluginScrapeWritebackTests(unittest.TestCase):
    def test_apply_scraped_content_promotes_longer_markdown(self):
        rows = [{"source": "brave", "url": "https://x.com/a", "scraped_content": "short"}]
        pool = {_norm_url("https://x.com/a"): {"markdown": "x" * 500, "via": "jina"}}
        apply_scraped_content(rows, pool)
        self.assertEqual(rows[0]["scraped_content"], "x" * 500)
        self.assertTrue(rows[0]["scraped"])
        self.assertEqual(rows[0]["scrape_via"], "jina")

    def test_apply_scraped_content_ignores_unrelated_and_shorter(self):
        rows = [{"source": "brave", "url": "https://x.com/a", "scraped_content": "y" * 100}]
        pool = {_norm_url("https://x.com/a"): {"markdown": "z" * 10, "via": "jina"}}
        apply_scraped_content(rows, pool)
        # shorter pooled content must not clobber the existing longer content,
        # but the row is still flagged as scraped.
        self.assertEqual(rows[0]["scraped_content"], "y" * 100)
        self.assertTrue(rows[0]["scraped"])

    def test_scrape_stage_writes_content_back_to_result_rows(self):
        all_results = [{"source": "brave", "url": "https://x.com/a", "title": "A", "description": "d"}]

        def fake_scrape(url, *a, **k):
            return {"url": url, "markdown": "BODY " * 100, "via": "jina"}

        from src.support.cache import JsonCache
        cache = JsonCache(tempfile.mkdtemp(), ttl_seconds=60, enabled=False)
        with mock.patch("src.service.scrape_url_smart", side_effect=fake_scrape):
            stage = service_module._run_scrape_stage(
                all_results, keys={"jina": "k"}, cache=cache, scrape_top=3,
                scrape_per_source=6, scrape_timeout=30, scrape_concurrency=2,
                site_memory=None, key_manager=None,
            )
        enriched = stage["final_without_content"]
        self.assertTrue(any(r.get("scraped_content") for r in enriched))
        self.assertTrue(any(r.get("scraped") for r in enriched))

    def test_scrape_stage_uses_configured_per_url_timeout_not_hardcoded(self):
        # P2-G: the orchestrator per-URL scrape timeout is config-driven, no
        # longer the old hardcoded ``timeout=30``.
        all_results = [{"source": "brave", "url": "https://x.com/a", "title": "A", "description": "d"}]
        seen: list[int] = []

        def fake_scrape(url, *a, **k):
            seen.append(k.get("timeout"))
            return {"url": url, "markdown": "BODY " * 100, "via": "jina"}

        from src.support.cache import JsonCache
        cache = JsonCache(tempfile.mkdtemp(), ttl_seconds=60, enabled=False)
        with mock.patch("src.service.scrape_url_smart", side_effect=fake_scrape):
            service_module._run_scrape_stage(
                all_results, keys={"jina": "k"}, cache=cache, scrape_top=3,
                scrape_per_source=6, scrape_timeout=120, scrape_concurrency=2,
                site_memory=None, key_manager=None, scrape_url_timeout=7,
            )
        self.assertTrue(seen)
        # Bounded by the configured per-URL cap (7), not 30 and not the 120s stage.
        self.assertTrue(all(0 < t <= 7 for t in seen), seen)


class PluginRankingTests(unittest.TestCase):
    def test_scraped_row_ranks_above_consensus_only(self):
        rows = [
            {"source": "a", "url": "https://x.com/p1", "also_from": ["b", "c"]},
            {"source": "d", "url": "https://x.com/p2", "scraped_content": "Z" * 400},
        ]
        ranked = rank_results(rows)
        self.assertEqual(ranked[0]["url"], "https://x.com/p2")

    def test_errors_sink_to_bottom(self):
        rows = [
            {"source": "a", "error": "boom"},
            {"source": "b", "url": "https://x.com/p"},
        ]
        ranked = rank_results(rows)
        self.assertNotIn("error", ranked[0])
        self.assertIn("error", ranked[-1])

    def test_single_source_route_ranks_by_content_length(self):
        # video/dev style: no also_from consensus; ordering must come from
        # content length / stars, not insertion order.
        rows = [
            {"source": "youtube", "url": "https://x.com/short", "scraped_content": "s" * 50},
            {"source": "youtube", "url": "https://x.com/long", "scraped_content": "l" * 900},
        ]
        ranked = rank_results(rows)
        self.assertEqual(ranked[0]["url"], "https://x.com/long")

    def test_json_results_order_matches_markdown_order(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "brave", "url": "https://x.com/lo", "title": "Lo", "description": "d"},
                    {"source": "tavily", "url": "https://x.com/hi", "title": "Hi", "also_from": ["exa"]},
                ]

        def fake_scrape_stage(all_results, **kwargs):
            return {
                "with_content": [],
                "final_without_content": list(all_results),
                "passthrough": [],
                "raw_counts": {}, "items_to_scrape": [], "scrape_errors": [], "scrapes": [],
            }

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", level="fast", use_state=False, output="both"))

        json_urls = [r["url"] for r in response["results"] if r.get("url")]
        markdown = response["markdown"]
        # The JSON order must match the order the URLs appear in the markdown.
        positions = [markdown.find(u) for u in json_urls]
        self.assertEqual(positions, sorted(positions))
        captured["ok"] = True
        self.assertTrue(captured["ok"])


class PluginCanonicalSourceTests(unittest.TestCase):
    def test_github_repos_claims_canonical_over_brave(self):
        deduped, _ = deduplicate([
            {"source": "brave", "url": "https://github.com/foo/bar", "title": "repo"},
            {"source": "github-repos", "url": "https://github.com/foo/bar", "title": "repo", "stars": 10},
        ])
        self.assertEqual(len(deduped), 1)
        row = deduped[0]
        self.assertEqual(row["source"], "github-repos")
        self.assertIn("brave", row.get("also_from", []))

    def test_non_authoritative_host_keeps_first_seen_source(self):
        deduped, _ = deduplicate([
            {"source": "brave", "url": "https://example.com/x", "title": "a"},
            {"source": "tavily", "url": "https://example.com/x", "title": "a"},
        ])
        self.assertEqual(deduped[0]["source"], "brave")
        self.assertIn("tavily", deduped[0].get("also_from", []))


class PluginRegistryConsistencyTests(unittest.TestCase):
    def test_route_meta_covers_every_route_profile(self):
        from src.search.search_runner import ROUTE_META
        missing = set(ROUTE_PROFILES) - set(ROUTE_META)
        self.assertEqual(missing, set(), f"routes without ROUTE_META entry: {sorted(missing)}")

    def test_count_caps_cover_every_default_count(self):
        from src.service import COUNT_CAPS, DEFAULT_COUNTS
        missing = set(DEFAULT_COUNTS) - set(COUNT_CAPS)
        self.assertEqual(missing, set(), f"sources missing a COUNT_CAPS entry: {sorted(missing)}")

    def test_route_profile_sources_are_known(self):
        from src.search.search_runner import ALL_SOURCE_NAMES
        profile_sources = {src for sources in ROUTE_PROFILES.values() for src in sources}
        unknown = profile_sources - ALL_SOURCE_NAMES
        self.assertEqual(unknown, set(), f"routes reference unknown sources: {sorted(unknown)}")

    def test_default_level_is_a_known_level(self):
        from src.search.search_runner import DEFAULT_LEVEL, LEVEL_META
        self.assertIn(DEFAULT_LEVEL, LEVEL_META)
        self.assertIn(DEFAULT_LEVEL, available_levels())

    def test_every_level_pins_a_search_depth(self):
        from src.search.search_runner import LEVEL_META
        for name, meta in LEVEL_META.items():
            self.assertTrue(str(meta.get("search_depth") or "").strip(), name)


if __name__ == "__main__":
    unittest.main()
