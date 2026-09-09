import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp import cli, tools
from multi_search_mcp.src import service
from multi_search_mcp.src.search import registry
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.state_store import StateStore


def stable_hits(response):
    return [{key: value for key, value in hit.items() if key not in {"source_id", "content_ref"}}
            for hit in response["results"]]


class QueryFusionAdapterTests(unittest.TestCase):
    def test_mcp_cli_share_policy_candidates_source_references_and_cached_reading(self):
        for policy in ({"mode": "equal"},
                       {"mode": "weighted", "primary_weight": 1.0, "variant_budget": 0.9}):
            with self.subTest(policy=policy), TemporaryDirectory() as directory:
                store = StateStore(Path(directory) / "state.sqlite")
                config_path = Path(directory) / "config.json"
                config_path.write_text(json.dumps({"query_fusion": policy}), encoding="utf-8")

                def provider(query, config, _context, _key):
                    self.assertFalse(config.want_content)
                    name = "z-primary" if query == "original" else "a-variant"
                    return [{"source": "brave", "title": name,
                             "url": "https://example.test/" + name}]

                with mock.patch.dict(os.environ, {"MULTI_SEARCH_CONFIG": str(config_path)}), \
                        mock.patch.object(service, "load_keys", return_value={}), \
                        mock.patch.object(service, "StateStore", return_value=store), \
                        mock.patch.object(registry, "build_provider_registry", return_value={
                            "brave": ProviderSpec("brave", "brave", provider)}), \
                        mock.patch.object(service, "validate_public_http_url", return_value=None), \
                        mock.patch.object(service, "scrape_url_smart", side_effect=lambda url, **_: {"url": url, "markdown": "Attribution: original release. " * 20, "via": "fake"}):
                    for variants in (["angle", "original", "angle"], []):
                        mcp_result = tools.search_web_tool("original", sources=["brave"], count=1, expand=variants)
                        output, errors = io.StringIO(), io.StringIO()
                        argv = ["search", "original", "--source", "brave", "--count", "1"]
                        for variant in variants:
                            argv.extend(["--expand", variant])
                        self.assertEqual(cli.main(argv, stdout=output, stderr=errors), 0, errors.getvalue())
                        cli_result = json.loads(output.getvalue())
                        self.assertEqual(stable_hits(mcp_result), stable_hits(cli_result))
                        self.assertEqual(mcp_result["diagnostics"]["query_fusion"], cli_result["diagnostics"]["query_fusion"])
                        self.assertEqual(cli_result["scrapes"][0]["markdown"], "Attribution: original release. " * 20)
                        self.assertNotIn("body", cli_result["results"][0])
                        source_id = mcp_result["results"][0]["source_id"]
                        fetched = service.run_fetch_source(
                            {"source_id": source_id, "max_chars": 12}, state_store=store,
                            scraper=lambda url, **_: {"url": url, "markdown": "Attribution: original release. " * 20},
                            keys={}, config={}, url_resolver=lambda _: ["93.184.216.34"],
                        )
                        self.assertEqual(len(fetched["body"]), 12)
                        mcp_read = tools.read_source_tool(source_id, keyword="original", limit=17)
                        read_output = io.StringIO()
                        self.assertEqual(cli.main(["read", source_id, "--keyword", "original", "--limit", "17"],
                                                  stdout=read_output, stderr=errors), 0, errors.getvalue())
                        self.assertEqual(mcp_read, json.loads(read_output.getvalue()))
                        self.assertEqual(mcp_read["content"], "original release.")


if __name__ == "__main__":
    unittest.main()
