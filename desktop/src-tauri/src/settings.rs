//! Non-secret search settings, persisted only in config.sqlite. Legacy files are migration inputs.
use crate::RuntimeEnvironment;
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};
pub const CONFIG_ENV: &str = crate::config_db::DB_ENV;
const ROUTES: &[&str] = &["default", "fast", "all", "social", "dev"];
pub const SOURCES: &[&str] = &[
    "baidu",
    "brave",
    "exa",
    "firecrawl",
    "github_repos",
    "hackernews",
    "parallel",
    "serpapi",
    "sov2ex",
    "stackoverflow",
    "tavily",
    "twitter",
];
const ALIASES: &[(&str, &str)] = &[
    ("baidu-ai-search", "baidu"),
    ("qianfan", "baidu"),
    ("github", "github_repos"),
    ("github-repos", "github_repos"),
    ("v2ex", "sov2ex"),
];
fn route_sources(route: &str) -> &'static [&'static str] {
    match route {
        "default" => &[
            "brave",
            "parallel",
            "tavily",
            "exa",
            "serpapi",
            "firecrawl",
            "baidu",
        ],
        "fast" => &["baidu", "tavily", "firecrawl", "exa"],
        "social" => &["twitter"],
        "dev" => &["stackoverflow", "github_repos", "hackernews"],
        "all" => &[
            "brave",
            "parallel",
            "tavily",
            "exa",
            "serpapi",
            "baidu",
            "firecrawl",
            "twitter",
            "stackoverflow",
            "github_repos",
            "hackernews",
            "sov2ex",
        ],
        _ => &[],
    }
}
#[derive(Clone, Debug, Deserialize)]
pub struct SettingsInput {
    pub route: String,
    pub timeout: u32,
    #[serde(default)]
    pub disabled_sources: Vec<String>,
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
    pub path_source: String,
    pub file_present: bool,
    pub read_source: String,
    pub route: String,
    pub timeout: u32,
    pub disabled_sources: Vec<String>,
    pub twitter_cookies_path: Option<String>,
    pub active_sources: Vec<String>,
    pub status: String,
    pub message: String,
}
pub fn config_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    crate::config_db::path(&environment.variables)
}
fn source_name(raw: &str) -> Result<&'static str, String> {
    let trimmed = raw.trim();
    let mapped = ALIASES
        .iter()
        .find(|(a, _)| *a == trimmed)
        .map(|(_, n)| *n)
        .unwrap_or(trimmed);
    SOURCES
        .iter()
        .copied()
        .find(|n| *n == mapped)
        .ok_or_else(|| "不支持的搜索源".into())
}
pub fn validate(input: &SettingsInput) -> Result<Validated, String> {
    if !ROUTES.contains(&input.route.as_str()) {
        return Err("不支持的搜索路由".into());
    }
    if !(1..=60).contains(&input.timeout) {
        return Err("超时时间必须在 1 到 60 秒之间".into());
    }
    let mut disabled = Vec::new();
    for raw in &input.disabled_sources {
        let name = source_name(raw)?.to_string();
        if !disabled.contains(&name) {
            disabled.push(name);
        }
    }
    disabled.sort();
    let twitter = match input.twitter_cookies_path.as_deref().map(str::trim) {
        None | Some("") => None,
        Some(path) => {
            if path.len() > 1024 || path.contains('\0') {
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
fn read_object(connection: &rusqlite::Connection) -> Result<Map<String, Value>, String> {
    let text: Option<String> = connection
        .query_row("SELECT data FROM settings WHERE id=1", [], |r| r.get(0))
        .optional()
        .map_err(|_| "无法读取配置数据库设置".to_string())?;
    match text {
        None => Ok(Map::new()),
        Some(text) => match serde_json::from_str(&text) {
            Ok(Value::Object(map)) => Ok(map),
            _ => Err("现有设置不是有效 JSON 对象，未保存".into()),
        },
    }
}
fn merge(mut map: Map<String, Value>, valid: &Validated) -> Map<String, Value> {
    map.insert("type".into(), Value::String(valid.route.clone()));
    map.insert("timeout".into(), Value::from(valid.timeout));
    map.insert(
        "disabled_sources".into(),
        serde_json::json!(valid.disabled_sources),
    );
    if let Some(path) = &valid.twitter_cookies_path {
        map.insert("twitter_cookies_path".into(), Value::String(path.clone()));
    } else {
        map.remove("twitter_cookies_path");
    }
    map
}
pub fn save(
    environment: &RuntimeEnvironment,
    input: &SettingsInput,
) -> Result<SettingsView, String> {
    let valid = validate(input)?;
    let path = config_path(environment).ok_or("无法定位配置数据库")?;
    let mut connection = crate::config_db::open(&path)?;
    let transaction = connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "配置数据库事务失败".to_string())?;
    let object = merge(read_object(&transaction)?, &valid);
    let body = serde_json::to_string(&object).map_err(|_| "无法序列化设置".to_string())?;
    transaction.execute("INSERT INTO settings(id,data) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data", [body]).map_err(|_| "保存失败，原设置未改变".to_string())?;
    transaction
        .commit()
        .map_err(|_| "保存失败，原设置未改变".to_string())?;
    Ok(view(environment))
}
// Retained injection seam: dev paths deliberately never participate in normal resolution.
pub fn save_with_dev(
    environment: &RuntimeEnvironment,
    input: &SettingsInput,
    _: &Path,
) -> Result<SettingsView, String> {
    save(environment, input)
}
pub fn view_with_dev(environment: &RuntimeEnvironment, _: &Path) -> SettingsView {
    view(environment)
}
pub fn view(environment: &RuntimeEnvironment) -> SettingsView {
    let path = config_path(environment);
    let present = path.as_ref().is_some_and(|p| p.exists());
    let object = if present {
        path.as_ref()
            .ok_or_else(|| "无法定位配置数据库".to_string())
            .and_then(|p| crate::config_db::open(p))
            .and_then(|c| read_object(&c))
    } else {
        Ok(Map::new())
    };
    let error = object.is_err();
    let map = object.unwrap_or_default();
    let route = map
        .get("type")
        .and_then(Value::as_str)
        .filter(|r| ROUTES.contains(r))
        .unwrap_or("default")
        .to_string();
    let timeout = map
        .get("timeout")
        .and_then(Value::as_u64)
        .filter(|n| (1..=60).contains(n))
        .unwrap_or(60) as u32;
    let mut disabled_sources: Vec<String> = map
        .get("disabled_sources")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .filter_map(|s| source_name(s).ok().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    disabled_sources.sort();
    disabled_sources.dedup();
    let active_sources: Vec<String> = if error {
        vec![]
    } else {
        route_sources(&route)
            .iter()
            .filter(|n| !disabled_sources.iter().any(|d| d == *n))
            .map(|n| n.to_string())
            .collect()
    };
    let status = if error {
        "config_unreadable"
    } else if active_sources.is_empty() {
        "no_active_source"
    } else {
        "ok"
    };
    let message = if error {
        "配置数据库无法读取，保存已被阻止。".into()
    } else if active_sources.is_empty() {
        format!("当前路由 {route} 的全部搜索源已被禁用，搜索不会运行。")
    } else {
        String::new()
    };
    SettingsView {
        config_path: path.map(|p| p.to_string_lossy().into_owned()),
        path_source: if environment
            .variables
            .get(CONFIG_ENV)
            .is_some_and(|v| !v.is_empty())
        {
            "env"
        } else {
            "user"
        }
        .into(),
        file_present: present,
        read_source: if present { "sqlite" } else { "defaults" }.into(),
        route,
        timeout,
        disabled_sources,
        twitter_cookies_path: map
            .get("twitter_cookies_path")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        active_sources,
        status: status.into(),
        message,
    }
}
