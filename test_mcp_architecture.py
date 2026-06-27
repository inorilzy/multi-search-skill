import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


MCP_ROOT = Path(__file__).resolve().parent / "multi_search_mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from src.scrape.scrape import scrape_url_smart
from src.search.search_runner import (
    ROUTE_PROFILES,
    resolve_route,
    route_meta,
)
from src.search.resolve import resolve_search_plan
from src.service import MultiSearchRequest, ScrapeRequest, doctor_data, list_sources, run_multi_search, run_scrape
from src.state.key_state import (
    COOLDOWN,
    INVALID,
    INVALID_STRIKE_LIMIT,
    QUOTA_EXHAUSTED,
    TRANSIENT_INVALID,
    KeyCandidate,
    KeyOutcome,
    SQLiteKeyManager,
    key_fingerprint,
    key_id_for,
)
from src.state.state_store import StateStore
from src.state.site_memory import ScrapeAttempt, SiteScraperMemory
from src.support.format import format_results
from multi_search_mcp import tools
from src.support import config as config_module
from src.support.dedup import _norm_url, apply_scraped_content, deduplicate, rank_results
from src import service as service_module


class PluginRouteRedesignTests(unittest.TestCase):
    def test_routes_are_semantic_profiles_not_single_provider_aliases(self):
        self.assertEqual(
            resolve_route("default"),
            {"brave", "tavily", "exa", "serpapi", "firecrawl", "baidu", "glm_web", "deepseek_web"},
        )
        self.assertEqual(resolve_route("social"), {"twitter"})
        self.assertEqual(resolve_route("dev"), {"stackoverflow", "github_repos", "hackernews"})
        self.assertEqual(resolve_route("cn-community"), {"zhihu", "v2ex", "linuxdo"})
        self.assertEqual(resolve_route("video"), {"youtube", "bilibili"})
        self.assertEqual(resolve_route("brave"), set())
        self.assertNotIn("lite", ROUTE_PROFILES)
        # ``fast`` is a route of providers that return body content inline.
        self.assertEqual(resolve_route("fast"), {"baidu", "tavily", "firecrawl", "exa"})
        self.assertNotIn("normal", ROUTE_PROFILES)
        self.assertEqual(resolve_route("ignored", lite=True), resolve_route("default"))

    def test_route_meta_carries_source_shaped_behavior(self):
        # Routes carry source-shaped defaults plus inline-content behavior.
        self.assertTrue(route_meta("video")["title_url_only"])
        self.assertEqual(route_meta("default")["scrape_top"], 20)
        self.assertEqual(route_meta("default")["count"], 10)
        self.assertEqual(route_meta("fast")["timeout"], 45)
        self.assertEqual(route_meta("all")["scrape_top"], 30)
        self.assertEqual(route_meta("social")["timeout"], 60)
        self.assertEqual(route_meta("dev")["scrape_top"], 20)
        self.assertEqual(route_meta("cn-community")["scrape_top"], 20)
        self.assertNotIn("search_depth", route_meta("default"))
        self.assertFalse(route_meta("default")["want_content"])

    def test_fast_route_pins_inline_content_and_no_scrape(self):
        meta = route_meta("fast")
        self.assertTrue(meta["want_content"])
        self.assertTrue(meta["show_answer"])
        self.assertEqual(meta["scrape_top"], 0)

    def test_list_sources_exposes_all_sources_after_single_provider_routes_removed(self):
        data = list_sources()
        self.assertIn("default", data["routes"])
        self.assertIn("fast", data["routes"])
        self.assertNotIn("levels", data)
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

    def test_structured_exhausted_flag_marks_jina_key_quota_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))
            cand = self._candidate("jina", "jk1")
            result = {"url": "https://example.com", "error": "Jina: exhausted", "exhausted": True}

            outcome = manager.classify_result("jina", result)
            manager.record_result("jina", cand, outcome)

            row = {r["key_id"]: r for r in manager.status_rows("jina")}[cand.key_id]
            self.assertEqual(outcome.error_type, "quota_exhausted")
            self.assertEqual(row["status"], QUOTA_EXHAUSTED)
            self.assertIsNotNone(row["exhausted_until"])

    def test_jina_rate_limit_without_exhausted_flag_uses_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SQLiteKeyManager(StateStore(Path(tmp) / "state.sqlite"))
            cand = self._candidate("jina", "jk1")
            result = {"url": "https://example.com", "error": "Jina: HTTP 429 rate limit", "rate_limited": True}

            outcome = manager.classify_result("jina", result)
            manager.record_result("jina", cand, outcome)

            row = {r["key_id"]: r for r in manager.status_rows("jina")}[cand.key_id]
            self.assertEqual(outcome.error_type, "rate_limit")
            self.assertEqual(row["status"], COOLDOWN)
            self.assertIsNotNone(row["cooldown_until"])

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

    def test_site_memory_order_is_not_overridden_by_primary_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SiteScraperMemory(StateStore(Path(tmp) / "state.sqlite"))
            url = "https://example.com/article"
            memory.record_attempt(ScrapeAttempt(url, "jina", False, error_message="timeout"))
            memory.record_attempt(ScrapeAttempt(url, "tavily", True, content_length=1000))
            memory.consume_updates()
            calls: list[str] = []

            def fake_jina(url, *args, **kwargs):
                calls.append("jina")
                return {"url": url, "title": "j", "markdown": "j" * 1000, "via": "jina"}

            def fake_tavily(url, *args, **kwargs):
                calls.append("tavily")
                return {"url": url, "title": "t", "markdown": "t" * 1000, "via": "tavily"}

            with mock.patch("src.scrape.scrape.scrape_url_jina", side_effect=fake_jina), \
                 mock.patch("src.scrape.scrape.scrape_url_tavily", side_effect=fake_tavily):
                result = scrape_url_smart(
                    url,
                    primary="jina",
                    backends=("jina", "tavily"),
                    tavily_keys=["tk"],
                    site_memory=memory,
                )

            self.assertEqual(result["via"], "tavily")
            self.assertEqual(calls[:1], ["tavily"])

    def test_primary_backend_still_leads_without_site_memory(self):
        calls: list[str] = []

        def fake_jina(url, *args, **kwargs):
            calls.append("jina")
            return {"url": url, "title": "j", "markdown": "j" * 1000, "via": "jina"}

        def fake_tavily(url, *args, **kwargs):
            calls.append("tavily")
            return {"url": url, "title": "t", "markdown": "t" * 1000, "via": "tavily"}

        with mock.patch("src.scrape.scrape.scrape_url_jina", side_effect=fake_jina), \
             mock.patch("src.scrape.scrape.scrape_url_tavily", side_effect=fake_tavily):
            result = scrape_url_smart(
                "https://example.com/article",
                primary="tavily",
                backends=("jina", "tavily"),
                tavily_keys=["tk"],
            )

        self.assertEqual(result["via"], "tavily")
        self.assertEqual(calls[:1], ["tavily"])

    def test_primary_backend_leads_on_cold_site_with_state_enabled(self):
        # Regression: with use_state=True (default) site_memory is non-None, but
        # a cold site has no learned/pinned order. The planner's per-URL primary
        # must still lead so scrape load spreads across backends instead of
        # collapsing onto enabled[0].
        with tempfile.TemporaryDirectory() as tmp:
            memory = SiteScraperMemory(StateStore(Path(tmp) / "state.sqlite"))
            calls: list[str] = []

            def fake_jina(url, *args, **kwargs):
                calls.append("jina")
                return {"url": url, "title": "j", "markdown": "j" * 1000, "via": "jina"}

            def fake_tavily(url, *args, **kwargs):
                calls.append("tavily")
                return {"url": url, "title": "t", "markdown": "t" * 1000, "via": "tavily"}

            with mock.patch("src.scrape.scrape.scrape_url_jina", side_effect=fake_jina), \
                 mock.patch("src.scrape.scrape.scrape_url_tavily", side_effect=fake_tavily):
                result = scrape_url_smart(
                    "https://cold-example.com/article",
                    primary="tavily",
                    backends=("jina", "tavily"),
                    tavily_keys=["tk"],
                    site_memory=memory,
                )

            self.assertEqual(result["via"], "tavily")
            self.assertEqual(calls[:1], ["tavily"])


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

    def test_fast_route_supplies_scrape_and_formatter_defaults(self):
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

        # The ``fast`` route pins scrape_top=0 (timeout 45, count 10).
        self.assertEqual(captured["timeout"], 45)
        self.assertEqual(captured["counts"]["tavily"], 10)
        self.assertEqual(captured["scrape_top"], 0)
        self.assertIn("DeepSeek Web Answer", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_meta"]["scrape_top"], 0)

    def test_fast_route_is_echoed_in_diagnostics(self):
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
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", use_state=False))

        self.assertEqual(response["route"], "fast")
        route_meta_out = response["diagnostics"]["route_meta"]
        self.assertTrue(route_meta_out["want_content"])
        self.assertEqual(route_meta_out["scrape_top"], 0)
        self.assertEqual(response["diagnostics"]["effective_counts"]["tavily"], 10)
        self.assertEqual(route_meta_out["route_default_count"], 10)

    def test_default_route_uses_route_scrape_top(self):
        # The default route does not pin scrape_top=0; it uses the route default (20).
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

        self.assertEqual(response["route"], "default")
        self.assertEqual(captured["scrape_top"], 20)

    def test_config_supplies_route_when_request_omits_it(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["want_content"] = config.want_content

            def run(self, query, lite=False):
                return [{"source": "tavily", "title": "t", "url": "https://e.com"}]

        with mock.patch("src.service._load_config_safe", return_value={"type": "fast"}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", use_state=False))

        # config-provided route drives both the echoed route and want_content.
        self.assertEqual(response["route"], "fast")
        self.assertTrue(captured["want_content"])

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

    def test_request_count_overrides_configured_per_source_counts(self):
        request = MultiSearchRequest(query="q", route="fast", count=6, use_state=False)
        config = {"counts": {"tavily": 10, "exa": 99}, "count": 4}

        plan = resolve_search_plan(request, config)

        self.assertEqual(plan.effective_counts["tavily"], 6)
        self.assertEqual(plan.effective_counts["exa"], 6)
        self.assertEqual(plan.effective_counts["firecrawl"], 6)

    def test_configured_counts_override_route_defaults_when_request_omits_count(self):
        request = MultiSearchRequest(query="q", route="fast", use_state=False)
        config = {"counts": {"tavily": 10}, "count": 4}

        plan = resolve_search_plan(request, config)

        self.assertEqual(plan.effective_counts["tavily"], 10)
        self.assertEqual(plan.effective_counts["exa"], 4)
        self.assertEqual(plan.route_defaults["count"], 10)

    def test_fast_route_want_content_flows_to_runner_and_diagnostics(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["want_content"] = config.want_content

            def run(self, query, lite=False):
                return [{"source": "baidu_answer", "answer": "summary"}]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(
                query="q", sources=["baidu"], route="fast", use_state=False,
            ))

        self.assertTrue(captured["want_content"])
        self.assertTrue(response["diagnostics"]["route_meta"]["want_content"])

    def test_answer_rows_are_exposed_as_top_level_summary(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {
                        "source": "baidu_answer",
                        "answer": "provider summary",
                        "endpoint": "/v2/ai_search/web_summary",
                        "request_id": "rid",
                    },
                    {"source": "baidu", "title": "Doc", "url": "https://example.com"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", sources=["baidu"], use_state=False))

        self.assertEqual(response["summary"], "provider summary")
        self.assertEqual(response["summaries"][0]["source"], "baidu_answer")
        self.assertEqual(response["summaries"][0]["endpoint"], "/v2/ai_search/web_summary")
        self.assertEqual(response["source_briefs"][0]["source"], "baidu")
        self.assertEqual(response["source_briefs"][0]["brief_type"], "native_answer")
        self.assertEqual(response["source_summaries"][0]["summary_type"], "native_answer")

    def test_source_briefs_cover_url_only_providers(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "baidu_answer", "answer": "baidu summary"},
                    {"source": "baidu", "title": "Baidu result", "url": "https://baidu.example", "description": "baidu snippet"},
                    {"source": "brave", "title": "Brave result", "url": "https://brave.example", "description": "brave snippet"},
                    {"source": "exa", "title": "Exa result", "url": "https://exa.example", "scraped_content": "exa highlights"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", use_state=False))

        by_source = {row["source"]: row for row in response["source_briefs"]}
        self.assertEqual(by_source["baidu"]["brief_type"], "native_answer")
        self.assertEqual(by_source["baidu"]["brief"], "baidu summary")
        self.assertEqual(by_source["brave"]["brief_type"], "result_brief")
        self.assertIn("brave snippet", by_source["brave"]["brief"])
        self.assertEqual(by_source["exa"]["top_urls"], ["https://exa.example"])

    def test_results_expose_public_content_and_body_aliases(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [{
                    "source": "exa",
                    "title": "Doc",
                    "url": "https://example.com",
                    "description": "short result content",
                    "scraped_content": "full page body",
                }]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", sources=["exa"], use_state=False))

        row = response["results"][0]
        self.assertEqual(row["content"], "short result content")
        self.assertEqual(row["body"], "full page body")
        self.assertEqual(row["full_content"], "full page body")

    def test_display_results_expose_verifiable_links(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "baidu_answer", "answer": "summary"},
                    {"source": "baidu", "title": "News", "url": "https://example.com/news", "description": "snippet"},
                    {"source": "exa", "status": "ok", "raw_hits": 1},
                    {"source": "tavily", "error": "boom"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", sources=["baidu"], use_state=False))

        self.assertEqual(response["display_results"], [{
            "title": "News",
            "url": "https://example.com/news",
            "source": "baidu",
            "snippet": "snippet",
        }])

    def test_display_results_snippet_is_truncated(self):
        from src.service import DISPLAY_SNIPPET_CHARS

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {
                        "source": "baidu",
                        "title": "Long",
                        "url": "https://example.com/long",
                        "scraped_content": "x" * 5000,
                    },
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", sources=["baidu"], use_state=False))

        snippet = response["display_results"][0]["snippet"]
        self.assertLessEqual(len(snippet), DISPLAY_SNIPPET_CHARS)
        # results[] keeps the full body so callers that need it are unaffected.
        full = next(r for r in response["results"] if r.get("url") == "https://example.com/long")
        self.assertEqual(len(full.get("scraped_content") or ""), 5000)

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

        self.assertEqual(captured["counts"]["brave"], 10)
        self.assertEqual(captured["counts"]["firecrawl"], 10)

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

    def test_expand_query_thread_pool_is_capped(self):
        captured: dict[str, int] = {}
        original_executor = service_module.concurrent.futures.ThreadPoolExecutor

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [{"source": "brave", "title": query, "url": f"https://example.com/{query}"}]

        def tracking_executor(*args, **kwargs):
            captured["max_workers"] = kwargs.get("max_workers", args[0] if args else None)
            return original_executor(*args, **kwargs)

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage), \
             mock.patch("src.service.concurrent.futures.ThreadPoolExecutor", side_effect=tracking_executor):
            run_multi_search(MultiSearchRequest(
                query="q",
                route="default",
                expand=[f"q{i}" for i in range(20)],
                use_state=False,
            ))

        self.assertLessEqual(captured["max_workers"], 5)

    def test_social_degradation_is_explicit_when_primary_providers_fail(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "twitter", "error": "missing session"},
                    {"source": "twitter", "error": "service unavailable"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="social", use_state=False))

        self.assertIn("social primary providers unavailable", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_degradation"]["fallback_sources"], [])

    def test_default_degradation_is_explicit_when_primary_providers_fail(self):
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "brave", "error": "down"},
                    {"source": "tavily", "error": "down"},
                    {"source": "exa", "error": "down"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="default", use_state=False))

        self.assertIn("default primary providers unavailable", response["markdown"])
        self.assertEqual(response["diagnostics"]["route_degradation"]["route"], "default")

    def test_public_source_name_success_prevents_false_degradation(self):
        # Regression: result rows use public names (deepseek-web) while
        # primary_success_sources uses internal names (deepseek_web). A genuine
        # success must normalize-match so degradation does not falsely fire.
        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                pass

            def run(self, query, lite=False):
                return [
                    {"source": "brave", "error": "down"},
                    {"source": "tavily", "error": "down"},
                    {"source": "deepseek-web", "title": "ok", "url": "https://x.example/a", "description": "d"},
                ]

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            response = run_multi_search(MultiSearchRequest(query="q", route="default", use_state=False))

        self.assertIsNone(response["diagnostics"]["route_degradation"])

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

    def test_direct_scrape_json_result_respects_scrape_chars(self):
        body = "x" * 100

        def fake_scrape(url, **kwargs):
            return {"url": url, "title": "Doc", "markdown": body, "length": len(body), "via": "jina"}

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.scrape_url_smart", side_effect=fake_scrape):
            response = run_scrape(ScrapeRequest(
                url="https://example.com",
                scrape_chars=12,
                output="json",
                use_state=False,
            ))

        self.assertEqual(response["result"]["markdown"], "x" * 12)
        self.assertEqual(response["result"]["length"], 100)

    def test_tavily_requests_provider_answer(self):
        from src.search.searchers import tavily as tavily_mod

        captured = {}

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"answer":"fast answer","results":[]}'

        def fake_urlopen(req, timeout=0):
            import json as _json
            captured.update(_json.loads(req.data))
            return _FakeResp()

        with mock.patch.object(tavily_mod, "urlopen_retry", side_effect=fake_urlopen):
            rows = tavily_mod.search_tavily("q", "tk", want_content=True)

        self.assertEqual(captured["search_depth"], "basic")
        self.assertEqual(captured["include_answer"], "basic")
        self.assertEqual(captured["include_raw_content"], "markdown")
        self.assertEqual(rows[0]["source"], "tavily_answer")

    def test_doctor_reports_config_key_and_state_boundaries(self):
        data = doctor_data(include_keys=False)

        self.assertIn("config_path", data)
        self.assertEqual(data["key_sources"]["file"], "~/.search-keys.json")
        self.assertIn("TAVILY_API_KEY", data["key_sources"]["env"])
        self.assertEqual(data["key_sources"]["state"], data["state_path"])
        self.assertNotIn("levels", data)


class PluginDisabledSourcesTests(unittest.TestCase):
    def _fake_scrape_stage(self, all_results, **kwargs):
        return {
            "with_content": [], "final_without_content": list(all_results), "passthrough": [],
            "raw_counts": {}, "items_to_scrape": [], "scrape_errors": [], "scrapes": [],
        }

    def _run(self, config, request, runner_cls):
        with mock.patch("src.service._load_config_safe", return_value=config), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", runner_cls), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=self._fake_scrape_stage):
            return run_multi_search(request)

    def test_route_default_sources_exclude_disabled(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.route_resolver = route_resolver

            def run(self, query, lite=False):
                captured["sources"] = self.route_resolver("default", lite=lite)
                return []

        response = self._run(
            {"disabled_sources": ["brave", "serpapi"]},
            MultiSearchRequest(query="q", route="default", use_state=False),
            FakeRunner,
        )

        self.assertNotIn("brave", captured["sources"])
        self.assertNotIn("serpapi", captured["sources"])
        self.assertIn("baidu", captured["sources"])
        self.assertEqual(response["diagnostics"]["disabled_sources"], ["brave", "serpapi"])
        self.assertNotIn("brave", response["diagnostics"]["active_sources"])
        self.assertIn("brave", response["diagnostics"]["route_sources"])

    def test_explicit_source_fully_disabled_returns_structured_error(self):
        with mock.patch("src.service._load_config_safe", return_value={"disabled_sources": ["brave"]}), \
             mock.patch("src.service.load_keys", return_value={}):
            result = tools.multi_search_tool("q", sources=["brave"], use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("all selected sources are disabled", result["error"])

    def test_disabled_source_alias_is_normalized(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.route_resolver = route_resolver

            def run(self, query, lite=False):
                captured["sources"] = self.route_resolver("default", lite=lite)
                return []

        self._run(
            {"disabled_sources": ["deepseek-web"]},
            MultiSearchRequest(query="q", route="default", use_state=False),
            FakeRunner,
        )
        self.assertNotIn("deepseek_web", captured["sources"])

    def test_unknown_disabled_source_is_invalid_request(self):
        with mock.patch("src.service._load_config_safe", return_value={"disabled_sources": ["not-a-source"]}), \
             mock.patch("src.service.load_keys", return_value={}):
            result = tools.multi_search_tool("q", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("unknown disabled source", result["error"])

    def test_disabled_sources_non_list_is_invalid_request(self):
        # Exercise the real config_list ConfigError -> ValueError -> invalid_request path.
        from src.support.config import config_list, ConfigError
        with self.assertRaises(ConfigError):
            config_list({"disabled_sources": "brave"}, "disabled_sources")

    def test_expand_lite_queries_skip_disabled_without_error(self):
        runs = []

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                self.route_resolver = route_resolver

            def run(self, query, lite=False):
                runs.append((query, sorted(self.route_resolver("default", lite=lite))))
                return [{"source": "baidu", "title": "t", "url": "https://e.com"}]

        # Disable everything the lite/default route would use except baidu so the
        # primary query still has an active source and expand queries (lite=True)
        # do not raise even if their set shrinks.
        response = self._run(
            {"disabled_sources": ["brave", "tavily", "exa", "serpapi", "firecrawl", "glm_web", "deepseek_web"]},
            MultiSearchRequest(query="q", route="default", expand=["q2"], use_state=False),
            FakeRunner,
        )
        self.assertEqual(response["route"], "default")
        self.assertTrue(runs)
        for _query, sources in runs:
            self.assertEqual(sources, ["baidu"])


class PluginEntryLayerTests(unittest.TestCase):
    def test_multi_search_unknown_route_returns_structured_error(self):
        result = tools.multi_search_tool("q", route="discussion", use_state=False)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("valid routes", result["error"])
        self.assertNotIn("markdown", result)

    def test_multi_search_web_route_uses_default_profile(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, providers, route_resolver=None, key_manager=None):
                captured["route"] = config.route

            def run(self, query, lite=False):
                return []

        with mock.patch("src.service._load_config_safe", return_value={}), \
             mock.patch("src.service.load_keys", return_value={}), \
             mock.patch("src.service.SearchRunner", FakeRunner), \
             mock.patch("src.search.registry.build_provider_registry", return_value={}), \
             mock.patch("src.service._run_scrape_stage", side_effect=lambda all_results, **kwargs: {
                 "with_content": [], "final_without_content": [], "passthrough": [],
                 "raw_counts": {}, "items_to_scrape": [], "scrape_errors": [], "scrapes": [],
             }):
            result = tools.multi_search_tool("q", route="web", use_state=False)

        self.assertNotIn("error", result)
        self.assertEqual(captured["route"], "default")
        self.assertEqual(result["route"], "default")

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

    def test_scrape_stage_completion_is_driven_by_plan_items_not_candidates(self):
        from src.scrape.scrape_planner import ScrapeKeyPools, ScrapePlan, ScrapePlanItem
        from src.support.cache import JsonCache

        candidates = [
            {"source": "brave", "url": "https://x.com/a", "title": "A"},
            {"source": "brave", "url": "https://x.com/b", "title": "B"},
        ]
        fake_plan = ScrapePlan(
            with_content=[],
            final_without_content=list(candidates),
            passthrough=[],
            raw_counts={"brave": 2},
            content_pool={},
            scrape_candidates=list(candidates),
            items_to_scrape=list(candidates),
            source_quota={"brave": 2},
            backend_order=["jina"],
            plan_items=[ScrapePlanItem(0, candidates[0], "jina", ScrapeKeyPools(jina=["jk"]))],
        )

        def fake_scrape(url, *a, **k):
            return {"url": url, "markdown": "BODY " * 100, "via": "jina"}

        cache = JsonCache(tempfile.mkdtemp(), ttl_seconds=60, enabled=False)
        started = time.monotonic()
        with mock.patch("src.service.plan_scrapes", return_value=fake_plan), \
             mock.patch("src.service.scrape_url_smart", side_effect=fake_scrape):
            stage = service_module._run_scrape_stage(
                candidates, keys={"jina": "jk"}, cache=cache, scrape_top=2,
                scrape_per_source=6, scrape_timeout=1, scrape_concurrency=1,
                site_memory=None, key_manager=None,
            )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        self.assertEqual(len(stage["scrape_errors"]), 0)
        self.assertEqual(stage["scrapes"][0]["url"], "https://x.com/a")


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
            response = run_multi_search(MultiSearchRequest(query="q", route="fast", use_state=False, output="both"))

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

if __name__ == "__main__":
    unittest.main()
