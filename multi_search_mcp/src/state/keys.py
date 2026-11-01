"""Load API keys from ~/.multi-search/keys.json + environment variables."""
import json
import os
import random
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


KEYS_FILE_MODE = 0o600


def write_keys_file_atomic(path: str | Path, data: dict) -> None:
    """Replace the keys file atomically, created with owner-only permissions.

    The new contents go to a sibling temporary file that is fsynced and then
    renamed over the target, so a crash or a failed write leaves either the old
    complete file or the new complete file. On POSIX the temporary file is 0600
    before the rename, so the plaintext secrets are never briefly world-readable
    and the mode survives the replacement.
    """
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temporary, KEYS_FILE_MODE)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def keys_file_permission_warning(path: str | Path) -> str | None:
    """Return a warning when a plaintext keys file is accessible by other users.

    Only meaningful on POSIX; Windows ACLs are not inspected. Returns ``None``
    when the file is absent, unreadable, or already owner-only.
    """
    if os.name != "posix":
        return None
    path = Path(path).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None
    if mode & 0o077:
        return (
            f"{path} is readable by other users (mode {mode:04o}); "
            f"it stores keys in plaintext. Run: chmod 600 {path}"
        )
    return None


class KeysError(ValueError):
    """Raised when the keys file exists but cannot be parsed safely.

    Carries only the file path, never the file contents, so a malformed keys
    file cannot leak secrets into a user-visible error.
    """


KEY_ENV_PAIRS = (
    ("BRAVE_SEARCH_API_KEY", "brave"),
    ("BRAVE_API_KEY", "brave"),
    ("PARALLEL_API_KEY", "parallel"),
    ("BAIDU_QIANFAN_API_KEY", "baidu"),
    ("QIANFAN_API_KEY", "baidu"),
    ("APPBUILDER_API_KEY", "baidu"),
    ("TAVILY_API_KEY", "tavily"),
    ("EXA_API_KEY", "exa"),
    ("JINA_API_KEY", "jina"),
    ("JINA_KEY", "jina"),
    ("GITHUB_TOKEN", "github"),
    ("GH_TOKEN", "github"),
    ("STACKEXCHANGE_KEY", "stackexchange"),
    ("FIRECRAWL_API_KEY", "firecrawl"),
    ("SERPAPI_API_KEY", "serpapi"),
    ("SERPAPI_KEY", "serpapi"),
    ("TWITTER_COOKIES_PATH", "twitter_cookies"),
)

KEY_ENV_NAMES = [env_name for env_name, _key_name in KEY_ENV_PAIRS]


def pick_key(value) -> str:
    """Return a single key string. If `value` is a list, pick one at random.

    Tolerates None / "" / str / list[str]. Empty lists or falsy values -> "".
    """
    if not value:
        return ""
    if isinstance(value, list):
        choices = [v for v in value if v]
        return random.choice(choices) if choices else ""
    return str(value)


def key_pool(value) -> list[str]:
    """Return a shuffled list of candidate keys for fallback retry."""
    if not value:
        return []
    if isinstance(value, list):
        choices = [str(v) for v in value if v]
    else:
        choices = [str(value)]
    random.shuffle(choices)
    return choices


def normalize_jina_config(value) -> list[dict]:
    """Normalize Jina config to list of {key, exhausted}.

    Supports: str, list[str], list[{key, exhausted}], single {key, exhausted}.
    """
    if not value:
        return []
    if isinstance(value, str):
        return [{"key": value, "exhausted": False}] if value else []
    if isinstance(value, dict):
        k = value.get("key", "")
        return [{"key": k, "exhausted": bool(value.get("exhausted"))}] if k else []
    if isinstance(value, list):
        out: list[dict] = []
        for item in value:
            if isinstance(item, str):
                if item:
                    out.append({"key": item, "exhausted": False})
            elif isinstance(item, dict):
                k = item.get("key", "")
                if k:
                    out.append({"key": k, "exhausted": bool(item.get("exhausted"))})
        return out
    return []


