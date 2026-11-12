"""OAuth login flows for Firecrawl PKCE and Parallel device code (ticket 07).

Every case drives the real CLI entry point against a temporary HOME. All HTTP
calls are replaced with a recording fake, and WebKit/browser opening, sleep and
the monotonic clock are injected so the suite is offline and instant. Each
assertion on stdout/stderr also proves that no API key or token is echoed.
"""
from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.state.key_state import key_fingerprint
from multi_search_mcp.src.plugins import oauth as oauth_module
from multi_search_mcp.src.plugins import oauth_store

FIRECRAWL_STATUS_URL = "https://www.firecrawl.dev/api/auth/cli/status"
FIRECRAWL_BALANCE_URL = "https://api.firecrawl.dev/v2/team/credit-usage"
PARALLEL_REGISTER_URL = "https://platform.parallel.ai/getServiceKeys/register"
PARALLEL_DEVICE_URL = "https://platform.parallel.ai/getServiceKeys/device/code"
PARALLEL_TOKEN_URL = "https://platform.parallel.ai/getServiceKeys/token"
PARALLEL_REVOKE_URL = "https://platform.parallel.ai/getServiceKeys/token/revoke"
PARALLEL_BALANCE_URL = "https://api.parallel.ai/account/service/v1/balance"


class FakeResponse:
    """Minimal urllib response: context manager plus bounded ``read``."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amount=None):
        if amount is None or amount < 0:
            return self.body
        return self.body[:amount]


class FakeHTTP:
    """Route-by-URL fake for ``support.http.urlopen_retry``.

    A route value may be a body, an exception to raise, a callable taking the
    request, or a list consumed from the front (the final item repeats).
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []

    def add(self, url, response):
        self.routes[url] = response

    def __call__(self, request, *, timeout, retries, deadline):
        self.requests.append(request)
        url = request.full_url
        if url not in self.routes:
            raise AssertionError(f"unexpected HTTP request: {url}")
        response = self.routes[url]
        if isinstance(response, list):
            response = response.pop(0) if len(response) > 1 else response[0]
        if callable(response) and not isinstance(response, BaseException):
            response = response(request)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response)

    def requests_for(self, url):
        return [request for request in self.requests if request.full_url == url]


def http_error(status, body=None, url=PARALLEL_TOKEN_URL):
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    return urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(payload))


def form_body(request):
    return dict(urllib.parse.parse_qsl(request.data.decode("utf-8")))


def json_body(request):
    return json.loads(request.data.decode("utf-8"))


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class HangsUpStdin:
    """Open when the login starts, then closed by the parent (a terminal or wrapper hanging up)."""

    def __init__(self, open_checks=1):
        self.open_checks = open_checks

    @property
    def closed(self):
        if self.open_checks > 0:
            self.open_checks -= 1
            return False
        return True


class RecordingStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


class OAuthTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="login-oauth-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        env_patcher = mock.patch.dict(os.environ, {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "PARALLEL_API_KEY": "",
            "FIRECRAWL_API_KEY": "",
        })
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        home_patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        home_patcher.start()
        self.addCleanup(home_patcher.stop)

        self.clock = FakeClock()
        clock_patcher = mock.patch.object(oauth_module, "_now", self.clock.monotonic)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)
        sleep_patcher = mock.patch.object(oauth_module, "_sleep", self.clock.sleep)
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

        self.keys_file = self.home / ".multi-search" / "keys.json"
        self.oauth_file = self.home / ".multi-search" / "oauth.json"

    def write_keys(self, data):
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def read_keys(self):
        return json.loads(self.keys_file.read_text(encoding="utf-8"))

    def write_oauth(self, data):
        self.oauth_file.parent.mkdir(parents=True, exist_ok=True)
        self.oauth_file.write_text(json.dumps(data), encoding="utf-8")

    def read_oauth(self):
        return json.loads(self.oauth_file.read_text(encoding="utf-8"))

    def run_cli(self, argv, stdin_text="", stdout=None):
        stdout = stdout or io.StringIO()
        stderr = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin_text)):
            code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def run_cli_with_stdin(self, argv, stdin):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", stdin):
            code = cli.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def events(self, stdout):
        return [json.loads(line) for line in stdout.splitlines() if line.strip()]

    def assert_no_secret(self, secret, stdout, stderr):
        self.assertNotIn(secret, stdout)
        self.assertNotIn(secret, stderr)


