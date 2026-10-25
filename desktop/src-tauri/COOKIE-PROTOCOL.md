# Managed Twitter cookies — protocol v1

Implementation evidence, not independent acceptance. No DDL/schema-version migration.

## Storage and validation

`credentials.provider = twitter_cookies`; encrypted_value is current-user Windows DPAPI (no optional entropy), wrapping compact UTF-8 JSON `{ "v":1, "key":{...cookieMap}, "saved_at":<finite seconds> }`. This provider is intentionally **not** in `STORE_PROVIDERS` (API-key editing/rotation); redaction explicitly includes it.

Cookie map: 1–128 entries, names matching `[A-Za-z0-9_]{1,128}`; values are nonempty strings, <=4096 UTF-8 bytes, no Unicode control characters. `auth_token` and `ct0` must be present and not whitespace-only. Serialized compact cookie map <=65536 bytes. Imported file including BOM/whitespace also <=65536 bytes. UTF-8 BOM accepted; arrays/export-list format rejected. Parse/I/O/DPAPI errors never include cookie content or source path.

## IPC

- `cookie_status()` → `CookieStatus {present:boolean, supported:boolean, mode:string}`
- `cookie_import({path:string, confirmed:boolean})` → CookieStatus
- `cookie_delete({confirmed:boolean})` → CookieStatus

All run in spawn_blocking. Status returns no values/reveal/fingerprint. `present` means a decryptable, validated managed row, not existence of a legacy file. Unreadable row/settings and unknown mode return a generic error. `supported` is Windows DPAPI availability by platform, not a guarantee encryption will succeed.

Unconfirmed import/delete refuse before any file/DB access. Import requires an absolute regular source file, reads at most limit+1 bytes, encrypts, and commits the row plus settings mode in one IMMEDIATE transaction. Unknown settings fields and old file path survive. If either write fails both roll back. Source file is never edited/deleted. Delete commits removal and `managed` mode together even if the row is already missing.

## Selection and migration

`settings.twitter_cookies_mode` absent means legacy `file`; known values only `file` / `managed`. Existing users are not auto-migrated. Import explicitly selects managed. Delete leaves managed unavailable: no automatic read of an old cookie file. General settings save preserves the mode; changing the old path cannot switch away from managed. This iteration has no managed→file UI command. A future switch must require explicit consent; consumers can read an explicitly configured `file` mode for compatibility.

Python loads managed values only when executing Twitter search/fetch and supplies dict directly to XKit `set_cookies`; no temporary plaintext file. Managed absent/corrupt/decryption error is fail-closed. Non-Windows import/delete report unsupported, never plaintext fallback. Legacy file mode is still plaintext and remains an explicitly documented compatibility limitation.

DPAPI mitigates copied DB/backup disclosure without the user's Windows key. It does not prevent same-user processes, a compromised UI allowed to invoke commands, memory inspection, or external plaintext originals/backups. Import leaves those originals untouched; user must remove obsolete copies themselves. No secure-erasure claim.

## Additional cross-language fixes from independent stage review

- Rust scrape-memory accepts known state versions 1 and 2, rejects unknown future versions. Python v2 adds only `content_sources.truncated`; memory SELECT columns remain compatible.
- Exact GitHub category keys `github.com/repo`, `/issues`, `/pull`, `/discussions` are accepted alongside hostnames; arbitrary paths/traversal/encoded paths remain rejected.
- Rust integration test launches real Python `StateStore` in disposable paths for both fresh-v2 creation and v1→v2 migration, obtains keys from Python `site_key`, then tests Rust filtered view/pin/reset for all four categories.

## Verification commands

Run from this crate, only disposable test DBs/profiles:

```powershell
cargo test --no-default-features
cargo test --no-default-features --features test-fixtures,ts
$env:TAURI_CONFIG = Get-Content tauri.check.conf.json -Raw
cargo check --all-targets --features test-fixtures,ts
cargo test --features install-test-boundary,ts
```

The check overlay does not certify a release bundle or dynamic WebView IPC authorization. Real bundle tests remain explicitly ignored until a controlled bundle exists. Linux unsupported test is cfg-gated and requires a Linux runner; Windows execution does not claim that test ran.
