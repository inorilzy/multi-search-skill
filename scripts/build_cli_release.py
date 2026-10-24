"""Single reproducible entry point for the desktop's bundled CLI.

Steps (each fails explicitly; nothing is copied from an old dist binary):
  1. verify every input against a locked hash (scripts/build_inputs.py): the official CPython
     archive (scripts/build-inputs.lock.json), the project wheel (--wheel-sha256 from the step that
     built it) and the pinned rustc (rust-toolchain.toml);
  2. compile the relocatable launcher (desktop/src-tauri/launcher/main.rs) with the pinned rustc and
     Authenticode-sign it when a signing certificate is configured (scripts/sign_windows.py);
  3. extract the verified CPython archive and install the pinned runtime
     (scripts/cli-bundle-requirements.txt, hashed) offline from the uv cache;
  4. build the bundle with build_cli_bundle.build (manifest + anchor), so the anchor covers the
     signed launcher;
  5. write the anchor to desktop/src-tauri/resources/cli-bundle.anchor, which build.rs compiles in.

``--require-signing`` makes a missing certificate a hard failure; release CI sets it.

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
from build_inputs import BuildInputError, check_rustc, extract_python, load_lock, verify_file  # noqa: E402
from sign_windows import SigningError, sign_file  # noqa: E402

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


def install_runtime(runtime: Path, requirements: Path, wheel: Path, xkit_source: Path | None) -> None:
    """Populate the runtime's site-packages offline: pinned hashed deps, the project wheel, optional xkit-py.

    Only site-packages is rebuilt; the verified CPython (python.exe, stdlib) is kept. The wheel's
    hash is checked by the caller before this runs; xkit-py is verified by its author separately.
    ``xkit_source`` is optional while the xkit dependency is disabled: without it the bundle keeps
    working everywhere except Twitter/X, which reports its own installation error at runtime.
    """
    required = ((requirements, "pinned requirements"), (wheel, "project wheel"))
    if xkit_source is not None:
        required += ((xkit_source, "xkit-py source"),)
    for path, label in required:
        if not path.exists():
            raise BundleError(f"{label} missing: {path}")
    site = runtime / "Lib" / "site-packages"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    _uv_install(["--require-hashes", "-r", str(requirements)], site, "pinned dependencies")
    _uv_install([str(wheel)], site, "project wheel")
    if xkit_source is not None:
        _uv_install([str(xkit_source)], site, "xkit-py")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python-archive", type=Path, required=True,
                        help="official Windows CPython embeddable zip locked in scripts/build-inputs.lock.json")
    parser.add_argument("--wheel", type=Path, required=True, help="built multi_search_mcp wheel")
    parser.add_argument("--wheel-sha256", required=True,
                        help="SHA-256 of --wheel, recorded by the pipeline step that built it")
    parser.add_argument("--xkit-source", type=Path, default=None,
                        help="optional xkit-py checkout at the pinned commit; omit while xkit is disabled")
    parser.add_argument("--version", required=True)
    parser.add_argument("--work", type=Path, default=REPO / "dist" / "cli-release-work")
    parser.add_argument("--require-signing", action="store_true",
                        help="fail unless the launcher can be Authenticode-signed (release CI)")
    options = parser.parse_args(argv)
    try:
        lock = load_lock()
        check_rustc()
        verify_file(options.wheel, options.wheel_sha256, "project wheel")
        launcher = compile_launcher(LAUNCHER_SRC, options.work / "launcher" / "multi-search.exe")
        sign_file(launcher, required=options.require_signing)
        runtime = options.work / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        extract_python(options.python_archive, runtime, lock)
        install_runtime(runtime, REQUIREMENTS, options.wheel, options.xkit_source)
        out = RESOURCES / "cli-bundle"
        if out.exists():
            shutil.rmtree(out)
        anchor = build(runtime, launcher, options.version, out, RESOURCES / "cli-bundle.anchor")
    except (BundleError, BuildInputError, SigningError) as error:
        print(f"release build refused: {error}", file=sys.stderr)
        return 2
    print(anchor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
