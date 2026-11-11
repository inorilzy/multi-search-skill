"""Regression tests for per-run log lookup, interrupted runs and redaction."""
import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import log_viewer, log_viewer_page
from multi_search_mcp.src.support import debug_log
from multi_search_mcp.src.support.secrets import scrub_secrets


OLD_TS = "2026-01-01T00:00:00+00:00"


def _event(run_id, kind, t_ms, ts=OLD_TS, **fields):
    return {"ts": ts, "run_id": run_id, "t_ms": t_ms, "event": kind, **fields}


def _write_run(path, events):
    lines = [json.dumps(event, ensure_ascii=False) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _completed_run(run_id, query):
    return [
        _event(run_id, "cli_request", 0, command="search", parameters={"query": query}),
        _event(run_id, "search_response", 10, outcome="success", result_count=1),
        _event(run_id, "cli_exit", 12, exit_code=0, elapsed_ms=12),
    ]


class LogViewerRunTests(unittest.TestCase):
    def _serve(self, directory):
        server = log_viewer.make_server([directory], port=0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def _get(self, server, path):
        host = "127.0.0.1:" + str(server.server_address[1])
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            connection.request("GET", path, headers={"Host": host})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_detail_endpoint_reads_only_the_selected_run_file(self):
        selected_id = "run_aaaaaaaaaaaa"
        other_id = "run_bbbbbbbbbbbb"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            selected = directory / f"20261110-100000-{selected_id}.jsonl"
            other = directory / f"20261110-100001-{other_id}.jsonl"
            _write_run(selected, _completed_run(selected_id, "selected"))
            _write_run(other, _completed_run(other_id, "other"))
            server = self._serve(directory)

            read_paths = []
            original = Path.read_text

            def record(path, *args, **kwargs):
                read_paths.append(path)
                return original(path, *args, **kwargs)

            with mock.patch.object(Path, "read_text", record):
                status, payload = self._get(server, "/api/runs/" + selected_id)

        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["query"], "selected")
        self.assertEqual([path.name for path in read_paths], [selected.name])

    def test_load_run_extracts_only_the_requested_run_from_an_aggregate_file(self):
        run_a = "run_aaaaaaaaaaaa"
        run_b = "run_bbbbbbbbbbbb"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            _write_run(path, [
                _event(run_a, "cli_request", 0, command="search", parameters={"query": "a"}),
                _event(run_b, "cli_request", 1, command="search", parameters={"query": "b"}),
                _event(run_a, "cli_exit", 2, exit_code=0),
                _event(run_b, "cli_exit", 3, exit_code=0),
            ])
            events = log_viewer.load_run([Path(temp)], run_a)

        self.assertEqual([event["event"] for event in events], ["cli_request", "cli_exit"])
        self.assertTrue(all(event["run_id"] == run_a for event in events))

    def test_finished_run_without_cli_exit_is_reported_as_interrupted(self):
        run_id = "run_cccccccccccc"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / f"20260101-000000-{run_id}.jsonl"
            _write_run(path, [
                _event(run_id, "cli_request", 0, command="search", parameters={"query": "cancelled"}),
                _event(run_id, "query_plan", 1, query="cancelled"),
            ])
            summary = log_viewer.list_runs(log_viewer.load_runs([Path(temp)]))[0]

        self.assertFalse(summary["complete"])
        self.assertTrue(summary["interrupted"])
        self.assertEqual(summary["outcome"], "interrupted")
        self.assertIn("中断（没有结束记录）", log_viewer_page.SCRIPT)

    def test_recent_run_without_cli_exit_is_not_reported_as_interrupted(self):
        run_id = "run_dddddddddddd"
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        events = [_event(run_id, "cli_request", 0, ts=now, command="search", parameters={"query": "running"})]

        summary = log_viewer.summarize_run(run_id, events)

        self.assertFalse(summary["complete"])
        self.assertFalse(summary["interrupted"])
        self.assertIsNone(summary["outcome"])

    def test_completed_run_keeps_its_search_outcome(self):
        run_id = "run_eeeeeeeeeeee"

        summary = log_viewer.summarize_run(run_id, _completed_run(run_id, "done"))

        self.assertTrue(summary["complete"])
        self.assertFalse(summary["interrupted"])
        self.assertEqual(summary["outcome"], "success")

    def test_signed_url_query_parameters_are_redacted_from_errors(self):
        message = (
            "GET https://bucket.example/object?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Credential=AKIAEXAMPLE&X-Amz-Signature=deadbeef1234"
            "&password=hunter2&client_secret=cs-secret&cookie=sess-cookie&sig=short-sig"
        )

        output = scrub_secrets(message)

        for secret in ("AKIAEXAMPLE", "deadbeef1234", "hunter2", "cs-secret", "sess-cookie", "short-sig"):
            self.assertNotIn(secret, output)
        self.assertIn("X-Amz-Signature=<redacted>", output)
        self.assertIn("X-Amz-Credential=<redacted>", output)
        self.assertIn("password=<redacted>", output)
        self.assertIn("client_secret=<redacted>", output)
        self.assertIn("cookie=<redacted>", output)

    def test_signed_url_query_parameters_are_redacted_from_debug_log(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            debug_log.configure(str(path))
            self.addCleanup(debug_log.disable)
            try:
                debug_log.event(
                    "fetch_failed",
                    url="https://bucket.example/object?X-Amz-Signature=deadbeef1234&password=hunter2",
                    error="client_secret=cs-secret&cookie=sess-cookie",
                )
            finally:
                debug_log.disable()
            text = path.read_text(encoding="utf-8")

        for secret in ("deadbeef1234", "hunter2", "cs-secret", "sess-cookie"):
            self.assertNotIn(secret, text)
        self.assertIn("X-Amz-Signature=<redacted>", text)


if __name__ == "__main__":
    unittest.main()
