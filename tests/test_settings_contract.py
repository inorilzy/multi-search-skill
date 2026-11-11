"""T07 settings contract: route timeouts, scrape backend caps and ranking bounds.

The desktop writable ranges live in Rust constants; the CLI ranges live in
Python. These tests read the Rust source as text (no Rust toolchain needed) and
pin both sides, then exercise the CLI behaviour the contract promises.
"""
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src import service
from multi_search_mcp.src.search import rerank, resolve
from multi_search_mcp.src.search.rerank import RerankPolicy
from multi_search_mcp.src.search.resolve import (
    SearchPlanRequest,
    resolve_search_plan,
)
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search_web import run_search_web
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config
from multi_search_mcp.src.support.requests import SearchWebRequest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_RS = ROOT / "desktop" / "src-tauri" / "src" / "settings.rs"
ON = {"mode": "rrf_model", "base_url": "http://gw.test/v1", "model": "m"}


def route_config(timeout):
    return {
        "type": "default",
        "routes": {
            "default": {
                "label": "默认",
                "sources": ["brave"],
                "timeout": timeout,
            }
        },
    }


def provider_rows(source="brave"):
    return [{
        "source": source,
        "title": "Example",
        "url": "https://example.com/one",
        "description": "excerpt",
    }]


class SettingsBoundaryContractTests(unittest.TestCase):
    """The Rust and Python boundary constants must never drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.source = SETTINGS_RS.read_text(encoding="utf-8")

    def rust_const(self, name, kind="u32"):
        match = re.search(rf"pub const {name}: {kind} = (\d+);", self.source)
        self.assertIsNotNone(match, f"{name} missing from settings.rs")
        return int(match.group(1))

    def test_route_timeout_bounds_match_the_desktop(self):
        self.assertEqual((resolve.TIMEOUT_MIN, resolve.TIMEOUT_MAX), (1, 90))
        self.assertEqual(self.rust_const("TIMEOUT_MIN"), resolve.TIMEOUT_MIN)
        self.assertEqual(self.rust_const("TIMEOUT_MAX"), resolve.TIMEOUT_MAX)

    def test_scrape_backend_timeout_bounds_match_the_desktop(self):
        self.assertEqual(
            self.rust_const("SCRAPE_BACKEND_TIMEOUT_MIN"),
            config.SCRAPE_BACKEND_TIMEOUT_MIN,
        )
        self.assertEqual(
            self.rust_const("SCRAPE_BACKEND_TIMEOUT_MAX"),
            config.SCRAPE_BACKEND_TIMEOUT_MAX,
        )
        self.assertEqual(
            self.rust_const("SCRAPE_BACKEND_TIMEOUT_DEFAULT"),
            config.SCRAPE_BACKEND_TIMEOUT_DEFAULT,
        )
        self.assertEqual(config.resolve_backend_timeout({"scrape_backend_timeout": 1}), 1)
        self.assertEqual(config.resolve_backend_timeout({"scrape_backend_timeout": 60}), 60)
        for bad in (0, 61):
            with self.subTest(value=bad), self.assertRaises(config.ConfigError):
                config.resolve_backend_timeout({"scrape_backend_timeout": bad})

    def test_ranking_numeric_bounds_match_the_desktop(self):
        pairs = (
            ("RANKING_CANDIDATE_LIMIT_MIN", rerank.CANDIDATE_LIMIT_RANGE[0], "u32"),
            ("RANKING_CANDIDATE_LIMIT_MAX", rerank.CANDIDATE_LIMIT_RANGE[1], "u32"),
            ("RANKING_BATCH_SIZE_MIN", rerank.BATCH_SIZE_RANGE[0], "u32"),
            ("RANKING_BATCH_SIZE_MAX", rerank.BATCH_SIZE_RANGE[1], "u32"),
            ("RANKING_RERANK_TIMEOUT_MIN", rerank.RERANK_TIMEOUT_RANGE[0], "u32"),
            ("RANKING_RERANK_TIMEOUT_MAX", rerank.RERANK_TIMEOUT_RANGE[1], "u32"),
            ("RANKING_BASE_URL_MAX", rerank.BASE_URL_MAX, "usize"),
            ("RANKING_MODEL_MAX", rerank.MODEL_MAX, "usize"),
        )
        for name, python_value, kind in pairs:
            with self.subTest(name=name):
                self.assertEqual(self.rust_const(name, kind), python_value)


class RouteTimeoutBehaviorTests(unittest.TestCase):
    def test_cli_route_timeouts_61_to_90_are_accepted(self):
        for seconds in (61, 90):
            with self.subTest(seconds=seconds):
                plan = resolve_search_plan(
                    SearchPlanRequest(query="q"), route_config(seconds)
                )
                self.assertEqual(plan.timeout, seconds)

    def test_91_second_route_and_global_timeouts_are_rejected(self):
        with self.assertRaises(config.ConfigError):
            resolve_search_plan(SearchPlanRequest(query="q"), route_config(91))
        with self.assertRaises(config.ConfigError):
            resolve_search_plan(SearchPlanRequest(query="q"), {"timeout": 91})
        with self.assertRaises(config.ConfigError):
            resolve_search_plan(SearchPlanRequest(query="q", timeout=91), {})

    def test_cli_search_runs_with_route_timeouts_61_to_90(self):
        for seconds in (61, 90):
            with self.subTest(seconds=seconds):
                settings = route_config(seconds)
                providers = {
                    "brave": ProviderSpec(
                        "brave", "brave", lambda *_args, **_kwargs: provider_rows(),
                        key_required=False,
                    ),
                }
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch(
                    "multi_search_mcp.src.state.runtime.load_config_safe",
                    return_value=settings,
                ), mock.patch(
                    "multi_search_mcp.src.state.runtime.load_keys", return_value={},
                ), mock.patch(
                    "multi_search_mcp.src.search.registry.build_provider_registry",
                    return_value=providers,
                ):
                    code = cli.main(
                        ["search", "q", "--source", "brave", "--no-fetch", "--no-state"],
                        stdout=stdout, stderr=stderr,
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                payload = json.loads(stdout.getvalue())
                self.assertEqual(
                    [row["url"] for row in payload["results"]],
                    ["https://example.com/one"],
                )


class RankingConfigBehaviorTests(unittest.TestCase):
    def test_mode_rrf_tolerates_unknown_and_legacy_fields(self):
        policy = RerankPolicy.from_config({
            "ranking": {
                "mode": "rrf",
                "reranker_profile_id": "jev_default",
                "candidate_limit": 0,
                "future_key": {"nested": True},
            }
        })
        self.assertFalse(policy.enabled)
        plan = resolve_search_plan(
            SearchPlanRequest(query="q"),
            {"ranking": {"mode": "rrf", "future_key": 1}},
        )
        self.assertEqual(plan.timeout, 60)

    def test_mode_rrf_model_still_rejects_unknown_fields(self):
        with self.assertRaisesRegex(config.ConfigError, "unsupported fields"):
            RerankPolicy.from_config({"ranking": {**ON, "future_key": 1}})
        with self.assertRaisesRegex(config.ConfigError, "unsupported fields"):
            resolve_search_plan(
                SearchPlanRequest(query="q"), {"ranking": {**ON, "future_key": 1}}
            )

    def test_rrf_model_without_base_url_is_a_doctor_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"ranking": {"mode": "rrf_model"}}), encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    config.CONFIG_ENV_VAR: str(path),
                    "HOME": tmp,
                    "USERPROFILE": tmp,
                },
            ), mock.patch(
                "multi_search_mcp.src.diagnostics.StateStore",
                return_value=StateStore(Path(tmp) / "state.sqlite"),
            ), mock.patch(
                "multi_search_mcp.src.state.runtime.load_keys", return_value={},
            ):
                data = service.doctor_data(include_keys=False)
        self.assertEqual(data["config_status"], "error")
        self.assertIn("base_url", data["config_error"])

    def test_search_fails_before_any_provider_when_ranking_is_invalid(self):
        calls = []

        def search(*_args, **_kwargs):
            calls.append("called")
            return provider_rows()

        providers = {
            "brave": ProviderSpec("brave", "brave", search, key_required=False),
        }
        with self.assertRaises(config.ConfigError):
            run_search_web(
                SearchWebRequest(
                    query="q", sources=["brave"], use_state=False,
                ),
                providers=providers, keys={},
                config={"ranking": {"mode": "rrf_model"}},
            )
        self.assertEqual(calls, [])

    def test_resaved_known_only_ranking_block_is_accepted(self):
        # A desktop save writes exactly these known keys, so the CLI must accept it.
        settings = {
            "ranking": {
                "mode": "rrf_model",
                "base_url": "http://gw.test/v1",
                "model": "m",
                "candidate_limit": 50,
                "batch_size": 20,
                "rerank_timeout": 10,
            }
        }
        plan = resolve_search_plan(SearchPlanRequest(query="q"), settings)
        self.assertEqual(plan.timeout, 60)
        self.assertEqual(RerankPolicy.from_config(settings).mode, "rrf_model")


if __name__ == "__main__":
    unittest.main()
