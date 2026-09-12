"""Explicit invalid defaults fail before providers and remain diagnosable."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli, tools
from multi_search_mcp.src import service
from multi_search_mcp.src.search.resolve import COUNT_CAPS, build_counts, resolve_search_plan
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config


BAD_CONFIGS = (
    ("timeout", "typo"),
    ("scrape_timeout", []),
    ("scrape_concurrency", "oops"),
    ("counts", "bad"),
)


class ExplicitConfigValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.store = StateStore(Path(self.temp.name) / "state.sqlite")
        self.provider = mock.Mock(return_value=[])
        providers = {"hackernews": ProviderSpec(
            name="hackernews", public_name="hackernews", call=self.provider,
        )}
        for patcher in (
            mock.patch.dict(os.environ, {config.CONFIG_ENV_VAR: str(self.path)}),
            mock.patch.object(service, "load_keys", return_value={}),
            mock.patch.object(service, "StateStore", return_value=self.store),
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry", return_value=providers),
            mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")),
            mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_config(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")
        self.provider.reset_mock()

    def test_search_rejects_bad_config_before_provider(self):
        for field, value in BAD_CONFIGS:
            for entrypoint in (service.run_search_web, service.run_multi_search):
                with self.subTest(field=field, entrypoint=entrypoint.__name__):
                    self.write_config({field: value})
                    with self.assertRaisesRegex(config.ConfigError, field):
                        entrypoint({"query": "test", "sources": ["hackernews"]})
                    self.provider.assert_not_called()

    def test_doctor_reports_bad_field(self):
        for field, value in BAD_CONFIGS:
            with self.subTest(field=field):
                self.write_config({field: value})
                data = service.doctor_data(include_keys=False)
                self.assertEqual(data["config_status"], "error")
                self.assertFalse(data["config_loaded"])
                self.assertIn(field, data["config_error"])
                self.assertFalse(data["network_checked"])
                self.provider.assert_not_called()

    def test_cli_search_and_doctor_report_bad_fields_in_all_formats(self):
        for field, value in BAD_CONFIGS:
            for output_format in ("json", "human", "markdown"):
                for command in (["search", "test", "--source", "hackernews"], ["doctor", "--no-keys"]):
                    with self.subTest(field=field, output_format=output_format, command=command[0]):
                        self.write_config({field: value})
                        stdout, stderr = io.StringIO(), io.StringIO()
                        code = cli.main(command + ["--format", output_format], stdout=stdout, stderr=stderr)
                        self.assertEqual(code, 1)
                        if command[0] == "doctor":
                            self.assertIn(field, stdout.getvalue())
                            if output_format == "json":
                                self.assertEqual(json.loads(stdout.getvalue())["config_status"], "error")
                        else:
                            self.assertIn(field, stderr.getvalue())
                        self.provider.assert_not_called()

    def test_mcp_returns_invalid_request_and_doctor_error(self):
        for field, value in BAD_CONFIGS:
            with self.subTest(field=field):
                self.write_config({field: value})
                for entrypoint in (tools.search_web_tool, tools.multi_search_tool):
                    data = entrypoint("test", sources=["hackernews"])
                    self.assertEqual(data.get("error_type"), "invalid_request")
                    self.assertIn(field, data["error"])
                data = tools.doctor_tool(include_keys=False)
                self.assertEqual(data["config_status"], "error")
                self.assertIn(field, data["config_error"])
                self.provider.assert_not_called()

    def test_missing_and_null_defaults_are_unchanged(self):
        request = service.MultiSearchRequest(query="test")
        default = resolve_search_plan(request, {})
        self.assertEqual(
            (default.timeout, default.scrape_top, default.scrape_chars,
             default.scrape_per_source, default.scrape_timeout,
             default.scrape_url_timeout, default.scrape_concurrency),
            (60, 20, 1200, 6, 60, 60, 5),
        )
        self.assertEqual(set(default.effective_counts.values()), {10})
        nulls = dict.fromkeys((
            "timeout", "scrape_top", "scrape_chars", "scrape_per_source",
            "scrape_timeout", "scrape_url_timeout", "scrape_concurrency", "count", "counts",
        ))
        self.assertEqual(resolve_search_plan(request, nulls), default)
        for defaults in ({}, nulls):
            self.write_config(defaults)
            self.assertEqual(service.doctor_data(include_keys=False)["config_status"], "ok")
            service.run_search_web({"query": "test", "sources": ["hackernews"]})
            self.provider.assert_called_once()
        fast = resolve_search_plan(service.MultiSearchRequest(query="test", route="fast"), {})
        self.assertEqual((fast.timeout, fast.scrape_top), (45, 0))

    def test_int_conversion_and_clamping_remain_compatible(self):
        minimums = {
            "timeout": 0, "scrape_top": 0, "scrape_timeout": 0, "scrape_url_timeout": 0,
            "scrape_chars": 1, "scrape_per_source": 1, "scrape_concurrency": 1,
        }
        for field, minimum in minimums.items():
            for value, integer in ((" 12 ", 12), ("0", 0), ("-4", -4), (2.9, 2), (False, 0), (True, 1)):
                with self.subTest(field=field, value=value):
                    plan = resolve_search_plan(service.MultiSearchRequest(query="test"), {field: value})
                    self.assertEqual(getattr(plan, field), max(minimum, integer))
        plan = resolve_search_plan(service.MultiSearchRequest(query="test"), {"scrape_timeout": "17"})
        self.assertEqual(plan.scrape_url_timeout, 17)
        for value, integer in (("999999", 999999), ("-2", -2), (2.9, 2), (False, 0), (True, 1)):
            self.assertEqual(build_counts({"count": value}), {
                source: max(1, min(integer, cap)) for source, cap in COUNT_CAPS.items()
            })

    def test_count_precedence_and_nested_nulls_are_unchanged(self):
        for defaults, explicit, expected in (
            ({"count": "4", "hackernews_count": "9", "counts": {"hackernews": "7"}}, None, 7),
            ({"count": "4", "hackernews_count": "9", "counts": {}}, None, 9),
            ({"count": "4", "hackernews_count": "9", "counts": {"hackernews": None}}, None, 4),
            ({"hackernews_count": "9", "counts": {"hackernews": None}}, None, 10),
            ({"count": "4", "counts": {"hackernews": "7"}}, 2, 2),
            ({"count": "bad", "counts": "bad"}, 3, 3),
        ):
            with self.subTest(defaults=defaults, explicit=explicit):
                self.assertEqual(build_counts(defaults, explicit)["hackernews"], expected)
        self.assertEqual(build_counts({"counts": {"unused": "unchanged"}}), build_counts({}))

    def test_invalid_count_shapes_and_values_report_the_selected_field(self):
        cases = [("counts", {"counts": value}) for value in ([], "", 0, False)]
        cases.extend((
            ("counts.hackernews", {"counts": {"hackernews": []}}),
            ("hackernews_count", {"hackernews_count": {}}),
            ("count", {"count": ""}),
        ))
        for field, defaults in cases:
            with self.subTest(field=field, defaults=defaults):
                self.write_config(defaults)
                with self.assertRaisesRegex(config.ConfigError, field.replace(".", r"\.")):
                    service.run_search_web({"query": "test", "sources": ["hackernews"]})
                self.assertIn(field, service.doctor_data(include_keys=False)["config_error"])
                self.provider.assert_not_called()

    def test_invalid_numeric_defaults_do_not_expose_values(self):
        secret = "synthetic-credential-must-not-appear"
        for field in ("timeout", "scrape_top", "scrape_chars", "scrape_per_source",
                      "scrape_timeout", "scrape_url_timeout", "scrape_concurrency", "count"):
            with self.subTest(field=field):
                self.write_config({field: secret})
                data = tools.multi_search_tool("test", sources=["hackernews"])
                self.assertEqual(data["error_type"], "invalid_request")
                self.assertIn(field, data["error"])
                self.assertNotIn(secret, data["error"])
                diagnostic = service.doctor_data(include_keys=False)
                self.assertIn(field, diagnostic["config_error"])
                self.assertNotIn(secret, diagnostic["config_error"])
                self.provider.assert_not_called()
        self.write_config({"counts": {"hackernews": secret}})
        data = tools.search_web_tool("test", sources=["hackernews"])
        self.assertIn("counts.hackernews", data["error"])
        self.assertNotIn(secret, data["error"])

    def test_valid_request_overrides_bad_defaults_through_both_search_stages(self):
        for field in ("timeout", "scrape_chars", "scrape_per_source", "scrape_timeout", "scrape_concurrency", "count"):
            with self.subTest(field=field):
                self.write_config({field: "bad"})
                response = service.run_multi_search({
                    "query": "test", "sources": ["hackernews"], field: 3,
                })
                self.assertNotIn("error", response)
                self.provider.assert_called_once()
                self.assertEqual(service.doctor_data(include_keys=False)["config_status"], "error")

    def test_search_web_scrape_overrides_preserve_caller_config(self):
        defaults = {"scrape_timeout": "bad", "scrape_chars": [], "scrape_concurrency": "bad"}
        url = "https://example.com/config-regression"
        self.provider.return_value = [{"source": "hackernews", "title": "Config", "url": url}]
        scraper = mock.Mock(return_value={"url": url, "markdown": "body " * 50, "via": "fixture"})
        with mock.patch.object(service, "run_ranked_fetch_stage", wraps=service.run_ranked_fetch_stage) as stage:
            response = service.run_search_web(
                {"query": "test", "sources": ["hackernews"]}, config=defaults,
                scrape_timeout=3, scrape_chars=100, scrape_concurrency=2,
                scraper=scraper, url_resolver=lambda _host: ["93.184.216.34"],
            )
        self.assertEqual((stage.call_args.kwargs["timeout"], stage.call_args.kwargs["concurrency"]), (3, 2))
        self.assertNotIn("error", response)
        self.provider.assert_called_once()
        scraper.assert_called_once()
        self.assertEqual(response["scrapes"][0]["markdown"], "body " * 20)
        self.assertEqual(response["errors"], [])
        self.assertEqual(defaults, {"scrape_timeout": "bad", "scrape_chars": [], "scrape_concurrency": "bad"})

    def test_invalid_explicit_scrape_values_fail_before_providers(self):
        for field in ("scrape_timeout", "scrape_chars", "scrape_concurrency"):
            with self.subTest(field=field):
                self.write_config({})
                with self.assertRaisesRegex(config.ConfigError, field):
                    service.run_search_web({"query": "test", "sources": ["hackernews"]}, **{field: "bad"})
                self.provider.assert_not_called()

    def test_cli_and_mcp_continue_normal_workflow_for_valid_numeric_strings(self):
        for output_format in ("json", "human", "markdown"):
            self.write_config({"timeout": "12", "scrape_timeout": "3", "scrape_concurrency": "2", "counts": {"hackernews": "4"}})
            stdout, stderr = io.StringIO(), io.StringIO()
            self.assertEqual(cli.main(
                ["search", "test", "--source", "hackernews", "--timeout", "8", "--count", "2", "--format", output_format],
                stdout=stdout, stderr=stderr,
            ), 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(stdout.getvalue())
            self.provider.assert_called_once()
            runner_config = self.provider.call_args.args[1]
            self.assertEqual((runner_config.timeout, runner_config.counts["hackernews"]), (8, 2))
            self.assertEqual(cli.main(["doctor", "--no-keys", "--format", output_format], stdout=io.StringIO(), stderr=io.StringIO()), 0)
        self.assertNotIn("error", tools.search_web_tool("test", sources=["hackernews"]))
        self.assertNotIn("error", tools.multi_search_tool("test", sources=["hackernews"]))
        self.assertEqual(tools.doctor_tool(include_keys=False)["config_status"], "ok")


if __name__ == "__main__":
    unittest.main()