def firecrawl_routes(api_key, *, statuses=None):
    routes = {
        FIRECRAWL_BALANCE_URL: {
            "data": {"remainingCredits": 42, "planCredits": 100, "billingPeriodEnd": None}
        },
    }
    if statuses is None:
        routes[FIRECRAWL_STATUS_URL] = {"status": "complete", "apiKey": api_key}
    else:
        routes[FIRECRAWL_STATUS_URL] = statuses
    return routes


class FirecrawlOAuthTests(OAuthTestCase):
    def test_firecrawl_oauth_complete_appends_the_api_key_to_keys_json(self):
        key = "fc-oauth-secret-key"
        self.write_keys({"firecrawl": "old-key", "brave": "keep-brave"})
        http = FakeHTTP(firecrawl_routes(key))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        events = self.events(stdout)
        self.assertEqual([event["event"] for event in events], ["open_url", "waiting", "complete"])
        self.assertEqual(set(events[0]), {"event", "url"})
        self.assertEqual(events[1], {"event": "waiting"})
        self.assertEqual(events[2], {
            "event": "complete", "credential": "firecrawl", "needs_search_key": False,
        })
        account_id = self.read_keys()["accounts"]["firecrawl"][0]["id"]
        self.assertRegex(account_id, r"^acc_[A-Za-z0-9]+$")
        self.assertEqual(self.read_keys(), {
            "firecrawl": ["old-key", key],
            "brave": "keep-brave",
            "accounts": {"firecrawl": [{
                "id": account_id, "name": "Firecrawl 登录", "source": "oauth",
                "keys": [key_fingerprint(key)], "balance_credentials": {},
            }]},
        })
        self.assert_no_secret(key, stdout, stderr)

    def test_firecrawl_oauth_complete_queries_the_new_key_balance_once(self):
        key = "fc-oauth-balance-key"
        http = FakeHTTP(firecrawl_routes(key))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        balance_requests = http.requests_for(FIRECRAWL_BALANCE_URL)
        self.assertEqual(len(balance_requests), 1)
        self.assertEqual(balance_requests[0].get_header("Authorization"), f"Bearer {key}")
        self.assert_no_secret(key, stdout, stderr)

    def test_firecrawl_oauth_posts_pkce_s256_challenge_and_matching_verifier(self):
        key = "fc-pkce-key"
        http = FakeHTTP(firecrawl_routes(key))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        open_url = self.events(stdout)[0]["url"]
        parsed = urllib.parse.urlsplit(open_url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["source"], ["coding-agent"])
        session_id = parsed.fragment.split("=", 1)[1]
        status_request = http.requests_for(FIRECRAWL_STATUS_URL)[0]
        posted = json_body(status_request)
        self.assertEqual(posted["session_id"], session_id)
        self.assertEqual(oauth_module.code_challenge_s256(posted["code_verifier"]), query["code_challenge"][0])
        self.assertNotIn(posted["code_verifier"], stdout)
        # Firecrawl answers HTTP 400 "Invalid session_id format" to anything but the
        # documented `openssl rand -hex 32` shape, and "Invalid code_verifier format" to
        # anything but its 43-char base64url verifier.
        self.assertRegex(session_id, r"^[0-9a-f]{64}$")
        self.assertRegex(posted["code_verifier"], r"^[A-Za-z0-9_-]{43}$")

    def test_oauth_with_stdin_at_eof_from_the_start_is_not_a_cancellation(self):
        # The desktop starts the CLI with stdin=/dev/null: EOF at once, never "closed later".
        key = "fc-devnull-key"
        http = FakeHTTP({FIRECRAWL_STATUS_URL: [{"status": "pending"}, {"status": "complete", "apiKey": key}]})
        with open(os.devnull, encoding="utf-8") as devnull, \
                mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http), \
                mock.patch.object(oauth_module, "_sleep", lambda _seconds: None):
            code, stdout, stderr = self.run_cli_with_stdin(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"],
                devnull,
            )
        self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(self.events(stdout)[-1]["event"], "complete")

    def test_a_poll_cut_off_by_the_flow_deadline_is_a_timeout_not_a_network_error(self):
        # urllib wraps the HTTP layer's deadline TimeoutError in URLError.
        deadline_hit = urllib.error.URLError(TimeoutError("HTTP request deadline exceeded"))
        http = FakeHTTP({FIRECRAWL_STATUS_URL: deadline_hit})
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )
        self.assertEqual(code, 1)
        error = self.events(stdout)[-1]
        self.assertEqual(error["error_kind"], "timeout")
        self.assertNotIn("网络错误", error["message"])

    def test_firecrawl_oauth_one_second_timeout_still_checks_status_once(self):
        key = "fc-one-second-key"
        http = FakeHTTP(firecrawl_routes(key))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "1"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.events(stdout)[-1], {
            "event": "complete", "credential": "firecrawl", "needs_search_key": False,
        })
        self.assertEqual(len(http.requests_for(FIRECRAWL_STATUS_URL)), 1)

    def test_firecrawl_oauth_timeout_emits_a_timeout_error_event(self):
        key = "fc-timeout-key"
        http = FakeHTTP(firecrawl_routes(key, statuses={"status": "pending"}))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "4"]
            )

        self.assertEqual(code, 1)
        events = self.events(stdout)
        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["error_kind"], "timeout")
        self.assertIn("超时", events[-1]["message"])
        self.assertEqual(self.events(stdout)[0]["event"], "open_url")
        self.assertFalse(self.keys_file.exists())

    def test_firecrawl_oauth_sigint_emits_a_cancelled_error_event(self):
        http = FakeHTTP({
            FIRECRAWL_STATUS_URL: KeyboardInterrupt(),
        })

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 1)
        error_event = self.events(stdout)[-1]
        self.assertEqual((error_event["event"], error_event["error_kind"]), ("error", "cancelled"))
        self.assertIn("取消", error_event["message"])
        self.assertFalse(self.keys_file.exists())

    def test_firecrawl_oauth_closed_stdin_emits_a_cancelled_error_event(self):
        # Hanging up an open stdin cancels; a stdin that was never open does not
        # (see test_oauth_with_stdin_at_eof_from_the_start_is_not_a_cancellation).
        http = FakeHTTP(firecrawl_routes("fc-never-issued"))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli_with_stdin(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"],
                HangsUpStdin(),
            )

        self.assertEqual(code, 1)
        error_event = self.events(stdout)[-1]
        self.assertEqual((error_event["event"], error_event["error_kind"]), ("error", "cancelled"))
        self.assertEqual(http.requests_for(FIRECRAWL_STATUS_URL), [])

    def test_firecrawl_oauth_opens_the_browser_by_default(self):
        key = "fc-browser-key"
        http = FakeHTTP(firecrawl_routes(key))

        with (
            mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http),
            mock.patch.object(oauth_module.webbrowser, "open") as opener,
        ):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        opener.assert_called_once_with(self.events(stdout)[0]["url"])

    def test_firecrawl_oauth_no_browser_does_not_open_the_browser(self):
        http = FakeHTTP(firecrawl_routes("fc-no-browser-key"))

        with (
            mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http),
            mock.patch.object(oauth_module.webbrowser, "open") as opener,
        ):
            code, _stdout, _stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 0)
        opener.assert_not_called()

    def test_oauth_jsonl_events_are_flushed_line_by_line(self):
        key = "fc-flush-key"
        http = FakeHTTP(firecrawl_routes(key))
        stream = RecordingStream()

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "firecrawl", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"],
                stdout=stream,
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(self.events(stdout)), 3)
        self.assertEqual(stream.flushes, 3)

    def test_oauth_text_format_prints_url_code_and_completion(self):
        routes = {
            PARALLEL_REGISTER_URL: {"client_id": "client-text"},
            PARALLEL_DEVICE_URL: {
                "device_code": "device-text",
                "user_code": "TEXT-1234",
                "verification_uri": "https://platform.parallel.ai/device",
                "verification_uri_complete": "https://platform.parallel.ai/device?user_code=TEXT-1234",
                "expires_in": 600,
                "interval": 1,
            },
            PARALLEL_TOKEN_URL: {
                "access_token": "access-text-secret",
                "refresh_token": "refresh-text-secret",
                "expires_in": 600,
            },
        }
        http = FakeHTTP(routes)

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("https://platform.parallel.ai/device?user_code=TEXT-1234", stdout)
        self.assertIn("TEXT-1234", stdout)
        self.assertIn("登录完成", stdout)
        self.assert_no_secret("access-text-secret", stdout, stderr)
        self.assert_no_secret("refresh-text-secret", stdout, stderr)


