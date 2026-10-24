"""Verify every release build input against hashes locked in the repository.

The bundle trust anchor only proves "installed files == built files"; it says nothing about whether
the built files were trustworthy. This module closes that gap before anything is copied into a
bundle:

* the Windows CPython tree is accepted only as the official archive whose SHA-256 is locked in
  ``scripts/build-inputs.lock.json``; the archive is hashed, then extracted into a fresh directory;
* the project wheel must match the SHA-256 recorded for it in the same pipeline (``--wheel-sha256``
  from the step that built it), so a swapped ``dist/`` file is refused;
* the launcher compiler must be the pinned ``rustc`` (``rust-toolchain.toml``).

Third-party Python dependencies stay under ``--require-hashes`` in ``cli-bundle-requirements.txt``.
The xkit-py input is verified by its author separately and is out of scope here.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO = SCRIPTS_DIR.parent
LOCK_FILE = SCRIPTS_DIR / "build-inputs.lock.json"
TOOLCHAIN_FILE = REPO / "rust-toolchain.toml"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BuildInputError(ValueError):
    """Raised when a build input is missing, unpinned or does not match its locked hash."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_sha256(value: object, what: str) -> str:
    if not isinstance(value, str) or not _SHA256.match(value):
        raise BuildInputError(f"{what} must be a lowercase 64-hex SHA-256")
    return value


def load_lock(path: Path = LOCK_FILE) -> dict:
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BuildInputError(f"build input lock unreadable: {path}: {error}") from None
    if not isinstance(lock, dict) or lock.get("schema") != 1:
        raise BuildInputError("build input lock must be a schema 1 JSON object")
    python = lock.get("python")
    if not isinstance(python, dict) or not isinstance(python.get("archive"), str):
        raise BuildInputError("build input lock lacks python.archive")
    _checked_sha256(python.get("sha256"), "python.sha256")
    return lock


def verify_file(path: Path, expected: str, what: str) -> str:
    """Hash ``path`` and require it to equal ``expected``. Returns the digest."""
    expected = _checked_sha256(expected, f"expected SHA-256 for {what}")
    if not path.is_file():
        raise BuildInputError(f"{what} missing: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise BuildInputError(f"{what} SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def _safe_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts or ":" in name or "\\" in name:
        raise BuildInputError(f"python archive contains an unsafe path: {name!r}")
    return member


def extract_python(archive: Path, dest: Path, lock: dict) -> Path:
    """Verify the locked CPython archive, then extract it into ``dest`` (which must not exist).

    An arbitrary pre-existing directory is never accepted as the runtime: only bytes that hash to
    the locked value become the bundle's Python.
    """
    python = lock["python"]
    if archive.name != python["archive"]:
        raise BuildInputError(f"python archive must be {python['archive']}, got {archive.name}")
    verify_file(archive, python["sha256"], "python archive")
    if dest.exists():
        raise BuildInputError(f"python extraction target already exists: {dest}")
    dest.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                _safe_member(info.filename)
                # Symlinks inside the archive are refused: only regular files and directories.
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise BuildInputError(f"python archive contains a symlink: {info.filename!r}")
            bundle.extractall(dest)
    except zipfile.BadZipFile as error:
        raise BuildInputError(f"python archive is not a valid zip: {error}") from None
    if not (dest / "python.exe").is_file():
        raise BuildInputError("python archive does not contain python.exe at its root")
    configure_embedded_path(dest)
    return dest


def configure_embedded_path(runtime: Path) -> Path:
    """Point the embeddable runtime's ``._pth`` file at the bundle's own site-packages.

    The official embeddable distribution ignores ``PYTHONPATH`` and the registry and reads its
    module search path only from ``pythonXY._pth``. That file lists the stdlib zip and the runtime
    root; the bundle installs dependencies into ``Lib/site-packages``, so that entry is added. The
    path stays explicit and relative to the runtime, and ``import site`` stays disabled.
    """
    pth_files = sorted(runtime.glob("python3*._pth"))
    if len(pth_files) != 1:
        raise BuildInputError("python runtime must contain exactly one pythonXY._pth file")
    pth = pth_files[0]
    lines = [line.strip() for line in pth.read_text(encoding="utf-8").splitlines()]
    entries = [line for line in lines if line and not line.startswith("#")]
    if any(entry == "import site" for entry in entries):
        raise BuildInputError("python runtime ._pth must not enable import site")
    if "Lib\\site-packages" not in entries:
        entries.append("Lib\\site-packages")
    pth.write_text("\n".join(entries) + "\n", encoding="utf-8")
    (runtime / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    return pth


def pinned_rustc_version(toolchain: Path = TOOLCHAIN_FILE) -> str:
    try:
        text = toolchain.read_text(encoding="utf-8")
    except OSError as error:
        raise BuildInputError(f"rust toolchain pin unreadable: {toolchain}: {error}") from None
    match = re.search(r'^\s*channel\s*=\s*"(\d+\.\d+\.\d+)"\s*$', text, re.MULTILINE)
    if not match:
        raise BuildInputError("rust-toolchain.toml must pin an exact channel such as \"1.99.1\"")
    return match.group(1)


def check_rustc(expected: str | None = None, runner=subprocess.run) -> str:
    """Require ``rustc --version`` to report the pinned version; return it."""
    expected = expected or pinned_rustc_version()
    try:
        result = runner(["rustc", "--version"], capture_output=True, text=True, cwd=REPO)
    except OSError as error:
        raise BuildInputError(f"rustc is not available: {error}") from None
    output = (result.stdout or "").strip()
    match = re.match(r"^rustc (\d+\.\d+\.\d+)(?:\s|$)", output)
    if result.returncode != 0 or not match:
        raise BuildInputError(f"rustc --version failed: {output or (result.stderr or '').strip()}")
    if match.group(1) != expected:
        raise BuildInputError(f"rustc {match.group(1)} does not match the pinned toolchain {expected}")
    return match.group(1)
