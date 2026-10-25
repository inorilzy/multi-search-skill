"""Verify every release build input against hashes locked in the repository.

The bundle trust anchor only proves "installed files == built files"; it says nothing about whether
the built files were trustworthy. This module closes that gap before anything is copied into a
bundle:

* the CPython tree is accepted only as the official archive whose SHA-256 is locked in
  ``scripts/build-inputs.lock.json`` for the requested target; the archive is hashed, then
  extracted into a fresh directory (a Windows ``.zip`` or a macOS ``.tar.gz``);
* the project wheel must match the SHA-256 recorded for it in the same pipeline (``--wheel-sha256``
  from the step that built it), so a swapped ``dist/`` file is refused;
* the launcher compiler must be the pinned ``rustc`` (``rust-toolchain.toml``).

Archive extraction never trusts member metadata blindly: absolute paths, ``..`` escapes, device
nodes, hard links and external links are refused before a single byte is written, and symbolic links
inside the archive are allowed only when they resolve to another internal archive member — they are
then materialised as regular files so the bundle contains no links for the installer to reject.

Third-party Python dependencies stay under ``--require-hashes`` in ``cli-bundle-requirements.txt``.
The xkit-py input is verified by its author separately and is out of scope here.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
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
    targets = lock.get("targets")
    if isinstance(targets, dict):
        if not targets or any(not isinstance(t, dict) for t in targets.values()):
            raise BuildInputError("build input lock has malformed targets")
        for name, target in targets.items():
            _checked_target(name, target, f"targets.{name}")
        return lock
    python = lock.get("python")
    if not isinstance(python, dict) or not isinstance(python.get("archive"), str):
        raise BuildInputError("build input lock lacks python archive pins")
    _checked_sha256(python.get("sha256"), "python.sha256")
    lock["targets"] = {"windows": {"python": python, "rust_target": "x86_64-pc-windows-msvc"}}
    return lock


def _checked_strip_symlinks(value: object, what: str) -> list[str]:
    """Validate the optional per-target list of archive symlinks to drop instead of materialise.

    ``python-build-standalone`` ships convenience aliases (``bin/python`` -> ``bin/python3`` ->
    ``bin/python3.12``); materialising them copies the 18 MB interpreter three times. The policy
    lives in the lock's per-target table so Windows, whose archive has no such links, is unchanged.
    """
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BuildInputError(f"{what} must be a list of archive-relative link paths")
    for item in value:
        member = PurePosixPath(item)
        if (not item or member.is_absolute() or ".." in member.parts or "." in member.parts
                or ":" in item or "\\" in item):
            raise BuildInputError(f"{what} contains an unsafe link path: {item!r}")
    return list(value)


def _checked_target(name: str, target: dict, what: str) -> None:
    if not isinstance(name, str) or not name:
        raise BuildInputError("build input lock target names must be non-empty strings")
    python = target.get("python")
    if not isinstance(python, dict) or not isinstance(python.get("archive"), str):
        raise BuildInputError(f"{what} lacks python.archive")
    _checked_sha256(python.get("sha256"), f"{what}.python.sha256")
    if not isinstance(python.get("url"), str) or not python["url"].startswith("https://"):
        raise BuildInputError(f"{what}.python.url must be an https URL")
    if not isinstance(target.get("rust_target"), str) or not target["rust_target"]:
        raise BuildInputError(f"{what} lacks rust_target")
    _checked_strip_symlinks(target.get("strip_symlinks", []), f"{what}.strip_symlinks")


def lock_target(lock: dict, target: str) -> dict:
    """Return the locked target entry for ``target`` (archive name, sha256, rust_target, ...)."""
    entry = lock.get("targets", {}).get(target)
    if entry is None:
        known = ", ".join(sorted(lock.get("targets", {}))) or "none"
        raise BuildInputError(f"build input lock has no target {target!r} (known: {known})")
    _checked_target(target, entry, f"targets.{target}")
    return entry


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
    if any(part == "" for part in member.parts):
        raise BuildInputError(f"python archive contains an unsafe path: {name!r}")
    return member


def _extract_zip_python(archive: Path, dest: Path) -> None:
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


def _tar_member_path(name: str) -> Path:
    """Validate one tar member name and return its path relative to the archive root.

    Names may carry a single leading ``./`` component (as python-build-standalone uses); every
    member must be a plain relative path with no drive, colon or ``..`` segment.
    """
    member = _safe_member(name)
    parts = member.parts
    if parts and parts[0] == ".":
        parts = parts[1:]
    if not parts:
        raise BuildInputError(f"python archive contains an empty member path: {name!r}")
    return Path(*parts)


def _tar_link_target(linkname: str, member_path: Path) -> Path:
    """Resolve a tar member's link target against the archive itself; external links are refused."""
    target = PurePosixPath(linkname)
    if target.is_absolute():
        raise BuildInputError(f"python archive contains an absolute link: {linkname!r}")
    if ":" in linkname or "\\" in linkname:
        raise BuildInputError(f"python archive contains an unsafe link: {linkname!r}")
    # The link target is interpreted relative to the directory holding the member.
    resolved = (PurePosixPath(member_path.parent.as_posix()) / target) if linkname else target
    parts: list[str] = []
    for part in resolved.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise BuildInputError(f"python archive link escapes the runtime: {linkname!r}")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise BuildInputError(f"python archive contains an empty link target: {linkname!r}")
    return Path(*parts)


