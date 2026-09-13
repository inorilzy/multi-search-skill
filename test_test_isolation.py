import http.server
import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.response
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from scripts.test_isolation import (
    NetworkGuard,
    NetworkIsolationError,
    active_guard,
    isolated_test_environment,
)


ROOT = Path(__file__).resolve().parent


class TestIsolationTests(unittest.TestCase):
    def test_default_environment_uses_disposable_home_and_synthetic_sources(self):
        context = (
            isolated_test_environment(source_root=ROOT)
            if active_guard() is None else nullcontext()
        )
        with context:
            home = Path.home()
            self.assertEqual(Path(os.environ["USERPROFILE"]), home)
            self.assertEqual(Path(os.environ["HOME"]), home)
            self.assertEqual(os.environ.get("MULTI_SEARCH_CONFIG", ""), "")

            completed = subprocess.run(
                [sys.executable, "-B", "-c", r'''
import json
import os
from pathlib import Path

home = Path.home()
assert home == Path(os.environ["USERPROFILE"])
from multi_search_mcp.src.support import config as config_module
from multi_search_mcp.src.state import state_store
from multi_search_mcp.src.state.keys import load_keys

assert config_module.USER_CONFIG_PATH == home / ".multi-search" / "multi-search-config.json"
assert config_module.USER_CONFIG_PATH.is_file()
assert json.loads(config_module.USER_CONFIG_PATH.read_text(encoding="utf-8")) == {}
keys_path = home / ".search-keys.json"
assert keys_path.is_file()
assert json.loads(keys_path.read_text(encoding="utf-8")) == {}
assert state_store.DEFAULT_STATE_PATH == home / ".multi-search" / "state.sqlite"
assert set(load_keys()) == set()
print("isolated defaults ok")
'''],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertIn("isolated defaults ok", completed.stdout or "")

    def test_existing_tests_can_inject_synthetic_credentials(self):
        with isolated_test_environment(source_root=ROOT):
            from multi_search_mcp.src.state.keys import load_keys

            with mock.patch.dict(os.environ, {"EXA_API_KEY": "synthetic-exa"}, clear=False):
                loaded_keys = load_keys()
                self.assertEqual(set(loaded_keys), {"exa"})
                self.assertTrue(loaded_keys["exa"])

    def test_external_opener_is_blocked_before_dns_and_recorded(self):
        with isolated_test_environment(source_root=ROOT) as isolation:
            guard = active_guard()
            self.assertIsNotNone(guard)
            before = guard.violation_count

            with mock.patch("socket.getaddrinfo", side_effect=AssertionError("DNS must not run")) as dns:
                with self.assertRaises(NetworkIsolationError) as error:
                    urllib.request.build_opener().open(
                        "https://outside.invalid/search?api_key=synthetic-secret",
                    )

            self.assertEqual(dns.call_count, 0)
            self.assertEqual(guard.violation_count, before + 1)
            self.assertNotIn("synthetic-secret", str(error.exception))
            with self.assertRaises(NetworkIsolationError):
                isolation.assert_clean()

    def test_external_url_cannot_use_a_loopback_system_proxy(self):
        if not hasattr(urllib.request, "getproxies_registry"):
            self.skipTest("Windows registry proxy handling is unavailable")

        with isolated_test_environment(source_root=ROOT) as isolation:
            with mock.patch.object(
                urllib.request,
                "getproxies_registry",
                return_value={"https": "http://127.0.0.1:3128"},
            ):
                with self.assertRaises(NetworkIsolationError) as error:
                    urllib.request.build_opener().open(
                        "https://outside.invalid/proxy?token=proxy-secret",
                    )

            self.assertNotIn("proxy-secret", str(error.exception))
            with self.assertRaises(NetworkIsolationError):
                isolation.assert_clean()

    def test_direct_external_ip_is_blocked_before_socket_connect(self):
        with isolated_test_environment(source_root=ROOT) as isolation:
            guard = active_guard()
            before = guard.violation_count
            sock = socket.socket()
            try:
                with self.assertRaises(NetworkIsolationError) as error:
                    sock.connect(("203.0.113.10", 443))
            finally:
                sock.close()

            self.assertEqual(guard.violation_count, before + 1)
            self.assertNotIn("203.0.113.10", str(error.exception))
            with self.assertRaises(NetworkIsolationError):
                isolation.assert_clean()

    def test_controlled_loopback_http_remains_allowed(self):
        with isolated_test_environment(source_root=ROOT):
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    body = b"controlled-local-response"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *_args):
                    pass

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/fixture",
                    timeout=3,
                ) as response:
                    self.assertEqual(response.read(), b"controlled-local-response")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_custom_memory_opener_remains_allowed(self):
        with isolated_test_environment(source_root=ROOT):
            class Handler(urllib.request.BaseHandler):
                def memory_open(self, request):
                    headers = {}
                    return urllib.response.addinfourl(
                        io.BytesIO(b"memory-response"), headers, request.full_url, 200,
                    )

            with urllib.request.build_opener(Handler()).open("memory://fixture") as response:
                self.assertEqual(response.read(), b"memory-response")

    def test_curl_cffi_is_blocked_before_native_transport(self):
        try:
            from curl_cffi import requests
        except ImportError:
            self.skipTest("curl_cffi is not installed")

        calls = []

        def fake_request(session, method, url, *args, **kwargs):
            calls.append((method, url))
            return object()

        with mock.patch.object(requests.Session, "request", fake_request):
            with tempfile.TemporaryDirectory() as temp:
                with NetworkGuard(Path(temp) / "violations.log") as guard:
                    with requests.Session(trust_env=False) as session:
                        with self.assertRaises(NetworkIsolationError) as error:
                            session.get("https://203.0.113.1/fixture?token=curl-secret")
                    self.assertEqual(calls, [])
                    with self.assertRaises(NetworkIsolationError):
                        guard.assert_clean()
            self.assertNotIn("curl-secret", str(error.exception))

    def test_child_process_inherits_home_credentials_and_network_guard(self):
        script = r'''
import json
import os
import socket
import urllib.request
from pathlib import Path

from scripts.test_isolation import NetworkIsolationError, active_guard

assert active_guard() is not None, "child test isolation was not activated"
home = Path.home()
assert home == Path(os.environ["USERPROFILE"])
assert os.environ.get("MULTI_SEARCH_CONFIG", "") == ""
from multi_search_mcp.src.support.config import USER_CONFIG_PATH
assert USER_CONFIG_PATH == home / ".multi-search" / "multi-search-config.json"
assert USER_CONFIG_PATH.is_file()
assert json.loads((home / ".search-keys.json").read_text(encoding="utf-8")) == {}
from multi_search_mcp.src.state.keys import load_keys
loaded_keys = load_keys()
assert not loaded_keys, "child key names: " + ",".join(sorted(loaded_keys))
try:
    urllib.request.build_opener().open(
        "https://outside.invalid/child?token=child-secret",
    )
except NetworkIsolationError:
    pass
else:
    raise AssertionError("child external HTTP was not blocked")
print("child isolation ok")
'''
        with isolated_test_environment(source_root=ROOT) as isolation:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertNotIn("child-secret", (completed.stdout or "") + (completed.stderr or ""))
            with self.assertRaises(NetworkIsolationError):
                isolation.assert_clean()

    def test_caught_child_violation_still_fails_isolated_run(self):
        script = r'''
import urllib.request
from scripts.test_isolation import NetworkIsolationError
try:
    urllib.request.build_opener().open("https://outside.invalid/child?token=child-secret")
except NetworkIsolationError:
    pass
'''
        with isolated_test_environment(source_root=ROOT) as isolation:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            with self.assertRaises(NetworkIsolationError) as error:
                isolation.assert_clean()
            self.assertNotIn("child-secret", str(error.exception))

    def test_explicit_child_environment_cannot_drop_the_guard_bootstrap(self):
        script = r'''
import urllib.request
from scripts.test_isolation import NetworkIsolationError, active_guard
assert active_guard() is not None, "explicit child environment dropped isolation"
try:
    urllib.request.build_opener().open("https://outside.invalid/child?token=filtered-secret")
except NetworkIsolationError:
    pass
else:
    raise AssertionError("external HTTP was not blocked")
'''
        minimal_env = {
            name: os.environ[name]
            for name in ("PATH", "SYSTEMROOT", "WINDIR")
            if name in os.environ
        }
        minimal_env["PYTHONPATH"] = str(ROOT)
        with isolated_test_environment(source_root=ROOT) as isolation:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=ROOT,
                env=minimal_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            with self.assertRaises(NetworkIsolationError):
                isolation.assert_clean()


if __name__ == "__main__":
    unittest.main()
