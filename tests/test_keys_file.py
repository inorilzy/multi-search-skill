"""The unified keys file ``~/.multi-search/keys.json`` and its one-time legacy copy.

Every reader and writer resolves the path through ``default_keys_file``; the
old ``~/.search-keys.json`` is copied once when the new file is missing and is
never modified. Resolution is environment > keys file.
"""
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.search import rerank
from multi_search_mcp.src.state import runtime
from multi_search_mcp.src.state.keys import (
    CREDENTIAL_STORE_PROVIDERS,
    KeysError,
    default_keys_file,
    key_sources,
    load_keys,
)
from multi_search_mcp.src.state.mark_exhausted import _mark_config_exhausted
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import config

SYNTHETIC_FILE_KEY = "synthetic-file-key-0301"
SYNTHETIC_ENV_KEY = "synthetic-env-key-0302"
SYNTHETIC_LEGACY_KEY = "synthetic-legacy-key-0303"


class HomeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keys-file-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.keys_file = self.home / ".multi-search" / "keys.json"
        self.legacy = self.home / ".search-keys.json"
        patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_keys(self, data):
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        self.keys_file.write_text(json.dumps(data), encoding="utf-8")

    def write_legacy(self, data) -> bytes:
        self.legacy.write_text(json.dumps(data), encoding="utf-8")
        return self.legacy.read_bytes()


class DefaultPathTests(HomeFixture):
    def test_default_path_is_under_dot_multi_search(self):
        self.assertEqual(default_keys_file(), self.home / ".multi-search" / "keys.json")
        self.assertFalse(self.keys_file.exists(), "no file is created without a legacy source")

    def test_keys_load_from_the_new_path(self):
        self.write_keys({"tavily": SYNTHETIC_FILE_KEY, "exa": ["e1", "e2"]})
        keys = load_keys(environ={})
        self.assertEqual(keys["tavily"], SYNTHETIC_FILE_KEY)
        self.assertEqual(keys["exa"], ["e1", "e2"])

    def test_legacy_file_is_ignored_once_the_new_file_exists(self):
        self.write_keys({"tavily": SYNTHETIC_FILE_KEY})
        self.write_legacy({"tavily": SYNTHETIC_LEGACY_KEY, "brave": "legacy-brave"})
        keys = load_keys(environ={})
        self.assertEqual(keys["tavily"], SYNTHETIC_FILE_KEY)
        self.assertNotIn("brave", keys)

    def test_env_overrides_the_file(self):
        self.write_keys({"tavily": SYNTHETIC_FILE_KEY, "brave": "file-brave"})
        keys = load_keys(environ={"TAVILY_API_KEY": SYNTHETIC_ENV_KEY})
        self.assertEqual(keys["tavily"], SYNTHETIC_ENV_KEY)
        self.assertEqual(keys["brave"], "file-brave")

    def test_corrupt_new_file_is_a_hard_error_and_is_not_overwritten(self):
        self.keys_file.parent.mkdir(parents=True)
        corrupt = '{"brave": "SUPERSECRET-0304"'
        self.keys_file.write_text(corrupt, encoding="utf-8")
        self.write_legacy({"brave": SYNTHETIC_LEGACY_KEY})
        with self.assertRaises(KeysError) as raised:
            load_keys(environ={})
        self.assertIn(str(self.keys_file), str(raised.exception))
        self.assertNotIn("SUPERSECRET-0304", str(raised.exception))
        with self.assertRaises(KeysError):
            key_sources(environ={})
        with self.assertRaises(KeysError):
            _mark_config_exhausted("j1")
        self.assertEqual(self.keys_file.read_text(encoding="utf-8"), corrupt)


