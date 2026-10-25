"""Tests for scripts/verify_macos_app.py: the shipped-bundle gate.

These build a synthetic .app tree with the same layout the Tauri build produces, so each
check is proven to fail for the defect it names and pass on a clean tree.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_macos_app as app_check  # noqa: E402


def make_app(root: Path, version: str = "0.4.0", *, executable: bool = True) -> Path:
    app = root / "Multi Search.app"
    bundle = app / "Contents" / "Resources" / "cli-bundle"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "runtime" / "bin").mkdir(parents=True)
    # A launcher that prints a version and writes nothing, like the real one.
    launcher = bundle / "bin" / "multi-search"
    launcher.write_text(f"#!/bin/sh\necho 'multi-search {version}'\n", encoding="utf-8")
    interpreter = bundle / "runtime" / "bin" / "python3.12"
    interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for path in (launcher, interpreter):
        path.chmod(0o755 if executable else 0o644)
    data = bundle / "runtime" / "lib" / "stdlib.txt"
    data.parent.mkdir(parents=True)
    data.write_text("stdlib\n", encoding="utf-8")
    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            files.append({
                "path": path.relative_to(bundle).as_posix(),
                "size": path.stat().st_size,
                "sha256": app_check.sha256_file(path),
            })
    (bundle / "manifest.json").write_text(
        json.dumps({"schema": 1, "version": version, "files": files}), encoding="utf-8"
    )
    return app


class ShippedBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_clean_tree_passes_and_reports_the_printed_version(self):
        app = make_app(self.root)
        with mock.patch.object(app_check, "verify_signature", return_value=None):
            report = app_check.verify(app, expected_version="0.4.0")
        self.assertGreater(report["files"], 0)
        self.assertEqual(report["printed"], "multi-search 0.4.0")
        self.assertEqual(report["version"], "0.4.0")

    def test_modified_bundled_file_is_refused(self):
        app = make_app(self.root)
        (app / "Contents/Resources/cli-bundle/runtime/lib/stdlib.txt").write_text(
            "stdlib\n".replace("stdlib", "TAMPER"), encoding="utf-8"
        )
        with self.assertRaisesRegex(app_check.AppVerificationError, "SHA-256 differs"):
            app_check.verify_manifest(app_check.bundle_dir(app))

    def test_bytecode_left_in_the_tree_is_refused(self):
        app = make_app(self.root)
        cache = app / "Contents/Resources/cli-bundle/runtime/lib/__pycache__"
        cache.mkdir()
        (cache / "os.cpython-312.pyc").write_bytes(b"\0")
        with self.assertRaisesRegex(app_check.AppVerificationError, "carries bytecode"):
            app_check.verify_layout(app_check.bundle_dir(app))

    def test_missing_execute_bit_is_refused_before_install(self):
        app = make_app(self.root, executable=False)
        with self.assertRaisesRegex(app_check.AppVerificationError, "not executable"):
            app_check.verify_layout(app_check.bundle_dir(app))

    def test_symlink_in_the_shipped_tree_is_refused(self):
        app = make_app(self.root)
        bundle = app / "Contents/Resources/cli-bundle"
        (bundle / "runtime/lib/link.txt").symlink_to("stdlib.txt")
        with self.assertRaisesRegex(app_check.AppVerificationError, "symlink"):
            app_check.verify_manifest(app_check.bundle_dir(app))

    def test_unlisted_file_in_the_shipped_tree_is_refused(self):
        app = make_app(self.root)
        (app / "Contents/Resources/cli-bundle/runtime/lib/extra.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(app_check.AppVerificationError, "outside the manifest"):
            app_check.verify_manifest(app_check.bundle_dir(app))

    def test_a_launcher_that_rewrites_the_bundle_is_caught(self):
        app = make_app(self.root)
        launcher = app / "Contents/Resources/cli-bundle/bin/multi-search"
        # Mimic Python writing bytecode next to a module it just imported.
        launcher.write_text(
            "#!/bin/sh\n"
            "mkdir -p \"$(dirname \"$0\")/../runtime/lib/__pycache__\"\n"
            "echo x > \"$(dirname \"$0\")/../runtime/lib/__pycache__/os.pyc\"\n"
            "echo 'multi-search 0.4.0'\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        # Re-seal the manifest so only the runtime-write check can catch this.
        bundle = app / "Contents/Resources/cli-bundle"
        files = []
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                files.append({
                    "path": path.relative_to(bundle).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": app_check.sha256_file(path),
                })
        (bundle / "manifest.json").write_text(
            json.dumps({"schema": 1, "version": "0.4.0", "files": files}), encoding="utf-8"
        )
        with self.assertRaisesRegex(app_check.AppVerificationError, "modified the app bundle"):
            app_check.verify_runs_immutably(app_check.bundle_dir(app), "0.4.0")

    def test_wrong_expected_version_is_refused(self):
        app = make_app(self.root, version="0.3.0")
        with self.assertRaisesRegex(app_check.AppVerificationError, "expected version"):
            app_check.verify_runs_immutably(app_check.bundle_dir(app), "0.4.0")

    def test_missing_bundle_is_refused(self):
        app = self.root / "Empty.app"
        (app / "Contents").mkdir(parents=True)
        with self.assertRaisesRegex(app_check.AppVerificationError, "lacks manifest.json"):
            app_check.verify_manifest(app_check.bundle_dir(app))

    def test_signature_failure_is_reported_for_a_local_build(self):
        app = make_app(self.root)
        with mock.patch.object(
            app_check.subprocess, "run",
            return_value=subprocess.CompletedProcess(["codesign"], 1, "", "invalid signature"),
        ):
            with self.assertRaisesRegex(app_check.AppVerificationError, "signature does not verify"):
                app_check.verify_signature(app)

    def test_ad_hoc_sign_never_uses_deep(self):
        """--deep would re-sign nested Mach-O files after the manifest was hashed."""
        app = make_app(self.root)
        with mock.patch.object(app_check.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["codesign"], 0, "", "")
            app_check.ad_hoc_sign(app)
        command = run.call_args[0][0]
        self.assertIn("--sign", command)
        self.assertNotIn("--deep", command)


if __name__ == "__main__":
    unittest.main()
