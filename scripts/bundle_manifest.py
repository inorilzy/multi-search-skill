"""Build the CLI bundle manifest and its trust anchor, deterministically.

The manifest lists every bundle file with its POSIX relative path, size, and SHA-256.
The anchor is the SHA-256 of the manifest's raw bytes; the desktop binary compiles it in,
so the installer checks the manifest before parsing it. Nothing beside the bundle is trusted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

MANIFEST_SCHEMA = 1
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_DRIVE = re.compile(r"^[A-Za-z]:")


class BundleError(ValueError):
    """Raised when a bundle cannot be described safely."""


def validate_relative_path(text: str) -> str:
    """Accept only plain relative POSIX paths that stay inside the bundle on Windows."""

    if not text or "\\" in text or text.startswith("/") or _DRIVE.match(text):
        raise BundleError(f"unsafe path: {text!r}")
    if ":" in text:
        raise BundleError(f"alternate data stream or drive syntax: {text!r}")
    # Check the raw segments: PurePosixPath would silently normalize "./a" and "a//b".
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BundleError(f"unsafe path segment: {text!r}")
    for part in parts:
        if part.endswith((" ", ".")) or part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise BundleError(f"windows-invalid path segment: {text!r}")
    return text


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(version: str, files: dict[str, Path]) -> bytes:
    """Return canonical manifest bytes for ``files`` (relative path -> source file)."""

    seen: dict[str, str] = {}
    entries = []
    for rel in sorted(files):
        validate_relative_path(rel)
        key = rel.lower()
        if key in seen:
            raise BundleError(f"duplicate or case-conflicting path: {rel!r} vs {seen[key]!r}")
        seen[key] = rel
        source = files[rel]
        entries.append({"path": rel, "size": source.stat().st_size, "sha256": sha256_file(source)})
    document = {"schema": MANIFEST_SCHEMA, "version": version, "files": entries}
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def anchor_for(manifest_bytes: bytes) -> str:
    return sha256_bytes(manifest_bytes)