class ParallelOAuthTests(OAuthTestCase):
    def _parallel_routes(self, token_responses, *, register=None, device=None):
        return {
            PARALLEL_REGISTER_URL: register or {"client_id": "client-1"},
            PARALLEL_DEVICE_URL: device or {
                "device_code": "device-1",
                "user_code": "ABCD-1234",
                "verification_uri": "https://platform.parallel.ai/device",
                "verification_uri_complete": "https://platform.parallel.ai/device?user_code=ABCD-1234",
                "expires_in": 600,
                "interval": 1,
            },
            PARALLEL_TOKEN_URL: list(token_responses),
        }

    def test_parallel_device_login_polls_pending_and_slow_down_then_saves_tokens(self):
        access, refresh = "parallel-access-secret", "parallel-refresh-secret"
        http = FakeHTTP(self._parallel_routes([
            http_error(400, {"error": "authorization_pending"}),
            http_error(400, {"error": "slow_down"}),
            {"access_token": access, "refresh_token": refresh, "expires_in": 600, "token_type": "Bearer"},
        ]))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "60"]
            )

        self.assertEqual(code, 0, stderr)
        events = self.events(stdout)
        self.assertEqual([event["event"] for event in events], ["open_url", "waiting", "complete"])
        self.assertEqual(set(events[0]), {"event", "url", "user_code"})
        self.assertEqual(events[0]["user_code"], "ABCD-1234")
        self.assertEqual(events[0]["url"], "https://platform.parallel.ai/device?user_code=ABCD-1234")
        self.assertEqual(events[2], {
            "event": "complete", "credential": "parallel_account", "needs_search_key": True,
        })

        stored = self.read_oauth()
        self.assertEqual(stored["parallel"], {"client_id": "client-1"})
        record = stored["parallel_account"]
        self.assertEqual(record["access_token"], access)
        self.assertEqual(record["refresh_token"], refresh)
        self.assertEqual(record["scope"], "balance:read")
        self.assertGreater(datetime.fromisoformat(record["expires_at"]), datetime.now(timezone.utc))

        register = http.requests_for(PARALLEL_REGISTER_URL)
        self.assertEqual(len(register), 1)
        # Parallel answers HTTP 400 "client_name or redirect_uris is required" to an
        # empty body; the documented request names the client and its platform.
        body = json_body(register[0])
        self.assertEqual(body["client_name"], "multi-search")
        self.assertEqual(
            set(body["platform"]), {"machine", "os_name", "processor", "release", "system", "version"},
        )
        self.assertTrue(all(isinstance(value, str) for value in body["platform"].values()))
        device = form_body(http.requests_for(PARALLEL_DEVICE_URL)[0])
        self.assertEqual(device, {"client_id": "client-1", "scope": "balance:read"})
        token_requests = http.requests_for(PARALLEL_TOKEN_URL)
        self.assertEqual(len(token_requests), 3)
        self.assertEqual(form_body(token_requests[0]), {
            "grant_type": oauth_module.PARALLEL_DEVICE_GRANT,
            "device_code": "device-1",
            "client_id": "client-1",
        })
        self.assertEqual(self.clock.sleeps, [1.0, 1.0, 6.0])
        self.assertEqual(self.clock.sleeps[2], 6.0, "slow_down extends the polling interval by five seconds")
        self.assert_no_secret(access, stdout, stderr)
        self.assert_no_secret(refresh, stdout, stderr)

    def test_parallel_login_reuses_a_cached_client_id(self):
        self.write_oauth({"parallel": {"client_id": "cached-client"}})
        http = FakeHTTP(self._parallel_routes([
            {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 600},
        ]))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(http.requests_for(PARALLEL_REGISTER_URL), [])
        device = form_body(http.requests_for(PARALLEL_DEVICE_URL)[0])
        self.assertEqual(device["client_id"], "cached-client")
        self.assertEqual(self.read_oauth()["parallel"], {"client_id": "cached-client"})

    def test_parallel_login_expired_device_code_emits_an_error_event(self):
        http = FakeHTTP(self._parallel_routes([
            http_error(400, {"error": "expired_token"}),
        ]))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "60"]
            )

        self.assertEqual(code, 1)
        error_event = self.events(stdout)[-1]
        self.assertEqual(error_event["event"], "error")
        self.assertIn("过期", error_event["message"])
        self.assertNotIn("parallel_account", self.read_oauth())

    def test_parallel_login_access_denied_emits_an_error_event(self):
        http = FakeHTTP(self._parallel_routes([
            http_error(400, {"error": "access_denied"}),
        ]))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "60"]
            )

        self.assertEqual(code, 1)
        error_event = self.events(stdout)[-1]
        self.assertEqual(error_event["event"], "error")
        self.assertIn("拒绝", error_event["message"])
        self.assertNotIn("parallel_account", self.read_oauth())

    def test_oauth_json_is_owner_only_on_posix(self):
        http = FakeHTTP(self._parallel_routes([
            {"access_token": "access-mode", "refresh_token": "refresh-mode", "expires_in": 600},
        ]))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.oauth_file.stat().st_mode), 0o600)

    def test_oauth_json_login_preserves_unrelated_entries(self):
        self.write_oauth({"other": {"access_token": "keep-this"}})
        http = FakeHTTP(self._parallel_routes([
            {"access_token": "access-keep", "refresh_token": "refresh-keep", "expires_in": 600},
        ]))

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["login", "parallel", "--method", "oauth", "--format", "jsonl",
                 "--no-browser", "--timeout", "10"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.read_oauth()["other"], {"access_token": "keep-this"})

    def test_corrupt_oauth_json_is_reported_and_never_overwritten(self):
        self.oauth_file.parent.mkdir(parents=True, exist_ok=True)
        corrupt = '{"parallel_account": "EXISTING-PRIVATE-TOKEN"'
        self.oauth_file.write_text(corrupt, encoding="utf-8")

        code, stdout, stderr = self.run_cli(
            ["login", "parallel", "--method", "oauth", "--format", "jsonl", "--no-browser"]
        )

        self.assertEqual(code, 1)
        error_event = self.events(stdout)[-1]
        self.assertEqual(error_event["event"], "error")
        self.assertIn("not valid JSON", error_event["message"])
        self.assertEqual(self.oauth_file.read_text(encoding="utf-8"), corrupt)
        self.assertNotIn("EXISTING-PRIVATE-TOKEN", stdout + stderr)


