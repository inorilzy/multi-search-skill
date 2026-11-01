"""Prepare verified inputs and warm uv's cache for the offline CLI bundle builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import urllib.request

from build_inputs import load_lock, lock_target, verify_file

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("macos", "windows", "linux"), required=True)
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    tag = os.environ["RELEASE_TAG"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or tag != f"v{version}":
        raise SystemExit(f"release tag {tag!r} must match project version v{version}")
    for path in ("desktop/package.json", "desktop/src-tauri/tauri.conf.json"):
        if json.loads((ROOT / path).read_text(encoding="utf-8"))["version"] != version:
            raise SystemExit(f"version mismatch in {path}")
    if tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))["package"]["version"] != version:
        raise SystemExit("Cargo package version differs from release tag")
    spec = lock_target(load_lock(), args.target)
    inputs = ROOT / "dist" / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    archive = inputs / spec["python"]["archive"]
    urllib.request.urlretrieve(spec["python"]["url"], archive)
    verify_file(archive, spec["python"]["sha256"], "CPython archive")
    wheel_dir = ROOT / "dist" / "wheel" / version
    # Build through a fresh sdist so an old build/lib tree cannot reintroduce deleted modules.
    subprocess.run([sys.executable, "-m", "build", "--outdir", str(wheel_dir)], cwd=ROOT, check=True)
    wheels = list(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("expected exactly one freshly built project wheel")
    wheel = wheels[0]
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    # The release builder deliberately installs offline. Populate that same uv cache first
    # using the exact platform, Python version and hashed dependency lock it will consume.
    cache_site = ROOT / "dist" / "cache-site"
    common = ["uv", "pip", "install", "--no-deps", "--target", str(cache_site),
              "--python-platform", spec["rust_target"], "--python-version", "3.12"]
    subprocess.run([*common, "--require-hashes", "-r", str(ROOT / "scripts/cli-bundle-requirements.txt")], check=True)
    subprocess.run([*common, str(wheel)], check=True)
    subprocess.run([sys.executable, "scripts/build_cli_release.py", "--target", args.target,
                    "--python-archive", str(archive), "--wheel", str(wheel),
                    "--wheel-sha256", wheel_hash, "--version", version], cwd=ROOT, check=True)
    launcher = ROOT / "desktop/src-tauri/resources/cli-bundle/bin" / (
        "multi-search.exe" if args.target == "windows" else "multi-search")
    result = subprocess.run([str(launcher), "--version"], cwd=inputs, check=True,
                            capture_output=True, text=True)
    if not result.stdout.strip().endswith(version):
        raise SystemExit(f"bundled CLI version mismatch: {result.stdout!r}")
    print(result.stdout.strip())
    if args.target == "windows":
        # NSIS embeds this command inside !uninstfinalize. Inline Python containing
        # quotes breaks its grammar; pass a script path as an ordinary argument.
        # Without a certificate, omit the hook entirely instead of a no-op signer.
        sign_command = None
        if os.environ.get("WINDOWS_SIGN_CERT_BASE64", "").strip():
            sign_command = {"cmd": "python", "args": [str(ROOT / "scripts/sign_windows.py"), "%1"]}
        overlay = {"bundle": {"windows": {"signCommand": sign_command}}}
        (ROOT / "dist/windows-bundle.conf.json").write_text(
            json.dumps(overlay, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
