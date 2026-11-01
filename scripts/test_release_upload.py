"""Release assets retain valid checksum references after GitHub name normalization."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import upload_desktop_release as upload


class ReleaseUpload(unittest.TestCase):
    def test_windows_checksum_references_uploaded_name_without_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "desktop/src-tauri/target/release/bundle/nsis/Multi Search_0.4.1_x64-setup.exe"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"synthetic installer")
            with patch.object(upload, "ROOT", root), patch.dict(os.environ, {
                "RELEASE_TARGET": "windows", "RELEASE_TAG": "v0.4.1",
            }), patch.object(upload.subprocess, "run") as gh:
                upload.main()
            args = gh.call_args.args[0]
            asset = Path(args[4])
            self.assertEqual(asset.name, "Multi.Search_0.4.1_x64-setup.exe")
            self.assertEqual(asset.read_bytes(), source.read_bytes())
            checksum = Path(args[5]).read_bytes()
            expected = f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {asset.name}\n".encode()
            self.assertEqual(checksum, expected)

    def test_linux_requires_both_installer_formats_before_uploading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deb = root / "desktop/src-tauri/target/release/bundle/deb/multi-search.deb"
            deb.parent.mkdir(parents=True)
            deb.write_bytes(b"synthetic deb")
            with patch.object(upload, "ROOT", root), patch.dict(os.environ, {
                "RELEASE_TARGET": "linux", "RELEASE_TAG": "v0.4.1",
            }), patch.object(upload.subprocess, "run") as gh:
                with self.assertRaisesRegex(SystemExit, "missing release package"):
                    upload.main()
            gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
