"""Local provider accounts, referencing credentials only by ``key_fingerprint``.

Interface (all functions accept keyword-only ``keys_file=None, oauth_file=None``;
paths default to keys.json and its sibling oauth.json, with no environment keys):

* ``list_accounts(provider_id=None) -> dict[str, list[dict]]`` returns registered
  providers in registry order (or just the requested provider). Each list starts
  with the virtual ``default`` account, even when empty, then saved accounts in
  creation order. The UI may hide an empty default when other accounts exist.
* ``create_account(provider_id, name, *, keys=(), balance_credentials=None)``
  creates a manual account and returns its record. Optional references must
  already exist in the credential files; assigning them moves their ownership.
* ``rename_account(provider_id, account_id, name)`` returns the renamed record.
* ``delete_account(provider_id, account_id, *, keep_keys=True)`` returns the
  removed record. Keeping keys makes them unassigned/default; otherwise only its
  search keys are deleted. Balance credentials are retained, never revoked.
* ``move_key(provider_id, fingerprint, to_account_id, *, credential=None)``
  returns the destination account; ``default`` removes a saved assignment.
  Omit credential for search keys; pass a declared balance-only entry name for
  e.g. ``exa_admin`` or ``parallel_account``. It never changes the key itself.
* ``upsert_oauth_account(provider_id, login_identity=None, *, name=None,
  keys=(), balance_credentials=None)`` returns a created/reused OAuth record.
  Login must save credentials first. Keys are merged; supplied balance entries
  replace those entries' references. Existing user-chosen names are retained.

Records have ``id, name, source, keys, balance_credentials`` and optionally
``login_identity``. IDs are ``acc_`` plus alphanumerics; default has name
``默认账号`` and source ``manual``. ``keys`` is a list of search-key fingerprints;
``balance_credentials`` maps declared balance-only entry names to fingerprints.
No function accepts raw credentials. Invalid references/arguments raise
``AccountError(ValueError)`` without echoing them. Corrupt keys/account data
raises ``KeysError``; corrupt OAuth data raises ``OAuthStoreError``. File write
errors propagate. Reads do not write or repair files (apart from the existing
one-time legacy keys-file migration).

Design note for downstream callers (T01):
- A single module owns grouping and reassignment, so CLI/usage callers need not
  duplicate it. Use these functions rather than rewriting the accounts object.
  Dictionaries match the existing JSON contracts; a second model layer was
  rejected. Only the requested provider's accounts change on a write.
- The file is authoritative, not environment overrides: ephemeral environment
  keys cannot acquire persistent ownership. Reuse the keys reader/atomic writer
  and the existing sha256 display fingerprint, not a new identifier scheme.
  Jina includes exhausted entries and fingerprints their key, not their object.
- Default is computed, never persisted. Stale references are filtered in memory;
  a successful mutation also drops them for that provider. Duplicate references
  belong to the first saved account, avoiding double counting in usage views.
- OAuth identity matches exactly, within a provider and only among OAuth rows.
  Without identity, reuse requires an overlapping credential fingerprint;
  otherwise create an account named ``<provider label> 登录``. Guessing identity
  from a label or merging all anonymous logins was rejected. A later identity
  may attach to an anonymous OAuth row with an overlapping fingerprint.
- Balance references resolve against keys.json or OAuth access_token records;
  stale ones are omitted. Unassigned balance entries appear under default (the
  first unassigned fingerprint per entry, as the schema has one value per name).
  Token refresh/login callers must update references after rotating a token.
  Account deletion does not perform logout or edit oauth.json: revocation is a
  separate operation and balance credentials may be shared outside this view.
- Writes use the existing 0600 atomic replace; like existing key writers they
  are read/modify/write operations, not cross-process serialized transactions.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..state.key_state import key_fingerprint
from ..state.keys import KeysError, _read_keys_file, default_keys_file, write_keys_file_atomic
from . import oauth_store, registry
from .balance import _credential_values
from .base import ProviderPlugin


DEFAULT_ACCOUNT_ID = "default"
_ACCOUNT_ID = re.compile(r"acc_[A-Za-z0-9]+\Z")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{8}\Z")


class AccountError(ValueError):
    """Invalid account operation; messages never include supplied credentials."""


def _plugin(provider_id: str) -> ProviderPlugin:
    try:
        return registry.get_plugin(provider_id)
    except KeyError:
        raise AccountError("unknown provider") from None


def _load(keys_file: str | Path | None) -> tuple[Path, dict]:
    path = Path(keys_file).expanduser() if keys_file is not None else default_keys_file()
    data = _read_keys_file(path)
    # The shared reader maps valid non-object JSON to {}. A writer must reject
    # that fallback rather than replace a file it cannot faithfully preserve.
    if not data and path.exists():
        try:
            is_object = path.read_text(encoding="utf-8-sig").lstrip().startswith("{")
        except OSError:
            raise KeysError(f"keys file cannot be read: {path}") from None
        if not is_object:
            raise KeysError(f"keys file is not a JSON object: {path}")
    if not isinstance(data.get("accounts", {}), dict):
        raise KeysError(f"invalid accounts object in keys file: {path}")
    return path, data


def _credentials(data: dict, plugin: ProviderPlugin, oauth_file: Path) -> dict[str, list[str]]:
    entries = {plugin.key_provider: data.get(plugin.key_provider)} if plugin.key_provider else {}
    balance_methods = [method for method in plugin.auth_methods if method.purpose == "balance_only"]
    oauth = oauth_store.balance_credentials(oauth_file) if any(
        method.type == "oauth" for method in balance_methods
    ) else {}
    for method in balance_methods:
        entries[method.credential] = (
            oauth.get(method.credential) if method.type == "oauth" else data.get(method.credential)
        )
    return {entry: list(dict.fromkeys(key_fingerprint(key) for key in _credential_values(value)))
            for entry, value in entries.items()}


def _view(data: dict, plugin: ProviderPlugin, credentials: dict[str, list[str]]) -> list[dict]:
    saved = data.get("accounts", {}).get(plugin.id, [])
    if not isinstance(saved, list):
        raise KeysError("invalid provider accounts list")
    available = credentials.get(plugin.key_provider, [])
    rotating = {method.credential for method in plugin.auth_methods
                if method.type == "oauth" and method.purpose == "balance_only"}
    used_keys: set[str] = set()
    used_balance: set[tuple[str, str]] = set()
    ids: set[str] = set()
    rows = []
    for raw in saved:
        if (not isinstance(raw, dict)
                or not isinstance(raw.get("id"), str) or not _ACCOUNT_ID.fullmatch(raw["id"])
                or raw["id"] in ids or raw.get("source") not in ("manual", "oauth")
                or not isinstance(raw.get("name"), str) or not raw["name"].strip()
                or not isinstance(raw.get("keys", []), list)
                or not isinstance(raw.get("balance_credentials", {}), dict)
                or ("login_identity" in raw and not isinstance(raw["login_identity"], str))):
            raise KeysError("invalid account record")
        ids.add(raw["id"])
        row = dict(raw)
        row["keys"] = []
        for fingerprint in raw.get("keys", []):
            if isinstance(fingerprint, str) and fingerprint in available and fingerprint not in used_keys:
                row["keys"].append(fingerprint)
                used_keys.add(fingerprint)
        row["balance_credentials"] = {}
        for entry, fingerprint in raw.get("balance_credentials", {}).items():
            current = credentials.get(entry, [])
            # An OAuth access token is replaced on every refresh, so its fingerprint goes
            # stale; the account owns the entry itself (there is one token per entry).
            if entry in rotating and isinstance(fingerprint, str) and len(current) == 1:
                fingerprint = current[0]
            if (entry != plugin.key_provider and isinstance(fingerprint, str)
                    and fingerprint in current
                    and (entry, fingerprint) not in used_balance):
                row["balance_credentials"][entry] = fingerprint
                used_balance.add((entry, fingerprint))
        rows.append(row)
    default = {
        "id": DEFAULT_ACCOUNT_ID, "name": "默认账号", "source": "manual",
        "keys": [fingerprint for fingerprint in available if fingerprint not in used_keys],
        "balance_credentials": {},
    }
    for entry, fingerprints in credentials.items():
        if entry != plugin.key_provider:
            unassigned = [fp for fp in fingerprints if (entry, fp) not in used_balance]
            if unassigned:
                default["balance_credentials"][entry] = unassigned[0]
    return [default, *rows]


def _read_provider(provider_id, keys_file, oauth_file):
    plugin = _plugin(provider_id)
    path, data = _load(keys_file)
    oauth_path = Path(oauth_file).expanduser() if oauth_file is not None else path.with_name("oauth.json")
    credentials = _credentials(data, plugin, oauth_path)
    return path, data, plugin, credentials, _view(data, plugin, credentials)


def _public(row: dict) -> dict:
    # Keep unknown saved fields when writing, but never expose them to callers.
    return {field: row[field] for field in (
        "id", "name", "source", "login_identity", "keys", "balance_credentials"
    ) if field in row}


def _save(path: Path, data: dict, provider_id: str, rows: list[dict]) -> None:
    data.setdefault("accounts", {})[provider_id] = [row for row in rows if row["id"] != DEFAULT_ACCOUNT_ID]
    write_keys_file_atomic(path, data)


def _name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise AccountError("account name must not be empty")
    return name.strip()


def _account(rows: list[dict], account_id: str, *, allow_default: bool = False) -> dict:
    if account_id == DEFAULT_ACCOUNT_ID and not allow_default:
        raise AccountError("the default account cannot be renamed or deleted")
    for row in rows:
        if row["id"] == account_id:
            return row
    raise AccountError("account not found")


def _new_account(rows: list[dict], name: str, source: str) -> dict:
    account_id = "acc_" + uuid.uuid4().hex
    while any(row["id"] == account_id for row in rows):
        account_id = "acc_" + uuid.uuid4().hex
    return {"id": account_id, "name": _name(name), "source": source,
            "keys": [], "balance_credentials": {}}


def _references(keys, balance_credentials, plugin, credentials) -> tuple[list[str], dict[str, str]]:
    if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
        raise AccountError("keys must be a sequence of fingerprints")
    for fingerprint in keys:
        if (not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint)
                or fingerprint not in credentials.get(plugin.key_provider, [])):
            raise AccountError("search key fingerprint not found")
    balance = {} if balance_credentials is None else balance_credentials
    if not isinstance(balance, Mapping):
        raise AccountError("balance credentials must map entry names to fingerprints")
    for entry, fingerprint in balance.items():
        if (entry == plugin.key_provider or not isinstance(fingerprint, str)
                or not _FINGERPRINT.fullmatch(fingerprint)
                or fingerprint not in credentials.get(entry, [])):
            raise AccountError("balance credential fingerprint not found")
    return list(dict.fromkeys(keys)), dict(balance)


def _assign(rows: list[dict], target: dict, keys: list[str], balance: dict[str, str]) -> None:
    for row in rows:
        row["keys"] = [fp for fp in row["keys"] if fp not in keys]
        row["balance_credentials"] = {
            entry: fp for entry, fp in row["balance_credentials"].items() if balance.get(entry) != fp
        }
    target["keys"].extend(keys)
    target["balance_credentials"].update(balance)


def list_accounts(
    provider_id: str | None = None, *, keys_file: str | Path | None = None,
    oauth_file: str | Path | None = None,
) -> dict[str, list[dict]]:
    """Return fingerprint-only account groups, including virtual default rows."""
    plugins = [_plugin(provider_id)] if provider_id is not None else registry.builtin_plugins()
    path, data = _load(keys_file)
    oauth_path = Path(oauth_file).expanduser() if oauth_file is not None else path.with_name("oauth.json")
    return {plugin.id: [_public(row) for row in _view(data, plugin, _credentials(data, plugin, oauth_path))]
            for plugin in plugins}


def create_account(
    provider_id: str, name: str, *, keys: Sequence[str] = (),
    balance_credentials: Mapping[str, str] | None = None,
    keys_file: str | Path | None = None, oauth_file: str | Path | None = None,
) -> dict:
    """Create a manual account, optionally assigning already-saved credentials."""
    path, data, plugin, credentials, rows = _read_provider(provider_id, keys_file, oauth_file)
    key_refs, balance_refs = _references(keys, balance_credentials, plugin, credentials)
    row = _new_account(rows, name, "manual")
    rows.append(row)
    _assign(rows, row, key_refs, balance_refs)
    _save(path, data, provider_id, rows)
    return _public(row)


def rename_account(
    provider_id: str, account_id: str, name: str, *, keys_file: str | Path | None = None,
    oauth_file: str | Path | None = None,
) -> dict:
    """Rename a saved account; default cannot be renamed."""
    path, data, _plugin_value, _credentials_value, rows = _read_provider(provider_id, keys_file, oauth_file)
    row = _account(rows, account_id)
    row["name"] = _name(name)
    _save(path, data, provider_id, rows)
    return _public(row)


def delete_account(
    provider_id: str, account_id: str, *, keep_keys: bool = True,
    keys_file: str | Path | None = None, oauth_file: str | Path | None = None,
) -> dict:
    """Remove a saved account, optionally deleting its search keys in the same write."""
    if not isinstance(keep_keys, bool):
        raise AccountError("keep_keys must be a boolean")
    path, data, plugin, _credentials_value, rows = _read_provider(provider_id, keys_file, oauth_file)
    row = _account(rows, account_id)
    if not keep_keys and row["keys"]:
        entry = plugin.key_provider
        value = data[entry]
        if isinstance(value, list):
            data[entry] = [item for item in value if not any(
                key_fingerprint(key) in row["keys"] for key in _credential_values(item)
            )]
        else:
            del data[entry]
    rows.remove(row)
    _save(path, data, provider_id, rows)
    return _public(row)


def move_key(
    provider_id: str, fingerprint: str, to_account_id: str, *, credential: str | None = None,
    keys_file: str | Path | None = None, oauth_file: str | Path | None = None,
) -> dict:
    """Move one saved search/balance credential reference, including to default."""
    path, data, plugin, credentials, rows = _read_provider(provider_id, keys_file, oauth_file)
    target = _account(rows, to_account_id, allow_default=True)
    search = credential is None or credential == plugin.key_provider
    keys, balance = _references(
        [fingerprint] if search else [], {} if search else {credential: fingerprint}, plugin, credentials,
    )
    _assign(rows, target, keys, balance)
    _save(path, data, provider_id, rows)
    # Recompute default when replacing a balance reference frees its predecessor.
    return _public(_account(_view(data, plugin, credentials), to_account_id, allow_default=True))


def upsert_oauth_account(
    provider_id: str, login_identity: str | None = None, *, name: str | None = None,
    keys: Sequence[str] = (), balance_credentials: Mapping[str, str] | None = None,
    keys_file: str | Path | None = None, oauth_file: str | Path | None = None,
) -> dict:
    """Create/reuse a provider's OAuth account after credentials have been saved."""
    if login_identity is not None and not isinstance(login_identity, str):
        raise AccountError("login identity must be text")
    identity = login_identity.strip() if login_identity else None
    identity = identity or None
    path, data, plugin, credentials, rows = _read_provider(provider_id, keys_file, oauth_file)
    key_refs, balance_refs = _references(keys, balance_credentials, plugin, credentials)
    if name is not None:
        name = _name(name)
    candidates = [row for row in rows if row["source"] == "oauth"]
    row = next((row for row in candidates if identity and row.get("login_identity") == identity), None)
    if row is None:
        row = next((row for row in candidates if not row.get("login_identity") and (
            any(fp in row["keys"] for fp in key_refs)
            or any(row["balance_credentials"].get(entry) == fp for entry, fp in balance_refs.items())
        )), None)
    if row is None:
        row = _new_account(rows, name or identity or f"{plugin.label} 登录", "oauth")
        rows.append(row)
    if identity:
        row["login_identity"] = identity
    _assign(rows, row, key_refs, balance_refs)
    _save(path, data, provider_id, rows)
    return _public(row)
