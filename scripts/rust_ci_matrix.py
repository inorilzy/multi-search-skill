"""Run the Windows Rust CI matrix under disposable state and a network guard.

Self-contained entry point for `.github/workflows/test.yml`. Does not rely on
cwd or PYTHONPATH: the repository root is derived from this file's location.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_isolation import isolated_test_environment  # noqa: E402


def main() -> int:
    manifest = str(ROOT / "desktop" / "src-tauri" / "Cargo.toml")
    # rustc compiles tests/fixture_cli.rs during tests; keep the toolchain on PATH.
    subprocess.run(["rustc", "--version"], check=True)
    with isolated_test_environment(source_root=ROOT) as isolation:
        os.environ["MULTI_SEARCH_STATE_DB"] = str(isolation.paths.state)
        # Rust interop tests call Command::new("python"), not a custom selector.
        from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES
        from multi_search_mcp.src.support.credential_store import CredentialStore
        assert ALL_SOURCE_NAMES and CredentialStore
        os.environ.pop("TAURI_CONFIG", None)
        for args in (
            ["test", "--no-default-features"],
            ["test", "--no-default-features", "--features", "test-fixtures,ts"],
            ["test", "--no-default-features", "--features", "install-test-boundary"],
        ):
            subprocess.run(
                ["cargo", *args, "--locked", "--offline", "--manifest-path", manifest],
                check=True,
            )
        overlay = ROOT / "desktop/src-tauri/tauri.check.conf.json"
        os.environ["TAURI_CONFIG"] = json.dumps(
            json.loads(overlay.read_text(encoding="utf-8"))
        )
        for args in (
            ["check", "--all-targets", "--features", "test-fixtures,ts"],
            ["test", "--features", "install-test-boundary,ts"],
        ):
            subprocess.run(
                ["cargo", *args, "--locked", "--offline", "--manifest-path", manifest],
                check=True,
            )
        isolation.assert_clean()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
