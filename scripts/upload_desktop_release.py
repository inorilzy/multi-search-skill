"""Upload only this runner's desktop installers and their SHA-256 checksums."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "macos": ("dist/*.dmg",),
    "windows": ("desktop/src-tauri/target/release/bundle/nsis/*.exe",),
    "linux": ("desktop/src-tauri/target/release/bundle/deb/*.deb",
              "desktop/src-tauri/target/release/bundle/appimage/*.AppImage"),
}


def main() -> None:
    target = os.environ["RELEASE_TARGET"]
    assets = []
    for pattern in PATTERNS[target]:
        matches = sorted(ROOT.glob(pattern))
        if not matches:
            raise SystemExit(f"missing release package: {pattern}")
        assets.extend(matches)
    checksums = ROOT / f"SHA256SUMS-{target}.txt"
    checksums.write_text("".join(
        f"{hashlib.sha256(asset.read_bytes()).hexdigest()}  {asset.name}\n" for asset in assets
    ), encoding="utf-8")
    subprocess.run(["gh", "release", "upload", os.environ["RELEASE_TAG"],
                    *map(str, assets), str(checksums), "--clobber"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
