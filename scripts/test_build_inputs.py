"""Tests for release build input verification and signing; synthetic inputs only, no network."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_inputs  # noqa: E402
from build_inputs import (  # noqa: E402
    BuildInputError, check_rustc, configure_embedded_path, extract_python, load_lock,
    pinned_rustc_version, verify_file,
)
from sign_windows import SigningError, sign_file  # noqa: E402

PTH = "python312.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"


def make_archive(path: Path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_for(archive: Path, sha: str) -> dict:
    return {"schema": 1, "python": {"archive": archive.name, "sha256": sha}}


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class LockedInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / "python-3.12.10-embed-amd64.zip"
        self.sha = make_archive(self.archive, {"python.exe": b"PY", "python312._pth": PTH.encode()})

    def test_repository_lock_is_valid_and_pins_an_official_archive(self):
        lock = load_lock()
        self.assertTrue(lock["python"]["archive"].endswith("-embed-amd64.zip"))
        self.assertRegex(lock["python"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(lock["python"]["url"].startswith("https://www.python.org/ftp/python/"))

    def test_locked_archive_is_extracted_and_its_path_file_points_at_site_packages(self):
        runtime = extract_python(self.archive, self.root / "runtime", lock_for(self.archive, self.sha))
        self.assertEqual((runtime / "python.exe").read_bytes(), b"PY")
        entries = (runtime / "python312._pth").read_text().split()
        self.assertEqual(entries, ["python312.zip", ".", "Lib\\site-packages"])
        self.assertTrue((runtime / "Lib" / "site-packages").is_dir())

    def test_a_tampered_or_renamed_archive_is_refused_before_extraction(self):
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("evil.py", b"backdoor")
        with self.assertRaisesRegex(BuildInputError, "SHA-256 mismatch"):
            extract_python(self.archive, self.root / "runtime", lock_for(self.archive, self.sha))
        self.assertFalse((self.root / "runtime").exists(), "nothing is extracted from an unverified archive")
        other = self.root / "python-3.13.0-embed-amd64.zip"
        other.write_bytes(self.archive.read_bytes())
        with self.assertRaisesRegex(BuildInputError, "must be"):
            extract_python(other, self.root / "r2", lock_for(self.archive, self.sha))

    def test_archive_path_traversal_and_symlinks_are_refused(self):
        for name in ("../escape.py", "/abs.py", "C:/x.py"):
            with self.subTest(name=name):
                bad = self.root / "python-3.12.10-embed-amd64.zip"
                sha = make_archive(bad, {"python.exe": b"PY", name: b"x"})
                with self.assertRaisesRegex(BuildInputError, "unsafe path"):
                    extract_python(bad, self.root / f"r-{abs(hash(name))}", lock_for(bad, sha))
        link = zipfile.ZipInfo("link")
        link.external_attr = (0o120777 << 16)
        bad = self.root / "python-3.12.10-embed-amd64.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("python.exe", b"PY")
            archive.writestr(link, "/etc/passwd")
        sha = hashlib.sha256(bad.read_bytes()).hexdigest()
        with self.assertRaisesRegex(BuildInputError, "symlink"):
            extract_python(bad, self.root / "r-link", lock_for(bad, sha))

    def test_an_existing_target_directory_is_never_reused(self):
        (self.root / "runtime").mkdir()
        with self.assertRaisesRegex(BuildInputError, "already exists"):
            extract_python(self.archive, self.root / "runtime", lock_for(self.archive, self.sha))

    def test_import_site_in_the_path_file_is_refused(self):
        runtime = self.root / "rt"
        runtime.mkdir()
        (runtime / "python312._pth").write_text("python312.zip\nimport site\n")
        with self.assertRaisesRegex(BuildInputError, "import site"):
            configure_embedded_path(runtime)

    def test_wheel_must_match_the_hash_recorded_by_the_pipeline(self):
        wheel = self.root / "multi_search_mcp-0.4.0-py3-none-any.whl"
        wheel.write_bytes(b"wheel")
        good = hashlib.sha256(b"wheel").hexdigest()
        self.assertEqual(verify_file(wheel, good, "project wheel"), good)
        wheel.write_bytes(b"swapped")
        with self.assertRaisesRegex(BuildInputError, "mismatch"):
            verify_file(wheel, good, "project wheel")
        for bad in ("", "abc", good.upper(), "g" * 64):
            with self.subTest(bad=bad), self.assertRaisesRegex(BuildInputError, "64-hex"):
                verify_file(wheel, bad, "project wheel")

    def test_malformed_lock_files_are_refused(self):
        for text in ("{", "[]", '{"schema": 2}', '{"schema": 1, "python": {"archive": "x.zip", "sha256": "nothex"}}'):
            with self.subTest(text=text):
                path = self.root / "lock.json"
                path.write_text(text)
                with self.assertRaises(BuildInputError):
                    load_lock(path)


class PinnedRustc(unittest.TestCase):
    def test_repository_pins_an_exact_rustc_and_release_uses_it(self):
        version = pinned_rustc_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        release = (Path(build_inputs.__file__).parent / "build_cli_release.py").read_text()
        self.assertIn("check_rustc()", release)

    def test_matching_rustc_passes_and_any_other_version_is_refused(self):
        ok = lambda *a, **k: Completed(0, "rustc 1.99.1 (58cf8f9c3 2026-10-13)\n")
        self.assertEqual(check_rustc("1.99.1", runner=ok), "1.99.1")
        newer = lambda *a, **k: Completed(0, "rustc 1.100.0 (abc 2026-11-01)\n")
        with self.assertRaisesRegex(BuildInputError, "does not match"):
            check_rustc("1.99.1", runner=newer)
        broken = lambda *a, **k: Completed(1, "", "error")
        with self.assertRaisesRegex(BuildInputError, "failed"):
            check_rustc("1.99.1", runner=broken)

    def test_a_floating_channel_is_not_an_acceptable_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            for channel in ("stable", "1.99", "nightly"):
                with self.subTest(channel=channel):
                    path = Path(tmp) / "rust-toolchain.toml"
                    path.write_text(f'[toolchain]\nchannel = "{channel}"\n')
                    with self.assertRaisesRegex(BuildInputError, "exact channel"):
                        pinned_rustc_version(path)


class Signing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "multi-search.exe"
        self.target.write_bytes(b"MZ")
        self.cert = base64.b64encode(b"synthetic-pfx").decode()

    def test_unconfigured_signing_is_optional_locally_but_fatal_when_required(self):
        self.assertFalse(sign_file(self.target, environ={}))
        with self.assertRaisesRegex(SigningError, "required"):
            sign_file(self.target, required=True, environ={})
        with self.assertRaisesRegex(SigningError, "required"):
            sign_file(self.target, environ={"WINDOWS_SIGN_REQUIRED": "1"})

    def test_signs_then_verifies_and_removes_the_certificate_file(self):
        calls, seen = [], {}

        def runner(command, **kwargs):
            calls.append(command)
            if command[1] == "sign":
                pfx = Path(command[command.index("/f") + 1])
                seen["pfx"] = pfx
                seen["bytes"] = pfx.read_bytes()
            return Completed(0)

        env = {"WINDOWS_SIGN_CERT_BASE64": self.cert, "WINDOWS_SIGN_CERT_PASSWORD": "synthetic-pass"}
        self.assertTrue(sign_file(self.target, environ=env, runner=runner, signtool="signtool"))
        sign, verify = calls
        self.assertEqual(sign[:2], ["signtool", "sign"])
        self.assertIn("sha256", sign)
        self.assertEqual(verify[:3], ["signtool", "verify", "/pa"])
        self.assertEqual(seen["bytes"], b"synthetic-pfx")
        self.assertFalse(seen["pfx"].exists(), "the certificate never outlives signing")
        self.assertFalse(seen["pfx"].parent.exists())

    def test_failures_never_echo_the_password_or_signtool_output(self):
        def runner(command, **kwargs):
            return Completed(1, "", "bad password synthetic-pass")

        env = {"WINDOWS_SIGN_CERT_BASE64": self.cert, "WINDOWS_SIGN_CERT_PASSWORD": "synthetic-pass"}
        with self.assertRaises(SigningError) as ctx:
            sign_file(self.target, environ=env, runner=runner, signtool="signtool")
        self.assertNotIn("synthetic-pass", str(ctx.exception))
        self.assertIn("exit 1", str(ctx.exception))

    def test_invalid_certificate_encoding_and_missing_file_are_refused(self):
        with self.assertRaisesRegex(SigningError, "base64"):
            sign_file(self.target, environ={"WINDOWS_SIGN_CERT_BASE64": "@@not base64@@"}, signtool="signtool")
        with self.assertRaisesRegex(SigningError, "missing"):
            sign_file(self.target.with_name("absent.exe"), environ={"WINDOWS_SIGN_CERT_BASE64": self.cert}, signtool="signtool")


class ReleaseWiring(unittest.TestCase):
    def test_tauri_signs_the_installer_through_the_shared_script(self):
        conf = json.loads((Path(__file__).resolve().parents[1] / "desktop/src-tauri/tauri.conf.json").read_text())
        windows = conf["bundle"]["windows"]
        self.assertEqual(windows["digestAlgorithm"], "sha256")
        command = windows["signCommand"]
        self.assertIn("%1", command["args"])
        self.assertIn("MULTI_SEARCH_SIGN_SCRIPT", " ".join(command["args"]))

    def test_release_cli_requires_a_locked_archive_and_a_wheel_hash(self):
        release = Path(__file__).resolve().parent / "build_cli_release.py"
        result = subprocess.run([sys.executable, str(release), "--python-tree", "x", "--wheel", "w",
                                 "--xkit-source", "k", "--version", "0.4.0"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, "an arbitrary --python-tree is no longer accepted")
        self.assertIn("--python-archive", result.stderr)
        self.assertIn("--wheel-sha256", result.stderr)


if __name__ == "__main__":
    unittest.main()
