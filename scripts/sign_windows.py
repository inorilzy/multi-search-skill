"""Authenticode-sign Windows release binaries; the certificate comes from CI secrets.

Used for the bundled CLI launcher (scripts/build_cli_release.py) and, through Tauri's
``bundle.windows.signCommand``, for the desktop executable and the NSIS installer.

Configuration (environment, normally CI secrets):
  WINDOWS_SIGN_CERT_BASE64    base64 of a PFX/PKCS#12 code-signing certificate
  WINDOWS_SIGN_CERT_PASSWORD  its password (optional)
  WINDOWS_SIGN_TIMESTAMP_URL  RFC 3161 timestamp server (default: DigiCert)
  WINDOWS_SIGN_REQUIRED=1     fail when no certificate is configured (release CI sets it)

The certificate is written only to a fresh file inside a private, randomly named temporary
directory (``mkdtemp``, mode 0700) and is deleted afterwards. Limitation: signtool accepts a PFX
password only on its command line (``/p``), so the password is visible in the process list while
signtool runs; CI runners are single-tenant. It is never printed: failures report only the exit
code, never signtool's output or argv.

Usage as a Tauri signCommand: ``python scripts/sign_windows.py <file>`` (Tauri passes the path).
"""
from __future__ import annotations

import base64
import binascii
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"
CERT_ENV = "WINDOWS_SIGN_CERT_BASE64"
PASSWORD_ENV = "WINDOWS_SIGN_CERT_PASSWORD"
TIMESTAMP_ENV = "WINDOWS_SIGN_TIMESTAMP_URL"
REQUIRED_ENV = "WINDOWS_SIGN_REQUIRED"


class SigningError(RuntimeError):
    """Raised when a required signature cannot be produced."""


def _signtool() -> str:
    tool = shutil.which("signtool") or shutil.which("signtool.exe")
    if not tool:
        raise SigningError("signtool.exe not found; install the Windows SDK signing tools")
    return tool


def sign_file(path: Path, *, required: bool = False, environ=None, runner=subprocess.run,
              signtool=None) -> bool:
    """Sign ``path`` in place. Returns False (unsigned) only when signing is optional and no
    certificate is configured; any configured-but-failing signature raises."""
    environ = os.environ if environ is None else environ
    required = required or environ.get(REQUIRED_ENV) == "1"
    encoded = environ.get(CERT_ENV, "").strip()
    if not encoded:
        if required:
            raise SigningError(f"signing is required but {CERT_ENV} is not set")
        print(f"warning: {CERT_ENV} not set; {path.name} is left unsigned", file=sys.stderr)
        return False
    if not path.is_file():
        raise SigningError(f"file to sign is missing: {path}")
    try:
        certificate = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise SigningError(f"{CERT_ENV} is not valid base64") from None
    tool = signtool or _signtool()
    timestamp = environ.get(TIMESTAMP_ENV) or DEFAULT_TIMESTAMP_URL
    # mkdtemp creates a 0700 directory with a random name; the PFX is created exclusively inside it.
    private = Path(tempfile.mkdtemp(prefix="ms-sign-"))
    try:
        pfx = private / "cert.pfx"
        with open(pfx, "xb") as handle:
            handle.write(certificate)
        command = [tool, "sign", "/fd", "sha256", "/tr", timestamp, "/td", "sha256", "/f", str(pfx)]
        password = environ.get(PASSWORD_ENV)
        if password:
            command += ["/p", password]
        command.append(str(path))
        result = runner(command, capture_output=True, text=True)
        if result.returncode != 0:
            # Never echo signtool output or argv: either could include the password.
            raise SigningError(f"signtool failed for {path.name} (exit {result.returncode})")
        verify = runner([tool, "verify", "/pa", str(path)], capture_output=True, text=True)
        if verify.returncode != 0:
            raise SigningError(f"signature verification failed for {path.name} (exit {verify.returncode})")
    finally:
        shutil.rmtree(private, ignore_errors=True)
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: sign_windows.py <file>", file=sys.stderr)
        return 2
    try:
        sign_file(Path(args[0]))
    except SigningError as error:
        print(f"signing refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
