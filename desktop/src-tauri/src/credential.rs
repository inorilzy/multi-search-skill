//! API keys in the plaintext keys file `~/.multi-search/keys.json`, shared with the Python CLI.
//!
//! Each provider is one top-level entry: a key string, a list of keys, or (Jina only) objects
//! with a `key` plus metadata such as `exhausted`. Every mutation is a read-modify-write of that
//! one entry through [`crate::keys_file::update`]; all other entries are kept as they are.
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;

pub(crate) const MAX_KEY_LENGTH: usize = 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CredentialError {
    /// The keys file cannot be located, read or written.
    Unavailable(String),
    /// The provider's entry exists but has a shape the editor cannot address.
    Unreadable,
    Invalid(&'static str),
}
impl std::fmt::Display for CredentialError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unavailable(message) => f.write_str(message),
            Self::Unreadable => f.write_str("已保存的 Key 格式无法识别，请检查 ~/.multi-search/keys.json"),
            Self::Invalid(message) => f.write_str(message),
        }
    }
}
impl From<String> for CredentialError {
    fn from(message: String) -> Self {
        Self::Unavailable(message)
    }
}

pub(crate) fn validate_key(key: &str) -> Result<String, CredentialError> {
    let text = key.trim();
    if text.is_empty()
        || text.len() > MAX_KEY_LENGTH
        || text.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
    {
        return Err(CredentialError::Invalid(
            "key must be 1-1024 characters with no control characters",
        ));
    }
    Ok(text.to_string())
}
fn validate_value(provider: &str, value: &Value) -> bool {
    match value {
        Value::String(s) => validate_key(s).is_ok(),
        Value::Array(items) => !items.is_empty() && items.iter().all(|v| (v.is_string() || provider == "jina" && v.is_object()) && validate_value(provider,v)),
        Value::Object(map) if provider == "jina" => map.get("key").and_then(Value::as_str).is_some_and(|s| validate_key(s).is_ok()) && map.get("exhausted").is_none_or(Value::is_boolean),
        _ => false,
    }
}
/// An entry the CLI also treats as "no key": absent, null, an empty string or an empty list.
fn is_empty_entry(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::String(s) => s.trim().is_empty(),
        Value::Array(items) => items.is_empty(),
        _ => false,
    }
}
/// The provider's stored value, `None` when it has no key, `Unreadable` for an unusable shape.
fn decode(provider: &str, value: Option<&Value>) -> Result<Option<Value>, CredentialError> {
    match value {
        None => Ok(None),
        Some(value) if is_empty_entry(value) => Ok(None),
        Some(value) if validate_value(provider, value) => Ok(Some(value.clone())),
        Some(_) => Err(CredentialError::Unreadable),
    }
}
fn editor_value(text: &str) -> Result<Value, CredentialError> {
    let keys: Vec<String> = text.lines().map(validate_key).collect::<Result<_, _>>()?;
    if keys.is_empty() || keys.len() > 256 {
        return Err(CredentialError::Invalid("provide 1-256 keys, one per line"));
    }
    Ok(if keys.len() == 1 {
        Value::String(keys[0].clone())
    } else {
        serde_json::json!(keys)
    })
}
pub(crate) fn snapshot(text: &str) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