def _extract_tar_python(archive: Path, dest: Path, drop_symlinks: list[str] | None = None) -> None:
    """Safely extract a ``.tar.gz`` python-build-standalone tree into ``dest``.

    Everything is validated before a single file is written: paths stay inside the archive,
    no devices/FIFOs/absolute names, hard links are refused, and symbolic links must resolve to
    another regular member of the same archive — they are then materialised as regular files
    (the destination never gains a link). ``drop_symlinks`` names archive-relative aliases that
    are skipped entirely instead of being materialised (see ``_checked_strip_symlinks``).
    Permission bits from the archive are preserved, which keeps ``bin/python3.12`` and friends
    executable without ever chmod'ing by name.
    """
    dropped = set(drop_symlinks or [])
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            plan: dict[Path, tarfile.TarInfo] = {}
            symlinks: dict[Path, Path] = {}
            for member in members:
                path = _tar_member_path(member.name)
                if member.isfile() or member.isdir():
                    plan[path] = member
                elif member.issym():
                    symlinks[path] = _tar_link_target(member.linkname, path)
                elif member.islnk():
                    raise BuildInputError(
                        f"python archive contains a hard link: {member.name!r} -> {member.linkname!r}"
                    )
                else:
                    raise BuildInputError(
                        f"python archive contains a special member: {member.name!r}"
                    )
            # python-build-standalone ships every member under a single top-level
            # directory (``python/``); strip that common root so the runtime lands
            # directly under ``dest``.
            roots = {path.parts[0] for path in list(plan) + list(symlinks)}
            if len(roots) == 1:
                root = roots.pop()
                if len(plan) + len(symlinks) > 1 and all(
                        len(path.parts) > 1 for path in symlinks):
                    plan = {Path(*p.parts[1:]): m for p, m in plan.items() if len(p.parts) > 1}
                    symlinks = {Path(*p.parts[1:]): t for p, t in symlinks.items()}
                    symlinks = {p: Path(*t.parts[1:]) if t.parts[:1] == (root,) else t
                                for p, t in symlinks.items()}
            for link_path, target in symlinks.items():
                if link_path.as_posix() in dropped:
                    continue
                seen = {link_path}
                while target in symlinks:
                    if target in seen:
                        raise BuildInputError(
                            f"python archive contains a symlink cycle at {link_path!s}"
                        )
                    seen.add(target)
                    target = symlinks[target]
                source = plan.get(target)
                if source is None or not source.isfile():
                    raise BuildInputError(
                        f"python archive symlink escapes the archive: {link_path!s} -> {target!s}"
                    )
                plan[link_path] = source  # materialise the resolved file under the link name
            for path in sorted(plan):
                member = plan[path]
                target = dest / path
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise BuildInputError(f"python archive member unreadable: {member.name!r}")
                with extracted, target.open("wb") as out:
                    shutil.copyfileobj(extracted, out)
                target.chmod(member.mode & 0o777)
    except tarfile.TarError as error:
        raise BuildInputError(f"python archive is not a valid tar.gz: {error}") from None


def extract_python(archive: Path, dest: Path, lock: dict, target: str = "windows") -> Path:
    """Verify the locked CPython archive, then extract it into ``dest`` (which must not exist).

    An arbitrary pre-existing directory is never accepted as the runtime: only bytes that hash to
    the locked value become the bundle's Python. ``target`` selects which locked archive is
    required (``windows``: the python.org embeddable zip; ``macos``: the python-build-standalone
    install_only tar.gz). A target may also name archive symlinks to drop (``strip_symlinks``),
    such as the macOS ``bin/python``/``bin/python3`` aliases that would triple the interpreter.
    """
    spec = lock_target(lock, target)
    python = spec["python"]
    if archive.name != python["archive"]:
        raise BuildInputError(f"python archive must be {python['archive']}, got {archive.name}")
    verify_file(archive, python["sha256"], f"{target} python archive")
    if dest.exists():
        raise BuildInputError(f"python extraction target already exists: {dest}")
    dest.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        _extract_zip_python(archive, dest)
        expected = dest / "python.exe"
        configure_embedded_path(dest)
    else:
        _extract_tar_python(archive, dest, drop_symlinks=spec.get("strip_symlinks", []))
        expected = dest / "bin" / "python3.12"
    if not expected.is_file():
        raise BuildInputError(f"python archive does not contain {expected.name} at its expected location")
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
