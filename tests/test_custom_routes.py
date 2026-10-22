import unittest
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.resolve import (
    resolve_configured_routes,
    resolve_search_plan,
)
from multi_search_mcp.src.search.search_runner import (
    ProviderSpec,
    default_routes_config,
)
from multi_search_mcp.src.support.config import ConfigError


EXPECTED_BUILTINS = {
    "default": {
        "label": "默认（网页综合）",
        "sources": ["brave", "parallel", "tavily", "exa", "serpapi", "firecrawl", "baidu"],
        "timeout": None,
    },
    "fast": {
        "label": "快速",
        "sources": ["baidu", "tavily", "firecrawl", "exa"],
        "timeout": None,
    },
    "all": {
        "label": "全部",
        "sources": [
            "brave", "parallel", "tavily", "exa", "serpapi", "baidu", "firecrawl",
            "twitter", "stackoverflow", "github_repos", "hackernews", "sov2ex",
        ],
        "timeout": None,
    },
    "social": {
        "label": "社交（Twitter）",
        "sources": ["twitter"],
        "timeout": None,
    },
    "dev": {
        "label": "开发者（Stack Overflow / GitHub / Hacker News）",
        "sources": ["stackoverflow", "github_repos", "hackernews"],
        "timeout": None,
    },
}


