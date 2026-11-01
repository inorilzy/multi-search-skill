"""Linux x86_64 release packaging tests; synthetic archives, no network access."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_cli_release as release
from build_inputs import BuildInputError, extract_python, load_lock, lock_target
from bundle_manifest import BundleError

ARCHIVE = "cpython-3.12.15+20261021-x86_64-unknown-linux-gnu-install_only.tar.gz"


class LinuxPackaging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / ARCHIVE
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data, mode in (
                ("bin/python3.12", b"ELF interpreter", 0o755),
                ("lib/libpython3.12.so.1.0", b"ELF library", 0o755),
                ("lib/python3.12/os.py", b"# stdlib", 0o644),
                ("licenses/LICENSE.cpython.txt", b"CPython license", 0o644),
                # Real PBS Linux archives have case-colliding names in this unused database.
                ("share/terminfo/2/2621A", b"terminal database", 0o644),
            ):
                info = tarfile.TarInfo("python/" + name)
                info.size, info.mode = len(data), mode
                archive.addfile(info, io.BytesIO(data))
            for name, target in (
                ("bin/python", "python3"),
                ("bin/python3", "python3.12"),
                ("lib/libpython3.12.so", "libpython3.12.so.1.0"),
            ):
                info = tarfile.TarInfo("python/" + name)
                info.type, info.linkname = tarfile.SYMTYPE, target
                archive.addfile(info)
        self.lock = load_lock()
        self.lock["targets"]["linux"]["python"]["sha256"] = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_official_pin_selects_baseline_gnu_x86_64(self):
        spec = lock_target(load_lock(), "linux")
        self.assertEqual(spec["rust_target"], "x86_64-unknown-linux-gnu")
        self.assertEqual(spec["python"]["archive"], ARCHIVE)
        self.assertEqual(spec["python"]["url"],
                         "https://github.com/astral-sh/python-build-standalone/releases/download/20261021/"
                         + ARCHIVE.replace("+", "%2B"))
        self.assertEqual(spec["python"]["sha256"],
                         "5ff9f0602ce964a529ed1e8555d3abab6341926d724402ba9a15e9e877191124")
        self.assertEqual(spec["strip_symlinks"], ["bin/python", "bin/python3"])

    def test_full_release_uses_linux_layout_platform_and_hashes_without_signing(self):
        wheel = self.root / "multi_search_mcp-0.4.0-py3-none-any.whl"
        wheel.write_bytes(b"synthetic wheel")
        resources = self.root / "resources"
        calls = []

        def compile_launcher(source, output, rust_target=None):
            calls.append(rust_target)
            output.parent.mkdir(parents=True)
            output.write_bytes(b"ELF launcher")
            output.chmod(0o755)
            return output

        def install(command, **kwargs):
            # Exercise the actual install_runtime and _uv_install argument construction.
            site = Path(command[command.index("--target") + 1])
            self.assertEqual(site.parts[-3:], ("lib", "python3.12", "site-packages"))
            self.assertEqual(command[command.index("--python-platform") + 1], "x86_64-unknown-linux-gnu")
            self.assertEqual(command[command.index("--python-version") + 1], "3.12")
            self.assertIn("--offline", command)
            self.assertIn("--no-deps", command)
            if "-r" in command:
                self.assertIn("--require-hashes", command)
            (site / "installed.py").write_bytes(b"# installed")
            # Residue must not enter the sealed bundle on Linux either.
            (site / "__pycache__").mkdir(exist_ok=True)
            (site / "__pycache__/installed.pyc").write_bytes(b"cache")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(release, "load_lock", return_value=self.lock), \
             patch.object(release, "check_rustc"), \
             patch.object(release, "compile_launcher", side_effect=compile_launcher), \
             patch.object(release.subprocess, "run", side_effect=install) as uv, \
             patch.object(release, "RESOURCES", resources), \
             patch.object(release, "sign_file") as windows_sign, \
             patch.object(release, "codesign_macos_bundle") as macos_sign:
            result = release.main([
                "--target", "linux", "--python-archive", str(self.archive),
                "--wheel", str(wheel), "--wheel-sha256", hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "--version", "0.4.0", "--work", str(self.root / "work"),
            ])
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["x86_64-unknown-linux-gnu"])
        self.assertEqual(uv.call_count, 2)
        windows_sign.assert_not_called()
        macos_sign.assert_not_called()
        bundle = resources / "cli-bundle"
        raw = (bundle / "manifest.json").read_bytes()
        self.assertEqual((resources / "cli-bundle.anchor").read_text().strip(), hashlib.sha256(raw).hexdigest())
        entries = json.loads(raw)["files"]
        paths = {entry["path"] for entry in entries}
        self.assertEqual(paths, {
            "bin/multi-search", "runtime/bin/python3.12", "runtime/lib/python3.12/os.py",
            "runtime/lib/libpython3.12.so.1.0", "runtime/lib/libpython3.12.so",
            "runtime/lib/python3.12/site-packages/installed.py", "runtime/licenses/LICENSE.cpython.txt",
        })
        for entry in entries:
            path = bundle / entry["path"]
            self.assertFalse(path.is_symlink())
            self.assertEqual(entry["size"], path.stat().st_size)
            self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        if os.name != "nt":
            for rel in ("bin/multi-search", "runtime/bin/python3.12"):
                self.assertEqual((bundle / rel).stat().st_mode & 0o777, 0o755)
        self.assertEqual((bundle / "runtime/lib/libpython3.12.so").read_bytes(), b"ELF library")

    def test_linux_archive_verification_rejects_tampering_and_other_targets(self):
        with self.assertRaisesRegex(BuildInputError, "must be"):
            extract_python(self.archive, self.root / "wrong", self.lock, target="macos")
        self.assertFalse((self.root / "wrong").exists())
        with self.archive.open("ab") as output:
            output.write(b"tampered")
        with self.assertRaisesRegex(BuildInputError, "SHA-256 mismatch"):
            extract_python(self.archive, self.root / "tampered", self.lock, target="linux")
        self.assertFalse((self.root / "tampered").exists())

    def test_unknown_install_target_is_rejected_before_creating_site_packages(self):
        requirements, wheel = self.root / "req.txt", self.root / "w.whl"
        requirements.touch()
        wheel.touch()
        with self.assertRaisesRegex(BundleError, "unknown bundle target"):
            release.install_runtime(self.root / "runtime", requirements, wheel, None, target="plan9")
        self.assertFalse((self.root / "runtime").exists())


if __name__ == "__main__":
    unittest.main()