class LegacyCopyTests(HomeFixture):
    def test_copy_happens_once_and_leaves_the_old_file_untouched(self):
        legacy_bytes = self.write_legacy({"tavily": SYNTHETIC_LEGACY_KEY, "unknown": {"x": 1}})
        keys = load_keys(environ={})
        self.assertEqual(keys["tavily"], SYNTHETIC_LEGACY_KEY)
        self.assertEqual(self.keys_file.read_bytes(), legacy_bytes)
        self.assertEqual(self.legacy.read_bytes(), legacy_bytes)
        self.assertEqual(sorted(p.name for p in self.keys_file.parent.iterdir()), ["keys.json"])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_copy_is_owner_only_even_from_a_world_readable_source(self):
        self.write_legacy({"tavily": SYNTHETIC_LEGACY_KEY})
        os.chmod(self.legacy, 0o644)
        default_keys_file()
        self.assertEqual(stat.S_IMODE(self.keys_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.legacy.stat().st_mode), 0o644)

    def test_copy_does_not_run_again_when_the_new_file_exists(self):
        self.write_legacy({"tavily": SYNTHETIC_LEGACY_KEY})
        default_keys_file()
        # The user edits the new file; a later legacy change must not leak back in.
        self.write_keys({"tavily": SYNTHETIC_FILE_KEY})
        self.write_legacy({"tavily": "legacy-changed"})
        self.assertEqual(load_keys(environ={})["tavily"], SYNTHETIC_FILE_KEY)
        self.assertEqual(json.loads(self.keys_file.read_text(encoding="utf-8")),
                         {"tavily": SYNTHETIC_FILE_KEY})

    def test_corrupt_legacy_file_is_copied_as_is_and_then_reported(self):
        self.legacy.write_text("{not json", encoding="utf-8")
        with self.assertRaises(KeysError) as raised:
            load_keys(environ={})
        self.assertIn(str(self.keys_file), str(raised.exception))
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), "{not json")

    def test_copy_failure_is_reported_without_touching_the_old_file(self):
        legacy_bytes = self.write_legacy({"tavily": SYNTHETIC_LEGACY_KEY})
        with mock.patch("multi_search_mcp.src.state.keys.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(KeysError):
                default_keys_file()
        self.assertFalse(self.keys_file.exists())
        self.assertEqual(sorted(p.name for p in self.keys_file.parent.iterdir()), [])
        self.assertEqual(self.legacy.read_bytes(), legacy_bytes)

    def test_a_file_that_appears_concurrently_wins_over_the_copy(self):
        self.write_legacy({"tavily": SYNTHETIC_LEGACY_KEY})
        real_link = os.link

        def racing_link(source, target):
            Path(target).write_text(json.dumps({"tavily": SYNTHETIC_FILE_KEY}), encoding="utf-8")
            return real_link(source, target)

        with mock.patch("multi_search_mcp.src.state.keys.os.link", side_effect=racing_link):
            default_keys_file()
        self.assertEqual(json.loads(self.keys_file.read_text(encoding="utf-8")),
                         {"tavily": SYNTHETIC_FILE_KEY})


class WriterTests(HomeFixture):
    def test_mark_exhausted_preserves_other_entries_and_unknown_keys(self):
        original = {
            "jina": [{"key": "j1"}, {"key": "j2", "note": "keep"}],
            "tavily": SYNTHETIC_FILE_KEY,
            "systemone": "synthetic-systemone-0305",
            "custom_unknown": {"nested": [1, 2]},
        }
        self.write_keys(original)
        self.assertTrue(_mark_config_exhausted("j2"))
        saved = json.loads(self.keys_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["jina"], [{"key": "j1"}, {"key": "j2", "note": "keep", "exhausted": True}])
        for name in ("tavily", "systemone", "custom_unknown"):
            self.assertEqual(saved[name], original[name], name)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.keys_file.stat().st_mode), 0o600)

    def test_mark_exhausted_works_on_a_freshly_copied_legacy_file(self):
        legacy_bytes = self.write_legacy({"jina": ["j1"], "brave": "legacy-brave"})
        self.assertTrue(_mark_config_exhausted("j1"))
        saved = json.loads(self.keys_file.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"jina": [{"key": "j1", "exhausted": True}], "brave": "legacy-brave"})
        self.assertEqual(self.legacy.read_bytes(), legacy_bytes)

    def test_systemone_key_is_read_from_the_new_path_with_env_override(self):
        self.write_keys({"systemone": " synthetic-systemone-0306 "})
        self.assertEqual(rerank.load_systemone_key(environ={}), "synthetic-systemone-0306")
        self.assertEqual(
            rerank.load_systemone_key(environ={"SYSTEMONE_API_KEY": "env-systemone"}),
            "env-systemone",
        )

    def test_systemone_key_is_empty_when_the_file_is_corrupt(self):
        self.keys_file.parent.mkdir(parents=True)
        self.keys_file.write_text("{oops", encoding="utf-8")
        self.assertEqual(rerank.load_systemone_key(environ={}), "")