class OAuthStoreTests(OAuthTestCase):
    def test_atomic_write_keeps_the_previous_file_when_replace_fails(self):
        oauth_store.set_entry("other", {"access_token": "old-token"})
        before = self.oauth_file.read_text(encoding="utf-8")

        with mock.patch.object(oauth_store.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                oauth_store.set_entry("parallel_account", {"access_token": "new-token"})

        self.assertEqual(self.oauth_file.read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.oauth_file.parent.glob(".oauth.json.*.tmp")), [])

    def test_set_and_delete_only_touch_their_own_entry(self):
        oauth_store.set_entry("other", {"access_token": "other-token"})
        oauth_store.set_client_id("parallel", "client-1")
        oauth_store.set_entry("parallel_account", {"access_token": "account-token"})

        self.assertEqual(set(self.read_oauth()), {"other", "parallel", "parallel_account"})
        self.assertTrue(oauth_store.delete_entry("parallel_account"))
        self.assertFalse(oauth_store.delete_entry("parallel_account"))
        self.assertEqual(set(self.read_oauth()), {"other", "parallel"})


class ParallelBalanceTests(OAuthTestCase):
    def _seed_account(self, *, expires_at, access="access-old", refresh="refresh-old"):
        self.write_oauth({
            "parallel": {"client_id": "client-1"},
            "parallel_account": {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires_at,
            },
        })

    def _future(self):
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def _past(self):
        return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    def _report(self, stdout):
        payload = json.loads(stdout)
        return payload["providers"][0]["reports"][0]

    def test_balance_reads_the_oauth_access_token_and_reports_usd(self):
        self._seed_account(expires_at=self._future())
        http = FakeHTTP({PARALLEL_BALANCE_URL: {
            "credit_balance_cents": 1234,
            "pending_debit_balance_cents": 0,
            "will_invoice": False,
        }})

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(["balance", "--provider", "parallel"])

        self.assertEqual(code, 0, stderr)
        report = self._report(stdout)
        self.assertEqual(
            (report["status"], report["scope"], report["unit"], report["remaining"]),
            ("ok", "account", "usd", 12.34),
        )
        request = http.requests_for(PARALLEL_BALANCE_URL)[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer access-old")
        self.assertNotIn("access-old", stdout)

    def test_expired_token_is_refreshed_and_the_rotated_refresh_token_is_saved(self):
        self._seed_account(expires_at=self._past())
        http = FakeHTTP({
            PARALLEL_TOKEN_URL: {
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 600,
            },
            PARALLEL_BALANCE_URL: {"credit_balance_cents": 500, "will_invoice": False},
        })

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(["balance", "--provider", "parallel"])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self._report(stdout)["remaining"], 5.0)
        refresh_request = form_body(http.requests_for(PARALLEL_TOKEN_URL)[0])
        self.assertEqual(refresh_request["grant_type"], "refresh_token")
        self.assertEqual(refresh_request["refresh_token"], "refresh-old")
        self.assertEqual(refresh_request["client_id"], "client-1")
        stored = self.read_oauth()["parallel_account"]
        self.assertEqual(stored["access_token"], "access-new")
        self.assertEqual(stored["refresh_token"], "refresh-new")
        balance_request = http.requests_for(PARALLEL_BALANCE_URL)[0]
        self.assertEqual(balance_request.get_header("Authorization"), "Bearer access-new")

    def test_refresh_failure_reports_needs_credential_and_keeps_the_store(self):
        self._seed_account(expires_at=self._past())
        before = self.read_oauth()
        http = FakeHTTP({
            PARALLEL_TOKEN_URL: http_error(400, {"error": "invalid_grant"}),
        })

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(["balance", "--provider", "parallel"])

        self.assertEqual(code, 0, stderr)
        report = self._report(stdout)
        self.assertEqual(report["status"], "needs_credential")
        self.assertIn("重新运行 login parallel", report["message"])
        self.assertEqual(self.read_oauth(), before)
        self.assertNotIn("refresh-old", stdout)

    def test_balance_401_is_invalid_and_never_echoes_the_access_token(self):
        self._seed_account(expires_at=self._future())
        http = FakeHTTP({PARALLEL_BALANCE_URL: http_error(
            401, {"error": "bad token access-old"}, url=PARALLEL_BALANCE_URL,
        )})

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(["balance", "--provider", "parallel"])

        self.assertEqual(code, 0, stderr)
        report = self._report(stdout)
        self.assertEqual((report["status"], report["error_kind"]), ("error", "invalid"))
        self.assert_no_secret("access-old", stdout, stderr)

    def test_will_invoice_balance_notes_postpaid_billing(self):
        self._seed_account(expires_at=self._future())
        http = FakeHTTP({PARALLEL_BALANCE_URL: {
            "credit_balance_cents": 0,
            "will_invoice": True,
        }})

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(["balance", "--provider", "parallel"])

        self.assertEqual(code, 0, stderr)
        report = self._report(stdout)
        self.assertEqual(report["status"], "ok")
        self.assertIn("后付费", report["message"])

    def test_balance_without_an_account_login_needs_a_credential(self):
        code, stdout, stderr = self.run_cli(["balance", "--provider", "parallel"])

        self.assertEqual(code, 0, stderr)
        report = self._report(stdout)
        self.assertEqual(report["status"], "needs_credential")
        self.assertIn("parallel_account", report["message"])
        self.assertIn("login parallel", report["message"])


