//! Non-secret CLI defaults written by the desktop: default route, timeout, disabled sources,
//! and the Twitter cookie file *path* reference.
//!
//! The file is the same JSON the CLI reads (`multi_search_mcp/src/support/config.py`). Only the
//! known keys are changed; every other field is preserved. Input is validated before the file
//! is touched, and the new content is written to a temp file in the same directory and then
//! atomically moved over the target, so a failed save leaves the last valid config in place.
//! Keys and cookie bodies never belong in this file and are never read or returned here.

use crate::RuntimeEnvironment;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::{
    fs,
    path::{Path, PathBuf},
};

/// CLI config env var; when set, the CLI reads exactly this path.
pub const CONFIG_ENV: &str = "MULTI_SEARCH_CONFIG";
pub const TWITTER_ENV: &str = "TWITTER_COOKIES_PATH";
const USER_CONFIG_RELATIVE: &[&str] = &[".multi-search", "multi-search-config.json"];
const ROUTES: &[&str] = &["default", "fast", "all", "social", "dev"];
/// Mirrors `ALL_SOURCE_NAMES` in search_runner.py. Change both together.
pub const SOURCES: &[&str] = &[
    "baidu", "brave", "exa", "firecrawl", "github_repos", "hackernews", "parallel", "serpapi",
    "sov2ex", "stackoverflow", "tavily", "twitter",
];
/// Mirrors `SOURCE_ALIASES` in search_runner.py.
const ALIASES: &[(&str, &str)] = &[
    ("baidu-ai-search", "baidu"),
    ("qianfan", "baidu"),
    ("github", "github_repos"),
    ("github-repos", "github_repos"),
    ("v2ex", "sov2ex"),
];
/// Mirrors `ROUTE_PROFILES` in search_runner.py.
fn route_sources(route: &str) -> &'static [&'static str] {
    match route {
        "default" => &["brave", "parallel", "tavily", "exa", "serpapi", "firecrawl", "baidu"],
        "fast" => &["baidu", "tavily", "firecrawl", "exa"],
        "social" => &["twitter"],
        "dev" => &["stackoverflow", "github_repos", "hackernews"],
        "all" => &[
            "brave", "parallel", "tavily", "exa", "serpapi", "baidu", "firecrawl", "twitter",
            "stackoverflow", "github_repos", "hackernews", "sov2ex",
        ],
        _ => &[],
    }
}
const MAX_PATH_BYTES: usize = 1024;

#[derive(Clone, Debug, Deserialize)]
pub struct SettingsInput {
    pub route: String,
    pub timeout: u32,
    #[serde(default)]
    pub disabled_sources: Vec<String>,
    /// Empty or absent clears the reference. Never a cookie body.
    #[serde(default)]
    pub twitter_cookies_path: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Validated {
    pub route: String,
    pub timeout: u32,
    pub disabled_sources: Vec<String>,
    pub twitter_cookies_path: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct SettingsView {
    pub config_path: Option<String>,
    /// "env" when MULTI_SEARCH_CONFIG selects the file, otherwise "user".
    pub path_source: String,
    pub file_present: bool,
    /// Where the displayed values were read from: "env" | "user" | "dev_fallback" | "defaults".
    pub read_source: String,
    /// True when the values come from the repo-root dev file and no user file exists yet:
    /// saving creates the user file, which the CLI then uses instead of the dev file.
    pub save_creates_override: bool,
    pub route: String,
    pub timeout: u32,
    pub disabled_sources: Vec<String>,
    pub twitter_cookies_path: Option<String>,
    /// True when TWITTER_COOKIES_PATH is set: it wins over the saved reference.
    pub twitter_env_overrides: bool,
    /// Sources the current route would run after disabling; empty means nothing will run.
    pub active_sources: Vec<String>,
    /// "ok" | "no_active_source" | "config_unreadable"
    pub status: String,
    pub message: String,
}

/// Save target: `MULTI_SEARCH_CONFIG` when set (explicit target, never redirected), else the
/// user config file. The repo-root dev file is never written.
pub fn config_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    if let Some(value) = environment.variables.get(CONFIG_ENV).filter(|v| !v.is_empty()) {
        return Some(PathBuf::from(value));
    }
    user_config_path(environment)
}

fn user_config_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    let home = environment
        .variables
        .get("USERPROFILE")
        .or_else(|| environment.variables.get("HOME"))
        .filter(|h| !h.is_empty())?;
    let mut path = PathBuf::from(home);
    for part in USER_CONFIG_RELATIVE {
        path.push(part);
    }
    Some(path)
}

/// Repo-root development fallback, the same file the CLI's `DEV_CONFIG_PATH` points to.
/// Read-only for this module: it seeds starting values and is never written.
fn dev_config_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("multi-search-config.json")
}

