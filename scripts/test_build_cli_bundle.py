"""Tests for the bundle build; use a tiny fake runtime, never the real one."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cli_bundle import build
from bundle_manifest import BundleError


def fake_tree(root: Path) -> Path:
    runtime = root / "runtime-src"
    (runtime / "Lib").mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"PY")
    (runtime / "Lib" / "os.py").write_bytes(b"# os")
    launcher = root / "launcher.exe"
    launcher.write_bytes(b"LAUNCHER")
    return runtime, launcher


class Build(unittest.TestCase):
    def test_manifest_covers_launcher_and_every_runtime_file_and_anchor_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, launcher = fake_tree(root)
            out, anchor_file = root / "bundle", root / "anchor.txt"
            anchor = build(runtime, launcher, "0.4.0", out, anchor_file)
            manifest_bytes = (out / "manifest.json").read_bytes()
            self.assertEqual(anchor, hashlib.sha256(manifest_bytes).hexdigest())
            self.assertEqual(anchor_file.read_text(encoding="ascii").strip(), anchor)
            paths = [f["path"] for f in json.loads(manifest_bytes)["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertEqual(set(paths), {"bin/multi-search.exe", "runtime/python.exe", "runtime/Lib/os.py"})
            self.assertNotIn("manifest.json", paths)

    def test_refuses_existing_output_and_missing_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, launcher = fake_tree(root)
            (root / "bundle").mkdir()
            with self.assertRaises(BundleError):
                build(runtime, launcher, "0.4.0", root / "bundle", root / "a.txt")
            (runtime / "python.exe").unlink()
            with self.assertRaises(BundleError):
                build(runtime, launcher, "0.4.0", root / "b", root / "a.txt")


if __name__ == "__main__":
    unittest.main()
