//! The one plaintext keys file every desktop writer shares with the CLI: `~/.multi-search/keys.json`.
//!
//! `~` is `USERPROFILE` (Windows) or `HOME`, taken from the given environment variables only. A
//! file that cannot be parsed is a hard error and is never overwritten, because it may hold other
//! providers' keys. Writers change only the touched entry and replace the file atomically with
//! owner-only permissions (0600 on Unix).
use serde_json::{Map, Value};
use std::{collections::BTreeMap, path::{Path, PathBuf}};

pub(crate) const DIR_NAME: &str = ".multi-search";
pub(crate) const FILE_NAME: &str = "keys.json";
/// The pre-unification location; read only by the one-time copy in [`prepare`].
pub(crate) const LEGACY_FILE_NAME: &str = ".search-keys.json";
/// How the UI and messages refer to the file.
pub(crate) const DISPLAY_PATH: &str = "~/.multi-search/keys.json";

fn home(variables: &BTreeMap<String, String>) -> Option<PathBuf> {
    variables
        .get("USERPROFILE")
        .filter(|v| !v.is_empty())
        .or_else(|| variables.get("HOME").filter(|v| !v.is_empty()))
        .map(PathBuf::from)
}

/// `~/.multi-search/keys.json` for these variables, or `None` without a home directory.
pub(crate) fn path(variables: &BTreeMap<String, String>) -> Option<PathBuf> {
    home(variables).map(|home| home.join(DIR_NAME).join(FILE_NAME))
}

/// Resolve the keys file and run the one-time legacy copy: when the new file is missing and
/// `~/.search-keys.json` exists, its bytes are copied to the new path (0600, atomic, never
/// replacing a file that appeared meanwhile). The legacy file is never modified.
pub(crate) fn prepare(variables: &BTreeMap<String, String>) -> Result<PathBuf, String> {
    let home = home(variables).ok_or("无法定位用户目录")?;
    let target = home.join(DIR_NAME).join(FILE_NAME);
    let legacy = home.join(LEGACY_FILE_NAME);
    if std::fs::symlink_metadata(&target).is_err() && legacy.is_file() {
        let bytes = std::fs::read(&legacy).map_err(|_| "无法读取旧密钥文件 ~/.search-keys.json".to_string())?;
        std::fs::create_dir_all(target.parent().expect("keys file has a parent"))
            .map_err(|_| "无法创建 ~/.multi-search 目录".to_string())?;
        crate::secure_temp::create_private_file_if_absent(&target, &bytes)
            .map_err(|_| "无法复制旧密钥文件到 ~/.multi-search/keys.json".to_string())?;
    }
    Ok(target)
}

/// Parse the keys file. A missing file is an empty object; anything else that is not a JSON
/// object is an error, so callers never overwrite it.
pub(crate) fn read(path: &Path) -> Result<Map<String, Value>, String> {
    match std::fs::read_to_string(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Map::new()),
        Err(_) => Err(format!("无法读取密钥文件 {DISPLAY_PATH}")),
        Ok(text) => match serde_json::from_str(text.trim_start_matches('\u{feff}')) {
            Ok(Value::Object(map)) => Ok(map),
            _ => Err(format!("密钥文件不是有效的 JSON 对象，未保存；请先修复 {DISPLAY_PATH}")),
        },
    }
}

/// Atomically replace the keys file with `map` (0600 on Unix), creating `~/.multi-search/`.
pub(crate) fn write(path: &Path, map: &Map<String, Value>) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|_| "无法创建 ~/.multi-search 目录".to_string())?;
    }
    let mut body = serde_json::to_vec_pretty(map).map_err(|_| "无法序列化密钥文件".to_string())?;
    body.push(b'\n');
    crate::secure_temp::replace_private_file(path, &body).map_err(|_| "无法写入密钥文件".to_string())
}

/// Read-modify-write of one entry. `change` gets the current value of `name` and returns the new
/// one (`None` removes it). Every other entry, known or not, is written back unchanged. Nothing is
/// written when `change` fails or leaves the entry as it was.
pub(crate) fn update<T>(
    variables: &BTreeMap<String, String>,
    name: &str,
    change: impl FnOnce(Option<&Value>) -> Result<(Option<Value>, T), String>,
) -> Result<T, String> {
    let path = prepare(variables)?;
    let mut map = read(&path)?;
    let before = map.get(name).cloned();
    let (after, result) = change(before.as_ref())?;
    if after == before {
        return Ok(result);
    }
    match after {
        Some(value) => {
            map.insert(name.to_string(), value);
        }
        None => {
            map.remove(name);
        }
    }
    write(&path, &map)?;
    Ok(result)
}
