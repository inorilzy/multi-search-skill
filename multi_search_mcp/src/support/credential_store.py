"""Shared SQLite configuration with current-user Windows DPAPI credentials.

Legacy Credential Manager access is retained only for explicit import. The default
store never reads it. Backend seams allow isolated tests; production never falls
back to plaintext when encryption, initialization, or a transaction fails.
"""
from __future__ import annotations

import json
import os
import sys
import time
import math
import sqlite3
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Protocol


NAMESPACE_ENV = "MULTI_SEARCH_CREDENTIAL_NAMESPACE"
DEFAULT_NAMESPACE = "multi-search"
BLOB_VERSION = 1
MAX_KEY_LENGTH = 1024

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
ERROR_ACCESS_DENIED = 5


class CredentialStoreError(RuntimeError):
    """The credential store is unavailable, denied, or holds an unreadable entry."""


@dataclass(frozen=True)
class StoredKey:
    key: Any
    saved_at: float


class CredentialBackend(Protocol):
    def read(self, target: str) -> bytes | None: ...
    def write(self, target: str, blob: bytes) -> None: ...
    def delete(self, target: str) -> bool: ...


def _store_error(code: int) -> CredentialStoreError:
    if code == ERROR_ACCESS_DENIED:
        return CredentialStoreError("credential store access denied")
    return CredentialStoreError(f"credential store unavailable (Windows error {code})")


def _windows_api() -> tuple[Any, Any, Any]:
    """Build ctypes bindings lazily so importing this module never touches Windows APIs."""
    import ctypes
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, CREDENTIALW, advapi32


class WindowsCredentialBackend:
    """Reads and writes the current user's Windows Credential Manager."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise CredentialStoreError("Windows Credential Manager is only available on Windows")

    def read(self, target: str) -> bytes | None:
        ctypes, CREDENTIALW, advapi32 = _windows_api()
        pointer = ctypes.POINTER(CREDENTIALW)()
        if not advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == ERROR_NOT_FOUND:
                return None
            raise _store_error(code)
        try:
            cred = pointer.contents
            if cred.CredentialBlobSize == 0:
                return b""
            return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            advapi32.CredFree(pointer)

    def write(self, target: str, blob: bytes) -> None:
        ctypes, CREDENTIALW, advapi32 = _windows_api()
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIALW()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        if not advapi32.CredWriteW(ctypes.byref(cred), 0):
            raise _store_error(ctypes.get_last_error())

    def delete(self, target: str) -> bool:
        ctypes, _CREDENTIALW, advapi32 = _windows_api()
        if advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return True
        code = ctypes.get_last_error()
        if code == ERROR_NOT_FOUND:
            return False
        raise _store_error(code)


def validate_key(key: object) -> str:
    """Return the trimmed key or raise a message that never echoes the value."""
    if not isinstance(key, str):
        raise ValueError("key must be a single-line string")
    text = key.strip()
    if not text or len(text) > MAX_KEY_LENGTH or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"key must be 1-{MAX_KEY_LENGTH} characters with no control characters")
    return text


CONFIG_DB_ENV = "MULTI_SEARCH_CONFIG_DB"
SCHEMA_VERSION = 1
PROVIDERS = ("baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github", "jina", "twitter_cookies")


def config_db_path(environ=None) -> Path:
    env = os.environ if environ is None else environ
    selected = env.get(CONFIG_DB_ENV)
    if selected:
        # Match desktop PathBuf semantics: this selector is a literal path, not
        # shell input; '~' and environment variables are not expanded.
        return Path(selected)
    # Respect the same explicit home order as the desktop process.
    home = env.get("USERPROFILE") or env.get("HOME")
    return (Path(home) if home else Path.home()) / ".multi-search" / "config.sqlite"


def validate_twitter_cookies(value: Any) -> dict:
    """Validate the desktop's independent cookie-map secret, never echo values."""
    if not isinstance(value, dict) or not 1 <= len(value) <= 128:
        raise ValueError("invalid managed Twitter cookie map")
    for name, item in value.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", name)
                or not isinstance(item, str) or not item
                or any(unicodedata.category(ch) == "Cc" for ch in item)):
            raise ValueError("invalid managed Twitter cookie entry")
        try:
            if len(item.encode("utf-8")) > 4096:
                raise ValueError("managed Twitter cookie value exceeds limit")
        except UnicodeError:
            raise ValueError("invalid managed Twitter cookie encoding") from None
    if not value.get("auth_token", "").strip() or not value.get("ct0", "").strip():
        raise ValueError("managed Twitter cookies require auth_token and ct0")
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 65536:
        raise ValueError("managed Twitter cookie map exceeds limit")
    return dict(value)