/// Which file the CLI reads now, in its own order: `MULTI_SEARCH_CONFIG`, then the user file
/// when it exists, then the dev fallback when it exists, else built-in defaults.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ReadSource {
    Env,
    User,
    DevFallback,
    Defaults,
}

fn read_source(environment: &RuntimeEnvironment, dev: &Path) -> (ReadSource, Option<PathBuf>) {
    if environment.variables.get(CONFIG_ENV).is_some_and(|v| !v.is_empty()) {
        return (ReadSource::Env, config_path(environment));
    }
    if let Some(user) = user_config_path(environment).filter(|p| p.exists()) {
        return (ReadSource::User, Some(user));
    }
    if dev.exists() {
        return (ReadSource::DevFallback, Some(dev.to_path_buf()));
    }
    (ReadSource::Defaults, None)
}

impl ReadSource {
    fn as_str(self) -> &'static str {
        match self {
            ReadSource::Env => "env",
            ReadSource::User => "user",
            ReadSource::DevFallback => "dev_fallback",
            ReadSource::Defaults => "defaults",
        }
    }
}

fn source_name(raw: &str) -> Result<&'static str, String> {
    let trimmed = raw.trim();
    let mapped = ALIASES
        .iter()
        .find(|(alias, _)| *alias == trimmed)
        .map(|(_, name)| *name)
        .unwrap_or(trimmed);
    SOURCES
        .iter()
        .copied()
        .find(|name| *name == mapped)
        .ok_or_else(|| "不支持的搜索源".to_string())
}

/// Validate before any file access. Errors never echo the rejected value.
pub fn validate(input: &SettingsInput) -> Result<Validated, String> {
    if !ROUTES.contains(&input.route.as_str()) {
        return Err("不支持的搜索路由".into());
    }
    if !(1..=60).contains(&input.timeout) {
        return Err("超时时间必须在 1 到 60 秒之间".into());
    }
    let mut disabled = Vec::new();
    for raw in &input.disabled_sources {
        let name = source_name(raw)?;
        if !disabled.contains(&name.to_string()) {
            disabled.push(name.to_string());
        }
    }
    disabled.sort();
    let twitter = match input.twitter_cookies_path.as_deref().map(str::trim) {
        None | Some("") => None,
        Some(path) => {
            if path.len() > MAX_PATH_BYTES || path.contains('\0') {
                return Err("Twitter cookie 文件路径无效".into());
            }
            Some(path.to_string())
        }
    };
    Ok(Validated {
        route: input.route.clone(),
        timeout: input.timeout,
        disabled_sources: disabled,
        twitter_cookies_path: twitter,
    })
}

/// Read the existing object. Missing file → empty object. Unreadable or non-object → error,
/// so a save never overwrites content it cannot preserve.
fn read_object(path: &Path) -> Result<Map<String, Value>, String> {
    if !path.exists() {
        return Ok(Map::new());
    }
    let text = fs::read_to_string(path).map_err(|_| "无法读取现有配置文件".to_string())?;
    match serde_json::from_str::<Value>(text.trim_start_matches('\u{feff}')) {
        Ok(Value::Object(map)) => Ok(map),
        _ => Err("现有配置文件不是有效的 JSON 对象，未保存，请先修复或删除该文件".into()),
    }
}

fn merge(existing: Map<String, Value>, valid: &Validated) -> Map<String, Value> {
    let mut map = existing;
    map.insert("type".into(), Value::String(valid.route.clone()));
    map.insert("timeout".into(), Value::from(valid.timeout));
    map.insert(
        "disabled_sources".into(),
        Value::Array(valid.disabled_sources.iter().cloned().map(Value::String).collect()),
    );
    match &valid.twitter_cookies_path {
        Some(path) => {
            map.insert("twitter_cookies_path".into(), Value::String(path.clone()));
        }
        None => {
            map.remove("twitter_cookies_path");
        }
    }
    map
}

/// Atomically replace `path` with `object`. The temp file lives in the same directory so the
/// final rename stays on one volume. On any failure the temp file is removed and the target
/// is left as it was.
fn write_atomic(path: &Path, object: &Map<String, Value>) -> Result<(), String> {
    let dir = path.parent().ok_or("配置路径无效")?;
    fs::create_dir_all(dir).map_err(|_| "无法创建配置目录".to_string())?;
    let mut body = serde_json::to_string_pretty(&Value::Object(object.clone()))
        .map_err(|_| "无法序列化配置".to_string())?;
    body.push('\n');
    // Randomly named, exclusively created sibling, renamed over the target; removed on failure.
    crate::secure_temp::replace_file(path, body.as_bytes()).map_err(|_| "保存失败，原配置未改变".to_string())
}

