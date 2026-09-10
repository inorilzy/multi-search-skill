import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import multi_search_mcp.src.search.search_runner as search_runner_module
import multi_search_mcp.src.scrape.stage as scrape_stage_module
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.scrape.stage import run_scrape_stage
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


def _live_threads(prefix: str) -> list[threading.Thread]:
    return [
        thread for thread in threading.enumerate()
        if thread.name.startswith(prefix) and thread.is_alive()
    ]


class BoundedDaemonExecutorTests(unittest.TestCase):
    def test_uses_available_workers_for_queued_tasks(self):
        release = threading.Event()
        both_started = threading.Event()
        started = 0
        started_lock = threading.Lock()
        pool = BoundedDaemonExecutor(max_workers=2, thread_name_prefix="test-pool-capacity")

        def blocking_task():
            nonlocal started
            with started_lock:
                started += 1
                if started == 2:
                    both_started.set()
            release.wait(timeout=2)

        try:
            deadline = time.monotonic() + 1
            self.assertIsNotNone(pool.submit_before(deadline, blocking_task))
            self.assertIsNotNone(pool.submit_before(deadline, blocking_task))
            self.assertTrue(both_started.wait(timeout=0.5))
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)


class SearchRunnerLifecycleTests(unittest.TestCase):
    def test_saturated_pool_preserves_completed_provider_outcomes(self):
        release = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-search-completed")

        def success(*_args):
            return [{"source": "success", "title": "Ready", "url": "https://example.test/ready"}]

        def broken(*_args):
            raise RuntimeError("provider unavailable")

        def blocked(*_args):
            release.wait(timeout=2)
            return []

        providers = {
            "success": ProviderSpec("success", "success", success),
            "empty": ProviderSpec("empty", "empty", lambda *_: []),
            "broken": ProviderSpec("broken", "broken", broken),
            "blocked": ProviderSpec("blocked", "blocked", blocked),
            "unsubmitted": ProviderSpec("unsubmitted", "unsubmitted", blocked),
        }
        runner = SearchRunner(
            SearchRunnerConfig("test", {}, 0.1, "google", {}), providers,
            route_resolver=lambda _route: list(providers),
        )
        try:
            with mock.patch.object(search_runner_module, "_SEARCH_POOL", pool):
                rows = runner.run("query")
            by_source = {row["source"]: row for row in rows}
            self.assertEqual(by_source["success"].get("url"), "https://example.test/ready")
            self.assertTrue(by_source["empty"].get("_empty"))
            self.assertEqual(by_source["broken"]["error"], "provider unavailable")
            for source in ("blocked", "unsubmitted"):
                self.assertIn("timeout", by_source[source]["error"])
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_timed_out_worker_does_not_delay_process_exit(self):
        script = """
import time
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig

def blocking_provider(*_args):
    time.sleep(5)
    return []

runner = SearchRunner(
    SearchRunnerConfig("test", {}, 0.01, "google", {}),
    {"blocking": ProviderSpec("blocking", "blocking", blocking_provider)},
    route_resolver=lambda _route: {"blocking"},
)
runner.run("query")
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_search_runner_timeouts_do_not_spawn_unbounded_workers(self):
        prefix = "test-search-runner-lifecycle"
        unblock = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=2, thread_name_prefix=prefix)

        def blocking_provider(_query, _config, _ctx, _api_key):
            unblock.wait(timeout=5)
            return [{"source": "blocking", "title": "done", "url": "https://example.com/done"}]

        runner = SearchRunner(
            SearchRunnerConfig(
                route="test",
                counts={},
                timeout=0.05,
                serpapi_engine="google",
                keys={},
            ),
            providers={
                "blocking": ProviderSpec(
                    name="blocking",
                    public_name="blocking",
                    call=blocking_provider,
                    timeout_default=30,
                )
            },
            route_resolver=lambda _route: {"blocking"},
        )

        try:
            with mock.patch.object(search_runner_module, "_SEARCH_POOL", pool, create=True):
                for _ in range(6):
                    started = time.monotonic()
                    rows = runner.run("stuck query")
                    self.assertLess(time.monotonic() - started, 0.25)
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["source"], "blocking")
                    self.assertIn("timeout after 0.05s", rows[0]["error"])

                time.sleep(0.05)
                self.assertLessEqual(len(_live_threads(prefix)), 2)
        finally:
            unblock.set()
            pool.shutdown(wait=True, cancel_futures=True)


class ScrapeStageLifecycleTests(unittest.TestCase):
    def test_scrape_stage_timeouts_do_not_spawn_unbounded_workers(self):
        prefix = "test-scrape-stage-lifecycle"
        unblock = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=2, thread_name_prefix=prefix)

        def blocking_scrape(url, **_kwargs):
            unblock.wait(timeout=5)
            return {"url": url, "title": "done", "markdown": "body"}

        all_results = [
            {"source": "brave", "title": "Doc", "url": "https://example.com/doc"}
        ]

        try:
            with mock.patch.object(scrape_stage_module, "_SCRAPE_POOL", pool, create=True):
                with mock.patch.object(scrape_stage_module, "scrape_url_smart", side_effect=blocking_scrape):
                    for _ in range(6):
                        started = time.monotonic()
                        result = run_scrape_stage(
                            all_results,
                            keys={},
                            scrape_top=1,
                            scrape_per_source=1,
                            scrape_timeout=0.05,
                            scrape_concurrency=1,
                            site_memory=None,
                        )
                        self.assertLess(time.monotonic() - started, 0.25)
                        self.assertEqual(len(result["scrape_errors"]), 1)
                        self.assertIn("scrape timeout after 0.05s", result["scrape_errors"][0]["error"])

                time.sleep(0.05)
                self.assertLessEqual(len(_live_threads(prefix)), 2)
        finally:
            unblock.set()
            pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