def validate_value(provider: str, value: Any) -> Any:
    """Keep single/list/Jina JSON shapes, validating each key without echoing it."""
    if provider == "twitter_cookies":
        return validate_twitter_cookies(value)
    if isinstance(value, str):
        return validate_key(value)
    if isinstance(value, list) and value and all(isinstance(item, str) or (provider == "jina" and isinstance(item, dict)) for item in value):
        return [validate_value(provider, item) for item in value]
    if provider == "jina" and isinstance(value, dict) and "key" in value:
        result = dict(value)
        result["key"] = validate_key(value["key"])
        if "exhausted" in value and not isinstance(value["exhausted"], bool):
            raise ValueError("Jina exhausted requires a boolean")
        # Ensure extra legacy metadata remains JSON, not a Python-only object.
        try:
            json.dumps(result, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("Jina entry must contain JSON values") from None
        return result
    raise ValueError("credential requires a key string, nonempty key list, or Jina entry")


class WindowsDPAPI:
    """Current-user protection, no optional entropy and no interactive UI."""

    def _crypt(self, value: bytes, *, decrypt: bool) -> bytes:
        if sys.platform != "win32":
            raise CredentialStoreError("Windows DPAPI is only available on Windows")
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        dll = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        source = DATA_BLOB(len(value), buffer)
        target = DATA_BLOB()
        fn = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
        fn.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        fn.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise CredentialStoreError("DPAPI decryption failed" if decrypt else "DPAPI encryption failed")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            kernel.LocalFree(target.pbData)

    def encrypt(self, value: bytes) -> bytes:
        return self._crypt(value, decrypt=False)

    def decrypt(self, value: bytes) -> bytes:
        return self._crypt(value, decrypt=True)


class ConfigDatabase:
    """Read/write a desktop-owned ``config.sqlite``.

    The desktop owns schema creation and migration. This class only validates
    the on-disk schema version and column layout; it never creates tables and
    never upgrades a version. A missing database reads as empty settings, and
    an unversioned or future-versioned database raises an explicit error that
    points the user at the desktop application instead of silently building a
    second schema.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else config_db_path()

    @contextmanager
    def connect(self):
        if not self.path.exists():
            yield None
            return
        conn = None
        try:
            conn = sqlite3.connect(str(self.path), timeout=5)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise CredentialStoreError(
                    "configuration database schema version "
                    f"{version} is not supported by this CLI (expected {SCHEMA_VERSION}); "
                    "the desktop application owns schema creation and migration"
                )
            expected = {"credentials": [("provider", "TEXT", 0, 1), ("encrypted_value", "BLOB", 1, 0), ("saved_at", "REAL", 1, 0)],
                        "settings": [("id", "INTEGER", 0, 1), ("data", "TEXT", 1, 0)]}
            for table, columns in expected.items():
                actual = [(r[1], r[2].upper(), r[3], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")]
                if actual != columns:
                    raise CredentialStoreError("configuration database schema is invalid")
            yield conn
            conn.commit()
        except CredentialStoreError:
            if conn is not None:
                conn.rollback()
            raise
        except (sqlite3.Error, OSError):
            if conn is not None:
                conn.rollback()
            raise CredentialStoreError("configuration database operation failed") from None
        finally:
            if conn is not None:
                conn.close()

    def read_settings(self) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT data FROM settings WHERE id=1").fetchone() if conn else None
        if not row:
            return {}
        try:
            data = json.loads(row[0])
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (TypeError, ValueError):
            raise CredentialStoreError("stored settings are unreadable") from None

    def write_settings(self, data: dict) -> None:
        try:
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raise CredentialStoreError("settings must contain JSON values") from None
        with self.connect() as conn:
            if conn is None:
                # No database means the desktop has not created one yet. Creating
                # it here would make the CLI a second schema owner, so fail with
                # an actionable message instead.
                raise CredentialStoreError(
                    "configuration database is missing; open the desktop application "
                    "to create and migrate config.sqlite"
                )
            conn.execute("INSERT INTO settings(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (raw,))


class SQLiteCredentialBackend:
    def __init__(self, path=None, protector=None):
        self.database = ConfigDatabase(path)
        self.protector = protector or WindowsDPAPI()

    def read(self, target: str) -> bytes | None:
        provider = target.rsplit("/", 1)[-1]
        with self.database.connect() as conn:
            row = conn.execute("SELECT encrypted_value FROM credentials WHERE provider=?", (provider,)).fetchone() if conn else None
        if not row:
            return None
        try:
            return self.protector.decrypt(bytes(row[0]))
        except (ValueError, TypeError):
            raise CredentialStoreError("stored credential ciphertext is unreadable") from None

    def write(self, target: str, blob: bytes) -> None:
        provider = target.rsplit("/", 1)[-1]
        encrypted = self.protector.encrypt(blob)
        stamp = float(json.loads(blob)["saved_at"])
        with self.database.connect() as conn:
            if conn is None:
                raise CredentialStoreError(
                    "configuration database is missing; open the desktop application "
                    "to create and migrate config.sqlite"
                )
            conn.execute("INSERT INTO credentials(provider,encrypted_value,saved_at) VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET encrypted_value=excluded.encrypted_value,saved_at=excluded.saved_at", (provider, encrypted, stamp))

    def delete(self, target: str) -> bool:
        provider = target.rsplit("/", 1)[-1]
        with self.database.connect() as conn:
            return bool(conn.execute("DELETE FROM credentials WHERE provider=?", (provider,)).rowcount) if conn else False

    def import_batch(self, values: dict, settings: dict | None, check) -> None:
        """Lock, revalidate, and import the entire approved selection atomically."""
        with self.database.connect() as conn:
            if conn is None:
                raise CredentialStoreError(
                    "configuration database is missing; open the desktop application "
                    "to create and migrate config.sqlite"
                )
            conn.execute("BEGIN IMMEDIATE")
            check()
            stamp = time.time()
            for provider, value in values.items():
                raw = json.dumps({"v": 1, "key": validate_value(provider, value), "saved_at": stamp},
                                 separators=(",", ":")).encode("utf-8")
                encrypted = self.protector.encrypt(raw)
                conn.execute("INSERT INTO credentials(provider,encrypted_value,saved_at) VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET encrypted_value=excluded.encrypted_value,saved_at=excluded.saved_at", (provider, encrypted, stamp))
            if settings is not None:
                raw = json.dumps(settings, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                conn.execute("INSERT INTO settings(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (raw,))


class CredentialStore:
    """JSON-valued credentials over a pluggable backend; SQLite/DPAPI by default."""

    def __init__(self, backend: CredentialBackend, namespace: str = DEFAULT_NAMESPACE) -> None:
        self._backend = backend
        self.namespace = namespace or DEFAULT_NAMESPACE

    def target(self, provider: str) -> str:
        if provider not in PROVIDERS:
            raise ValueError("unsupported credential provider")
        return f"{self.namespace}/{provider}"

    def get_record(self, provider: str) -> StoredKey | None:
        blob = self._backend.read(self.target(provider))
        if blob is None:
            return None
        try:
            data = json.loads(blob.decode("utf-8"))
            key = data["key"]
            saved_at = float(data["saved_at"])
            if data.get("v") != BLOB_VERSION or not math.isfinite(saved_at):
                raise ValueError
            key = validate_value(provider, key)
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            # Do not echo the entry contents; the entry is unusable as stored.
            raise CredentialStoreError(f"stored credential for {provider} is unreadable") from None
        return StoredKey(key=key, saved_at=saved_at)

    def get(self, provider: str) -> Any:
        record = self.get_record(provider)
        return record.key if record else None

    def set(self, provider: str, key: Any, *, saved_at: float | None = None) -> float:
        value = validate_value(provider, key)
        stamp = time.time() if saved_at is None else float(saved_at)
        if not math.isfinite(stamp):
            raise ValueError("saved_at must be finite")
        blob = json.dumps(
            {"v": BLOB_VERSION, "key": value, "saved_at": stamp},
            separators=(",", ":"),
        ).encode("utf-8")
        self._backend.write(self.target(provider), blob)
        return stamp

    def delete(self, provider: str) -> bool:
        return self._backend.delete(self.target(provider))


def credential_namespace(environ: dict | os._Environ | None = None) -> str:
    environ = os.environ if environ is None else environ
    return environ.get(NAMESPACE_ENV) or DEFAULT_NAMESPACE


def default_store(environ: dict | os._Environ | None = None) -> CredentialStore:
    return CredentialStore(SQLiteCredentialBackend(config_db_path(environ)))


def legacy_store(environ=None) -> CredentialStore:
    """Explicit migration source only; callers must never write/delete this store."""
    return CredentialStore(WindowsCredentialBackend(), credential_namespace(environ))
