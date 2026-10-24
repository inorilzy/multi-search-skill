//! Explicit Windows cookie custody. Never writes, deletes, or silently migrates the source file.
use crate::{credential, RuntimeEnvironment};
use rusqlite::OptionalExtension;
use serde::Serialize;
use serde_json::{Map, Value};
use std::{io::Read, path::Path};

pub(crate) const PROVIDER: &str = "twitter_cookies";
const LIMIT: usize = 65_536;

#[derive(Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CookieStatus {
    pub present: bool,
    pub supported: bool,
    pub mode: String,
}

pub(crate) fn valid(value: &Value) -> bool {
    let Some(map) = value.as_object() else { return false };
    !map.is_empty() && map.len() <= 128
        && ["auth_token", "ct0"].iter().all(|name| map.get(*name).and_then(Value::as_str).is_some_and(|v| !v.trim().is_empty()))
        && map.iter().all(|(name, value)| {
            !name.is_empty() && name.len() <= 128
                && name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
                && value.as_str().is_some_and(|v| !v.is_empty() && v.len() <= 4096 && !v.chars().any(char::is_control))
        })
        && serde_json::to_vec(value).is_ok_and(|bytes| bytes.len() <= LIMIT)
}
fn settings(connection: &rusqlite::Connection) -> Result<Map<String, Value>, String> {
    let text: Option<String> = connection.query_row("SELECT data FROM settings WHERE id=1", [], |r| r.get(0))
        .optional().map_err(|_| "Cookie settings unavailable")?;
    match text {
        None => Ok(Map::new()),
        Some(text) => serde_json::from_str::<Value>(&text).ok().and_then(|v| v.as_object().cloned()).ok_or("Cookie settings unreadable".into()),
    }
}
fn mode(map: &Map<String, Value>) -> Result<String, String> {
    match map.get("twitter_cookies_mode") {
        None => Ok("file".into()),
        Some(Value::String(value)) if value == "file" || value == "managed" => Ok(value.clone()),
        _ => Err("Unsupported cookie mode".into()),
    }
}
fn supported() -> Result<(), String> {
    if cfg!(windows) { Ok(()) } else { Err("Managed cookies require Windows DPAPI; no plaintext fallback".into()) }
}
pub fn status(environment: &RuntimeEnvironment) -> Result<CookieStatus, String> {
    let path = crate::config_db::path(&environment.variables).ok_or("Cookie database unavailable")?;
    if !path.exists() { return Ok(CookieStatus { supported: cfg!(windows), present: false, mode: "file".into() }); }
    let connection = crate::config_db::open(&path)?;
    // One read snapshot prevents mixed mode/presence observations during import/delete.
    let transaction = connection.unchecked_transaction().map_err(|_| "Cookie database unavailable")?;
    let mode = mode(&settings(&transaction)?)?;
    let blob: Option<Vec<u8>> = transaction.query_row("SELECT encrypted_value FROM credentials WHERE provider=?1", [PROVIDER], |r| r.get(0))
        .optional().map_err(|_| "Cookie database unavailable")?;
    if let Some(blob) = blob.as_ref() {
        supported()?;
        let clear = credential::crypt(blob, false).map_err(|_| "Managed cookies unreadable")?;
        credential::decode_blob(PROVIDER, &clear).map_err(|_| "Managed cookies unreadable")?;
    }
    Ok(CookieStatus { supported: cfg!(windows), present: blob.is_some(), mode })
}
pub fn import(environment: &RuntimeEnvironment, path: &Path, confirmed: bool) -> Result<CookieStatus, String> {
    if !confirmed { return Err("Confirm cookie import before reading the source file".into()); }
    supported()?;
    if !path.is_absolute() { return Err("Select an absolute cookie JSON file path".into()); }
    let metadata = std::fs::symlink_metadata(path).map_err(|_| "Cookie source unavailable")?;
    if !metadata.is_file() || crate::windows_util::is_link(&metadata) { return Err("Cookie source must be a regular file".into()); }
    let file = std::fs::File::open(path).map_err(|_| "Cookie source unavailable")?;
    let mut bytes = Vec::new();
    file.take((LIMIT + 1) as u64).read_to_end(&mut bytes).map_err(|_| "Cookie source unreadable")?;
    if bytes.len() > LIMIT { return Err("Cookie JSON exceeds 64 KiB".into()); }
    let text = std::str::from_utf8(&bytes).map_err(|_| "Cookie source must be UTF-8 JSON")?.trim_start_matches('\u{feff}');
    let value: Value = serde_json::from_str(text).map_err(|_| "Cookie source is invalid JSON")?;
    if !valid(&value) { return Err("Invalid cookie map: auth_token and ct0 are required; values must be bounded strings".into()); }
    let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_err(|_| "System clock unavailable")?.as_secs_f64();
    let encrypted = credential::crypt(&credential::encode_blob(&value, stamp), true).map_err(|_| "Cookie encryption failed")?;
    let db = crate::config_db::path(&environment.variables).ok_or("Cookie database unavailable")?;
    let mut connection = crate::config_db::open(&db)?;
    let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|_| "Cookie transaction unavailable")?;
    let mut object = settings(&tx)?;
    mode(&object)?;
    object.insert("twitter_cookies_mode".into(), Value::String("managed".into()));
    tx.execute("INSERT INTO credentials(provider,encrypted_value,saved_at) VALUES(?1,?2,?3) ON CONFLICT(provider) DO UPDATE SET encrypted_value=excluded.encrypted_value,saved_at=excluded.saved_at", rusqlite::params![PROVIDER, encrypted, stamp]).map_err(|_| "Cookie import failed; existing data unchanged")?;
    tx.execute("INSERT INTO settings(id,data) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data", [Value::Object(object).to_string()]).map_err(|_| "Cookie import failed; existing data unchanged")?;
    tx.commit().map_err(|_| "Cookie import failed; existing data unchanged")?;
    Ok(CookieStatus { supported: cfg!(windows), present: true, mode: "managed".into() })
}
pub fn delete(environment: &RuntimeEnvironment, confirmed: bool) -> Result<CookieStatus, String> {
    if !confirmed { return Err("Confirm managed cookie deletion".into()); }
    supported()?;
    let db = crate::config_db::path(&environment.variables).ok_or("Cookie database unavailable")?;
    let mut connection = crate::config_db::open(&db)?;
    let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|_| "Cookie transaction unavailable")?;
    let mut object = settings(&tx)?;
    mode(&object)?;
    // Deletion never re-enables the old plaintext file, even if the row was absent.
    object.insert("twitter_cookies_mode".into(), Value::String("managed".into()));
    tx.execute("DELETE FROM credentials WHERE provider=?1", [PROVIDER]).map_err(|_| "Cookie deletion failed")?;
    tx.execute("INSERT INTO settings(id,data) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data", [Value::Object(object).to_string()]).map_err(|_| "Cookie deletion failed")?;
    tx.commit().map_err(|_| "Cookie deletion failed")?;
    Ok(CookieStatus { supported: cfg!(windows), present: false, mode: "managed".into() })
}
