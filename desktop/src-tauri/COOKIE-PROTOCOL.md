# Twitter cookies: file mode

Implementation evidence, not independent acceptance. No DDL/schema-version change.

## Storage and validation

Only file mode exists. The CLI reads the cookie file named by `TWITTER_COOKIES_PATH` or by the settings field `twitter_cookies_path`. A legacy `twitter_cookies_mode` key in settings is ignored and treated as file mode, with no error. The encrypted `managed` mode and the `twitter_cookies` credentials row are removed; existing rows in `config.sqlite` `credentials` are no longer read.

Cookie map: 1–128 entries, names matching `[A-Za-z0-9_]{1,128}`; values are nonempty strings, <=4096 UTF-8 bytes, no Unicode control characters. `auth_token` and `ct0` must be present and not whitespace-only. Serialized compact cookie map <=65536 bytes. Imported file including BOM/whitespace also <=65536 bytes. UTF-8 BOM accepted; arrays/export-list format rejected. Errors never include cookie content.

## IPC

- `cookie_status()` → `CookieStatus {present:boolean, mode:"file", path:string|null, configured_path:string|null}`
- `cookie_import({path:string, confirmed:boolean})` → CookieStatus
- `cookie_delete({confirmed:boolean})` → CookieStatus

All run in spawn_blocking and work on every platform. Status returns no values. `present` means `~/.multi-search/twitter-cookies.json` exists; `path` is that file; `configured_path` is the current `twitter_cookies_path` setting.

Unconfirmed import/delete refuse before any file/DB access. Import requires an absolute regular (non-link) source file, reads at most limit+1 bytes, validates it, writes the map to `~/.multi-search/twitter-cookies.json` (atomic replace, 0600 on Unix), then sets `twitter_cookies_path` to that path in one IMMEDIATE settings transaction. Other settings fields are kept. The source file is never edited or deleted.

Delete removes `~/.multi-search/twitter-cookies.json` and clears `twitter_cookies_path` only when it points at that file; a setting that names another file is left alone.

The copy is plaintext, protected only by file permissions. It does not protect against same-user processes. The user handles other plaintext copies.

## Verification commands

Run from this crate, only disposable test homes/DBs:

```sh
cargo test --no-default-features --features test-fixtures,ts
cargo test --no-default-features --features install-test-boundary,ts
```
