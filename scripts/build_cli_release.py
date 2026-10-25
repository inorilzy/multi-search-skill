"""Single reproducible entry point for the desktop's bundled CLI.

Steps (each fails explicitly; nothing is copied from an old dist binary):
  1. verify every input against a locked hash (scripts/build_inputs.py): the official CPython
     archive for the requested --target (scripts/build-inputs.lock.json), the project wheel
     (--wheel-sha256 from the step that built it) and the pinned rustc (rust-toolchain.toml);
  2. compile the relocatable launcher (desktop/src-tauri/launcher/main.rs) with the pinned rustc
     for the target's Rust triple and Authenticode-sign it on Windows when a signing certificate
     is configured (scripts/sign_windows.py); on macOS every Mach-O in the bundle — the launcher
     and the runtime's own binaries — is ad-hoc codesigned before the manifest is hashed;
  3. extract the verified CPython archive (safe tar/zip extraction, internal symlinks
     materialised) and install the pinned runtime requirements
     (scripts/cli-bundle-requirements.txt, hashed) offline from the uv cache. The per-target
     lock names convenience aliases to drop while extracting (macOS ``bin/python`` and
     ``bin/python3``): the launcher only executes ``bin/python3.12``, and materialising the
     aliases would copy the 18 MB interpreter three times;
  4. build the bundle with build_cli_bundle.build (manifest + anchor), so the anchor covers the
     signed launcher and the signed runtime binaries. The builder prunes build-machine residue
     (``__pycache__``/``.pyc``, uv's console scripts with absolute shebangs, ``.lock``, dist-info
     ``direct_url.json``) before hashing, so a dirty work tree can never be sealed;
  5. write the anchor to desktop/src-tauri/resources/cli-bundle.anchor, which build.rs compiles in.

``--target windows`` reproduces the original Windows bundle; ``--target macos`` builds the
aarch64-apple-darwin bundle with ``bin/multi-search`` and the interpreter at
``runtime/bin/python3.12``. ``--require-signing`` makes a missing Windows certificate a hard
failure; release CI sets it. On macOS ad-hoc codesigning is mandatory and runs locally.

The output goes to desktop/src-tauri/resources/cli-bundle (gitignored) so the Tauri resource
directory carries it. The redistribution of the runtime is NOT cleared; this entry point builds,
it does not publish.
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
from build_cli_bundle import TARGETS, build  # noqa: E402
from build_inputs import BuildInputError, check_rustc, extract_python, load_lock, lock_target, verify_file  # noqa: E402
from sign_windows import SigningError, sign_file  # noqa: E402

REPO = SCRIPTS_DIR.parent
LAUNCHER_SRC = REPO / "desktop" / "src-tauri" / "launcher" / "main.rs"
RESOURCES = REPO / "desktop" / "src-tauri" / "resources"
REQUIREMENTS = SCRIPTS_DIR / "cli-bundle-requirements.txt"
PYTHON_VERSION = "3.12"


def compile_launcher(source: Path, output: Path, rust_target: str | None = None) -> Path:
    if not source.is_file():
        raise BundleError(f"launcher source is missing: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["rustc", "--edition=2021", "-O", str(source), "-o", str(output)]
    if rust_target:
        command.extend(["--target", rust_target])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not output.is_file():
        raise BundleError(f"launcher compile failed: {result.stderr.strip()}")
    return output


def _is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    return magic in (
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",  # 32-bit
        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",  # 64-bit
        b"\xca\xfe\xba\xbe",                      # universal
    )


def codesign_macos_bundle(root: Path) -> int:
    """Ad-hoc codesign every Mach-O inside ``root``, depth-first so nested runtime
    binaries are signed before the launcher's signature is taken.

    Returns the number of signed binaries. Signing must happen before the manifest is
    built because codesigning changes the file bytes (and therefore their SHA-256).
    """
    count = 0
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink() or not path.is_file() or not _is_macho(path):
            continue
        result = subprocess.run(
            ["codesign", "--force", "--sign", "-", str(path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise BundleError(f"codesign failed for {path.name}: {result.stderr.strip()[-300:]}")
        count += 1
    return count


def _uv_install(args: list[str], site: Path, what: str, platform_tag: str) -> None:
    result = subprocess.run(
        ["uv", "pip", "install", "--offline", "--no-deps", *args, "--target", str(site),
         "--python-platform", platform_tag, "--python-version", PYTHON_VERSION],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BundleError(f"offline install of {what} failed: {result.stderr.strip()[-400:]}")


def install_runtime(runtime: Path, requirements: Path, wheel: Path, xkit_source: Path | None,
                    target: str = "windows") -> None:
    """Populate the runtime's site-packages offline: pinned hashed deps, the project wheel, optional xkit-py.

    Only site-packages is rebuilt; the verified CPython (python.exe/python3.12, stdlib) is kept.
    The wheel's hash is checked by the caller before this runs; xkit-py is verified by its author
    separately. ``xkit_source`` is optional while the xkit dependency is disabled: without it the
    bundle keeps working everywhere except Twitter/X, which reports its own installation error
    at runtime.
    """
    if xkit_source is not None:
        raise BundleError("xkit is disabled for this build; do not pass --xkit-source")
    required = ((requirements, "pinned requirements"), (wheel, "project wheel"))
    for path, label in required:
        if not path.exists():
            raise BundleError(f"{label} missing: {path}")
    if target == "macos":
        site = runtime / "lib" / f"python{PYTHON_VERSION}" / "site-packages"
        platform_tag = "aarch64-apple-darwin"
    else:
        site = runtime / "Lib" / "site-packages"
        platform_tag = "x86_64-pc-windows-msvc"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    _uv_install(["--require-hashes", "-r", str(requirements)], site, "pinned dependencies", platform_tag)
    _uv_install([str(wheel)], site, "project wheel", platform_tag)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=sorted(TARGETS), default="windows",
                        help="bundle target: windows (embeddable zip) or macos (arm64 install_only tar.gz)")
    parser.add_argument("--python-archive", type=Path, required=True,
                        help="official CPython archive locked in scripts/build-inputs.lock.json for --target")
    parser.add_argument("--wheel", type=Path, required=True, help="built multi_search_mcp wheel")
    parser.add_argument("--wheel-sha256", required=True,
                        help="SHA-256 of --wheel, recorded by the pipeline step that built it")
    parser.add_argument("--xkit-source", type=Path, default=None,
                        help="disabled: xkit must not be added to this build")
    parser.add_argument("--version", required=True)
    parser.add_argument("--work", type=Path, default=None,
                        help="isolated work dir (default dist/<target>-cli-release-work)")
    parser.add_argument("--require-signing", action="store_true",
                        help="fail unless the launcher can be Authenticode-signed (Windows release CI)")
    options = parser.parse_args(argv)
    work = options.work or (REPO / "dist" / f"{options.target}-cli-release-work")
    try:
        lock = load_lock()
        spec = lock_target(lock, options.target)
        check_rustc()
        verify_file(options.wheel, options.wheel_sha256, "project wheel")
        launcher_rel = TARGETS[options.target]["launcher_rel"]
        launcher = compile_launcher(LAUNCHER_SRC, work / "launcher" / Path(launcher_rel).name,
                                    rust_target=spec.get("rust_target"))
        if options.target == "windows":
            sign_file(launcher, required=options.require_signing)
        elif options.require_signing:
            raise BundleError("--require-signing is only meaningful for the Windows target")
        runtime = work / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        extract_python(options.python_archive, runtime, lock, target=options.target)
        install_runtime(runtime, REQUIREMENTS, options.wheel, options.xkit_source, target=options.target)
        staging = work / "staging"
        if staging.exists():
            shutil.rmtree(staging)
        (staging / "bin").mkdir(parents=True)
        shutil.copy2(launcher, staging / "bin" / Path(launcher_rel).name)
        _copy_runtime(runtime, staging / "runtime")
        if options.target == "macos":
            signed = codesign_macos_bundle(staging)
            print(f"codesigned {signed} Mach-O binaries (ad hoc)", file=sys.stderr)
        out = RESOURCES / "cli-bundle"
        if out.exists():
            shutil.rmtree(out)
        anchor = build(staging / "runtime", staging / "bin" / Path(launcher_rel).name,
                       options.version, out, RESOURCES / "cli-bundle.anchor",
                       target=options.target)
    except (BundleError, BuildInputError, SigningError) as error:
        print(f"release build refused: {error}", file=sys.stderr)
        return 2
    print(anchor)
    return 0


def _copy_runtime(source: Path, dest: Path) -> None:
    """Copy the prepared runtime into staging; symlinks were already materialised at extraction."""
    shutil.copytree(source, dest, symlinks=False)


if __name__ == "__main__":
    raise SystemExit(main())
