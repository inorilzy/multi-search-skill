"""Independent synthetic runtime check: managed Twitter cookies bypass key rotation.

No network, no real credentials, no product file changes. Run with the repo venv.
"""
import asyncio
import builtins
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from multi_search_mcp.src.providers.xkit import ManagedTwitterCookies
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.search_runner import SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.state.key_state import SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore

SEEN = {}

class FakeTweet:
    id = "1"
    full_text = "synthetic tweet"
    reply_count = favorite_count = retweet_count = 0
    user = types.SimpleNamespace(screen_name="synthetic")

class FakeHttp:
    async def aclose(self):
        pass

class FakeClient:
    def __init__(self, *args, **kwargs):
        self.http = FakeHttp()
    def set_cookies(self, cookies):
        SEEN["cookies"] = cookies
    async def search_tweet(self, query, mode, count=10):
        SEEN["query"] = query
        return [FakeTweet()]

fake_module = types.ModuleType("xkit")
fake_module.Client = FakeClient
sys.modules["xkit"] = fake_module

cookies = {"auth_token": "synthetic-auth", "ct0": "synthetic-csrf"}
store = mock.Mock()
store.get.return_value = cookies

class NoOpen:
    def __call__(self, *args, **kwargs):
        raise AssertionError("managed mode opened a plaintext file")
    def __getattr__(self, name):
        raise AssertionError(f"managed mode touched file API {name}")

with tempfile.TemporaryDirectory() as temp:
    state = StateStore(Path(temp) / "state.sqlite")
    manager = SQLiteKeyManager(state)
    config = SearchRunnerConfig(
        route="social", counts={"twitter": 10}, timeout=10,
        serpapi_engine="google", keys={"twitter_cookies_path": ManagedTwitterCookies(), "twitter": ManagedTwitterCookies()},
    )
    with mock.patch("multi_search_mcp.src.support.credential_store.default_store", return_value=store), \
         mock.patch.object(builtins, "open", NoOpen()):
        rows = SearchRunner(config, build_provider_registry(), key_manager=manager).run("synthetic")
    assert SEEN.get("cookies") == cookies, SEEN
    assert SEEN.get("query") == "synthetic"
    assert [r.get("source") for r in rows] == ["twitter"], rows
    assert manager.status_rows() == [], f"key_state rows created: {manager.status_rows()}"
    print(json.dumps({
        "twitter_result_rows": len(rows),
        "cookies_reached_client": SEEN["cookies"],
        "key_state_rows": manager.status_rows(),
        "credential_store_reads": [c.args for c in store.get.call_args_list],
    }))

# Missing managed row: real search_twitter must fail closed into an error row, still no key_state.
store.get.return_value = None
with tempfile.TemporaryDirectory() as temp:
    state = StateStore(Path(temp) / "state.sqlite")
    manager = SQLiteKeyManager(state)
    config = SearchRunnerConfig(route="social", counts={"twitter": 10}, timeout=10,
        serpapi_engine="google", keys={"twitter_cookies_path": ManagedTwitterCookies()})
    with mock.patch("multi_search_mcp.src.support.credential_store.default_store", return_value=store):
        rows = SearchRunner(config, build_provider_registry(), key_manager=manager).run("synthetic")
    assert rows and rows[0].get("source") == "twitter" and "error" in rows[0], rows
    assert "synthetic-auth" not in str(rows), rows
    assert manager.status_rows() == []
    print(json.dumps({"missing_managed_rows": rows, "key_state_rows": manager.status_rows()}))