def jina_config_keys(value) -> list[str]:
    """Return configured Jina keys that are not statically disabled.

    Honors the config-level ``exhausted: true`` flag (a user/operator opt-out),
    but performs no shuffling and no runtime exhaustion bookkeeping. Live key
    health (cooldown / quota / invalid) is owned by ``SQLiteKeyManager`` so that
    Jina shares the same state-aware LRU rotation as the other providers.
    """
    return [e["key"] for e in normalize_jina_config(value) if not e["exhausted"]]


def count_jina_keys(value) -> tuple[int, int]:
    """Return ``(config_active, total)`` Jina key counts.

    Reflects only static config state. Runtime health lives in the key-state DB.
    """
    entries = normalize_jina_config(value)
    total = len(entries)
    active = sum(1 for e in entries if not e["exhausted"])
    return active, total


# Keyed providers whose API keys live in the keys file (and env overrides).
# The name is historical: the source catalog still publishes it as
# ``credential_store_providers`` so desktop consumers need no change.
# Twitter cookies are a separate reference (``twitter_cookies``) and are not
# listed here.
# Resolution order: environment variable > ~/.multi-search/keys.json.
# Environment variables always win so automation can override a saved key.
CREDENTIAL_STORE_PROVIDERS = (
    "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github", "jina",
    "stackexchange",
)

KEYS_DIR_NAME = ".multi-search"
KEYS_FILE_NAME = "keys.json"
# Pre-unification location, read only by the one-time copy in ``default_keys_file``.
LEGACY_KEYS_FILE_NAME = ".search-keys.json"
DISPLAY_KEYS_FILE = f"~/{KEYS_DIR_NAME}/{KEYS_FILE_NAME}"


def _copy_legacy_keys_file(legacy: Path, target: Path) -> None:
    """Copy the old keys file to the new path once, byte for byte.

    The copy goes to a 0600 sibling temporary file that is fsynced and then
    hard-linked into place, so a concurrent copier or a desktop write that
    lands first is never overwritten. The legacy file is only read.
    """
    if target.exists() or target.is_symlink() or not legacy.is_file():
        return
    try:
        payload = legacy.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
    except OSError:
        raise KeysError(f"could not copy legacy keys file {legacy} to {target}") from None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temporary, KEYS_FILE_MODE)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass  # someone else created the new file first; theirs wins
        except OSError:
            # Hard links unsupported on this filesystem: replace only if still absent.
            if not target.exists():
                os.replace(temporary, target)
    except OSError:
        raise KeysError(f"could not copy legacy keys file {legacy} to {target}") from None
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def default_keys_file() -> Path:
    """The keys file every reader and writer uses: ``~/.multi-search/keys.json``.

    ``~`` is ``Path.home()``: ``USERPROFILE`` on Windows, ``HOME`` elsewhere.
    When the file is missing and the legacy ``~/.search-keys.json`` exists, the
    legacy file is copied here once (0600, atomic); afterwards only this path is
    read. Raises :class:`KeysError` when that copy fails.
    """
    home = Path.home()
    path = home / KEYS_DIR_NAME / KEYS_FILE_NAME
    _copy_legacy_keys_file(home / LEGACY_KEYS_FILE_NAME, path)
    return path


def _resolve_keys_file(keys_file: str | Path | None) -> Path:
    return Path(keys_file).expanduser() if keys_file else default_keys_file()


@dataclass(frozen=True)
class KeyLoad:
    """Keys plus per-provider credential errors that kept a key out of rotation.

    With the keys file as the only stored source, ``errors`` is always empty;
    the field stays so the search pipeline's per-source error seam is stable.
    """

    keys: dict
    errors: dict[str, str]


