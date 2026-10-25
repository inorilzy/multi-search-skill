"""Tests for macOS (aarch64-apple-darwin) release packaging: safe tar extraction,
symlink materialisation, per-target bundle layout and ad-hoc codesign ordering."""
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cli_bundle import build  # noqa: E402
from build_cli_release import (  # noqa: E402
    LAUNCHER_SRC, _is_macho, codesign_macos_bundle, compile_launcher, install_runtime,
)
from build_inputs import BuildInputError, extract_python, load_lock, lock_target  # noqa: E402
from bundle_manifest import BundleError  # noqa: E402

MACOS_ARCHIVE = "cpython-3.12.15+20261021-aarch64-apple-darwin-install_only.tar.gz"


def macos_lock(archive: Path, sha: str) -> dict:
    return {"schema": 1, "targets": {"macos": {
        "python": {"archive": archive.name, "sha256": sha,
                   "url": "https://example.invalid/archive.tar.gz"},
        "rust_target": "aarch64-apple-darwin"}}}


def tar_member(name: str, data: bytes = b"", mode: int = 0o644,
               type: bytes = tarfile.REGTYPE, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.type = type
    info.linkname = linkname
    return info


def make_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> str:
    with tarfile.open(path, "w:gz") as archive:
        for info, data in members:
            archive.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_runtime_tar(path: Path, extra: list[tuple[tarfile.TarInfo, bytes]] | None = None) -> str:
    members = [
        (tar_member("python", type=tarfile.DIRTYPE, mode=0o755), b""),
        (tar_member("python/bin", type=tarfile.DIRTYPE, mode=0o755), b""),
        (tar_member("python/bin/python3.12", b"#!/fake\n", mode=0o755), b"#!/fake\n"),
        (tar_member("python/lib", type=tarfile.DIRTYPE, mode=0o755), b""),
        (tar_member("python/lib/libpython3.12.dylib", b"DYLIB", mode=0o755), b"DYLIB"),
        (tar_member("python/lib/python3.12", type=tarfile.DIRTYPE, mode=0o755), b""),
        (tar_member("python/lib/python3.12/os.py", b"# os"), b"# os"),
        (tar_member("python/PYTHON.json", b"{}"), b"{}"),
        (tar_member("python/licenses", type=tarfile.DIRTYPE, mode=0o755), b""),
        (tar_member("python/licenses/NOTICE.txt", b"CPython licence"), b"CPython licence"),
    ]
    if extra:
        members.extend(extra)
    return make_tar(path, members)


class TarExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / MACOS_ARCHIVE
        self.sha = make_runtime_tar(self.archive)
        self.lock = macos_lock(self.archive, self.sha)

    def test_install_only_tree_extracts_with_modes_and_notices(self):
        runtime = extract_python(self.archive, self.root / "rt", self.lock, target="macos")
        python = runtime / "bin" / "python3.12"
        self.assertTrue(python.is_file())
        self.assertTrue(os.access(python, os.X_OK), "interpreter keeps its executable mode")
        self.assertTrue((runtime / "lib" / "libpython3.12.dylib").is_file())
        self.assertTrue((runtime / "licenses" / "NOTICE.txt").is_file(),
                        "redistribution notices stay in the runtime")

    def test_internal_symlink_is_materialised_as_a_regular_file(self):
        extra = [(tar_member("python/bin/python3", type=tarfile.SYMTYPE,
                             linkname="python3.12"), b"")]
        self.sha = make_runtime_tar(self.archive, extra)
        runtime = extract_python(self.archive, self.root / "rt",
                                 macos_lock(self.archive, self.sha), target="macos")
        link = runtime / "bin" / "python3"
        self.assertFalse(link.is_symlink(), "archive links never become filesystem links")
        self.assertEqual(link.read_bytes(), b"#!/fake\n")
        self.assertTrue(os.access(link, os.X_OK))

    def test_target_configured_alias_links_are_not_materialised(self):
        """`bin/python`/`bin/python3` are convenience aliases: copying them triples an 18MB binary."""
        extra = [
            (tar_member("python/bin/python3", type=tarfile.SYMTYPE,
                        linkname="python3.12"), b""),
            (tar_member("python/bin/python", type=tarfile.SYMTYPE,
                        linkname="python3"), b""),
        ]
        self.sha = make_runtime_tar(self.archive, extra)
        lock = macos_lock(self.archive, self.sha)
        lock["targets"]["macos"]["strip_symlinks"] = ["bin/python", "bin/python3"]
        runtime = extract_python(self.archive, self.root / "rt", lock, target="macos")
        interpreter = runtime / "bin" / "python3.12"
        self.assertTrue(interpreter.is_file(), "the interpreter the launcher executes must stay")
        self.assertTrue((runtime / "lib" / "libpython3.12.dylib").is_file())
        for dropped in ("python", "python3"):
            with self.subTest(dropped=dropped):
                self.assertFalse((runtime / "bin" / dropped).exists(),
                                 f"bin/{dropped} must be dropped by the target policy")
        self.assertEqual(sorted(p.name for p in (runtime / "bin").iterdir()), ["python3.12"])

    def test_both_targets_declare_their_alias_policy_in_the_repository_lock(self):
        lock = load_lock()
        self.assertEqual(lock_target(lock, "macos").get("strip_symlinks"),
                         ["bin/python", "bin/python3"])
        self.assertEqual(lock_target(lock, "windows").get("strip_symlinks"), [],
                         "Windows must keep extracting every archive member as before")

    def test_libpython_style_symlink_chain_resolves_inside_the_archive(self):
        extra = [
            (tar_member("python/lib/libpython.dylib", type=tarfile.SYMTYPE,
                        linkname="libpython3.dylib"), b""),
            (tar_member("python/lib/libpython3.dylib", type=tarfile.SYMTYPE,
                        linkname="libpython3.12.dylib"), b""),
        ]
        self.sha = make_runtime_tar(self.archive, extra)
        runtime = extract_python(self.archive, self.root / "rt",
                                 macos_lock(self.archive, self.sha), target="macos")
        link = runtime / "lib" / "libpython.dylib"
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_bytes(), b"DYLIB")

    def test_escaping_devices_and_external_links_are_refused_before_writing(self):
        cases = {
            "absolute link": [(tar_member("python/x", type=tarfile.SYMTYPE,
                                          linkname="/etc/passwd"), b"")],
            "relative escape": [(tar_member("python/lib/evil", type=tarfile.SYMTYPE,
                                           linkname="../../../../etc/passwd"), b"")],
            "hard link": [(tar_member("python/x", type=tarfile.LNKTYPE,
                                      linkname="python/bin/python3.12"), b"")],
            "device node": [(tar_member("python/dev/null", type=tarfile.CHRTYPE), b"")],
            "fifo": [(tar_member("python/fifo", type=tarfile.FIFOTYPE), b"")],
            "link to absent member": [(tar_member("python/x", type=tarfile.SYMTYPE,
                                                  linkname="not-there"), b"")],
            "link to a directory": [(tar_member("python/x", type=tarfile.SYMTYPE,
                                                linkname="lib"), b"")],
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                sha = make_runtime_tar(self.archive, extra)
                dest = self.root / "rt"
                with self.assertRaises(BuildInputError):
                    extract_python(self.archive, dest, macos_lock(self.archive, sha), target="macos")
                self.assertFalse((dest / "python" / "x").exists())
                shutil_rmtree(dest)

    def test_path_traversal_members_are_refused(self):
        for name in ("../escape.py", "python/../../escape.py", "/abs.py", "python/a\\b"):
            with self.subTest(name=name):
                sha = make_runtime_tar(self.archive,
                                       [(tar_member(name, b"x"), b"x")])
                with self.assertRaises(BuildInputError):
                    extract_python(self.archive, self.root / "rt",
                                   macos_lock(self.archive, sha), target="macos")
                shutil_rmtree(self.root / "rt")

    def test_windows_archive_is_never_accepted_for_macos(self):
        both = {"schema": 1, "targets": {
            "macos": {"python": {"archive": MACOS_ARCHIVE, "sha256": "0" * 64,
                                 "url": "https://example.invalid/a"},
                      "rust_target": "aarch64-apple-darwin"},
            "windows": {"python": {"archive": "python-3.12.10-embed-amd64.zip", "sha256": "0" * 64,
                                   "url": "https://example.invalid/b"},
                        "rust_target": "x86_64-pc-windows-msvc"}}}
        with self.assertRaisesRegex(BuildInputError, "must be"):
            extract_python(self.archive, self.root / "rt", both, target="windows")
        with self.assertRaisesRegex(BuildInputError, "no target"):
            extract_python(self.archive, self.root / "rt2",
                           macos_lock(self.archive, self.sha), target="windows")


def shutil_rmtree(path: Path) -> None:
    import shutil
    if path.exists():
        shutil.rmtree(path)


class MacosBundle(unittest.TestCase):
    def fake_runtime(self, root: Path) -> Path:
        runtime = root / "runtime-src"
        (runtime / "bin").mkdir(parents=True)
        (runtime / "lib" / "python3.12").mkdir(parents=True)
        python = runtime / "bin" / "python3.12"
        python.write_bytes(b"PY")
        python.chmod(0o755)
        (runtime / "lib" / "python3.12" / "os.py").write_bytes(b"# os")
        return runtime

    def test_macos_layout_names_bin_multi_search_and_runtime_bin_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / "multi-search"
            launcher.write_bytes(b"LAUNCHER")
            launcher.chmod(0o755)
            out, anchor_file = root / "bundle", root / "anchor.txt"
            anchor = build(self.fake_runtime(root), launcher, "0.4.0", out, anchor_file,
                           target="macos")
            paths = {f["path"] for f in json.loads((out / "manifest.json").read_bytes())["files"]}
            self.assertIn("bin/multi-search", paths)
            self.assertIn("runtime/bin/python3.12", paths)
            self.assertNotIn("bin/multi-search.exe", paths)
            self.assertEqual(anchor_file.read_text().strip(), anchor)

    def test_macos_requires_the_runtime_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = self.fake_runtime(root)
            (runtime / "bin" / "python3.12").unlink()
            launcher = root / "multi-search"
            launcher.write_bytes(b"L")
            with self.assertRaisesRegex(BundleError, "bin/python3.12"):
                build(runtime, launcher, "0.4.0", root / "out", root / "a", target="macos")

    def test_symlinks_in_the_runtime_tree_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = self.fake_runtime(root)
            (runtime / "bin" / "python3").symlink_to("python3.12")
            launcher = root / "multi-search"
            launcher.write_bytes(b"L")
            with self.assertRaisesRegex(BundleError, "links"):
                build(runtime, launcher, "0.4.0", root / "out", root / "a", target="macos")

    def test_unknown_targets_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(BundleError, "target"):
                build(root / "r", root / "l", "0.4.0", root / "o", root / "a", target="linux")


class MacosSigning(unittest.TestCase):
    def test_only_macho_files_are_signed(self):
        self.assertTrue(_is_macho(_write(self, b"\xcf\xfa\xed\xfe")))
        self.assertTrue(_is_macho(_write(self, b"\xca\xfe\xba\xbe")))
        self.assertFalse(_is_macho(_write(self, b"#!/bin/sh\n")))
        self.assertFalse(_is_macho(_write(self, b"MZ")))


def _write(case: unittest.TestCase, data: bytes) -> Path:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / "f"
    path.write_bytes(data)
    return path


class MacosSitePackages(unittest.TestCase):
    def test_xkit_source_is_refused_for_this_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            req = root / "req.txt"
            req.write_text("")
            wheel = root / "w.whl"
            wheel.write_bytes(b"w")
            xkit = root / "xkit"
            xkit.mkdir()
            with self.assertRaisesRegex(BundleError, "xkit"):
                install_runtime(root / "rt", req, wheel, xkit, target="macos")

    def test_macos_site_packages_lives_under_lib_python312(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "rt"
            site = runtime / "lib" / "python3.12" / "site-packages"
            site.mkdir(parents=True)
            req = root / "req.txt"
            req.write_text("")
            wheel = root / "w.whl"
            wheel.write_bytes(b"w")
            calls = []
            import build_cli_release
            original = build_cli_release._uv_install
            build_cli_release._uv_install = lambda args, site_arg, what, platform: calls.append((args, site_arg, platform))
            try:
                install_runtime(runtime, req, wheel, None, target="macos")
            finally:
                build_cli_release._uv_install = original
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][1], site)
            self.assertEqual(calls[0][2], "aarch64-apple-darwin")


