"""Assemble the relocatable CLI bundle, its manifest, and the compiled trust anchor.

Inputs are explicit so the build never depends on implicit machine state:
  --runtime   a prepared CPython tree (Windows: python.exe, Lib/, DLLs/; macOS: bin/python3.12,
              lib/, ...) built only from the locked, hash-verified archive
  --launcher  the compiled relocatable launcher (Windows: bin/multi-search.exe,
              macOS: bin/multi-search)
  --version   the CLI version that the bundle's probe must report
  --out       the bundle directory to create (must not exist)
  --anchor-out where the 64-hex anchor is written for the desktop build
  --target    ``windows`` or ``macos``; selects the expected runtime layout and launcher name

The output contains bundle files only; the manifest is written beside them but the
installer trusts it solely through the anchor compiled into the desktop binary. On Unix
the bundle must carry no symlinks: the manifest verifier rejects them outright. Before
hashing, build-machine residue (``__pycache__``/``.pyc``, uv's ``site-packages/bin``
console scripts with absolute shebangs, ``site-packages/.lock``, and dist-info
``direct_url.json``) is pruned so a dirty work tree can never be sealed.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from bundle_manifest import BundleError, anchor_for, build_manifest, validate_relative_path  # noqa: E402

TARGETS = {
    "windows": {
        "launcher_rel": "bin/multi-search.exe",
        "python_rel": "python.exe",
    },
    "macos": {
        "launcher_rel": "bin/multi-search",
        "python_rel": "bin/python3.12",
    },
}


def collect_runtime(runtime: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(runtime.rglob("*")):
        if path.is_symlink():
            raise BundleError(f"runtime tree must not contain links: {path}")
        if path.is_file():
            rel = path.relative_to(runtime).as_posix()
            files[f"runtime/{rel}"] = path
    return files


def _copytree_no_symlinks(source: Path, dest: Path) -> None:
    """Copy a tree, materialising nothing but regular files and directories.

    A symlink inside ``source`` is refused rather than followed: the bundle must contain only
    plain files so the installer's manifest verification (which rejects links) stays sound.
    """
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        target = dest / rel
        if path.is_symlink():
            raise BundleError(f"runtime tree must not contain links: {path}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _prune_runtime(runtime: Path) -> None:
    """Delete build-machine residue that must never be sealed into the bundle.

    * ``__pycache__`` directories and stray ``.pyc`` files: a previous probe or import may have
      written bytecode into the work tree; if it were hashed, installing/running the CLI would
      change files the manifest promised.
    * ``site-packages/bin``: uv writes console scripts there whose shebang embeds the build
      machine's absolute interpreter path. The launcher imports the package directly, so these
      scripts are unnecessary (and would leak a private path).
    * ``site-packages/.lock``: uv's empty lock file, created mode 0666 and not part of the product.
    * ``*.dist-info/direct_url.json``: PEP 610 metadata recording where the wheel was installed
      from. For a locally built wheel it embeds the builder's absolute path, leaking the build
      machine and making the manifest hash differ across machines that produced identical bits.

    Pruning happens on the copied output tree, before the manifest/anchor is computed, so the
    source work directory stays untouched and cannot leak into the sealed bundle.
    """
    for path in sorted(list(runtime.rglob("*")), key=lambda item: len(item.parts), reverse=True):
        if not path.exists():
            continue
        if path.name == "__pycache__" and path.is_dir():
            shutil.rmtree(path)
        elif path.suffix == ".pyc" and path.is_file():
            path.unlink()
        elif path.name == "bin" and path.is_dir() and path.parent.name == "site-packages":
            shutil.rmtree(path)
        elif path.name == ".lock" and path.is_file() and path.parent.name == "site-packages":
            path.unlink()
        elif (path.name == "direct_url.json" and path.is_file()
              and path.parent.name.endswith(".dist-info")):
            # Drop the file and its RECORD row together, so installed metadata has no dangling
            # reference to a file the bundle does not contain.
            record = path.parent / "RECORD"
            if record.is_file():
                lines = record.read_text(encoding="utf-8").splitlines(keepends=True)
                kept = []
                for line in lines:
                    name = line.split(",", 1)[0]
                    if name == "direct_url.json" or name.endswith("/direct_url.json"):
                        continue
                    kept.append(line)
                if len(kept) != len(lines):
                    record.write_text("".join(kept), encoding="utf-8")
            path.unlink()


def build(runtime: Path, launcher: Path, version: str, out: Path, anchor_out: Path,
          target: str = "windows") -> str:
    if target not in TARGETS:
        raise BundleError(f"unknown bundle target: {target!r}")
    spec = TARGETS[target]
    if out.exists():
        raise BundleError(f"output already exists: {out}")
    python_rel = spec["python_rel"]
    if not (runtime / python_rel).is_file():
        raise BundleError(f"runtime tree lacks {python_rel}")
    if not launcher.is_file():
        raise BundleError("launcher binary is missing")
    out.mkdir(parents=True)
    (out / "bin").mkdir()
    launcher_rel = spec["launcher_rel"]
    shutil.copy2(launcher, out / launcher_rel)
    _copytree_no_symlinks(runtime, out / "runtime")
    _prune_runtime(out / "runtime")

    files = {launcher_rel: out / launcher_rel, **collect_runtime(out / "runtime")}
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
    parser.add_argument("--target", choices=sorted(TARGETS), default="windows")
    options = parser.parse_args(argv)
    try:
        anchor = build(options.runtime, options.launcher, options.version, options.out,
                       options.anchor_out, target=options.target)
    except BundleError as error:
        print(f"bundle build refused: {error}", file=sys.stderr)
        return 2
    print(anchor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
