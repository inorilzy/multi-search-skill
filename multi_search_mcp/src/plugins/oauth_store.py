"""Owner-only atomic storage for OAuth client and account records.

The file lives beside ``keys.json`` (``~/.multi-search/oauth.json``) and is
separate because OAuth records carry rotating refresh tokens that the keys
loader must never treat as search keys. A corrupt file is never overwritten:
callers must repair or remove it explicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

OAUTH_DIR_NAME = ".multi-search"
OAUTH_FILE_NAME = "oauth.json"
OAUTH_FILE_MODE = 0o600

# Client registration and account tokens are separate entries so a logout of
# the account (``parallel_account``) keeps the cached OAuth client id.
PARALLEL_CLIENT_ENTRY = "parallel"
PARALLEL_ACCOUNT_ENTRY = "parallel_account"


class OAuthStoreError(ValueError):
    """Raised when oauth.json exists but cannot be parsed safely.

    The message contains only the path, never the file body, because the body
    stores plaintext tokens.
    """


def default_oauth_file() -> Path:
    return Path.home() / OAUTH_DIR_NAME / OAUTH_FILE_NAME


def _resolve(path: str | Path | None) -> Path:
    return Path(path).expanduser() if path else default_oauth_file()


def read_oauth_file(path: str | Path | None = None) -> dict[str, Any]:
    """Return the parsed object; a missing file is an empty object."""
    target = _resolve(path)
    if not target.exists():
        return {}
    try:
        text = target.read_text(encoding="utf-8-sig")
    except OSError:
        raise OAuthStoreError(f"oauth file cannot be read: {target}") from None
    try:
        data = json.loads(text)
    except Exception:
        raise OAuthStoreError(f"oauth file is not valid JSON: {target}") from None
    if not isinstance(data, dict):
        raise OAuthStoreError(f"oauth file is not a JSON object: {target}")
    return data


def write_oauth_file_atomic(path: str | Path | None, data: dict[str, Any]) -> None:
    """Replace oauth.json atomically, created owner-only on POSIX.

    The temporary sibling is fsynced and renamed over the target, so a crash
    leaves either the previous complete file or the new complete file. On POSIX
    the temporary is chmod 0600 before the rename, so plaintext tokens are
    never briefly readable by other users and the mode survives replacement.
    """
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temporary, OAUTH_FILE_MODE)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def get_entry(entry: str, path: str | Path | None = None) -> dict[str, Any] | None:
    """Return one entry object, or None when absent or malformed."""
    value = read_oauth_file(path).get(entry)
    return value if isinstance(value, dict) else None


def set_entry(entry: str, value: dict[str, Any], path: str | Path | None = None) -> None:
    """Replace one entry while leaving every other top-level entry untouched."""
    data = read_oauth_file(path)
    data[entry] = value
    write_oauth_file_atomic(path, data)


def delete_entry(entry: str, path: str | Path | None = None) -> bool:
    """Delete one entry; missing files or entries are not an error."""
    data = read_oauth_file(path)
    if entry not in data:
        return False
    del data[entry]
    write_oauth_file_atomic(path, data)
    return True


def get_client_id(provider: str, path: str | Path | None = None) -> str:
    """Return the cached OAuth client id registered for one provider."""
    value = read_oauth_file(path).get(provider)
    if not isinstance(value, dict):
        return ""
    client_id = value.get("client_id")
    return client_id if isinstance(client_id, str) else ""


def set_client_id(provider: str, client_id: str, path: str | Path | None = None) -> None:
    set_entry(provider, {"client_id": client_id}, path)


def balance_credential_ref(entry: str, record: dict[str, Any]) -> str:
    """A stable, non-secret stand-in for one browser login's balance credential.

    The access token is replaced on every refresh, so anything keyed by its
    fingerprint (balance cache, balance history, account ownership) would lose
    track after ten minutes. ``login_id`` is created once per login and kept by
    refreshes; records saved before it existed share one per-entry reference.
    """
    login_id = record.get("login_id")
    return f"oauth-login:{entry}:{login_id if isinstance(login_id, str) and login_id else 'legacy'}"


def balance_credentials(path: str | Path | None = None) -> dict[str, str]:
    """Stable references for logged-in balance credentials, keyed by credential entry.

    Account tokens and browser-session records contribute references; cached
    client registrations are ignored. Callers never receive the secret itself:
    the balance adapter reads the record directly.
    """
    credentials: dict[str, str] = {}
    for entry, value in read_oauth_file(path).items():
        if not isinstance(value, dict):
            continue
        tokens = (value.get("access_token"), value.get("cookie_header"))
        if any(isinstance(token, str) and token for token in tokens):
            credentials[entry] = balance_credential_ref(entry, value)
    # An explicit file argument is a file-only read (account operations rely on
    # this). The process override never becomes a search key or a stored token.
    if path is None:
        for env, entry in (("EXA_DASHBOARD_COOKIE", "exa_admin"), ("BRAVE_DASHBOARD_COOKIE", "brave_dashboard")):
            cookie = os.environ.get(env)
            if cookie:
                login_id = hashlib.sha256(cookie.encode()).hexdigest()[:16]
                credentials[entry] = balance_credential_ref(entry, {"login_id": login_id})
    return credentials


def secret_values(path: str | Path | None = None) -> list[str]:
    """Every token-like string stored in the file, for redaction of messages."""
    secret_keys = {
        "access_token", "refresh_token", "client_id", "token", "token_secret",
        "client_secret", "device_code", "cookie_header",
    }
    values: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in secret_keys and isinstance(item, str) and len(item) >= 4:
                    values.append(item)
                    if key == "cookie_header":
                        values.extend(part.partition("=")[2].strip() for part in item.split(";")
                                      if len(part.partition("=")[2].strip()) >= 4)
                elif isinstance(item, (dict, list, tuple)):
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(read_oauth_file(path))
    if path is None:
        for name in ("BRAVE_DASHBOARD_COOKIE", "EXA_DASHBOARD_COOKIE"):
            visit({"cookie_header": os.environ.get(name)})
    return list(dict.fromkeys(values))
