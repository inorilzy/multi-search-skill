"""MCP scheduling regressions with controlled Core work and no network access."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from mcp import types
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from multi_search_mcp import server
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


class MCPDispatchConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pool = BoundedDaemonExecutor(max_workers=4, thread_name_prefix="test-mcp-tool")
        patcher = mock.patch.object(server, "_TOOL_POOL", self.pool)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.pool.shutdown)

    async def test_light_tool_finishes_while_search_core_is_still_running(self):
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_core(request):
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(3):
                    raise RuntimeError("test watchdog released a blocked MCP loop")
                return {"results": [], "errors": []}
            finally:
                finished.set()

        with mock.patch("multi_search_mcp.tools.run_search_web", side_effect=slow_core):
            search = asyncio.create_task(server.mcp.call_tool("search_web", {"query": "fixture"}))
            try:
                await started.wait()
                content = await asyncio.wait_for(server.mcp.call_tool("list_sources", {}), 1)
                result = json.loads(content[0].text)
                self.assertIn("sources", result)
                self.assertFalse(finished.is_set(), "list_sources waited for the slow Core to finish")
                self.assertFalse(search.done())
            finally:
                release.set()
                await search

    async def test_network_doctor_runs_off_loop_while_light_tool_finishes(self):
        loop_thread = threading.get_ident()
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        captured = {}
        payload = {
            "network_checked": True,
            "network_ok": True,
            "network_checks": [{"status": "ok"}],
        }

        def slow_doctor(include_keys=True, include_network=False):
            captured["thread"] = threading.get_ident()
            captured["include_keys"] = include_keys
            captured["include_network"] = include_network
            started.set()
            try:
                if not release.wait(3):
                    raise RuntimeError("test watchdog released a blocked doctor")
                return payload
            finally:
                finished.set()

        with mock.patch("multi_search_mcp.server.doctor_tool", side_effect=slow_doctor):
            release_timer = threading.Timer(0.3, release.set)
            release_timer.daemon = True
            release_timer.start()
            doctor = asyncio.create_task(server.mcp.call_tool(
                "doctor", {"include_keys": False, "include_network": True}
            ))
            try:
                await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1)
                content = await asyncio.wait_for(server.mcp.call_tool("list_sources", {}), 1)
                self.assertIn("sources", json.loads(content[0].text))
                self.assertFalse(finished.is_set(), "list_sources waited for network doctor")
                self.assertNotEqual(captured["thread"], loop_thread)
                self.assertFalse(captured["include_keys"])
                self.assertTrue(captured["include_network"])
            finally:
                release.set()
                release_timer.cancel()
                content = await doctor
            self.assertEqual(json.loads(content[0].text), payload)

    async def test_doctor_preserves_defaults_and_structured_network_failures(self):
        success_payload = {
            "network_checked": False,
            "network_ok": None,
            "network_checks": [],
        }
        with mock.patch("multi_search_mcp.server.doctor_tool", return_value=success_payload) as doctor_tool:
            content = await server.mcp.call_tool("doctor", {})
        doctor_tool.assert_called_once_with(True, False)
        self.assertEqual(json.loads(content[0].text), success_payload)

        failure_payload = {
            "network_checked": True,
            "network_ok": False,
            "network_checks": [{"status": "error", "error": "probe failed"}],
        }
        with mock.patch("multi_search_mcp.server.doctor_tool", return_value=failure_payload) as doctor_tool:
            content = await server.mcp.call_tool(
                "doctor", {"include_keys": False, "include_network": True}
            )
        doctor_tool.assert_called_once_with(False, True)
        self.assertEqual(json.loads(content[0].text), failure_payload)

    async def test_cancelled_doctors_keep_capacity_until_probes_finish(self):
        release = threading.Event()
        all_started = threading.Event()
        started_threads = []
        started_lock = threading.Lock()
        calls = []
        payload = {
            "network_checked": True,
            "network_ok": True,
            "network_checks": [{"status": "ok"}],
        }

        def slow_doctor(include_keys=True, include_network=False):
            with started_lock:
                started_threads.append(threading.get_ident())
                if len(started_threads) == 4:
                    all_started.set()
            if not release.wait(3):
                raise RuntimeError("test watchdog released blocked doctors")
            return payload

        with mock.patch("multi_search_mcp.server.doctor_tool", side_effect=slow_doctor) as doctor_tool:
            try:
                calls = [asyncio.create_task(server.mcp.call_tool(
                    "doctor", {"include_keys": False, "include_network": True}
                )) for _ in range(4)]
                await asyncio.wait_for(asyncio.to_thread(all_started.wait, 2), 2)
                self.assertEqual(len(started_threads), 4)

                for call in calls:
                    call.cancel()
                for call in calls:
                    with self.assertRaises(asyncio.CancelledError):
                        await call

                for _ in range(8):
                    content = await server.mcp.call_tool(
                        "doctor", {"include_keys": False, "include_network": True}
                    )
                    error = json.loads(content[0].text)
                    self.assertEqual(error["error_type"], "runtime_error")
                    self.assertIn("capacity exhausted", error["error"])
                self.assertEqual(doctor_tool.call_count, 4)

                content = await server.mcp.call_tool("list_sources", {})
                self.assertIn("sources", json.loads(content[0].text))
            finally:
                release.set()
                await asyncio.gather(*calls, return_exceptions=True)

        await asyncio.to_thread(self.pool._tasks.join)
        with mock.patch("multi_search_mcp.server.doctor_tool", return_value=payload):
            content = await server.mcp.call_tool(
                "doctor", {"include_keys": False, "include_network": True}
            )
        self.assertEqual(json.loads(content[0].text), payload)

    async def test_network_doctor_reports_probe_failure_over_mcp(self):
        from multi_search_mcp.src import service
        from multi_search_mcp.src.state.state_store import StateStore

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            store = StateStore(temp_path / "state.sqlite")
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = b"{}"
            with mock.patch.object(service, "StateStore", return_value=store), \
                 mock.patch.object(service, "load_keys", return_value={}), \
                 mock.patch.object(service, "load_config", return_value={}), \
                 mock.patch.object(service, "resolve_config_path", return_value=temp_path / "config.json"), \
                 mock.patch("multi_search_mcp.src.support.http.urlopen_retry",
                            side_effect=[response, TimeoutError("probe timeout")]) as opener:
                content = await server.mcp.call_tool(
                    "doctor", {"include_keys": False, "include_network": True}
                )

        result = json.loads(content[0].text)
        self.assertEqual(opener.call_count, 2)
        self.assertTrue(result["network_checked"])
        self.assertFalse(result["network_ok"])
        self.assertEqual([row["status"] for row in result["network_checks"]], ["ok", "error"])
        self.assertIn("probe timeout", result["network_checks"][1]["error"])

    async def test_all_expensive_tools_run_core_off_loop_and_preserve_results(self):
        cases = [
            ("search_web", "run_search_web", {"query": "fixture", "timeout": 7}),
            ("multi_search", "run_multi_search", {"query": "fixture", "timeout": 7,
                                                  "scrape_timeout": 5, "output": "json"}),
            ("fetch_source", "run_fetch_source", {"url": "https://example.com/fixture",
                                                  "timeout": 7, "full_content": True}),
            ("scrape_url", "run_scrape", {"url": "https://example.com/fixture",
                                          "scrape_timeout": 7, "output": "json"}),
        ]
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        for name, core_name, arguments in cases:
            with self.subTest(tool=name):
                started = asyncio.Event()
                release = threading.Event()
                captured = {}
                payload = {"results": [{"url": "https://example.com/fixture"}],
                           "errors": [{"source": "fixture", "error": "deadline exceeded"}]}

                def slow_core(request):
                    captured["thread"] = threading.get_ident()
                    captured["request"] = request
                    loop.call_soon_threadsafe(started.set)
                    if not release.wait(3):
                        raise RuntimeError("test watchdog released a blocked MCP loop")
                    return payload

                with mock.patch(f"multi_search_mcp.tools.{core_name}", side_effect=slow_core):
                    call = asyncio.create_task(server.mcp.call_tool(name, arguments))
                    try:
                        await started.wait()
                        self.assertNotEqual(captured["thread"], loop_thread)
                        self.assertFalse(call.done())
                        self.assertEqual(captured["request"].timeout, 7)
                        if name == "multi_search":
                            self.assertEqual(captured["request"].scrape_timeout, 5)
                        if name == "fetch_source":
                            self.assertTrue(captured["request"].full_content)
                    finally:
                        release.set()
                        content = await call
                    self.assertEqual(json.loads(content[0].text), payload)

    async def test_cancelled_waiters_keep_capacity_until_core_finishes(self):
        loop = asyncio.get_running_loop()
        started = [asyncio.Event() for _ in range(4)]
        release = threading.Event()
        calls = []

        def slow_core(request):
            index = int(request.query)
            loop.call_soon_threadsafe(started[index].set)
            if not release.wait(3):
                raise RuntimeError("test watchdog released blocked workers")
            return {"results": []}

        with mock.patch("multi_search_mcp.tools.run_search_web", side_effect=slow_core) as core:
            try:
                calls = [asyncio.create_task(server.mcp.call_tool("search_web", {"query": str(i)}))
                         for i in range(4)]
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 2)
                for call in calls:
                    call.cancel()
                for call in calls:
                    with self.assertRaises(asyncio.CancelledError):
                        await call
                # Repeated requests after cancellation cannot enqueue more Core work.
                for _ in range(8):
                    content = await server.mcp.call_tool("search_web", {"query": "extra"})
                    error = json.loads(content[0].text)
                    self.assertEqual(error["error_type"], "runtime_error")
                    self.assertIn("capacity exhausted", error["error"])
                self.assertEqual(core.call_count, 4)
                content = await server.mcp.call_tool("list_sources", {})
                self.assertIn("sources", json.loads(content[0].text))
            finally:
                release.set()
                await asyncio.gather(*calls, return_exceptions=True)
        # Wait for actual completion, including the executor's slot release.
        await asyncio.to_thread(self.pool._tasks.join)
        self.assertEqual(len(self.pool._threads), 4)
        with mock.patch("multi_search_mcp.tools.run_search_web", return_value={"results": []}):
            content = await server.mcp.call_tool("search_web", {"query": "after completion"})
        self.assertEqual(json.loads(content[0].text), {"results": []})

    async def test_protocol_cancel_is_received_before_running_core_finishes(self):
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_core(request):
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(3):
                    raise RuntimeError("test watchdog released a blocked MCP loop")
                return {"results": []}
            finally:
                finished.set()

        with mock.patch("multi_search_mcp.tools.run_search_web", side_effect=slow_core):
            async with create_connected_server_and_client_session(server.mcp) as client:
                await client.list_tools()  # Populate schema cache before tracking the call id.
                request_id = client._request_id
                call = asyncio.create_task(client.call_tool("search_web", {"query": "fixture"}))
                try:
                    await asyncio.wait_for(started.wait(), 2)
                    light = await asyncio.wait_for(client.call_tool("list_sources", {}), 1)
                    self.assertFalse(light.isError)
                    self.assertFalse(finished.is_set())
                    await client.send_notification(types.ClientNotification(types.CancelledNotification(
                        params=types.CancelledNotificationParams(requestId=request_id, reason="fixture")
                    )))
                    with self.assertRaises(McpError) as error:
                        await asyncio.wait_for(call, 1)
                    self.assertEqual(error.exception.error.message, "Request cancelled")
                    self.assertFalse(finished.is_set(), "cancel was delayed until Core completion")
                finally:
                    release.set()
                    await asyncio.gather(call, return_exceptions=True)

    async def test_protocol_tool_errors_keep_existing_payload_and_error_flag(self):
        async with create_connected_server_and_client_session(server.mcp) as client:
            for exception, error_type in [(ValueError("fixture invalid"), "invalid_request"),
                                          (RuntimeError("fixture failed"), "runtime_error")]:
                with self.subTest(error_type=error_type), \
                     mock.patch("multi_search_mcp.tools.run_search_web", side_effect=exception):
                    result = await client.call_tool("search_web", {"query": "fixture"})
                    self.assertFalse(result.isError)
                    self.assertIsNone(result.structuredContent)
                    self.assertEqual(json.loads(result.content[0].text),
                                     {"error": str(exception), "error_type": error_type})
            invalid_schema = await client.call_tool("search_web", {})
            self.assertTrue(invalid_schema.isError)


if __name__ == "__main__":
    unittest.main()
