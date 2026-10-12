"""Single reproducible entry point for the desktop's bundled CLI.

Steps (each fails explicitly; nothing is copied from an old dist binary):
  1. compile the relocatable launcher (desktop/src-tauri/launcher/main.rs) with rustc;
  2. install the pinned runtime (scripts/cli-bundle-requirements.txt, hashed) offline from the uv cache;
  3. build the bundle with build_cli_bundle.build (manifest + anchor);
  4. write the anchor to desktop/src-tauri/resources/cli-bundle.anchor, which build.rs compiles in.

The output goes to desktop/src-tauri/resources/cli-bundle (gitignored) so the Tauri resource directory
carries it. The redistribution of the runtime is NOT cleared; this entry point builds, it does not publish.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from bundle_manifest import BundleError  # noqa: E402
from build_cli_bundle import build  # noqa: E402

REPO = SCRIPTS_DIR.parent
LAUNCHER_SRC = REPO / "desktop" / "src-tauri" / "launcher" / "main.rs"
RESOURCES = REPO / "desktop" / "src-tauri" / "resources"
REQUIREMENTS = SCRIPTS_DIR / "cli-bundle-requirements.txt"
PYTHON_VERSION = "3.12"
PLATFORM = "x86_64-pc-windows-msvc"


def compile_launcher(source: Path, output: Path) -> Path:
    if not source.is_file():
        raise BundleError(f"launcher source is missing: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["rustc", "--edition=2021", "-O", str(source), "-o", str(output)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output.is_file():
        raise BundleError(f"launcher compile failed: {result.stderr.strip()}")
    return output


def _uv_install(args: list[str], site: Path, what: str) -> None:
    result = subprocess.run(
        ["uv", "pip", "install", "--offline", "--no-deps", *args, "--target", str(site),
         "--python-platform", PLATFORM, "--python-version", PYTHON_VERSION],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BundleError(f"offline install of {what} failed: {result.stderr.strip()[-400:]}")


def install_runtime(runtime: Path, requirements: Path, wheel: Path, xkit_source: Path) -> None:
    """Populate the runtime's site-packages offline: pinned hashed deps, the project wheel, pinned xkit-py.

    Only site-packages is rebuilt; the copied CPython (python.exe, Lib/, DLLs/) is kept.
    """
    for path, label in ((requirements, "pinned requirements"), (wheel, "project wheel"), (xkit_source, "xkit-py source")):
        if not path.exists():
            raise BundleError(f"{label} missing: {path}")
    site = runtime / "Lib" / "site-packages"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    _uv_install(["--require-hashes", "-r", str(requirements)], site, "pinned dependencies")
    _uv_install([str(wheel)], site, "project wheel")
    _uv_install([str(xkit_source)], site, "xkit-py")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python-tree", type=Path, required=True,
                        help="pinned Windows CPython tree (python.exe, Lib/, DLLs/)")
    parser.add_argument("--wheel", type=Path, required=True, help="built multi_search_mcp wheel")
    parser.add_argument("--xkit-source", type=Path, required=True,
                        help="xkit-py checkout at the pinned commit (see scripts/cli-bundle-requirements.txt)")
    parser.add_argument("--version", required=True)
    parser.add_argument("--work", type=Path, default=REPO / "dist" / "cli-release-work")
    options = parser.parse_args(argv)
    try:
        launcher = compile_launcher(LAUNCHER_SRC, options.work / "launcher" / "multi-search.exe")
        runtime = options.work / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        shutil.copytree(options.python_tree, runtime)
        install_runtime(runtime, REQUIREMENTS, options.wheel, options.xkit_source)
        out = RESOURCES / "cli-bundle"
        if out.exists():
            shutil.rmtree(out)
        anchor = build(runtime, launcher, options.version, out, RESOURCES / "cli-bundle.anchor")
    except BundleError as error:
        print(f"release build refused: {error}", file=sys.stderr)
        return 2
    print(anchor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