class ParallelLogoutTests(OAuthTestCase):
    def _seed(self):
        self.write_oauth({
            "parallel": {"client_id": "client-1"},
            "parallel_account": {
                "access_token": "access-logout",
                "refresh_token": "refresh-logout",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            },
        })

    def test_logout_revokes_the_grant_and_deletes_only_the_account_entry(self):
        self._seed()
        http = FakeHTTP({PARALLEL_REVOKE_URL: {}})

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["logout", "parallel", "--credential", "parallel_account"]
            )

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual((payload["provider"], payload["credential"], payload["removed"]),
                         ("parallel", "parallel_account", True))
        self.assertEqual(self.read_oauth(), {"parallel": {"client_id": "client-1"}})
        revoke = form_body(http.requests_for(PARALLEL_REVOKE_URL)[0])
        self.assertEqual(revoke["token"], "refresh-logout")
        self.assertEqual(revoke["client_id"], "client-1")
        self.assertNotIn("refresh-logout", stdout)

    def test_logout_deletes_the_entry_even_when_revoke_fails(self):
        self._seed()
        http = FakeHTTP({PARALLEL_REVOKE_URL: http_error(500, {"error": "boom"})})

        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", http):
            code, stdout, stderr = self.run_cli(
                ["logout", "parallel", "--credential", "parallel_account"]
            )

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["removed"])
        self.assertIn("撤销令牌失败", payload["message"])
        self.assertEqual(self.read_oauth(), {"parallel": {"client_id": "client-1"}})


if __name__ == "__main__":
    unittest.main()