class LoadedKeys(dict):
    """The key map returned by :func:`load_keys`, carrying per-provider errors.

    A plain ``dict`` everywhere it is used; ``errors`` is read by the search
    pipeline. Callers that copy with ``dict(keys)`` intentionally drop it.
    """

    def __init__(self, keys: dict, errors: dict[str, str]):
        super().__init__(keys)
        self.errors = dict(errors)


def _read_keys_file(keys_file: Path) -> dict:
    """Read the plaintext keys file. A whole-file parse failure is fatal."""
    if not keys_file.exists():
        return {}
    try:
        # utf-8-sig tolerates BOM (PowerShell 5.1 writes BOM by default)
        loaded = json.loads(keys_file.read_text(encoding="utf-8-sig"))
    except Exception:
        # Fail loudly instead of silently returning zero keys: a corrupt keys
        # file otherwise surfaces as every provider "missing key", hiding the
        # real cause. Reference only the path, never the (secret-bearing)
        # file contents or parser detail.
        raise KeysError(f"keys file is not valid JSON: {keys_file}") from None
    return loaded if isinstance(loaded, dict) else {}


def _source_rows(file_keys: dict, environ: Mapping[str, str]) -> dict[str, dict]:
    """The single effective-source decision shared by key loading and reporting.

    Order: environment > keys file.
    """
    report: dict[str, dict] = {}
    for provider in CREDENTIAL_STORE_PROVIDERS:
        env_names = [name for name, key_name in KEY_ENV_PAIRS if key_name == provider and environ.get(name)]
        if env_names:
            effective = "env"
        elif file_keys.get(provider):
            effective = "file"
        else:
            effective = "none"
        report[provider] = {
            "effective_source": effective,
            "env_vars_set": env_names,
            "file_present": bool(file_keys.get(provider)),
            # Count only, never values.
            "file_key_count": _file_key_count(file_keys.get(provider)),
        }
    return report


def _load_keys_result(keys_file: str | Path | None, environ: Mapping[str, str]) -> dict:
    keys = _read_keys_file(_resolve_keys_file(keys_file))
    for env_name, key_name in KEY_ENV_PAIRS:
        val = environ.get(env_name)
        if val:
            keys[key_name] = val
            if env_name == "TWITTER_COOKIES_PATH":
                keys["twitter"] = val
    return keys


def load_keys_detailed(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    twitter_cookies_path: str | None = None,
) -> KeyLoad:
    """Load keys as a :class:`KeyLoad`; see :func:`load_keys`."""
    environ = os.environ if environ is None else environ
    keys = _load_keys_result(keys_file, environ)
    # Config reference: below the env path, above the keys file's twitter entry.
    if not environ.get("TWITTER_COOKIES_PATH") and twitter_cookies_path:
        keys["twitter"] = twitter_cookies_path
    return KeyLoad(keys=keys, errors={})


def load_keys(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    twitter_cookies_path: str | None = None,
) -> LoadedKeys:
    """Load API keys: environment > ``~/.multi-search/keys.json``.

    A keys file that cannot be parsed raises :class:`KeysError`.

    ``twitter_cookies_path`` is the non-secret cookie file reference from config. It
    ranks below ``TWITTER_COOKIES_PATH`` and above the keys file's twitter entry.
    Only the path string is stored here; the cookie file is never read by this function.
    """
    loaded = load_keys_detailed(
        keys_file,
        environ,
        twitter_cookies_path=twitter_cookies_path,
    )
    return LoadedKeys(loaded.keys, loaded.errors)


def _file_key_count(value) -> int:
    if isinstance(value, list):
        return sum(1 for item in value if item)
    return 1 if value else 0


def key_sources(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, dict]:
    """Report provenance (never values) of each keyed provider's key.

    Uses the same decision as :func:`load_keys`, so CLI state, doctor output,
    and a real search all give the same answer.
    """
    environ = os.environ if environ is None else environ
    return _source_rows(_read_keys_file(_resolve_keys_file(keys_file)), environ)