def request(**overrides):
    values = {
        "query": "routes",
        "route": None,
        "count": None,
        "sources": None,
        "scrape_top": None,
        "scrape_chars": None,
        "scrape_per_source": None,
        "scrape_timeout": None,
        "scrape_concurrency": None,
        "timeout": None,
        "output": "both",
        "title_url_only": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ConfiguredRouteTests(unittest.TestCase):
    def test_missing_routes_initializes_exact_legacy_groups(self):
        self.assertEqual(default_routes_config(), EXPECTED_BUILTINS)
        routes = resolve_configured_routes({})
        self.assertEqual(list(routes), ["default", "fast", "all", "social", "dev"])
        for route_id, expected in EXPECTED_BUILTINS.items():
            self.assertEqual(routes[route_id].label, expected["label"])
            self.assertEqual(list(routes[route_id].sources), expected["sources"])
            self.assertIsNone(routes[route_id].timeout)

    def test_explicit_map_is_complete_and_does_not_restore_deleted_builtins(self):
        config = {
            "type": "focus",
            "routes": {
                "focus": {
                    "label": "  专注  ",
                    "sources": [" github ", "github-repos", " v2ex "],
                }
            },
        }
        plan = resolve_search_plan(request(), config)
        self.assertEqual(plan.route, "focus")
        self.assertEqual(plan.available_routes, ("focus",))
        self.assertEqual(plan.route_sources, {"github_repos", "sov2ex"})
        self.assertEqual(plan.route_defaults["scrape_top"], 20)
        self.assertEqual(
            plan.route_defaults["primary_success_sources"],
            {"github_repos", "sov2ex"},
        )
        self.assertEqual(resolve_configured_routes(config)["focus"].label, "专注")

    def test_builtin_ids_keep_behavior_when_edited(self):
        plan = resolve_search_plan(request(), {
            "type": "fast",
            "routes": {
                "fast": {
                    "label": "Edited fast",
                    "sources": ["hackernews"],
                    "timeout": None,
                }
            },
        })
        self.assertEqual(plan.route_sources, {"hackernews"})
        self.assertEqual(plan.scrape_top, 0)
        self.assertTrue(plan.show_answer)
        self.assertEqual(plan.route_defaults["primary_success_sources"], {"hackernews"})
        self.assertEqual(plan.timeout, 45)

    def test_web_remains_an_alias_but_cannot_be_defined(self):
        plan = resolve_search_plan(request(route="web"), {})
        self.assertEqual(plan.route, "default")
        with self.assertRaisesRegex(ConfigError, "reserved"):
            resolve_configured_routes({
                "routes": {"web": {"label": "Web", "sources": ["hackernews"]}}
            })

    def test_timeout_precedence_is_request_group_config_then_route_meta(self):
        route = {"label": "Fast", "sources": ["hackernews"], "timeout": None}
        base = {"type": "fast", "routes": {"fast": route}}
        self.assertEqual(resolve_search_plan(request(), base).timeout, 45)
        self.assertEqual(resolve_search_plan(request(), {**base, "timeout": 17}).timeout, 17)
        grouped = {**base, "timeout": 17, "routes": {"fast": {**route, "timeout": 9}}}
        self.assertEqual(resolve_search_plan(request(), grouped).timeout, 9)
        self.assertEqual(resolve_search_plan(request(timeout=4), grouped).timeout, 4)

    def test_route_meta_timeouts_match_desktop_effective_timeout_previews(self):
        for route_id, expected in {
            "default": 60,
            "fast": 45,
            "all": 90,
            "social": 60,
            "dev": 60,
        }.items():
            with self.subTest(route_id=route_id):
                self.assertEqual(
                    resolve_search_plan(request(route=route_id), {}).timeout,
                    expected,
                )
        self.assertEqual(resolve_search_plan(request(), {
            "type": "custom",
            "routes": {
                "custom": {
                    "label": "Custom",
                    "sources": ["hackernews"],
                    "timeout": None,
                }
            },
        }).timeout, 60)

    def test_unknown_route_lists_only_current_ids_even_with_source_override(self):
        config = {
            "type": "one",
            "routes": {
                "one": {"label": "One", "sources": ["hackernews"]},
                "two": {"label": "Two", "sources": ["stackoverflow"]},
            },
        }
        with self.assertRaisesRegex(ValueError, r"unknown route: missing; valid routes: one, two"):
            resolve_search_plan(request(route="missing", sources=["hackernews"]), config)

    def test_routes_shape_and_selected_type_are_strictly_validated(self):
        valid = {"ok": {"label": "Ok", "sources": ["hackernews"]}}
        cases = (
            ({"routes": None}, "routes requires a JSON object"),
            ({"routes": {}}, "at least one route"),
            ({"routes": {"UPPER": valid["ok"]}}, "routes ids"),
            ({"routes": {"x" * 65: valid["ok"]}}, "routes ids"),
            ({"routes": {"ok": {"label": " ", "sources": ["hackernews"]}}}, "label"),
            ({"routes": {"ok": {"label": "x" * 81, "sources": ["hackernews"]}}}, "label"),
            ({"routes": {"ok": {"label": "Ok", "sources": []}}}, "sources"),
            ({"routes": {"ok": {"label": "Ok", "sources": ["missing"]}}}, "unknown source"),
            ({"routes": {"ok": {"label": "Ok", "sources": ["hackernews"], "extra": 1}}}, "unknown field"),
            ({"routes": {"ok": {"label": "Ok", "sources": ["hackernews"], "timeout": True}}}, "timeout"),
            ({"routes": {"ok": {"label": "Ok", "sources": ["hackernews"], "timeout": 0}}}, "timeout"),
            ({"routes": {"ok": {"label": "Ok", "sources": ["hackernews"], "timeout": 61}}}, "timeout"),
            ({"routes": valid}, "type references unknown route: default"),
            ({"type": "missing", "routes": valid}, "type references unknown route: missing"),
        )
        for config, message in cases:
            with self.subTest(config=config):
                with self.assertRaisesRegex(ConfigError, message):
                    resolve_search_plan(request(), config)

    def test_legacy_config_without_routes_keeps_existing_route_alias_and_null_behavior(self):
        fast = resolve_search_plan(request(), {"type": "fast"})
        self.assertEqual(fast.route_sources, set(EXPECTED_BUILTINS["fast"]["sources"]))
        self.assertEqual(fast.timeout, 45)
        web = resolve_search_plan(request(), {"type": "web"})
        self.assertEqual(web.route, "default")
        self.assertEqual(web.route_sources, set(EXPECTED_BUILTINS["default"]["sources"]))
        for config in ({}, {"type": None}):
            with self.subTest(config=config):
                plan = resolve_search_plan(request(), config)
                self.assertEqual(plan.route, "default")
                self.assertEqual(
                    plan.route_sources, set(EXPECTED_BUILTINS["default"]["sources"])
                )

    def test_null_type_does_not_choose_an_arbitrary_route_when_default_was_deleted(self):
        with self.assertRaisesRegex(ConfigError, "type references unknown route: default"):
            resolve_search_plan(request(), {
                "type": None,
                "routes": {"only": {"label": "Only", "sources": ["hackernews"]}},
            })

    def test_non_string_types_are_invalid_instead_of_silently_defaulting(self):
        for bad_type in (7, False, [], {}):
            with self.subTest(bad_type=bad_type):
                with self.assertRaisesRegex(ConfigError, "type requires a route id string"):
                    resolve_search_plan(request(), {"type": bad_type})

    def test_custom_route_sources_reach_runner_and_global_disabled_sources_filter_them(self):
        calls = []

        def fake(name):
            def run(*_args, **_kwargs):
                calls.append(name)
                return []
            return run

        providers = {
            name: ProviderSpec(name=name, public_name=name, call=fake(name), key_required=False)
            for name in ("hackernews", "stackoverflow")
        }
        config = {
            "type": "focus",
            "routes": {
                "focus": {
                    "label": "Focus",
                    "sources": ["hackernews", "stackoverflow"],
                    "timeout": 7,
                }
            },
            "disabled_sources": ["stackoverflow"],
            "scrape_timeout": 0,
        }
        with mock.patch("multi_search_mcp.src.core.runtime.load_runtime_keys", return_value={}):
            response = service.run_search_web(
                service.SearchWebRequest(query="fixture", use_state=False),
                config=config,
                providers=providers,
            )
        self.assertEqual(calls, ["hackernews"])
        self.assertEqual(response["route"], "focus")
        self.assertEqual(response["diagnostics"]["route_sources"], ["hackernews", "stackoverflow"])
        self.assertEqual(response["diagnostics"]["active_sources"], ["hackernews"])

    def test_bad_routes_fail_before_provider_execution(self):
        provider = mock.Mock(return_value=[])
        providers = {
            "hackernews": ProviderSpec(
                name="hackernews", public_name="hackernews", call=provider, key_required=False
            )
        }
        with self.assertRaisesRegex(ConfigError, "routes.bad.timeout"):
            service.run_search_web(
                service.SearchWebRequest(query="fixture", use_state=False),
                config={
                    "type": "bad",
                    "routes": {
                        "bad": {
                            "label": "Bad",
                            "sources": ["hackernews"],
                            "timeout": False,
                        }
                    },
                },
                providers=providers,
                keys={},
            )
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
