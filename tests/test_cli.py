import io
import json
import sys
import tempfile
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

    def test_search_without_expand_leaves_request_unset(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"query": request.query, "results": [], "provider_status": [], "diagnostics": {}}

        with mock.patch.object(cli, "run_search_web", side_effect=fake_run):
            code, _stdout, stderr = self.run_cli(["search", "primary"])

        self.assertEqual(code, 0, stderr)
        self.assertIsNone(captured["request"].expand)

    def test_search_no_fetch_flag_requests_candidates_only(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"query": request.query, "results": [], "provider_status": [], "diagnostics": {}}

        with mock.patch.object(cli, "run_search_web", side_effect=fake_run):
            code, _stdout, stderr = self.run_cli(["search", "primary", "--no-fetch"])

        self.assertEqual(code, 0, stderr)
        self.assertTrue(captured["request"].no_fetch)

    def test_search_fetches_bodies_without_the_no_fetch_flag(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"query": request.query, "results": [], "provider_status": [], "diagnostics": {}}

        with mock.patch.object(cli, "run_search_web", side_effect=fake_run):
            code, _stdout, stderr = self.run_cli(["search", "primary"])

        self.assertEqual(code, 0, stderr)
        self.assertFalse(captured["request"].no_fetch)

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

    def test_fetch_reads_url_from_file_verbatim(self):
        captured = {}
        shell_hostile = "https://example.com/a?q=$(touch /tmp/pwned)&r=`id`"

        def fake_run(request):
            captured["request"] = request
            return {"source_id": "generated", "url": request.url, "body": "body"}

        with tempfile.TemporaryDirectory() as directory:
            url_file = Path(directory) / "url.txt"
            url_file.write_text("  " + shell_hostile + "\n", encoding="utf-8")
            with mock.patch.object(cli, "run_fetch_source", side_effect=fake_run):
                code, stdout, stderr = self.run_cli(["fetch", "--url-file", str(url_file)])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(captured["request"].url, shell_hostile)
        self.assertIsNone(captured["request"].source_id)
        self.assertEqual(json.loads(stdout)["url"], shell_hostile)

    def test_fetch_reads_url_from_stdin_with_dash(self):
        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"source_id": "generated", "url": request.url, "body": "body"}

        with mock.patch.object(sys, "stdin", io.StringIO("https://example.com/stdin\n")), \
             mock.patch.object(cli, "run_fetch_source", side_effect=fake_run):
            code, _stdout, stderr = self.run_cli(["fetch", "--url-file", "-"])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(captured["request"].url, "https://example.com/stdin")

    def test_fetch_rejects_url_file_with_more_than_one_url(self):
        with tempfile.TemporaryDirectory() as directory:
            url_file = Path(directory) / "url.txt"
            url_file.write_text("https://example.com/one\nhttps://example.com/two\n", encoding="utf-8")
            code, stdout, stderr = self.run_cli(["fetch", "--url-file", str(url_file)])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--url-file must contain exactly one URL", stderr)

    def test_fetch_rejects_empty_or_unreadable_url_file(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.txt"
            empty.write_text(" \n", encoding="utf-8")
            missing = Path(directory) / "missing.txt"
            for path, message in ((empty, "--url-file is empty"), (missing, "cannot read --url-file")):
                with self.subTest(path=path.name):
                    code, stdout, stderr = self.run_cli(["fetch", "--url-file", str(path)])
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn(message, stderr)

    def test_fetch_rejects_url_file_combined_with_other_inputs(self):
        for arguments in (
            ["fetch", "src-1", "--url-file", "url.txt"],
            ["fetch", "--url", "https://example.com", "--url-file", "url.txt"],
        ):
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.run_cli(arguments)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("provide exactly one of source_id, --url, or --url-file", stderr)

    def test_fetch_help_lists_url_file_for_skill_compatibility(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), self.assertRaises(SystemExit) as exited:
            cli.main(["fetch", "--help"])

        self.assertEqual(exited.exception.code, 0)
        self.assertIn("--url-file", stdout.getvalue())

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

    def test_keys_status_uses_the_shared_core_operation(self):
        with mock.patch.object(
            cli, "key_status", return_value=[{"provider": "exa", "status": "active"}],
        ) as status:
            code, stdout, stderr = self.run_cli([
                "keys",
                "status",
                "--provider", "exa",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["key_status"], [{"provider": "exa", "status": "active"}])
        status.assert_called_once_with("exa")

    def test_keys_reset_uses_the_shared_core_operation(self):
        with mock.patch.object(cli, "reset_key_state", return_value=3) as reset:
            code, stdout, stderr = self.run_cli([
                "keys",
                "reset",
                "--provider", "tavily",
                "--key-id", "tavily:abcd",
            ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["updated"], 3)
        reset.assert_called_once_with(provider="tavily", key_id="tavily:abcd")

    def test_keys_reset_requires_a_selection_or_all(self):
        with mock.patch.object(cli, "reset_key_state") as reset:
            code, stdout, stderr = self.run_cli(["keys", "reset"])
        self.assertEqual(code, 2)
        self.assertIn("--all", stderr)
        reset.assert_not_called()

    def test_keys_reset_all_clears_every_row_via_shared_operation(self):
        with mock.patch.object(cli, "reset_key_state", return_value=7) as reset:
            code, stdout, stderr = self.run_cli(["keys", "reset", "--all"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["updated"], 7)
        reset.assert_called_once_with(provider=None, key_id=None)

    def test_keys_reset_all_rejects_conflicting_selectors_without_writes(self):
        for selector in (["--provider", "exa"], ["--key-id", "exa:abcd"],
                         ["--provider", "exa", "--key-id", "exa:abcd"]):
            with self.subTest(selector=selector), mock.patch.object(cli, "reset_key_state") as reset:
                code, stdout, stderr = self.run_cli(["keys", "reset", "--all", *selector])
                self.assertEqual(code, 2)
                self.assertIn("--all", stderr)
                self.assertEqual(stdout, "")
                reset.assert_not_called()

    def test_service_error_is_reported_to_stderr_with_nonzero_exit(self):
        with mock.patch.object(cli, "run_search_web", side_effect=ValueError("bad query")):
            code, stdout, stderr = self.run_cli(["search", "oops"])

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), {"error": "bad query", "error_type": "invalid_request"})
        self.assertIn("bad query", stderr)

    def test_service_exception_output_is_secret_scrubbed(self):
        with mock.patch.object(
            cli, "run_search_web",
            side_effect=ValueError("failed with Authorization: Bearer super-secret-token"),
        ):
            code, stdout, stderr = self.run_cli(["search", "oops"])
        self.assertEqual(code, 1)
        self.assertNotIn("super-secret-token", stdout + stderr)
        self.assertIn("<redacted>", stdout)


    def test_usage_error_returns_exit_code_2(self):
        code, stdout, stderr = self.run_cli([
            "fetch",
            "src-1",
            "--url", "https://example.com",
        ])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("provide exactly one of source_id, --url, or --url-file", stderr)

    def test_pyproject_registers_multi_search_console_script(self):
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn(
            'multi-search = "multi_search_mcp.cli:entrypoint"',
            pyproject,
        )


if __name__ == "__main__":
    unittest.main()
