import io
import json
import unittest
from pathlib import Path
from unittest import mock

import multi_search_mcp.cli as cli


class CliTests(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_search_json_calls_search_web_with_repeated_sources_and_expand(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {
                "query": request.query,
                "route": request.route,
                "results": [],
                "provider_status": [],
                "diagnostics": {},
            }

        with mock.patch.object(cli, "run_search_web", side_effect=fake_run):
            code, stdout, stderr = self.run_cli([
                "search",
                "graph rag",
                "--route", "dev",
                "--source", "github-repos",
                "--source", "stackoverflow",
                "--count", "7",
                "--timeout", "9",
                "--expand", "retrieval augmented generation",
                "--expand", "rrf ranking",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["query"], "graph rag")
        self.assertEqual(payload["route"], "dev")
        self.assertEqual(captured["request"].sources, ["github-repos", "stackoverflow"])
        self.assertEqual(captured["request"].count, 7)
        self.assertEqual(captured["request"].timeout, 9)
        self.assertEqual(
            captured["request"].expand,
            ["retrieval augmented generation", "rrf ranking"],
        )

    def test_search_markdown_renders_compact_search_hits(self):
        with mock.patch.object(cli, "run_search_web", return_value={
            "query": "python",
            "route": "default",
            "results": [{
                "title": "Docs",
                "url": "https://example.com/docs",
                "source": "exa",
                "content": "reference",
            }],
            "provider_status": [],
            "diagnostics": {},
        }):
            code, stdout, stderr = self.run_cli([
                "search",
                "python",
                "--format", "markdown",
            ])

        self.assertEqual(code, 0, stderr)
        self.assertIn("# Search", stdout)
        self.assertIn("Docs", stdout)
        self.assertIn("https://example.com/docs", stdout)

    def test_fetch_accepts_positional_source_id(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"source_id": request.source_id, "url": "https://example.com", "body": "body"}

        with mock.patch.object(cli, "run_fetch_source", side_effect=fake_run):
            code, stdout, stderr = self.run_cli([
                "fetch",
                "src-123",
                "--timeout", "5",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "src-123")
        self.assertEqual(captured["request"].source_id, "src-123")
        self.assertIsNone(captured["request"].url)
        self.assertEqual(captured["request"].timeout, 5)

    def test_fetch_accepts_url(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"source_id": "generated", "url": request.url, "body": "body"}

        with mock.patch.object(cli, "run_fetch_source", side_effect=fake_run):
            code, stdout, stderr = self.run_cli([
                "fetch",
                "--url", "https://example.com/article",
                "--max-chars", "1200",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["url"], "https://example.com/article")
        self.assertEqual(captured["request"].url, "https://example.com/article")
        self.assertEqual(captured["request"].max_chars, 1200)

    def test_read_passes_keyword_offset_and_limit(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"source_id": request.source_id, "content": "chunk", "start": 12, "end": 17}

        with mock.patch.object(cli, "run_read_source", side_effect=fake_run):
            code, stdout, stderr = self.run_cli([
                "read",
                "src-456",
                "--keyword", "needle",
                "--offset", "12",
                "--limit", "200",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "src-456")
        self.assertEqual(captured["request"].keyword, "needle")
        self.assertEqual(captured["request"].offset, 12)
        self.assertEqual(captured["request"].limit, 200)

    def test_doctor_human_output_uses_service_data(self):
        with mock.patch.object(cli, "doctor_data", return_value={
            "server": "multi-search-mcp",
            "config_loaded": True,
            "state_path": "D:/tmp/state.sqlite",
            "network_checked": False,
        }):
            code, stdout, stderr = self.run_cli([
                "doctor",
                "--format", "human",
            ])

        self.assertEqual(code, 0, stderr)
        self.assertIn("server: multi-search-mcp", stdout)
        self.assertIn("state_path: D:/tmp/state.sqlite", stdout)

    def test_keys_status_uses_state_store_and_manager(self):
        fake_manager = mock.Mock()
        fake_manager.status_rows.return_value = [{"provider": "exa", "status": "active"}]

        with mock.patch.object(cli, "StateStore", return_value=object()) as store_cls, \
             mock.patch.object(cli, "SQLiteKeyManager", return_value=fake_manager):
            code, stdout, stderr = self.run_cli([
                "keys",
                "status",
                "--provider", "exa",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["key_status"], [{"provider": "exa", "status": "active"}])
        store_cls.assert_called_once_with()
        fake_manager.status_rows.assert_called_once_with("exa")

    def test_keys_reset_reports_updated_rows(self):
        fake_manager = mock.Mock()
        fake_manager.reset.return_value = 3

        with mock.patch.object(cli, "StateStore", return_value=object()) as store_cls, \
             mock.patch.object(cli, "SQLiteKeyManager", return_value=fake_manager):
            code, stdout, stderr = self.run_cli([
                "keys",
                "reset",
                "--provider", "tavily",
                "--key-id", "tavily:abcd",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["updated"], 3)
        store_cls.assert_called_once_with()
        fake_manager.reset.assert_called_once_with(provider="tavily", key_id="tavily:abcd")

    def test_service_error_is_reported_to_stderr_with_nonzero_exit(self):
        with mock.patch.object(cli, "run_search_web", side_effect=ValueError("bad query")):
            code, stdout, stderr = self.run_cli(["search", "oops"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("bad query", stderr)

    def test_usage_error_returns_exit_code_2(self):
        code, stdout, stderr = self.run_cli([
            "fetch",
            "src-1",
            "--url", "https://example.com",
        ])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("provide exactly one of source_id or --url", stderr)

    def test_pyproject_registers_multi_search_console_script(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn(
            'multi-search = "multi_search_mcp.cli:entrypoint"',
            pyproject,
        )


if __name__ == "__main__":
    unittest.main()
