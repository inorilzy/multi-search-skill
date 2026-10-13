"""Windows Credential Manager access for single-secret search providers.

Each provider secret is one generic credential named ``<namespace>/<provider>``.
The credential blob is UTF-8 JSON ``{"v": 1, "key": <secret>, "saved_at": <unix seconds>}``.
The Tauri desktop writes the same format (``desktop/src-tauri/src/credential.rs``);
change both together.

Errors never include secret material. Store failures raise ``CredentialStoreError``
and callers must surface them; there is no plaintext fallback.
"""
from __future__ import annotations

import json
import os
import sys
import time
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
    key: str
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


class CredentialStore:
    """Single-secret store keyed by provider name, over a pluggable backend."""

    def __init__(self, backend: CredentialBackend, namespace: str = DEFAULT_NAMESPACE) -> None:
        self._backend = backend
        self.namespace = namespace or DEFAULT_NAMESPACE

    def target(self, provider: str) -> str:
        return f"{self.namespace}/{provider}"

    def get_record(self, provider: str) -> StoredKey | None:
        blob = self._backend.read(self.target(provider))
        if blob is None:
            return None
        try:
            data = json.loads(blob.decode("utf-8"))
            key = data["key"]
            saved_at = float(data["saved_at"])
            if data.get("v") != BLOB_VERSION or not isinstance(key, str) or not key:
                raise ValueError
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            # Do not echo the entry contents; the entry is unusable as stored.
            raise CredentialStoreError(f"stored credential for {provider} is unreadable") from None
        return StoredKey(key=key, saved_at=saved_at)

    def get(self, provider: str) -> str | None:
        record = self.get_record(provider)
        return record.key if record else None

    def set(self, provider: str, key: str, *, saved_at: float | None = None) -> float:
        value = validate_key(key)
        stamp = time.time() if saved_at is None else float(saved_at)
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
    return CredentialStore(WindowsCredentialBackend(), credential_namespace(environ))