/// The provider's stored value plus the keys file's modification time (seconds), which the UI
/// uses to notice that the saved state changed.
pub(crate) fn load(
    variables: &BTreeMap<String, String>,
    provider: &str,
) -> Result<Option<(Value, f64)>, CredentialError> {
    let path = crate::keys_file::prepare(variables)?;
    let map = crate::keys_file::read(&path)?;
    let Some(value) = decode(provider, map.get(provider))? else { return Ok(None) };
    let saved_at = std::fs::metadata(&path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    Ok(Some((value, saved_at)))
}

/// Jina editor semantics: the editor shows one key per line. A line whose key
/// matches a stored structured entry keeps that entry verbatim (including
/// `exhausted` and any extra metadata); a new/changed line is saved as a plain
/// key string; a removed line drops its entry. Other providers are unaffected.
pub(crate) fn merge_jina_metadata(edited: Value, previous: Option<&Value>) -> Value {
    let Some(previous) = previous else { return edited };
    let mut stored: Vec<&Value> = match previous {
        Value::Array(items) => items.iter().collect(),
        _ => vec![previous],
    };
    let lines: Vec<String> = match &edited {
        Value::String(s) => vec![s.clone()],
        Value::Array(items) => items.iter().filter_map(Value::as_str).map(str::to_string).collect(),
        _ => Vec::new(),
    };
    if lines.is_empty() {
        return edited;
    }
    let merged: Vec<Value> = lines
        .into_iter()
        .map(|line| {
            match stored.iter().position(|item| {
                // The editor trims input; compare the same normalized key without
                // rewriting the original entry or its metadata.
                item.as_str()
                    .or_else(|| item.get("key").and_then(Value::as_str))
                    .map(str::trim) == Some(line.as_str())
            }) {
                // Consume matches in stored order, preserving duplicate entries independently.
                Some(index) => stored.remove(index).clone(),
                None => Value::String(line),
            }
        })
        .collect();
    if merged.len() == 1 {
        merged.into_iter().next().unwrap()
    } else {
        Value::Array(merged)
    }
}

/// Run `change` on the provider's decoded entry and write the result back to the keys file.
fn mutate(
    variables: &BTreeMap<String, String>,
    provider: &str,
    change: impl FnOnce(Option<&Value>) -> Result<Option<Value>, CredentialError>,
) -> Result<(), CredentialError> {
    let mut failure = None;
    crate::keys_file::update(variables, provider, |current| {
        let outcome = decode(provider, current).and_then(|stored| change(stored.as_ref()));
        match outcome {
            Ok(next) => Ok((next, ())),
            Err(error) => {
                failure = Some(error);
                Err(String::new())
            }
        }
    })
    .map_err(|message| failure.take().unwrap_or(CredentialError::Unavailable(message)))
}

/// Whole-editor save: the edited lines replace the provider's entry. Jina keeps the metadata of
/// unchanged lines; an unreadable Jina entry fails instead of silently losing it.
pub(crate) fn save(
    variables: &BTreeMap<String, String>,
    provider: &str,
    key: &str,
) -> Result<(), CredentialError> {
    let value = editor_value(key)?;
    if provider == "jina" {
        return mutate(variables, provider, |stored| Ok(Some(merge_jina_metadata(value, stored))));
    }
    crate::keys_file::update(variables, provider, |_| Ok((Some(value), ())))
        .map_err(CredentialError::Unavailable)
}
/// Remove the provider's entry. Cleanup works whatever shape the entry has.
pub(crate) fn remove(variables: &BTreeMap<String, String>, provider: &str) -> Result<bool, CredentialError> {
    crate::keys_file::update(variables, provider, |current| Ok((None, current.is_some())))
        .map_err(CredentialError::Unavailable)
}

/// Flatten a stored value into row entries. Strings and Jina objects are
/// kept verbatim (objects preserve every metadata field).
fn stored_rows(provider: &str, key: &Value) -> Result<Vec<Value>, CredentialError> {
    let items: &[Value] = match key {
        Value::Array(items) => items,
        other => std::slice::from_ref(other),
    };
    if !validate_value(provider, key) {
        return Err(CredentialError::Unreadable);
    }
    Ok(items.to_vec())
}
fn collapse_rows(rows: Vec<Value>) -> Value {
    if rows.len() == 1 {
        rows.into_iter().next().unwrap()
    } else {
        Value::Array(rows)
    }
}
/// Editor line for one row. `credential_read` renders every valid entry
/// (string or Jina object `key`), so any entry without a line is a shape the
/// row operations cannot address: reject instead of silently hiding it.
fn row_editor_line(value: &Value) -> Result<String, CredentialError> {
    value
        .as_str()
        .or_else(|| value.get("key").and_then(Value::as_str))
        .map(str::to_string)
        .ok_or(CredentialError::Unreadable)
}
/// Rows after appending `new_keys` to an already-decoded stored value.
fn append_rows(provider: &str, stored: Option<&Value>, keys: &[String]) -> Result<Value, CredentialError> {
    if keys.is_empty() || keys.len() > 256 {
        return Err(CredentialError::Invalid("provide 1-256 keys"));
    }
    let mut new_keys: Vec<String> = Vec::with_capacity(keys.len());
    for key in keys {
        new_keys.push(validate_key(key)?);
    }
    let mut rows = match stored {
        Some(key) => stored_rows(provider, key)?,
        None => Vec::new(),
    };
    for row in &rows {
        row_editor_line(row)?;
    }
    if rows.len() + new_keys.len() > 256 {
        return Err(CredentialError::Invalid("credential rows cannot exceed 256"));
    }
    rows.extend(new_keys.into_iter().map(Value::String));
    Ok(collapse_rows(rows))
}
/// Rows after removing stored entry `index` (the editor row number, so
/// duplicates keep their identity and remove the exact occurrence). `expected`
/// is the snapshot hash of the `credential_read` value the UI saw; a mismatch
/// means the caller is working from stale rows and nothing is written. `None`
/// means the last row was removed and the provider's entry must be deleted.
fn remove_row_at(provider: &str, stored: &Value, index: usize, expected: &str) -> Result<Option<Value>, CredentialError> {
    let mut rows = stored_rows(provider, stored)?;
    let snapshot = rows
        .iter()
        .map(row_editor_line)
        .collect::<Result<Vec<_>, _>>()?
        .join("\n");
    if self::snapshot(&snapshot) != expected {
        return Err(CredentialError::Invalid("credential rows changed; refresh and retry"));
    }
    if index >= rows.len() {
        return Err(CredentialError::Invalid("credential row index out of range"));
    }
    rows.remove(index);
    Ok(if rows.is_empty() { None } else { Some(collapse_rows(rows)) })
}
/// Append validated keys to the CURRENT stored rows for `provider`. Existing
/// scalar/object rows are preserved verbatim; no whole-list replacement and
/// no Jina metadata reconstruction.
pub(crate) fn append_keys(
    variables: &BTreeMap<String, String>,
    provider: &str,
    keys: &[String],
) -> Result<(), CredentialError> {
    mutate(variables, provider, |stored| append_rows(provider, stored, keys).map(Some))
}
/// Remove one editor row for `provider`, guarded by the snapshot hash of the rows the UI saw.
pub(crate) fn remove_at(
    variables: &BTreeMap<String, String>,
    provider: &str,
    index: usize,
    expected: &str,
) -> Result<(), CredentialError> {
    mutate(variables, provider, |stored| {
        let stored = stored.ok_or(CredentialError::Invalid("credential rows changed; refresh and retry"))?;
        remove_row_at(provider, stored, index, expected)
    })
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CredentialStatus {
    /// present | absent | unreadable | unavailable, or a new value added later; UI must fall back to a raw string.
    pub state: String,
    /// Modification time of the keys file (seconds) when this provider has a key.
    pub saved_at: Option<f64>,
    pub error: String,
}
pub(crate) fn status_of(result: Result<Option<(Value, f64)>, CredentialError>) -> CredentialStatus {
    match result {
        Ok(Some((_, saved_at))) => CredentialStatus {
            state: "present".into(),
            saved_at: Some(saved_at),
            error: String::new(),
        },
        Ok(None) => CredentialStatus {
            state: "absent".into(),
            saved_at: None,
            error: String::new(),
        },
        Err(error) => CredentialStatus {
            state: if matches!(error, CredentialError::Unreadable) { "unreadable" } else { "unavailable" }.into(),
            saved_at: None,
            error: error.to_string(),
        },
    }
}
