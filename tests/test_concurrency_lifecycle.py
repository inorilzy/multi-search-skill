import gc
import subprocess
import sys
import threading
import time
import unittest
import weakref
from unittest import mock

import multi_search_mcp.src.search.search_runner as search_runner_module
import multi_search_mcp.src.scrape.stage as scrape_stage_module
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.scrape.stage import run_ranked_fetch_stage
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


def _live_threads(prefix: str) -> list[threading.Thread]:
    return [
        thread for thread in threading.enumerate()
        if thread.name.startswith(prefix) and thread.is_alive()
    ]


class _LifecyclePayload:
    def __init__(self, size: int = 1):
        self.data = bytearray(size)


def _success_task_factory(closure_payload, result_payload):
    def task(_value):
        if closure_payload is None:
            raise AssertionError("fixture closure was unexpectedly cleared")
        return result_payload

    return task


def _failure_task_factory(closure_payload):
    def task(value):
        if closure_payload is None:
            raise AssertionError("fixture closure was unexpectedly cleared")
        # Keep value in the traceback frame without putting it in the exception.
        raise RuntimeError("fixture task failed")

    return task


def _search_provider_factory(payload):
    def provider(*_args):
        if payload is None:
            raise AssertionError("fixture provider payload was unexpectedly cleared")
        return []

    return provider


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

    def test_success_releases_argument_closure_and_result_references(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-reference-success")
        try:
            argument = _LifecyclePayload(10_000_000)
            closure = _LifecyclePayload()
            result = _LifecyclePayload()
            references = tuple(weakref.ref(item) for item in (argument, closure, result))
            task = _success_task_factory(closure, result)
            future = pool.submit_nowait(task, argument)
            self.assertIsNotNone(future)
            self.assertIs(future.result(timeout=2), result)
            pool._tasks.join()
            del future, task, argument, closure, result

            gc.collect()

            for reference in references:
                self.assertIsNone(reference())
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def test_failure_releases_argument_closure_and_traceback_references(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-reference-failure")
        try:
            argument = _LifecyclePayload(10_000_000)
            closure = _LifecyclePayload()
            references = tuple(weakref.ref(item) for item in (argument, closure))
            task = _failure_task_factory(closure)
            future = pool.submit_nowait(task, argument)
            self.assertIsNotNone(future)
            self.assertIsInstance(future.exception(timeout=2), RuntimeError)
            pool._tasks.join()
            del future, task, argument, closure

            gc.collect()

            for reference in references:
                self.assertIsNone(reference())
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def test_search_runner_releases_provider_closure_after_completion(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-reference-search")
        try:
            payload = _LifecyclePayload(10_000_000)
            reference = weakref.ref(payload)
            provider_call = _search_provider_factory(payload)
            del payload
            providers = {
                "fixture": ProviderSpec(
                    "fixture", "fixture", provider_call, key_required=False,
                ),
            }
            runner = SearchRunner(
                SearchRunnerConfig("test", {}, 0.2, "google", {}),
                providers,
                route_resolver=lambda _route: ["fixture"],
            )
            with mock.patch.object(search_runner_module, "_SEARCH_POOL", pool):
                self.assertEqual(
                    runner.run("query"),
                    [{"source": "fixture", "status": "ok", "raw_hits": 0, "_empty": True}],
                )
            pool._tasks.join()
            del runner, providers, provider_call

            gc.collect()

            self.assertIsNone(reference())
        finally:
            pool.shutdown(wait=True, cancel_futures=True)


class AbandonTests(unittest.TestCase):
    def test_abandoned_running_task_frees_its_slot_immediately(self):
        release = threading.Event()
        started = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-abandon-free")

        def stuck():
            started.set()
            release.wait(timeout=5)
            return "late"

        try:
            stuck_future = pool.submit_nowait(stuck)
            self.assertTrue(started.wait(timeout=1))
            self.assertIsNone(pool.submit_nowait(lambda: "blocked"))
            self.assertTrue(pool.abandon(stuck_future))
            self.assertEqual(pool.detached_count, 1)
            fresh = pool.submit_nowait(lambda: "fresh")
            self.assertIsNotNone(fresh)
            self.assertEqual(fresh.result(timeout=1), "fresh")
            release.set()
            self.assertEqual(stuck_future.result(timeout=1), "late")
            pool._tasks.join()
            self.assertEqual(pool.detached_count, 0)
            # The detached task must not return a slot it no longer holds.
            self.assertIsNotNone(pool.submit_nowait(lambda: None))
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_detached_budget_bounds_threads_and_then_retains_the_slot(self):
        release = threading.Event()
        prefix = "test-abandon-bound"
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix=prefix, max_detached=1)
        first_started = threading.Event()
        second_started = threading.Event()

        def blocked(started):
            started.set()
            return release.wait(5)

        try:
            first = pool.submit_nowait(blocked, first_started)
            self.assertTrue(first_started.wait(timeout=1))
            self.assertTrue(pool.abandon(first))
            second = pool.submit_nowait(blocked, second_started)
            self.assertTrue(second_started.wait(timeout=1))
            self.assertFalse(pool.abandon(second), "no detached budget remains")
            self.assertIsNone(pool.submit_nowait(lambda: None))
            self.assertLessEqual(len(_live_threads(prefix)), 2)
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_abandoning_a_finished_task_is_a_no_op(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-abandon-done")
        try:
            future = pool.submit_nowait(lambda: "done")
            self.assertEqual(future.result(timeout=1), "done")
            pool._tasks.join()
            self.assertTrue(pool.abandon(future))
            self.assertEqual(pool.detached_count, 0)
            # The finished task's slot was released exactly once.
            self.assertIsNotNone(pool.submit_nowait(lambda: None))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)


class SearchRunnerLifecycleTests(unittest.TestCase):
    def test_new_search_runs_normally_after_consecutive_provider_timeouts(self):
        """Regression: a stuck provider must not starve later searches."""
        prefix = "test-search-after-timeouts"
        unblock = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix=prefix)

        def stuck(*_args):
            unblock.wait(timeout=5)
            return []

        def fast(*_args):
            return [{"source": "fast", "title": "Fresh", "url": "https://example.test/fresh"}]

        stuck_runner = SearchRunner(
            SearchRunnerConfig("test", {}, 0.05, "google", {}),
            {"stuck": ProviderSpec("stuck", "stuck", stuck)},
            route_resolver=lambda _route: ["stuck"],
        )
        fast_runner = SearchRunner(
            SearchRunnerConfig("test", {}, 1, "google", {}),
            {"fast": ProviderSpec("fast", "fast", fast)},
            route_resolver=lambda _route: ["fast"],
        )
        try:
            with mock.patch.object(search_runner_module, "_SEARCH_POOL", pool):
                # max_workers=1 => one stuck call can be detached.
                rows = stuck_runner.run("stuck")
                self.assertIn("timeout after 0.05s", rows[0]["error"])
                started = time.monotonic()
                rows = fast_runner.run("fresh")
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual(rows[0].get("url"), "https://example.test/fresh")
                self.assertNotIn("error", rows[0])
        finally:
            unblock.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_saturated_pool_is_reported_as_capacity_not_timeout(self):
        release = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-search-capacity", max_detached=0)
        try:
            pool.submit_nowait(release.wait, 5)
            runner = SearchRunner(
                SearchRunnerConfig("test", {}, 0.05, "google", {}),
                {"fixture": ProviderSpec("fixture", "fixture", lambda *_: [])},
                route_resolver=lambda _route: ["fixture"],
            )
            with mock.patch.object(search_runner_module, "_SEARCH_POOL", pool):
                rows = runner.run("query")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["error_type"], "capacity")
            self.assertIn("saturated", rows[0]["error"])
            self.assertNotIn("timeout", rows[0]["error"])
            from multi_search_mcp.src.state.key_state import classify_error
            self.assertEqual(classify_error(rows[0]["error"], error_type=rows[0]["error_type"]), "capacity")
            self.assertNotEqual(classify_error(rows[0]["error"]), "timeout")
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

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
            # The provider that started and ran out of time is a timeout; the
            # one that never obtained a worker slot is reported as saturation.
            self.assertIn("timeout", by_source["blocked"]["error"])
            self.assertIn("saturated", by_source["unsubmitted"]["error"])
            self.assertEqual(by_source["unsubmitted"]["error_type"], "capacity")
            self.assertNotIn("timeout", by_source["unsubmitted"]["error"])
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_timed_out_worker_does_not_delay_process_exit(self):
        script = """
import threading
from multi_search_mcp.src.search.search_runner import ProviderSpec, SearchRunner, SearchRunnerConfig

def blocking_provider(*_args):
    threading.Event().wait()  # never released: only process exit ends it
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
                for attempt in range(6):
                    started = time.monotonic()
                    rows = runner.run("stuck query")
                    self.assertLess(time.monotonic() - started, 0.25)
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["source"], "blocking")
                    # Runs 1-2 detach their stuck call (freeing the slot), runs
                    # 3-4 exhaust the detached budget and keep their slots; the
                    # bounded pool then reports saturation instead of timeout.
                    expected = "timeout after 0.05s" if attempt < 4 else "saturated"
                    self.assertIn(expected, rows[0]["error"])

                # Workers start synchronously at submission, so the bound holds now:
                # max_workers running plus at most max_detached abandoned threads.
                self.assertLessEqual(len(_live_threads(prefix)), 4)
        finally:
            unblock.set()
            pool.shutdown(wait=True, cancel_futures=True)


class RankedFetchStageLifecycleTests(unittest.TestCase):
    def test_fetch_runs_normally_after_a_timed_out_fetch(self):
        unblock = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-fetch-after-timeout")
        hit = [{"source_id": "src_doc", "title": "Doc", "url": "https://example.com/doc"}]
        try:
            with mock.patch.object(scrape_stage_module, "_SCRAPE_POOL", pool):
                stuck = run_ranked_fetch_stage(
                    hit, fetch=lambda *_: unblock.wait(timeout=5) and {}, timeout=0.05,
                )
                self.assertIn("fetch timeout", stuck["errors"][0]["error"])
                fresh = run_ranked_fetch_stage(
                    hit, fetch=lambda h, _r: {"source_id": h["source_id"], "url": h["url"], "body": "ok"},
                    timeout=1,
                )
            self.assertEqual(fresh["errors"], [])
            self.assertEqual(fresh["results"][0]["body"], "ok")
        finally:
            unblock.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_saturated_fetch_pool_is_reported_as_capacity(self):
        release = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-fetch-capacity", max_detached=0)
        hit = [{"source_id": "src_doc", "title": "Doc", "url": "https://example.com/doc"}]
        try:
            pool.submit_nowait(release.wait, 5)
            with mock.patch.object(scrape_stage_module, "_SCRAPE_POOL", pool):
                result = run_ranked_fetch_stage(hit, fetch=mock.Mock(), timeout=0.05)
            self.assertEqual(result["errors"][0]["error_type"], "capacity")
            self.assertIn("saturated", result["errors"][0]["error"])
            self.assertNotIn("timeout", result["errors"][0]["error"])
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)

    def test_ranked_fetch_timeouts_do_not_spawn_unbounded_workers(self):
        prefix = "test-ranked-fetch-stage-lifecycle"
        unblock = threading.Event()
        pool = BoundedDaemonExecutor(max_workers=2, thread_name_prefix=prefix)

        def blocking_fetch(hit, _remaining):
            unblock.wait(timeout=5)
            return {"source_id": hit["source_id"], "url": hit["url"], "body": "body"}

        hits = [
            {"source_id": "src_doc", "title": "Doc", "url": "https://example.com/doc"}
        ]

        try:
            with mock.patch.object(scrape_stage_module, "_SCRAPE_POOL", pool):
                for attempt in range(6):
                    started = time.monotonic()
                    result = run_ranked_fetch_stage(
                        hits, fetch=blocking_fetch, timeout=0.05, concurrency=1,
                    )
                    self.assertLess(time.monotonic() - started, 0.25)
                    self.assertEqual(len(result["errors"]), 1)
                    self.assertEqual(result["errors"][0]["source_id"], "src_doc")
                    expected = "fetch timeout after 0.05s" if attempt < 4 else "saturated"
                    self.assertIn(expected, result["errors"][0]["error"])

                # Workers start synchronously at submission, so the bound holds now:
                # max_workers running plus at most max_detached abandoned threads.
                self.assertLessEqual(len(_live_threads(prefix)), 4)
        finally:
            unblock.set()
            pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
