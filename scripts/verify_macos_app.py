"""Verify a built macOS app's managed CLI bundle before shipping or installing it.

The desktop app installs the CLI from `<App>.app/Contents/Resources/cli-bundle` after checking
that bundle against the trust anchor compiled into the binary. Nothing proves the *copied* tree
still matches: Tauri recreates resource files, an archive/copy step can drop the execute bit, and
`codesign --deep` re-signs nested Mach-O files, which changes their bytes after the manifest was
hashed. This script closes that gap for one app bundle:

* every manifest-listed file exists, is a regular file, and matches its recorded size and SHA-256;
* no symlinks and no bytecode appear in the shipped tree;
* the launcher and `runtime/bin/*` are executable (`0755`), the interpreter runs;
* the app's code signature verifies;
* running the shipped launcher from a throwaway HOME prints the expected version and leaves the
  tree byte-identical, so an installed CLI cannot silently rewrite the signed app.

Exit code 0 means all checks passed; anything else lists the concrete failure. It never modifies
the app; pass ``--sign`` to replace a broken ad-hoc seal first (e.g. one Tauri left behind).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLI_REL = "bin/multi-search"
RUNTIME_BIN = "runtime/bin"


class AppVerificationError(ValueError):
    """Raised when the shipped bundle or the app seal fails a check."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_dir(app: Path) -> Path:
    app = app.resolve()
    if not app.is_dir():
        raise AppVerificationError(f"app bundle not found: {app}")
    return app / "Contents" / "Resources" / "cli-bundle"


def verify_manifest(bundle: Path) -> dict:
    """Every listed file must exist as a regular file with its recorded size and digest."""
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise AppVerificationError(f"shipped bundle lacks manifest.json: {bundle}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise AppVerificationError(f"shipped manifest is unreadable: {error}") from None
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AppVerificationError("shipped manifest lists no files")
    problems = []
    for entry in files:
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel:
            raise AppVerificationError("shipped manifest contains an entry without a path")
        path = bundle / rel
        if path.is_symlink():
            problems.append(f"symlink in shipped bundle: {rel}")
            continue
        if not path.is_file():
            problems.append(f"missing from shipped bundle: {rel}")
            continue
        if path.stat().st_size != entry.get("size"):
            problems.append(f"size differs in shipped bundle: {rel}")
            continue
        if sha256_file(path) != entry.get("sha256"):
            problems.append(f"SHA-256 differs in shipped bundle: {rel}")
    # The shipped tree must be exactly the manifest: an unlisted file or symlink would be
    # copied into every install without ever being verified against the trust anchor.
    listed = {bundle / entry["path"] for entry in files if isinstance(entry.get("path"), str)}
    for path in sorted(bundle.rglob("*")):
        if path == manifest_path:
            continue
        if path.is_symlink():
            problems.append(f"symlink outside the manifest: {path.relative_to(bundle)}")
        elif path.is_file() and path not in listed:
            problems.append(f"file outside the manifest: {path.relative_to(bundle)}")
    if problems:
        raise AppVerificationError(
            "shipped bundle does not match its manifest:\n  " + "\n  ".join(problems[:20])
        )
    return manifest


def verify_layout(bundle: Path) -> None:
    """No bytecode, and the launcher/interpreter keep their execute bits."""
    stray = [p.relative_to(bundle) for p in bundle.rglob("__pycache__")]
    stray += [p.relative_to(bundle) for p in bundle.rglob("*.pyc")]
    if stray:
        raise AppVerificationError(
            "shipped bundle carries bytecode (running it would rewrite the app): "
            + ", ".join(str(p) for p in stray[:5])
        )
    cli = bundle / CLI_REL
    python = bundle / "runtime" / "bin" / "python3.12"
    for label, path in (("launcher", cli), ("interpreter", python)):
        if not path.is_file():
            raise AppVerificationError(f"shipped bundle lacks the {label}: {path}")
        if not os.access(path, os.X_OK):
            raise AppVerificationError(f"shipped {label} is not executable: {path}")
    for path in sorted((bundle / RUNTIME_BIN).iterdir()):
        if path.is_file() and not os.access(path, os.X_OK):
            raise AppVerificationError(f"shipped runtime binary is not executable: {path.name}")


def snapshot_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def verify_runs_immutably(bundle: Path, expected_version: str | None) -> str:
    """Run the shipped launcher in a clean environment and prove the tree is unchanged."""
    before = snapshot_tree(bundle)
    with tempfile.TemporaryDirectory(prefix="multi-search-app-check-") as home:
        result = subprocess.run(
            [str(bundle / CLI_REL), "--version"],
            env={"HOME": home, "PATH": "/usr/bin:/bin"},
            cwd=home,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AppVerificationError(
                "shipped launcher failed to run: " + (result.stderr.strip() or "no output")
            )
        printed = result.stdout.strip()
        if expected_version and not printed.endswith(expected_version):
            raise AppVerificationError(
                f"shipped launcher printed {printed!r}, expected version {expected_version}"
            )
    after = snapshot_tree(bundle)
    if before != after:
        changed = sorted(set(before) ^ set(after)) or sorted(
            key for key in before if before[key] != after.get(key)
        )
        raise AppVerificationError(
            "running the shipped CLI modified the app bundle: " + ", ".join(changed[:5])
        )
    return printed


def verify_signature(app: Path) -> None:
    result = subprocess.run(
        ["codesign", "--verify", "--strict", str(app)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AppVerificationError(
            "app signature does not verify (re-run with --sign for a local ad-hoc seal): "
            + (result.stderr.strip() or "codesign failed")
        )


def ad_hoc_sign(app: Path) -> None:
    """Replace a broken seal without touching nested code.

    `--deep` would re-sign the bundle's own Mach-O files *after* the manifest was hashed,
    invalidating every entry the installer verifies. Signing only the app seals the
    resources by hashing them instead of rewriting them.
    """
    result = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(app)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AppVerificationError(
            "ad-hoc codesign failed: " + (result.stderr.strip() or "codesign failed")
        )


def verify(app: Path, *, expected_version: str | None = None) -> dict:
    bundle = bundle_dir(app)
    manifest = verify_manifest(bundle)
    verify_layout(bundle)
    printed = verify_runs_immutably(bundle, expected_version)
    verify_signature(app.resolve())
    return {"files": len(manifest["files"]), "version": manifest.get("version"), "printed": printed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("app", type=Path, help="the built .app bundle")
    parser.add_argument("--expect-version", default=None, help="require this printed CLI version")
    parser.add_argument("--sign", action="store_true",
                        help="replace the app seal with a local ad-hoc signature first")
    options = parser.parse_args(argv)
    try:
        if options.sign:
            ad_hoc_sign(options.app)
        report = verify(options.app, expected_version=options.expect_version)
    except AppVerificationError as error:
        print(f"app verification failed: {error}", file=sys.stderr)
        return 2
    print(f"verified {report['files']} bundled files; CLI reports {report['printed']} "
          f"(manifest version {report['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
