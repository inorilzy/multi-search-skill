"""Tests for bundle manifest path rules; run with python -m unittest."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bundle_manifest import BundleError, anchor_for, build_manifest, validate_relative_path


class PathRules(unittest.TestCase):
    def test_accepts_plain_relative_paths(self):
        for ok in ("runtime/python.exe", "runtime/Lib/site-packages/x/__init__.py", "bin/multi-search.exe"):
            self.assertEqual(validate_relative_path(ok), ok)

    def test_rejects_unsafe_paths(self):
        bad = [
            "/abs/path", "C:/x", "c:x", r"\\server\share\x", "..", "a/../b", "a//b", "./a",
            r"a\b", "file.txt:stream", "dir/CON", "dir/nul.txt", "trailing./x", "trailing /x", "",
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(BundleError):
                validate_relative_path(text)


class Manifest(unittest.TestCase):
    def test_case_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            a.write_bytes(b"1")
            with self.assertRaises(BundleError):
                build_manifest("0.4.0", {"Lib/x.py": a, "lib/X.py": a})

    def test_manifest_is_deterministic_and_anchor_is_sha256_of_raw_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            a.write_bytes(b"alpha")
            b.write_bytes(b"beta")
            first = build_manifest("0.4.0", {"z.txt": b, "a.txt": a})
            second = build_manifest("0.4.0", {"a.txt": a, "z.txt": b})
            self.assertEqual(first, second)
            document = json.loads(first)
            self.assertEqual([f["path"] for f in document["files"]], ["a.txt", "z.txt"])
            self.assertEqual(document["files"][0]["sha256"], hashlib.sha256(b"alpha").hexdigest())
            self.assertEqual(anchor_for(first), hashlib.sha256(first).hexdigest())


if __name__ == "__main__":
    unittest.main()