class DoctorKeySourcesTests(HomeFixture):
    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch("multi_search_mcp.src.diagnostics.StateStore",
                       return_value=StateStore(self.home / "state.sqlite")),
            mock.patch.object(config, "USER_CONFIG_PATH", self.home / "missing-user.json"),
            mock.patch.object(config, "IS_SOURCE_CHECKOUT", False),
            mock.patch.dict(os.environ, {
                config.CONFIG_ENV_VAR: "",
                config.CONFIG_DB_ENV: str(self.home / "missing.sqlite"),
                **{name: "" for name in ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "BRAVE_API_KEY",
                                         "EXA_API_KEY", "JINA_API_KEY", "JINA_KEY")},
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def doctor(self, *extra, expected_code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["doctor", "--format", "json", *extra], stdout=stdout, stderr=stderr)
        self.assertEqual(code, expected_code, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def test_key_sources_rows_have_exactly_the_contract_fields(self):
        self.write_keys({"brave": SYNTHETIC_FILE_KEY, "exa": ["e1", "", "e2"], "tavily": "file-tavily"})
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": SYNTHETIC_ENV_KEY}):
            payload = self.doctor()
        sources = payload["key_sources"]
        self.assertEqual(set(sources), set(CREDENTIAL_STORE_PROVIDERS))
        fields = {"effective_source", "env_vars_set", "file_present", "file_key_count"}
        for provider, row in sources.items():
            with self.subTest(provider=provider):
                self.assertEqual(set(row), fields)
        self.assertEqual(sources["tavily"], {"effective_source": "env", "env_vars_set": ["TAVILY_API_KEY"],
                                             "file_present": True, "file_key_count": 1})
        self.assertEqual(sources["brave"], {"effective_source": "file", "env_vars_set": [],
                                            "file_present": True, "file_key_count": 1})
        self.assertEqual(sources["exa"]["file_key_count"], 2)
        self.assertEqual(sources["jina"], {"effective_source": "none", "env_vars_set": [],
                                           "file_present": False, "file_key_count": 0})
        text = json.dumps(payload)
        for secret in (SYNTHETIC_FILE_KEY, SYNTHETIC_ENV_KEY, "file-tavily"):
            self.assertNotIn(secret, text)

    def test_no_keys_block_shows_the_new_file_and_no_store_fields(self):
        payload = self.doctor("--no-keys")
        block = payload["key_sources"]
        self.assertEqual(block["file"], "~/.multi-search/keys.json")
        for removed in ("storage", "database", "legacy_sources"):
            self.assertNotIn(removed, block)

    def test_doctor_reports_a_corrupt_keys_file_instead_of_crashing(self):
        self.keys_file.parent.mkdir(parents=True)
        self.keys_file.write_text("{oops", encoding="utf-8")
        payload = self.doctor(expected_code=1)
        self.assertIn(str(self.keys_file), payload["keys_error"])
        self.assertIn("key_sources_error", payload)
        self.assertEqual(self.keys_file.read_text(encoding="utf-8"), "{oops")


class LegacyTwitterModeTests(HomeFixture):
    def test_managed_mode_in_settings_is_ignored(self):
        self.write_keys({"twitter": str(self.home / "file-cookies.json")})
        with mock.patch.dict(os.environ, {"TWITTER_COOKIES_PATH": ""}):
            keys = runtime.load_runtime_keys({"twitter_cookies_mode": "managed"})
            self.assertEqual(keys["twitter"], str(self.home / "file-cookies.json"))
            configured = runtime.load_runtime_keys({
                "twitter_cookies_mode": "managed",
                "twitter_cookies_path": str(self.home / "configured.json"),
            })
        self.assertEqual(configured["twitter"], str(self.home / "configured.json"))
        self.assertNotIn("twitter_cookies", keys)


if __name__ == "__main__":
    unittest.main()
