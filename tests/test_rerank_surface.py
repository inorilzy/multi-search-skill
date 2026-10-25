"""Surface coverage for the optional model-rerank switch (t2).

The core rerank stage lives in ``search/rerank.py`` + ``candidates.py``; this
file covers the surfaces that expose it: the CLI flags, the MCP tool
parameters, and the human/markdown formatters. No test here touches the
network — service entry points are mocked at the boundary each surface owns.
"""
import io
import json
import unittest
from unittest import mock

import multi_search_mcp.cli as cli
from multi_search_mcp import tools
from multi_search_mcp.src.support.config import ConfigError
from multi_search_mcp.src.support.format import format_results


def _search_payload(**overrides):
    payload = {
        "query": "q",
        "route": "default",
        "results": [],
        "provider_status": [],
        "diagnostics": {},
        "mode_requested": "rrf",
        "mode_used": "rrf",
        "fallback_reason": None,
    }
    payload.update(overrides)
    return payload


class CliRerankFlagTests(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def _captured(self, argv):
        captured = {}

        def fake_run(request, **kwargs):
            captured["request"] = request
            captured["kwargs"] = kwargs
            return _search_payload(query=request.query)

        with mock.patch.object(cli, "run_search_web", side_effect=fake_run):
            code, stdout, stderr = self.run_cli(argv)
        return code, stdout, stderr, captured

    def test_no_rerank_flag_leaves_ranking_none(self):
        code, _stdout, stderr, captured = self._captured(["search", "q"])
        self.assertEqual(code, 0, stderr)
        self.assertIsNone(captured["request"].ranking)
        # No reranker is built or passed for the default pure-RRF path.
        self.assertEqual(captured["kwargs"], {})

    def test_rerank_flag_requests_model_mode(self):
        code, _stdout, stderr, captured = self._captured(["search", "q", "--rerank"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(captured["request"].ranking, {"mode": "rrf_model"})

    def test_rerank_flag_leaves_adapter_construction_to_core(self):
        # The CLI no longer builds a reranker: core constructs it from the
        # merged policy, so no surface can forget to (the original dead-code
        # bug). End-to-end proof lives in CliRerankEndToEndTests.
        code, _stdout, stderr, captured = self._captured(["search", "q", "--rerank"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(captured["kwargs"], {})

    def test_rerank_profile_is_forwarded(self):
        code, _stdout, stderr, captured = self._captured(
            ["search", "q", "--rerank", "--rerank-profile", "jev_default"],
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            captured["request"].ranking,
            {"mode": "rrf_model", "reranker_profile_id": "jev_default"},
        )

    def test_legacy_jev_profile_is_a_usage_error(self):
        # "jev" was a CLI-only alias the desktop never accepted; the single
        # authoritative id is core's "jev_default".
        with mock.patch.object(cli, "run_search_web") as run:
            code, _stdout, stderr = self.run_cli(
                ["search", "q", "--rerank", "--rerank-profile", "jev"],
            )
        self.assertEqual(code, 2)
        self.assertIn("unknown rerank profile", stderr)
        self.assertIn("jev_default", stderr)
        run.assert_not_called()

    def test_profile_without_rerank_is_a_usage_error(self):
        with mock.patch.object(cli, "run_search_web") as run:
            code, stdout, stderr = self.run_cli(
                ["search", "q", "--rerank-profile", "jev_default"],
            )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--rerank-profile requires --rerank", stderr)
        run.assert_not_called()

    def test_unknown_profile_is_a_usage_error_not_a_fallback(self):
        with mock.patch.object(cli, "run_search_web") as run:
            code, stdout, stderr = self.run_cli(
                ["search", "q", "--rerank", "--rerank-profile", "bogus"],
            )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown rerank profile", stderr)
        run.assert_not_called()

    def test_invalid_ranking_config_fails_instead_of_falling_back(self):
        # A config-level ranking error is a ConfigError -> exit 1 with an
        # explicit error payload; the CLI never silently downgrades to RRF.
        with mock.patch.object(
            cli, "run_search_web",
            side_effect=ConfigError("ranking.mode must be rrf or rrf_model"),
        ):
            code, stdout, stderr = self.run_cli(["search", "q", "--rerank"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout)
        self.assertEqual(payload["error_type"], "invalid_request")
        self.assertIn("ranking.mode", payload["error"])
        self.assertNotIn("results", payload)

    def test_json_output_carries_ranking_mode_fields(self):
        with mock.patch.object(cli, "run_search_web", return_value=_search_payload(
            mode_requested="rrf_model", mode_used="rrf",
            fallback_reason="timeout",
        )):
            code, stdout, stderr = self.run_cli(["search", "q", "--rerank"])
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["mode_requested"], "rrf_model")
        self.assertEqual(payload["mode_used"], "rrf")
        self.assertEqual(payload["fallback_reason"], "timeout")


class CliRerankDisplayTests(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def _render(self, payload, fmt):
        with mock.patch.object(cli, "run_search_web", return_value=payload):
            return self.run_cli(["search", "q", "--format", fmt])

    def test_human_output_names_the_used_mode(self):
        for fields, expected in (
            ({"mode_used": "rrf"}, "RRF 排序"),
            ({"mode_used": "rrf_model"}, "模型重排"),
            (
                {"mode_used": "rrf", "mode_requested": "rrf_model",
                 "fallback_reason": "auth"},
                "模型暂不可用，已使用 RRF",
            ),
        ):
            with self.subTest(fields=fields):
                code, stdout, stderr = self._render(_search_payload(**fields), "human")
                self.assertEqual(code, 0, stderr)
                self.assertIn(f"ranking: {expected}", stdout)

    def test_markdown_output_names_the_used_mode(self):
        code, stdout, stderr = self._render(
            _search_payload(mode_used="rrf_model"), "markdown",
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("- ranking: 模型重排", stdout)

    def test_relevance_score_only_renders_when_scored(self):
        results = [
            {"title": "A", "url": "https://example.com/a", "source": "exa",
             "relevance_score": 0.9},
            {"title": "B", "url": "https://example.com/b", "source": "brave",
             "relevance_score": None},
        ]
        code, stdout, stderr = self._render(
            _search_payload(results=results, mode_used="rrf_model"), "human",
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("A (relevance: 0.900)", stdout)
        b_line = next(line for line in stdout.splitlines() if " B" in line and "example.com" not in line)
        self.assertNotIn("relevance", b_line)
        self.assertNotIn("0.000", stdout)


class FormatResultsRankingTests(unittest.TestCase):
    """The MCP markdown formatter mirrors the CLI mode line."""

    def _rows(self):
        return [
            {"source": "brave", "title": "First",
             "url": "https://example.com/first", "rrf_score": 0.1},
            {"source": "exa", "title": "Second",
             "url": "https://example.com/second", "rrf_score": 0.9},
        ]

    def test_three_mode_lines(self):
        for ranking, expected in (
            ({"mode_used": "rrf"}, "RRF 排序"),
            ({"mode_used": "rrf_model"}, "模型重排"),
            (
                {"mode_requested": "rrf_model", "mode_used": "rrf",
                 "fallback_reason": "unavailable"},
                "模型暂不可用，已使用 RRF",
            ),
        ):
            with self.subTest(ranking=ranking):
                output = format_results(self._rows(), "q", ranking=ranking)
                self.assertIn(f"**排序：** {expected}", output)

    def test_missing_metadata_defaults_to_rrf_label(self):
        output = format_results(self._rows(), "q")
        self.assertIn("**排序：** RRF 排序", output)

    def test_scored_rows_without_metadata_imply_model_rerank(self):
        rows = self._rows()
        rows[0]["relevance_score"] = 0.75
        output = format_results(rows, "q")
        self.assertIn("**排序：** 模型重排", output)
        self.assertIn("rel=0.750", output)

    def test_unscored_relevance_never_renders_as_zero(self):
        rows = self._rows()
        for row in rows:
            row["relevance_score"] = None
        output = format_results(rows, "q")
        self.assertNotIn("rel=", output)
        self.assertNotIn("0.000", output)

    def test_formatter_still_never_reranks_input_order(self):
        rows = self._rows()
        rows[0]["relevance_score"] = 0.4
        rows[1]["relevance_score"] = 0.9
        output = format_results(rows, "q", ranking={"mode_used": "rrf_model"})
        self.assertLess(
            output.index("https://example.com/first"),
            output.index("https://example.com/second"),
        )


class ToolRerankPassthroughTests(unittest.TestCase):
    def test_search_web_tool_defaults_to_config_ranking(self):
        captured = {}
        with mock.patch.object(
            tools, "run_search_web",
            side_effect=lambda request, **kw: captured.update(
                request=request, kwargs=kw,
            ) or _search_payload(),
        ):
            tools.search_web_tool("q")
        self.assertIsNone(captured["request"].ranking)
        self.assertEqual(captured["kwargs"], {})

    def test_search_web_tool_forwards_rerank_flags(self):
        captured = {}
        with mock.patch.object(
            tools, "run_search_web",
            side_effect=lambda request, **kw: captured.update(
                request=request, kwargs=kw,
            ) or _search_payload(),
        ):
            tools.search_web_tool("q", rerank=True, rerank_profile="jev_default")
        self.assertEqual(
            captured["request"].ranking,
            {"mode": "rrf_model", "reranker_profile_id": "jev_default"},
        )
        # Core builds the adapter; the tool passes no reranker of its own.
        self.assertEqual(captured["kwargs"], {})

    def test_multi_search_tool_forwards_rerank_flags(self):
        captured = {}
        with mock.patch.object(
            tools, "run_multi_search",
            side_effect=lambda request, **kw: captured.update(
                request=request, kwargs=kw,
            ) or _search_payload(),
        ):
            tools.multi_search_tool("q", rerank=True)
        self.assertEqual(captured["request"].ranking, {"mode": "rrf_model"})
        self.assertIsNone(captured["request"].ranking.get("reranker_profile_id"))
        self.assertEqual(captured["kwargs"], {})

    def test_tool_unknown_profile_is_invalid_request_from_core(self):
        # The tool has no private profile list: core's registry rejects it.
        from multi_search_mcp.src.search.search_runner import ProviderSpec
        from multi_search_mcp.src.service import run_search_web as real_run

        provider = ProviderSpec("brave", "brave", lambda *_a: [
            {"source": "brave", "title": "a", "url": "https://example.com/a"},
        ])
        with mock.patch.object(
            tools, "run_search_web",
            side_effect=lambda request: real_run(
                request, providers={"brave": provider}, keys={}, config={},
            ),
        ):
            result = tools.search_web_tool(
                "q", sources=["brave"], use_state=False,
                rerank=True, rerank_profile="jev",
            )
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("reranker_profile_id", result["error"])

    def test_config_error_surfaces_as_invalid_request_not_fallback(self):
        with mock.patch.object(
            tools, "run_search_web",
            side_effect=ConfigError("ranking contains unsupported fields"),
        ):
            result = tools.search_web_tool("q", rerank=True)
        self.assertEqual(result["error_type"], "invalid_request")
        self.assertIn("unsupported fields", result["error"])
        self.assertNotIn("results", result)


class CliRerankEndToEndTests(unittest.TestCase):
    """Prove ``--rerank`` reaches a real adapter, not the ``reranker=None`` path.

    With no ``TYPESAFE_API_KEY`` the adapter fails closed with ``auth``. If the
    CLI forgot to build and pass a reranker, the core would report
    ``unavailable`` instead — so the reason code itself proves the wiring.
    """

    def test_missing_key_reports_auth_proving_the_adapter_ran(self):
        from types import SimpleNamespace

        from multi_search_mcp.src.search.search_runner import ProviderSpec

        rows = [
            {
                "source": "brave", "title": f"b-{i}",
                "url": f"https://example.com/b-{i}",
                "description": "excerpt", "content_kind": "excerpt",
            }
            for i in range(1, 6)
        ]
        providers = {
            "brave": ProviderSpec("brave", "brave", lambda *_a, **_kw: rows),
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch(
                 "multi_search_mcp.src.state.runtime.load_config_safe",
                 return_value={},
             ), \
             mock.patch(
                 "multi_search_mcp.src.state.runtime.load_runtime_key_context",
                 return_value=SimpleNamespace(keys={}, errors={}),
             ), \
             mock.patch(
                 "multi_search_mcp.src.search.registry.build_provider_registry",
                 return_value=providers,
             ):
            import os
            os.environ.pop("TYPESAFE_API_KEY", None)
            code = cli.main(
                ["search", "q", "--source", "brave", "--no-fetch", "--no-state",
                 "--rerank"],
                stdout=stdout, stderr=stderr,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["mode_requested"], "rrf_model")
        self.assertEqual(payload["mode_used"], "rrf")
        # "auth" (adapter ran and failed closed), never "unavailable" (no adapter).
        self.assertEqual(payload["fallback_reason"], "auth")
        self.assertEqual(len(payload["results"]), 5)

    def test_default_run_does_not_request_rerank(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(
            cli, "run_search_web", return_value=_search_payload(),
        ) as run:
            code = cli.main(["search", "q"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        run.assert_called_once()
        self.assertIsNone(run.call_args.args[0].ranking)
        self.assertEqual(run.call_args.kwargs, {})


if __name__ == "__main__":
    unittest.main()
