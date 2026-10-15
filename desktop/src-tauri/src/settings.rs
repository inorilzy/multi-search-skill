//! 桌面搜索设置只保存在 config.sqlite 的 settings JSON 中；旧 JSON/env/dev 文件不参与日常读取。
//! 保存前完整校验动态路由，并在 Immediate 事务内保留所有未知字段。

use crate::RuntimeEnvironment;
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

pub const CONFIG_ENV: &str = crate::config_db::DB_ENV;
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
const MAX_PATH_BYTES: usize = 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RouteConfig {
    pub label: String,
    pub sources: Vec<String>,
    #[serde(default)]
    pub timeout: Option<u32>,
}

pub type RouteMap = BTreeMap<String, RouteConfig>;

fn route(label: &str, sources: &[&str]) -> RouteConfig {
    RouteConfig {
        label: label.into(),
        sources: sources.iter().map(|source| (*source).into()).collect(),
        timeout: None,
    }
}

pub fn builtin_routes() -> RouteMap {
    BTreeMap::from([
        (
            "default".into(),
            route(
                "默认（网页综合）",
                &[
                    "brave",
                    "parallel",
                    "tavily",
                    "exa",
                    "serpapi",
                    "firecrawl",
                    "baidu",
                ],
            ),
        ),
        (
            "fast".into(),
            route("快速", &["baidu", "tavily", "firecrawl", "exa"]),
        ),
        (
            "all".into(),
            route(
                "全部",
                &[
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
            ),
        ),
        ("social".into(), route("社交（Twitter）", &["twitter"])),
        (
            "dev".into(),
            route(
                "开发者（Stack Overflow / GitHub / Hacker News）",
                &["stackoverflow", "github_repos", "hackernews"],
            ),
        ),
    ])
}

#[derive(Clone, Debug, Deserialize)]
pub struct SettingsInput {
    pub route: String,
    pub timeout: u32,
    #[serde(default)]
    pub disabled_sources: Vec<String>,
    #[serde(default)]
    pub routes: Option<RouteMap>,
    #[serde(default)]
    pub twitter_cookies_path: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Validated {
    pub route: String,
    pub timeout: u32,
    pub disabled_sources: Vec<String>,
    pub routes: Option<RouteMap>,
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
    pub timeout_configured: bool,
    pub effective_timeout: u32,
    pub effective_timeouts: BTreeMap<String, u32>,
    pub routes: RouteMap,
    pub builtin_routes: RouteMap,
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
        .find(|(alias, _)| *alias == trimmed)
        .map(|(_, name)| *name)
        .unwrap_or(trimmed);
    SOURCES
        .iter()
        .copied()
        .find(|name| *name == mapped)
        .ok_or_else(|| "不支持的搜索源".to_string())
}

fn route_id_valid(id: &str) -> bool {
    (1..=64).contains(&id.len())
        && id != "web"
        && id.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_' || byte == b'-'
        })
}

fn canonical_route_id(raw: &str) -> String {
    if raw == "web" { "default" } else { raw }.to_string()
}

fn builtin_meta_timeout(route: &str) -> u32 {
    match route {
        "fast" => 45,
        "all" => 90,
        _ => 60,
    }
}

fn normalize_routes(routes: &RouteMap) -> Result<RouteMap, String> {
    if routes.is_empty() {
        return Err("至少需要一个搜索路由分组".into());
    }
    let mut normalized = RouteMap::new();
    for (id, route) in routes {
        if !route_id_valid(id) {
            return Err(
                "路由标识必须是 1 到 64 个 ASCII 小写字母、数字、下划线或连字符，且不能使用 web"
                    .into(),
            );
        }
        let label = route.label.trim();
        if !(1..=80).contains(&label.chars().count()) {
            return Err("路由名称必须是 1 到 80 个字符".into());
        }
        if route.sources.is_empty() {
            return Err("每个路由至少需要一个搜索源".into());
        }
        let mut sources = Vec::new();
        for raw in &route.sources {
            let source = source_name(raw)?.to_string();
            if !sources.contains(&source) {
                sources.push(source);
            }
        }
        if route
            .timeout
            .is_some_and(|timeout| !(1..=60).contains(&timeout))
        {
            return Err("路由超时时间必须在 1 到 60 秒之间".into());
        }
        normalized.insert(
            id.clone(),
            RouteConfig {
                label: label.into(),
                sources,
                timeout: route.timeout,
            },
        );
    }
    Ok(normalized)
}

fn routes_from_object(object: &Map<String, Value>) -> Result<RouteMap, String> {
    let Some(value) = object.get("routes") else {
        return Ok(builtin_routes());
    };
    let routes: RouteMap = serde_json::from_value(value.clone())
        .map_err(|_| "routes 必须是完整且有效的路由对象".to_string())?;
    normalize_routes(&routes)
}

fn selected_route(object: &Map<String, Value>, routes: &RouteMap) -> Result<String, String> {
    let route = match object.get("type") {
        None | Some(Value::Null) => "default".to_string(),
        Some(Value::String(route)) => canonical_route_id(route),
        Some(_) => return Err("type 必须是有效的路由标识".into()),
    };
    if !routes.contains_key(&route) {
        return Err("type 引用的路由不存在".into());
    }
    Ok(route)
}

fn config_routes(object: &Map<String, Value>) -> Result<(RouteMap, String), String> {
    let routes = routes_from_object(object)?;
    let route = selected_route(object, &routes)?;
    Ok((routes, route))
}

