"""Exercise the CI entrypoints without spawning a native Rust build."""
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from scripts import check_glossary_paths, rust_ci_matrix


class RustMatrixEntrypointTests(unittest.TestCase):
    def test_all_native_feature_sets_run_locked_offline_under_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "desktop" / "src-tauri"
            native.mkdir(parents=True)
            (native / "tauri.check.conf.json").write_text('{"bundle":{"active":false}}', encoding="utf-8")
            isolation = mock.Mock(spec=["paths", "assert_clean"])
            isolation.paths.state = root / "state.sqlite"
            active = [False]
            calls = []

            @contextmanager
            def isolated(**kwargs):
                self.assertEqual(kwargs, {"source_root": root})
                active[0] = True
                yield isolation
                active[0] = False

            def run(command, **kwargs):
                self.assertTrue(kwargs["check"])
                calls.append(command)
                if command[0] == "rustc":
                    self.assertFalse(active[0])
                    return
                self.assertTrue(active[0])
                self.assertEqual(os.environ["MULTI_SEARCH_STATE_DB"], str(isolation.paths.state))
                self.assertIn("--locked", command)
                self.assertIn("--offline", command)
                self.assertEqual(command[-2:], ["--manifest-path", str(native / "Cargo.toml")])
                if "--no-default-features" in command:
                    self.assertNotIn("TAURI_CONFIG", os.environ)
                else:
                    self.assertEqual(json.loads(os.environ["TAURI_CONFIG"]), {"bundle": {"active": False}})

            with mock.patch.object(rust_ci_matrix, "ROOT", root), mock.patch.object(
                rust_ci_matrix, "isolated_test_environment", side_effect=isolated,
            ), mock.patch.object(rust_ci_matrix.subprocess, "run", side_effect=run), mock.patch.dict(os.environ):
                self.assertEqual(rust_ci_matrix.main(), 0)
            isolation.assert_clean.assert_called_once_with()
            self.assertEqual(calls[0], ["rustc", "--version"])
            self.assertEqual([command[1:command.index("--locked")] for command in calls[1:]], [
                ["test", "--no-default-features"],
                ["test", "--no-default-features", "--features", "test-fixtures,ts"],
                ["test", "--no-default-features", "--features", "install-test-boundary"],
                ["check", "--all-targets", "--features", "test-fixtures,ts"],
                ["test", "--features", "install-test-boundary,ts"],
            ])


class GlossaryCheckerTests(unittest.TestCase):
    def test_existing_code_paths_and_local_links_pass_but_missing_ones_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "sample.py").write_text("", encoding="utf-8")
            glossary = root / "docs" / "glossary.md"
            glossary.write_text("| 术语 | 代码出处 |\n| **样例** | `sample.py` |\n", encoding="utf-8")
            (root / "README.md").write_text("[glossary](docs/glossary.md)", encoding="utf-8")
            (root / "docs" / "README.md").write_text("[root](../README.md)", encoding="utf-8")
            self.assertEqual(check_glossary_paths.check(root), [])
            glossary.write_text("| 术语 | 代码出处 |\n| **样例** | `missing.py` |\n", encoding="utf-8")
            (root / "README.md").write_text("[missing](docs/missing.md)", encoding="utf-8")
            self.assertEqual(check_glossary_paths.check(root), [
                "docs/glossary.md:2: missing missing.py", "README.md: missing link docs/missing.md",
            ])


if __name__ == "__main__":
    unittest.main()