/// Validate, merge into the existing file, and atomically replace it. Returns the new view.
///
/// When no user file exists yet, the starting object is what the CLI reads today (the dev
/// fallback when present), so fields the CLI already honours are kept. The result is written to
/// the save target only; a dev fallback is never modified.
pub fn save(environment: &RuntimeEnvironment, input: &SettingsInput) -> Result<SettingsView, String> {
    save_with_dev(environment, input, &dev_config_path())
}

/// `save` with the dev fallback location injected (tests point it at a temp file).
pub fn save_with_dev(
    environment: &RuntimeEnvironment,
    input: &SettingsInput,
    dev: &Path,
) -> Result<SettingsView, String> {
    let valid = validate(input)?;
    let path = config_path(environment).ok_or("无法确定配置文件位置")?;
    let existing = match read_source(environment, dev) {
        (ReadSource::Env, _) => read_object(&path)?,
        (ReadSource::User, Some(user)) => read_object(&user)?,
        (ReadSource::DevFallback, Some(dev)) => read_object(&dev)?,
        _ => Map::new(),
    };
    let merged = merge(existing, &valid);
    write_atomic(&path, &merged)?;
    Ok(view_with_dev(environment, dev))
}

/// Current saved settings and the source that will actually run for the current route.
pub fn view(environment: &RuntimeEnvironment) -> SettingsView {
    view_with_dev(environment, &dev_config_path())
}

/// `view` with the dev fallback location injected (tests point it at a temp file).
pub fn view_with_dev(environment: &RuntimeEnvironment, dev: &Path) -> SettingsView {
    let path = config_path(environment);
    let path_source = if environment.variables.get(CONFIG_ENV).is_some_and(|v| !v.is_empty()) {
        "env"
    } else {
        "user"
    }
    .to_string();
    let file_present = path.as_ref().is_some_and(|p| p.exists());
    let twitter_env_overrides = environment.variables.get(TWITTER_ENV).is_some_and(|v| !v.is_empty());
    let config_path_text = path.as_ref().map(|p| p.to_string_lossy().into_owned());
    let (read, read_path) = read_source(environment, dev);
    // Saving writes the user file; that overrides a dev fallback the CLI reads today.
    let save_creates_override = read == ReadSource::DevFallback && path_source == "user" && !file_present;
    let object = match read_path.as_deref().map(read_object) {
        Some(Ok(map)) => Some(map),
        Some(Err(_)) => None,
        None => Some(Map::new()),
    };
    let Some(object) = object else {
        return SettingsView {
            config_path: config_path_text,
            path_source,
            file_present,
            read_source: read.as_str().into(),
            save_creates_override,
            route: "default".into(),
            timeout: 60,
            disabled_sources: vec![],
            twitter_cookies_path: None,
            twitter_env_overrides,
            active_sources: vec![],
            status: "config_unreadable".into(),
            message: "现有配置文件无法读取或不是有效 JSON，保存已被阻止。".into(),
        };
    };
    let route = object
        .get("type")
        .and_then(Value::as_str)
        .filter(|r| ROUTES.contains(r))
        .unwrap_or("default")
        .to_string();
    let timeout = object
        .get("timeout")
        .and_then(Value::as_u64)
        .filter(|t| (1..=60).contains(t))
        .map(|t| t as u32)
        .unwrap_or(60);
    let disabled_sources: Vec<String> = object
        .get("disabled_sources")
        .and_then(Value::as_array)
        .map(|items| {
            let mut names: Vec<String> = items
                .iter()
                .filter_map(Value::as_str)
                .filter_map(|raw| source_name(raw).ok().map(str::to_string))
                .collect();
            names.sort();
            names.dedup();
            names
        })
        .unwrap_or_default();
    let twitter_cookies_path = object
        .get("twitter_cookies_path")
        .and_then(Value::as_str)
        .filter(|p| !p.trim().is_empty())
        .map(str::to_string);
    let active_sources: Vec<String> = route_sources(&route)
        .iter()
        .filter(|name| !disabled_sources.iter().any(|d| d == *name))
        .map(|name| name.to_string())
        .collect();
    let (status, message) = if active_sources.is_empty() {
        (
            "no_active_source",
            format!("当前路由 {route} 的全部搜索源已被禁用，搜索不会运行。请启用至少一个搜索源。"),
        )
    } else {
        ("ok", String::new())
    };
    SettingsView {
        config_path: config_path_text,
        path_source,
        file_present,
        read_source: read.as_str().into(),
        save_creates_override,
        route,
        timeout,
        disabled_sources,
        twitter_cookies_path,
        twitter_env_overrides,
        active_sources,
        status: status.into(),
        message,
    }
}