pub fn validate(input: &SettingsInput) -> Result<Validated, String> {
    let route = canonical_route_id(&input.route);
    if !route_id_valid(&route) {
        return Err("不支持的搜索路由".into());
    }
    if !(1..=60).contains(&input.timeout) {
        return Err("超时时间必须在 1 到 60 秒之间".into());
    }
    let routes = input.routes.as_ref().map(normalize_routes).transpose()?;
    if routes
        .as_ref()
        .is_some_and(|routes| !routes.contains_key(&route))
    {
        return Err("当前路由不能被删除，请先切换到其他路由".into());
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
            if path.len() > MAX_PATH_BYTES || path.contains('\0') {
                return Err("Twitter cookie 文件路径无效".into());
            }
            Some(path.to_string())
        }
    };
    Ok(Validated {
        route,
        timeout: input.timeout,
        disabled_sources: disabled,
        routes,
        twitter_cookies_path: twitter,
    })
}

fn read_object(connection: &rusqlite::Connection) -> Result<Map<String, Value>, String> {
    let text: Option<String> = connection
        .query_row("SELECT data FROM settings WHERE id=1", [], |row| row.get(0))
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
    if let Some(routes) = &valid.routes {
        map.insert(
            "routes".into(),
            serde_json::to_value(routes).expect("validated routes serialize"),
        );
    }
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
    let existing = read_object(&transaction)?;
    let (existing_routes, _) = config_routes(&existing)?;
    let selected_routes = valid.routes.as_ref().unwrap_or(&existing_routes);
    if !selected_routes.contains_key(&valid.route) {
        return Err("当前路由不能被删除，请先切换到其他路由".into());
    }
    let object = merge(existing, &valid);
    let body = serde_json::to_string(&object).map_err(|_| "无法序列化设置".to_string())?;
    transaction
        .execute(
            "INSERT INTO settings(id,data) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            [body],
        )
        .map_err(|_| "保存失败，原设置未改变".to_string())?;
    transaction
        .commit()
        .map_err(|_| "保存失败，原设置未改变".to_string())?;
    Ok(view(environment))
}

// 保留测试注入缝；旧开发 JSON 路径不参与正常解析。
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

fn unreadable_view(path: Option<PathBuf>, environment: &RuntimeEnvironment) -> SettingsView {
    let present = path.as_ref().is_some_and(|path| path.exists());
    SettingsView {
        config_path: path.map(|path| path.to_string_lossy().into_owned()),
        path_source: if environment
            .variables
            .get(CONFIG_ENV)
            .is_some_and(|value| !value.is_empty())
        {
            "env"
        } else {
            "user"
        }
        .into(),
        file_present: present,
        read_source: if present { "sqlite" } else { "defaults" }.into(),
        route: String::new(),
        timeout: 60,
        timeout_configured: false,
        effective_timeout: 60,
        effective_timeouts: BTreeMap::new(),
        routes: RouteMap::new(),
        builtin_routes: builtin_routes(),
        disabled_sources: vec![],
        twitter_cookies_path: None,
        active_sources: vec![],
        status: "config_unreadable".into(),
        message: "配置数据库无法读取，或 routes/type 不是有效配置；保存已被阻止。".into(),
    }
}

pub fn view(environment: &RuntimeEnvironment) -> SettingsView {
    let path = config_path(environment);
    let present = path.as_ref().is_some_and(|path| path.exists());
    let object = if present {
        path.as_ref()
            .ok_or_else(|| "无法定位配置数据库".to_string())
            .and_then(|path| crate::config_db::open(path))
            .and_then(|connection| read_object(&connection))
    } else {
        Ok(Map::new())
    };
    let object = match object {
        Ok(object) => object,
        Err(_) => return unreadable_view(path, environment),
    };
    let (routes, route) = match config_routes(&object) {
        Ok(state) => state,
        Err(_) => return unreadable_view(path, environment),
    };
    let configured_timeout = object
        .get("timeout")
        .and_then(Value::as_u64)
        .filter(|timeout| (1..=60).contains(timeout))
        .map(|timeout| timeout as u32);
    let timeout_configured = configured_timeout.is_some();
    let timeout = configured_timeout.unwrap_or(60);
    let mut disabled_sources: Vec<String> = object
        .get("disabled_sources")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .filter_map(|raw| source_name(raw).ok().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    disabled_sources.sort();
    disabled_sources.dedup();
    let effective_timeouts: BTreeMap<String, u32> = routes
        .iter()
        .map(|(id, config)| {
            (
                id.clone(),
                config
                    .timeout
                    .or(configured_timeout)
                    .unwrap_or_else(|| builtin_meta_timeout(id)),
            )
        })
        .collect();
    let selected = routes.get(&route).expect("selected route was validated");
    let effective_timeout = effective_timeouts[&route];
    let active_sources: Vec<String> = selected
        .sources
        .iter()
        .filter(|source| !disabled_sources.contains(source))
        .cloned()
        .collect();
    let (status, message) = if active_sources.is_empty() {
        (
            "no_active_source",
            format!("当前路由 {route} 的全部搜索源已被禁用，搜索不会运行。"),
        )
    } else {
        ("ok", String::new())
    };
    SettingsView {
        config_path: path.map(|path| path.to_string_lossy().into_owned()),
        path_source: if environment
            .variables
            .get(CONFIG_ENV)
            .is_some_and(|value| !value.is_empty())
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
        timeout_configured,
        effective_timeout,
        effective_timeouts,
        routes,
        builtin_routes: builtin_routes(),
        disabled_sources,
        twitter_cookies_path: object
            .get("twitter_cookies_path")
            .and_then(Value::as_str)
            .filter(|path| !path.trim().is_empty())
            .map(str::to_string),
        active_sources,
        status: status.into(),
        message,
    }
}
