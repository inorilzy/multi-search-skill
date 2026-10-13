"""Twitter cookie file reference: a non-secret path in config, with explicit priority.

Priority for the cookie file path: TWITTER_COOKIES_PATH env > config
``twitter_cookies_path`` > keys file ``twitter`` / ``twitter_cookies``.
Cookie bodies are never read into config and never echoed.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state.keys import load_keys
from multi_search_mcp.src.support.config import ConfigError, config_str, load_config


SYNTHETIC_AUTH = "synthetic-auth-token-0041"
SYNTHETIC_CT0 = "synthetic-ct0-value-0042"


class TwitterCookieReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.keys_file = root / "keys.json"
        self.config_file = root / "config.json"
        self.env_cookie = root / "env-cookies.json"
        self.config_cookie = root / "config-cookies.json"
        self.file_cookie = root / "file-cookies.json"
        for path in (self.env_cookie, self.config_cookie, self.file_cookie):
            path.write_text(json.dumps({"auth_token": SYNTHETIC_AUTH, "ct0": SYNTHETIC_CT0}), encoding="utf-8")

    def write_keys(self, data):
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def write_config(self, data):
        self.config_file.write_text(json.dumps(data), encoding="utf-8")

    def test_env_path_beats_config_and_file(self):
        self.write_keys({"twitter": str(self.file_cookie)})
        self.write_config({"twitter_cookies_path": str(self.config_cookie)})
        keys = load_keys(self.keys_file, environ={"TWITTER_COOKIES_PATH": str(self.env_cookie)})
        self.assertEqual(keys["twitter"], str(self.env_cookie))

    def test_config_path_beats_file_when_env_absent(self):
        self.write_keys({"twitter": str(self.file_cookie)})
        keys = load_keys(self.keys_file, environ={}, twitter_cookies_path=str(self.config_cookie))
        self.assertEqual(keys["twitter"], str(self.config_cookie))

    def test_file_used_when_neither_env_nor_config_set(self):
        self.write_keys({"twitter": str(self.file_cookie)})
        keys = load_keys(self.keys_file, environ={}, twitter_cookies_path=None)
        self.assertEqual(keys["twitter"], str(self.file_cookie))

    def test_config_value_is_a_path_only_and_cookie_body_is_not_read(self):
        config = {"twitter_cookies_path": str(self.config_cookie)}
        self.write_config(config)
        loaded = load_config(str(self.config_file))
        serialized = json.dumps(loaded)
        self.assertEqual(loaded["twitter_cookies_path"], str(self.config_cookie))
        self.assertNotIn(SYNTHETIC_AUTH, serialized)
        self.assertNotIn(SYNTHETIC_CT0, serialized)

    def test_config_rejects_non_string_cookie_path(self):
        self.write_config({"twitter_cookies_path": {"auth_token": SYNTHETIC_AUTH}})
        loaded = load_config(str(self.config_file))
        with self.assertRaises(ConfigError) as ctx:
            config_str(loaded, "twitter_cookies_path")
        self.assertNotIn(SYNTHETIC_AUTH, str(ctx.exception))


class TwitterConfigPathReachesSearchTests(unittest.TestCase):
    """Config-only cookie path must reach search_twitter through run_search_web.

    Keys file and environ are isolated to temp paths and the Windows store is
    not consulted, so the real user keys/config are never read.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.keys_file = root / "keys.json"
        self.keys_file.write_text(json.dumps({"twitter": str(root / "file-cookies.json")}), encoding="utf-8")
        self.config_cookie = str(root / "config-cookies.json")
        self.env_cookie = str(root / "env-cookies.json")
        self.environ = {}
        self.received = []

        from multi_search_mcp.src.state import keys as keys_module

        real_load_keys = keys_module.load_keys

        def isolated_load_keys(keys_file=None, environ=None, credential_store=None, *, twitter_cookies_path=None):
            return real_load_keys(
                self.keys_file, environ=self.environ, credential_store=None,
                twitter_cookies_path=twitter_cookies_path,
            )

        def fake_search_twitter(query, count=10, cookies="", timeout=None, *, publish_partial=None, deadline=None):
            self.received.append(cookies)
            return []

        for target, replacement in (
            ("multi_search_mcp.src.service.load_keys", isolated_load_keys),
            ("multi_search_mcp.src.search.registry.search_twitter", fake_search_twitter),
        ):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_twitter(self, config):
        from multi_search_mcp.src.service import run_search_web

        run_search_web(
            {"query": "fixture", "sources": ["twitter"], "use_state": False},
            config=config,
        )

    def test_config_path_alone_reaches_search_twitter(self):
        self.run_twitter({"twitter_cookies_path": self.config_cookie})
        self.assertEqual(self.received, [self.config_cookie])

    def test_env_path_wins_over_config_path(self):
        self.environ = {"TWITTER_COOKIES_PATH": self.env_cookie}
        self.run_twitter({"twitter_cookies_path": self.config_cookie})
        self.assertEqual(self.received, [self.env_cookie])

    def test_keys_file_path_used_when_config_absent(self):
        self.run_twitter({})
        self.assertEqual(self.received, [str(Path(self.tmp.name) / "file-cookies.json")])


if __name__ == "__main__":
    unittest.main()
