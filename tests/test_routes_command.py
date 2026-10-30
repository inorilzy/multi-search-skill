"""`multi-search routes` reports the routes the current settings would use."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.search.resolve import SearchPlanRequest, resolve_search_plan
from multi_search_mcp.src.support import config

BUILTIN_IDS = ["default", "fast", "all", "social", "dev"]


class RoutesCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        patcher = mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: str(self.path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        # The command must never open the credential store or touch the network.
        for target in (
            "multi_search_mcp.src.support.credential_store.default_store",
            "socket.getaddrinfo",
            "socket.socket.connect",
        ):
            guard = mock.patch(target, side_effect=AssertionError(f"unexpected access: {target}"))
            guard.start()
            self.addCleanup(guard.stop)

    def write_config(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def routes_json(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["routes", *extra], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def test_without_routes_setting_lists_five_builtins_with_default_marked(self):
        self.write_config({})
        payload = self.routes_json()
        self.assertEqual(payload["default_route"], "default")
        self.assertEqual(payload["aliases"], {"web": "default"})
        self.assertEqual([route["id"] for route in payload["routes"]], BUILTIN_IDS)
        by_id = {route["id"]: route for route in payload["routes"]}
        self.assertTrue(by_id["default"]["is_default"])
        self.assertFalse(by_id["dev"]["is_default"])
        self.assertEqual(by_id["dev"]["label"], "开发者（Stack Overflow / GitHub / Hacker News）")
        self.assertEqual(by_id["dev"]["sources"], ["stackoverflow", "github_repos", "hackernews"])
        self.assertIsNone(by_id["dev"]["timeout"])
        for route in payload["routes"]:
            self.assertEqual(
                set(route), {"id", "label", "sources", "disabled_sources", "timeout", "is_default"}
            )

    def test_custom_route_appears_in_settings_order_and_deleted_builtin_is_absent(self):
        self.write_config({
            "routes": {
                "research": {"label": "研究", "sources": ["exa", "tavily"], "timeout": 30},
                "fast": {"label": "快速", "sources": ["baidu"], "timeout": None},
                "default": {"label": "默认", "sources": ["brave"], "timeout": None},
            },
        })
        payload = self.routes_json()
        self.assertEqual([route["id"] for route in payload["routes"]], ["research", "fast", "default"])
        research = payload["routes"][0]
        self.assertEqual(research["sources"], ["exa", "tavily"])
        self.assertEqual(research["timeout"], 30)
        self.assertNotIn("dev", [route["id"] for route in payload["routes"]])

    def test_changing_type_moves_default_marker_and_default_route(self):
        self.write_config({"type": "dev"})
        payload = self.routes_json()
        self.assertEqual(payload["default_route"], "dev")
        flags = {route["id"]: route["is_default"] for route in payload["routes"]}
        self.assertTrue(flags["dev"])
        self.assertFalse(flags["default"])
        self.assertEqual(sum(flags.values()), 1)

    def test_globally_disabled_source_moves_from_sources_to_disabled_sources(self):
        self.write_config({"disabled_sources": ["github_repos", "stackoverflow"]})
        payload = self.routes_json()
        by_id = {route["id"]: route for route in payload["routes"]}
        self.assertEqual(by_id["dev"]["sources"], ["hackernews"])
        self.assertEqual(by_id["dev"]["disabled_sources"], ["stackoverflow", "github_repos"])
        for route in payload["routes"]:
            self.assertEqual(set(route["sources"]) & set(route["disabled_sources"]), set())

    def test_disabled_sources_is_empty_when_no_source_is_disabled(self):
        self.write_config({})
        for route in self.routes_json()["routes"]:
            with self.subTest(route=route["id"]):
                self.assertEqual(route["disabled_sources"], [])

    def test_source_order_follows_route_settings_order(self):
        self.write_config({
            "disabled_sources": ["exa"],
            "routes": {
                "research": {"label": "研究", "sources": ["tavily", "exa", "brave", "baidu"], "timeout": None},
                "default": {"label": "默认", "sources": ["brave"], "timeout": None},
            },
        })
        research = self.routes_json()["routes"][0]
        self.assertEqual(research["sources"], ["tavily", "brave", "baidu"])
        self.assertEqual(research["disabled_sources"], ["exa"])

    def test_every_listed_id_is_accepted_by_search_route_planning(self):
        self.write_config({
            "routes": {
                "research": {"label": "研究", "sources": ["exa"], "timeout": None},
                "default": {"label": "默认", "sources": ["brave"], "timeout": None},
            },
            "type": "research",
        })
        payload = self.routes_json()
        config_dict = config.load_config()
        for route in payload["routes"]:
            with self.subTest(route=route["id"]):
                plan = resolve_search_plan(SearchPlanRequest(query="q", route=route["id"]), config_dict)
                self.assertEqual(plan.route, route["id"])
        plan = resolve_search_plan(SearchPlanRequest(query="q", route="web"), config_dict)
        self.assertEqual(plan.route, "default")

    def test_each_run_reads_current_settings(self):
        self.write_config({"type": "fast"})
        self.assertEqual(self.routes_json()["default_route"], "fast")
        self.write_config({"type": "dev"})
        self.assertEqual(self.routes_json()["default_route"], "dev")

    def test_explicit_format_json_matches_default(self):
        self.write_config({})
        self.assertEqual(self.routes_json(), self.routes_json("--format", "json"))

    def routes_text(self, output_format):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["routes", "--format", output_format], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        return stdout.getvalue()

    def test_human_output_lists_every_route_id_source_and_marks_default(self):
        self.write_config({"type": "dev"})
        text = self.routes_text("human")
        self.assertTrue(text.strip())
        self.assertIn("default_route: dev", text)
        self.assertIn("web -> default", text)
        for route_id in BUILTIN_IDS:
            self.assertIn(f"- {route_id}", text)
        self.assertIn("- dev (default): 开发者（Stack Overflow / GitHub / Hacker News）", text)
        self.assertIn("sources: stackoverflow, github_repos, hackernews", text)
        self.assertNotIn("- default (default)", text)

    def test_markdown_output_is_table_with_default_marked(self):
        self.write_config({"routes": {"research": {"label": "x|y", "sources": ["exa"], "timeout": None}}, "type": "research"})
        text = self.routes_text("markdown")
        self.assertTrue(text.strip())
        self.assertIn("Default route: `research`", text)
        self.assertIn("Aliases: web -> default", text)
        self.assertIn("| Route | Default | Label | Sources |", text)
        self.assertIn("| `research` | yes | x\\|y | exa |", text)

    def test_human_output_with_no_routes_setting_shows_builtin_default(self):
        self.write_config({})
        text = self.routes_text("human")
        self.assertIn("default_route: default", text)
        self.assertIn("- default (default): ", text)

    def test_routes_is_listed_in_top_level_help(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit) as exit_info:
            cli.build_parser().parse_args(["--help"])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertIn("routes", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