@unittest.skipIf(sys.platform == "win32", "uses a POSIX shell fake interpreter")
class LauncherBytecodeIsolation(unittest.TestCase):
    """The launcher must disable bytecode writes both by flag and by child environment."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("rustc") is None:
            raise unittest.SkipTest("rustc is required to compile the launcher")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bundle = Path(cls.tmp.name) / "bundle"
        cls.launcher = compile_launcher(LAUNCHER_SRC, cls.bundle / "bin" / "multi-search")
        bin_dir = cls.bundle / "runtime" / "bin"
        bin_dir.mkdir(parents=True)
        cls.fake_python = bin_dir / "python3.12"
        cls.fake_python.write_text(
            "#!/bin/sh\n"
            "seen_b=0\n"
            'for arg in "$@"; do [ "$arg" = "-B" ] && seen_b=1; done\n'
            'printf "%s\\n" "$@" > "$(dirname "$0")/args.txt"\n'
            'printf "%s\\n" "${PYTHONDONTWRITEBYTECODE:-unset}" > "$(dirname "$0")/env.txt"\n'
            'if [ "$seen_b" = "0" ]; then\n'
            '  mkdir -p "$(dirname "$0")/../lib/python3.12/__pycache__"\n'
            '  : > "$(dirname "$0")/../lib/python3.12/__pycache__/probe.cpython-312.pyc"\n'
            "fi\n"
            'echo "multi-search 0.4.0"\n',
            encoding="utf-8",
        )
        cls.fake_python.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_launcher_passes_B_and_sets_PYTHONDONTWRITEBYTECODE_for_the_child(self):
        result = subprocess.run([str(self.launcher), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.bundle / "runtime" / "bin" / "args.txt").read_text().splitlines()
        self.assertIn("-B", args, "CPython needs -B; PYTHONDONTWRITEBYTECODE alone is ignored by -I")
        self.assertIn("-I", args)
        self.assertEqual((self.bundle / "runtime" / "bin" / "env.txt").read_text().strip(), "1")
        self.assertFalse((self.bundle / "runtime" / "lib" / "python3.12" / "__pycache__").exists(),
                         "no bytecode may be written into the installed bundle")


BUNDLE_DIR = os.environ.get("MULTI_SEARCH_BUNDLE_DIR")


def _bundle_snapshot(bundle: Path) -> dict[str, str]:
    """Map every regular file (including symlink entries) to a hash so a run must be byte-identical."""
    snapshot = {}
    for root, dirs, files in os.walk(bundle, followlinks=False):
        root_path = Path(root)
        for name in dirs:
            path = root_path / name
            if path.is_symlink():
                snapshot[path.relative_to(bundle).as_posix()] = f"link:{os.readlink(path)}"
        for name in files:
            path = root_path / name
            rel = path.relative_to(bundle).as_posix()
            if path.is_symlink():
                snapshot[rel] = f"link:{os.readlink(path)}"
            else:
                snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


@unittest.skipUnless(BUNDLE_DIR, "set MULTI_SEARCH_BUNDLE_DIR to verify a built bundle")
class BuiltBundleIntegrity(unittest.TestCase):
    """Acceptance checks against a real built bundle; run after scripts/build_cli_release.py."""

    def setUp(self):
        self.bundle = Path(BUNDLE_DIR).resolve()
        self.manifest_bytes = (self.bundle / "manifest.json").read_bytes()
        self.document = json.loads(self.manifest_bytes)

    def verify_manifest(self):
        listed = {entry["path"]: entry for entry in self.document["files"]}
        actual = {path.relative_to(self.bundle).as_posix()
                  for path in self.bundle.rglob("*") if path.is_file()}
        self.assertEqual(actual, set(listed) | {"manifest.json"})
        for rel, entry in listed.items():
            path = self.bundle / rel
            self.assertEqual(path.stat().st_size, entry["size"], rel)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"], rel)
        anchor = (self.bundle.parent / "cli-bundle.anchor").read_text(encoding="ascii").strip()
        self.assertEqual(anchor, hashlib.sha256(self.manifest_bytes).hexdigest(),
                         "the anchor compiled by build.rs must be the manifest hash")

    def assert_clean(self):
        links = [p for p in self.bundle.rglob("*") if p.is_symlink()]
        self.assertEqual(links, [], "the bundle must contain no symlinks")
        self.assertEqual([p for p in self.bundle.rglob("__pycache__") if p.is_dir()], [])
        self.assertEqual([p for p in self.bundle.rglob("*.pyc") if p.is_file()], [])
        self.assertEqual([p for p in self.bundle.rglob("direct_url.json") if p.is_file()], [],
                         "dist-info direct_url.json embeds the builder's absolute wheel path")
        absolute = []
        for path in self.bundle.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            with path.open("rb") as handle:
                first = handle.readline(512)
            if first.startswith(b"#!") and any(
                    prefix in first for prefix in (b"/Users/", b"/home/", b"/private/", b"/opt/", b"/tmp/")):
                absolute.append(path)
        self.assertEqual(absolute, [], "console scripts must not embed build-machine shebangs")
        self.assertFalse((self.bundle / "runtime" / "bin" / "python").exists(),
                         "the convenience alias must not be materialised")
        self.assertFalse((self.bundle / "runtime" / "bin" / "python3").exists(),
                         "the convenience alias must not be materialised")
        self.assertTrue((self.bundle / "runtime" / "bin" / "python3.12").is_file())

    def test_bundle_is_clean_and_a_relocated_version_probe_leaves_it_byte_identical(self):
        self.verify_manifest()
        self.assert_clean()
        before = _bundle_snapshot(self.bundle)
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                [str(self.bundle / "bin" / "multi-search"), "--version"],
                env={"HOME": home, "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.document["version"], result.stdout)
        self.assertEqual(_bundle_snapshot(self.bundle), before,
                         "running the installed CLI must not add, remove or rewrite bundle files")
        self.verify_manifest()
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
