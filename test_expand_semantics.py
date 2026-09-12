import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp import tools
from multi_search_mcp.src import service
from multi_search_mcp.src.search import registry
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.state_store import StateStore


class ExpandSemanticsTests(unittest.TestCase):
    def invoke(self, entrypoint, *, expand=mock.sentinel.omitted):
        calls = []

        def provider(query, _config, _context, _key):
            calls.append(query)
            return []

        config = {
            "expand": ["configured extra"],
            "expand_queries": ["configured alias"],
        }
        kwargs = {"sources": ["hackernews"], "use_state": False}
        if expand is not mock.sentinel.omitted:
            kwargs["expand"] = expand
        with mock.patch.object(service, "_load_config_safe", return_value=config), \
                mock.patch.object(registry, "build_provider_registry", return_value={
                    "hackernews": ProviderSpec("hackernews", "hackernews", provider),
                }):
            result = entrypoint("primary", **kwargs)

        self.assertNotIn("error", result)
        return calls, result

    def test_omitted_expand_inherits_config_for_both_tool_entries(self):
        for entrypoint in (tools.search_web_tool, tools.multi_search_tool):
            with self.subTest(entrypoint=entrypoint.__name__):
                calls, _result = self.invoke(entrypoint)
                self.assertCountEqual(calls, ["primary", "configured extra"])

    def test_explicit_empty_expand_disables_config_for_both_tool_entries(self):
        for entrypoint in (tools.search_web_tool, tools.multi_search_tool):
            with self.subTest(entrypoint=entrypoint.__name__):
                calls, result = self.invoke(entrypoint, expand=[])
                self.assertEqual(calls, ["primary"])
                self.assertEqual(result["diagnostics"]["queries"], ["primary"])

    def test_nonempty_expand_replaces_config_for_both_tool_entries(self):
        for entrypoint in (tools.search_web_tool, tools.multi_search_tool):
            with self.subTest(entrypoint=entrypoint.__name__):
                calls, _result = self.invoke(entrypoint, expand=["request extra"])
                self.assertCountEqual(calls, ["primary", "request extra"])

    def test_cli_omitted_expand_inherits_config(self):
        calls = []

        def provider(query, _config, _context, _key):
            calls.append(query)
            return []

        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.sqlite")
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(service, "_load_config_safe", return_value={
                "expand": ["configured extra"],
            }), mock.patch.object(service, "load_keys", return_value={}), \
                    mock.patch.object(service, "StateStore", return_value=store), \
                    mock.patch.object(registry, "build_provider_registry", return_value={
                        "hackernews": ProviderSpec("hackernews", "hackernews", provider),
                    }):
                code = cli.main(
                    ["search", "primary", "--source", "hackernews"],
                    stdout=stdout, stderr=stderr,
                )

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertCountEqual(calls, ["primary", "configured extra"])


if __name__ == "__main__":
    unittest.main()
