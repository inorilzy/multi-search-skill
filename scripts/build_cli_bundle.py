"""Assemble the relocatable CLI bundle, its manifest, and the compiled trust anchor.

Inputs are explicit so the build never depends on implicit machine state:
  --runtime   a prepared Windows CPython tree (python.exe, Lib/, DLLs/, ...)
  --launcher  the compiled relocatable launcher (becomes bin/multi-search.exe)
  --version   the CLI version that the bundle's probe must report
  --out       the bundle directory to create (must not exist)
  --anchor-out where the 64-hex anchor is written for the desktop build

The output contains bundle files only; the manifest is written beside them but the
installer trusts it solely through the anchor compiled into the desktop binary.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from bundle_manifest import BundleError, anchor_for, build_manifest, validate_relative_path  # noqa: E402

LAUNCHER_REL = "bin/multi-search.exe"
RUNTIME_PYTHON_REL = "runtime/python.exe"


def collect_runtime(runtime: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(runtime.rglob("*")):
        if path.is_file():
            rel = path.relative_to(runtime).as_posix()
            files[f"runtime/{rel}"] = path
    return files


def build(runtime: Path, launcher: Path, version: str, out: Path, anchor_out: Path) -> str:
    if out.exists():
        raise BundleError(f"output already exists: {out}")
    if not (runtime / "python.exe").is_file():
        raise BundleError("runtime tree lacks python.exe")
    if not launcher.is_file():
        raise BundleError("launcher binary is missing")
    out.mkdir(parents=True)
    (out / "bin").mkdir()
    shutil.copy2(launcher, out / LAUNCHER_REL)
    shutil.copytree(runtime, out / "runtime")

    files = {LAUNCHER_REL: out / LAUNCHER_REL, **collect_runtime(out / "runtime")}
    for rel in files:
        validate_relative_path(rel)
    manifest_bytes = build_manifest(version, files)
    (out / "manifest.json").write_bytes(manifest_bytes)
    anchor = anchor_for(manifest_bytes)
    anchor_out.parent.mkdir(parents=True, exist_ok=True)
    anchor_out.write_text(anchor + "\n", encoding="ascii")
    return anchor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--anchor-out", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        anchor = build(options.runtime, options.launcher, options.version, options.out, options.anchor_out)
    except BundleError as error:
        print(f"bundle build refused: {error}", file=sys.stderr)
        return 2
    print(anchor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
