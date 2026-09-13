import json
import subprocess
import threading
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest import mock

from multi_search_mcp.src.search import registry, search_runner
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.search.searchers import github
from multi_search_mcp.src.support import concurrency
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


class InlineExecutor:
    """Keep clock-driven budget tests independent of thread scheduling."""

    def submit_before(self, deadline, call):
        future = Future()
        try:
            future.set_result(call())
        except Exception as exc:
            future.set_exception(exc)
        return future


def gh_result(error=""):
    return subprocess.CompletedProcess(
        ["gh"], 1 if error else 0,
        stdout=json.dumps({"items": [{
            "full_name": "owner/repo", "html_url": "https://github.com/owner/repo",
            "description": "Repository description", "stargazers_count": 42,
        }]}).encode(),
        stderr=error.encode(),
    )


class GitHubDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        clock = SimpleNamespace(monotonic=lambda: self.now)
        for module in (search_runner, github, concurrency):
            patcher = mock.patch.object(module, "time", clock)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(search_runner, "_SEARCH_POOL", InlineExecutor())
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, *, timeout=10, keys=None, handoff_delay=0):
        providers = build_provider_registry()
        if handoff_delay:
            original = providers["github_repos"].call

            def delayed_call(*args):
                self.now += handoff_delay
                return original(*args)

            providers["github_repos"].call = delayed_call
        return SearchRunner(
            SearchRunnerConfig("test", {"github": 3}, timeout, "google_light", keys or {}),
            providers, route_resolver=lambda _: ["github_repos"],
        )

    def test_runner_retries_use_original_deadline_after_provider_handoff(self):
        starts = []

        def run(args, *, capture_output, timeout):
            starts.append((self.now, timeout))
            self.now += 1
            return gh_result("unexpected EOF" if len(starts) < 3 else "")

        with mock.patch.object(github.subprocess, "run", side_effect=run):
            rows = self.runner(timeout=60, handoff_delay=2).run("query", deadline=110)

        self.assertEqual(starts, [(102, 8), (103, 7), (104, 6)])
        self.assertEqual(rows, [{
            "source": "github-repos", "title": "owner/repo",
            "url": "https://github.com/owner/repo", "description": "Repository description",
            "content_kind": "excerpt", "stars": 42, "provider_rank": 1,
        }])

    def test_runner_long_budget_preserves_per_process_timeout_cap(self):
        budgets = []

        def run(args, *, capture_output, timeout):
            budgets.append(timeout)
            self.now += 15
            return gh_result("unexpected EOF" if len(budgets) < 3 else "")

        with mock.patch.object(github.subprocess, "run", side_effect=run):
            rows = self.runner(timeout=60).run("query")

        self.assertEqual(budgets, [20, 20, 20])
        self.assertEqual(rows[0]["url"], "https://github.com/owner/repo")

    def test_expired_deadline_at_provider_handoff_starts_no_process(self):
        with mock.patch.object(github.subprocess, "run", return_value=gh_result()) as run:
            rows = self.runner(handoff_delay=10).run("query")

        run.assert_not_called()
        self.assertIn("timeout", rows[0]["error"])

    def test_standalone_search_retries_share_one_timeout_budget(self):
        starts = []

        def run(args, *, capture_output, timeout):
            starts.append((self.now, timeout))
            self.now += 6
            return gh_result("unexpected EOF")

        with mock.patch.object(github.subprocess, "run", side_effect=run):
            rows = github.search_github_repos("query", timeout=10)

        self.assertEqual(starts, [(100, 10), (106, 4)])
        self.assertIn("timeout", rows[0]["error"])

    def test_runner_keeps_timeout_final_eof_and_other_process_errors_distinct(self):
        cases = [
            (subprocess.TimeoutExpired(["gh"], 10), 1, "timeout"),
            (gh_result("unexpected EOF"), 3, "unexpected EOF"),
            (gh_result("authentication required"), 1, "authentication required"),
        ]
        for result, attempts, error in cases:
            with self.subTest(error=error):
                options = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with mock.patch.object(github.subprocess, "run", **options) as run:
                    rows = self.runner().run("query")
                self.assertEqual(run.call_count, attempts)
                self.assertEqual(rows, [{"source": "github-repos", "error": error}])

    def test_runner_token_rest_search_preserves_request_and_success(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = gh_result().stdout
        with mock.patch.object(github, "urlopen_retry", return_value=response) as http, \
                mock.patch.object(github.subprocess, "run") as run:
            rows = self.runner(keys={"github": "fixture-token"}).run("a query")

        run.assert_not_called()
        request = http.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/search/repositories?q=a+query&sort=stars&per_page=3")
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-token")
        self.assertEqual(http.call_args.kwargs, {"timeout": 10})
        self.assertEqual(rows[0]["url"], "https://github.com/owner/repo")

    def test_runner_gh_success_preserves_command_and_count(self):
        with mock.patch.object(github.subprocess, "run", return_value=gh_result()) as run:
            rows = self.runner().run("a query")

        run.assert_called_once_with(
            ["gh", "api", "search/repositories?q=a+query&sort=stars&per_page=3"],
            capture_output=True, timeout=10,
        )
        self.assertEqual(rows[0]["url"], "https://github.com/owner/repo")

    def test_registry_keeps_legacy_provider_signature_compatible(self):
        def legacy_search(query, count, token, timeout=20):
            self.assertEqual((query, count, token, timeout), ("query", 3, "", 10))
            return [{"source": "github-repos", "url": "https://github.com/owner/repo"}]

        with mock.patch.object(registry, "search_github_repos", legacy_search):
            rows = self.runner().run("query")

        self.assertEqual(rows[0]["url"], "https://github.com/owner/repo")

    def test_runner_timeout_keeps_other_results_and_prevents_late_eof_retry(self):
        first_started = threading.Event()
        release_eof = threading.Event()
        caller_returned = threading.Event()
        starts = []
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-github-deadline")
        runner = self.runner()
        other_rows = [
            {"source": "other", "url": "https://example.test/ready", "title": "Ready"},
            {"source": "other", "error": "partial provider error"},
        ]
        runner.providers["other"] = ProviderSpec("other", "other", lambda *_: other_rows)
        # One worker guarantees the other provider completes before gh starts.
        runner.route_resolver = lambda _: ["other", "github_repos"]

        def run(args, *, capture_output, timeout):
            starts.append((self.now, timeout, caller_returned.is_set()))
            first_started.set()
            if not release_eof.wait(timeout=5):
                raise AssertionError("test did not release the blocked gh process")
            return gh_result("unexpected EOF")

        def expire_wait(futures, *, timeout, return_when):
            self.assertTrue(first_started.wait(timeout=5))
            self.now = 110
            return set(), set(futures)

        with mock.patch.object(search_runner, "_SEARCH_POOL", pool), \
                mock.patch.object(search_runner, "wait", side_effect=expire_wait), \
                mock.patch.object(github.subprocess, "run", side_effect=run):
            try:
                rows = runner.run("query")
                caller_returned.set()
                self.assertTrue(first_started.is_set())
                self.assertEqual(rows, [
                    {**other_rows[0], "provider_rank": 1}, other_rows[1],
                    {"source": "github-repos", "error": "timeout after 10s"},
                ])
            finally:
                release_eof.set()
                pool.shutdown(wait=True)

        self.assertEqual(starts, [(100, 10, False)])


if __name__ == "__main__":
    unittest.main()
