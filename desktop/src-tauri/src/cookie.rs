//! Twitter / X cookie import in file mode. The chosen file is validated and copied to
//! `~/.multi-search/twitter-cookies.json` (0600, atomic); the settings field
//! `twitter_cookies_path` then points at that copy. The source file is never modified or deleted.
use crate::RuntimeEnvironment;
use rusqlite::OptionalExtension;
use serde::Serialize;
use serde_json::{Map, Value};
use std::{io::Read, path::{Path, PathBuf}};

pub(crate) const FILE_NAME: &str = "twitter-cookies.json";
const SETTINGS_KEY: &str = "twitter_cookies_path";
const LIMIT: usize = 65_536;

#[derive(Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CookieStatus {
    /// The managed copy `~/.multi-search/twitter-cookies.json` exists.
    pub present: bool,
    /// Always `file`; the encrypted mode was removed. A legacy `twitter_cookies_mode` setting is ignored.
    pub mode: String,
    /// Absolute path of the managed copy, or `None` without a home directory.
    pub path: Option<String>,
    /// The `twitter_cookies_path` setting, if any (it may point at another file).
    pub configured_path: Option<String>,
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

/// `~/.multi-search/twitter-cookies.json` for this environment.
pub(crate) fn managed_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    crate::keys_file::path(&environment.variables).map(|keys| keys.with_file_name(FILE_NAME))
}

fn settings(connection: &rusqlite::Connection) -> Result<Map<String, Value>, String> {
    let text: Option<String> = connection.query_row("SELECT data FROM settings WHERE id=1", [], |r| r.get(0))
        .optional().map_err(|_| "Cookie 设置无法读取")?;
    match text {
        None => Ok(Map::new()),
        Some(text) => serde_json::from_str::<Value>(&text).ok().and_then(|v| v.as_object().cloned()).ok_or("Cookie 设置无法读取".into()),
    }
}
fn configured(map: &Map<String, Value>) -> Option<String> {
    map.get(SETTINGS_KEY).and_then(Value::as_str).filter(|p| !p.trim().is_empty()).map(str::to_string)
}
fn same_path(a: &str, b: &Path) -> bool {
    Path::new(a) == b
}

/// Change only `twitter_cookies_path` in the settings record, inside one IMMEDIATE transaction.
fn set_configured(environment: &RuntimeEnvironment, change: impl FnOnce(&mut Map<String, Value>)) -> Result<Option<String>, String> {
    let db = crate::config_db::path(&environment.variables).ok_or("无法定位配置数据库")?;
    let mut connection = crate::config_db::open(&db)?;
    let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|_| "配置数据库事务失败")?;
    let mut object = settings(&tx)?;
    let before = object.clone();
    change(&mut object);
    if object != before {
        tx.execute("INSERT INTO settings(id,data) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data", [Value::Object(object.clone()).to_string()])
            .map_err(|_| "保存 Cookie 设置失败")?;
    }
    tx.commit().map_err(|_| "保存 Cookie 设置失败")?;
    Ok(configured(&object))
}

fn view(environment: &RuntimeEnvironment, configured_path: Option<String>) -> CookieStatus {
    let path = managed_path(environment);
    CookieStatus {
        present: path.as_ref().is_some_and(|p| p.is_file()),
        mode: "file".into(),
        path: path.map(|p| p.to_string_lossy().into_owned()),
        configured_path,
    }
}

pub fn status(environment: &RuntimeEnvironment) -> Result<CookieStatus, String> {
    let configured_path = match crate::config_db::path(&environment.variables) {
        Some(db) if db.exists() => configured(&settings(&crate::config_db::open(&db)?)?),
        _ => None,
    };
    Ok(view(environment, configured_path))
}

fn read_source(path: &Path) -> Result<Value, String> {
    if !path.is_absolute() { return Err("请选择 Cookie JSON 文件的绝对路径".into()); }
    let metadata = std::fs::symlink_metadata(path).map_err(|_| "无法读取 Cookie 文件")?;
    if !metadata.is_file() || crate::windows_util::is_link(&metadata) { return Err("Cookie 文件必须是普通文件".into()); }
    let file = std::fs::File::open(path).map_err(|_| "无法读取 Cookie 文件")?;
    let mut bytes = Vec::new();
    file.take((LIMIT + 1) as u64).read_to_end(&mut bytes).map_err(|_| "无法读取 Cookie 文件")?;
    if bytes.len() > LIMIT { return Err("Cookie JSON 超过 64 KiB".into()); }
    let text = std::str::from_utf8(&bytes).map_err(|_| "Cookie 文件必须是 UTF-8 JSON")?.trim_start_matches('\u{feff}');
    let value: Value = serde_json::from_str(text).map_err(|_| "Cookie 文件不是有效的 JSON")?;
    if !valid(&value) { return Err("Cookie 内容无效：需要 auth_token 与 ct0，且每个值都是有限长度的字符串".into()); }
    Ok(value)
}

pub fn import(environment: &RuntimeEnvironment, path: &Path, confirmed: bool) -> Result<CookieStatus, String> {
    if !confirmed { return Err("Confirm cookie import before reading the source file".into()); }
    let value = read_source(path)?;
    let target = managed_path(environment).ok_or("无法定位用户目录")?;
    std::fs::create_dir_all(target.parent().expect("managed cookie path has a parent")).map_err(|_| "无法创建 ~/.multi-search 目录")?;
    let mut body = serde_json::to_vec_pretty(&value).map_err(|_| "无法序列化 Cookie")?;
    body.push(b'\n');
    crate::secure_temp::replace_private_file(&target, &body).map_err(|_| "Cookie 导入失败，原文件未改动")?;
    let text = target.to_string_lossy().into_owned();
    let configured_path = set_configured(environment, |object| {
        object.insert(SETTINGS_KEY.into(), Value::String(text.clone()));
    })?;
    Ok(view(environment, configured_path))
}

pub fn delete(environment: &RuntimeEnvironment, confirmed: bool) -> Result<CookieStatus, String> {
    if !confirmed { return Err("Confirm cookie deletion".into()); }
    let target = managed_path(environment).ok_or("无法定位用户目录")?;
    match std::fs::remove_file(&target) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("Cookie 删除失败".into()),
    }
    // Clear the setting only when it points at the managed copy; another explicit file stays.
    let configured_path = set_configured(environment, |object| {
        if configured(object).is_some_and(|p| same_path(&p, &target)) {
            object.remove(SETTINGS_KEY);
        }
    })?;
    Ok(view(environment, configured_path))
}
