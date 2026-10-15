//! 桌面端写入的非敏感 CLI 默认设置：默认路由、超时、全局禁用源、可编辑路由分组，
//! 以及 Twitter cookie 文件的路径引用。
//!
//! 这里读写的 JSON 与 CLI 使用的配置文件相同。保存时只修改已知字段，保留其余字段；
//! 写入前先完成校验，再在同目录创建临时文件并原子替换目标，因此失败时旧配置保持有效。
//! 本模块不会读取或返回 Key、cookie 正文。

use crate::RuntimeEnvironment;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::{
    collections::BTreeMap,
    fs,
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

/// CLI 配置环境变量；设置后 CLI 只读取该路径。
pub const CONFIG_ENV: &str = "MULTI_SEARCH_CONFIG";
pub const TWITTER_ENV: &str = "TWITTER_COOKIES_PATH";
const USER_CONFIG_RELATIVE: &[&str] = &[".multi-search", "multi-search-config.json"];
/// 与 search_runner.py 的 `ALL_SOURCE_NAMES` 保持一致，修改时必须同步。
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
/// 与 search_runner.py 的 `SOURCE_ALIASES` 保持一致。
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

/// 配置缺少 `routes` 时使用的五个内置分组。UI 恢复内置项时也使用同一份映射，
/// 避免桌面端出现第二套工厂定义。
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
    /// `None` 表示调用方未编辑分组，保存时保留文件中的完整映射。
    #[serde(default)]
    pub routes: Option<RouteMap>,
    /// 空值或缺失会清除路径引用；这里绝不接收 cookie 正文。
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
    /// MULTI_SEARCH_CONFIG 选择文件时为 "env"，否则为 "user"。
    pub path_source: String,
    pub file_present: bool,
    /// 展示值的读取来源："env" | "user" | "dev_fallback" | "defaults"。
    pub read_source: String,
    /// 当前值来自仓库开发配置且用户配置尚不存在时为 true；
    /// 保存会创建用户配置，之后 CLI 不再读取开发回退文件。
    pub save_creates_override: bool,
    pub route: String,
    /// 全局超时；分组独立超时优先。
    pub timeout: u32,
    /// 文件中是否存在合法的显式 `timeout`。为 false 时，CLI 旧版内置路由元数据
    /// 仍决定当前实际超时。
    pub timeout_configured: bool,
    pub effective_timeout: u32,
    /// 当前已读取配置下每个路由的实际超时预览。
    pub effective_timeouts: BTreeMap<String, u32>,
    pub routes: RouteMap,
    pub builtin_routes: RouteMap,
    pub disabled_sources: Vec<String>,
    pub twitter_cookies_path: Option<String>,
    /// 设置 TWITTER_COOKIES_PATH 时为 true；环境变量优先于保存的路径引用。
    pub twitter_env_overrides: bool,
    /// 当前路由扣除全局禁用项后会执行的搜索源；为空表示不会执行搜索。
    pub active_sources: Vec<String>,
    /// 状态值："ok" | "no_active_source" | "config_unreadable"。
    pub status: String,
    pub message: String,
}

/// 保存目标：设置 `MULTI_SEARCH_CONFIG` 时严格写入该显式路径，否则写用户配置；
/// 仓库根目录的开发配置永不写入。
pub fn config_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    if let Some(value) = environment
        .variables
        .get(CONFIG_ENV)
        .filter(|v| !v.is_empty())
    {
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

/// 仓库根目录开发回退文件，与 CLI 的 `DEV_CONFIG_PATH` 一致。
/// 本模块只读该文件作为初始值，绝不写入。
fn dev_config_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("multi-search-config.json")
}

/// 按 CLI 的既定优先级选择当前读取源：`MULTI_SEARCH_CONFIG`、已存在的用户配置、
/// 已存在的开发回退文件，最后是内置默认值。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ReadSource {
    Env,
    User,
    DevFallback,
    Defaults,
}

fn read_source(environment: &RuntimeEnvironment, dev: &Path) -> (ReadSource, Option<PathBuf>) {
    if environment
        .variables
        .get(CONFIG_ENV)
        .is_some_and(|v| !v.is_empty())
    {
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

/// 仅在配置没有显式全局超时时使用的旧版 CLI 路由元数据。
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
        if let Some(timeout) = route.timeout {
            if !(1..=60).contains(&timeout) {
                return Err("路由超时时间必须在 1 到 60 秒之间".into());
            }
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

/// 在访问文件前校验用户输入；错误信息不回显被拒绝的值。
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
        route,
        timeout: input.timeout,
        disabled_sources: disabled,
        routes,
        twitter_cookies_path: twitter,
    })
}

/// 读取现有 JSON 对象。文件缺失时返回空对象；无法读取或顶层非对象时返回错误，
/// 从而避免保存覆盖无法保留的内容。
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
        Value::Array(
            valid
                .disabled_sources
                .iter()
                .cloned()
                .map(Value::String)
                .collect(),
        ),
    );
    if let Some(routes) = &valid.routes {
        map.insert(
            "routes".into(),
            serde_json::to_value(routes).expect("validated routes serialize"),
        );
    }
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

/// 用 `object` 原子替换 `path`。临时文件位于同目录，确保最终重命名不跨卷；
/// 任一步失败都会清理临时文件并保留原目标。
fn write_atomic(path: &Path, object: &Map<String, Value>) -> Result<(), String> {
    let dir = path.parent().ok_or("配置路径无效")?;
    fs::create_dir_all(dir).map_err(|_| "无法创建配置目录".to_string())?;
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("config.json");
    let temp = dir.join(format!(".{name}.tmp-{}-{nanos}", std::process::id()));
    let mut body = serde_json::to_string_pretty(&Value::Object(object.clone()))
        .map_err(|_| "无法序列化配置".to_string())?;
    body.push('\n');
    let result = (|| -> std::io::Result<()> {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(body.as_bytes())?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
        return Err("保存失败，原配置未改变".into());
    }
    Ok(())
}

/// 校验输入、合并现有配置并原子替换文件，返回保存后的视图。
pub fn save(
    environment: &RuntimeEnvironment,
    input: &SettingsInput,
) -> Result<SettingsView, String> {
    save_with_dev(environment, input, &dev_config_path())
}

/// 可注入开发回退路径的 `save`，测试用它指向临时文件。
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
    // 显式损坏的 routes/type 会阻止所有保存，不能用新输入静默覆盖。
    let (existing_routes, _) = config_routes(&existing)?;
    let selected_routes = valid.routes.as_ref().unwrap_or(&existing_routes);
    if !selected_routes.contains_key(&valid.route) {
        return Err("当前路由不能被删除，请先切换到其他路由".into());
    }
    let merged = merge(existing, &valid);
    write_atomic(&path, &merged)?;
    Ok(view_with_dev(environment, dev))
}

/// 当前已保存设置，以及当前路由实际会执行的搜索源。
pub fn view(environment: &RuntimeEnvironment) -> SettingsView {
    view_with_dev(environment, &dev_config_path())
}

fn unreadable_view(
    config_path: Option<String>,
    path_source: String,
    file_present: bool,
    read_source: String,
    save_creates_override: bool,
    twitter_env_overrides: bool,
) -> SettingsView {
    SettingsView {
        config_path,
        path_source,
        file_present,
        read_source,
        save_creates_override,
        route: String::new(),
        timeout: 60,
        timeout_configured: false,
        effective_timeout: 60,
        effective_timeouts: BTreeMap::new(),
        routes: RouteMap::new(),
        builtin_routes: builtin_routes(),
        disabled_sources: vec![],
        twitter_cookies_path: None,
        twitter_env_overrides,
        active_sources: vec![],
        status: "config_unreadable".into(),
        message: "现有配置文件无法读取，或 routes/type 不是有效配置；保存已被阻止。".into(),
    }
}

/// 可注入开发回退路径的 `view`，测试用它指向临时文件。
pub fn view_with_dev(environment: &RuntimeEnvironment, dev: &Path) -> SettingsView {
    let path = config_path(environment);
    let path_source = if environment
        .variables
        .get(CONFIG_ENV)
        .is_some_and(|v| !v.is_empty())
    {
        "env"
    } else {
        "user"
    }
    .to_string();
    let file_present = path.as_ref().is_some_and(|p| p.exists());
    let twitter_env_overrides = environment
        .variables
        .get(TWITTER_ENV)
        .is_some_and(|v| !v.is_empty());
    let config_path_text = path.as_ref().map(|p| p.to_string_lossy().into_owned());
    let (read, read_path) = read_source(environment, dev);
    let read_source_text = read.as_str().to_string();
    // 保存会写用户配置，从而覆盖 CLI 当前读取的开发回退文件。
    let save_creates_override =
        read == ReadSource::DevFallback && path_source == "user" && !file_present;
    let object = match read_path.as_deref().map(read_object) {
        Some(Ok(map)) => map,
        Some(Err(_)) => {
            return unreadable_view(
                config_path_text,
                path_source,
                file_present,
                read_source_text,
                save_creates_override,
                twitter_env_overrides,
            )
        }
        None => Map::new(),
    };
    let (routes, route) = match config_routes(&object) {
        Ok(state) => state,
        Err(_) => {
            return unreadable_view(
                config_path_text,
                path_source,
                file_present,
                read_source_text,
                save_creates_override,
                twitter_env_overrides,
            )
        }
    };
    let configured_timeout = object
        .get("timeout")
        .and_then(Value::as_u64)
        .filter(|t| (1..=60).contains(t))
        .map(|t| t as u32);
    let timeout_configured = configured_timeout.is_some();
    // 编辑表单仍以 60 作为全局默认值，但文件缺少 `timeout` 时不能声称它已生效：
    // CLI 此时仍使用内置路由元数据（fast=45、all=90）。
    let timeout = configured_timeout.unwrap_or(60);
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
        .filter(|name| !disabled_sources.contains(name))
        .cloned()
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
        read_source: read_source_text,
        save_creates_override,
        route,
        timeout,
        timeout_configured,
        effective_timeout,
        effective_timeouts,
        routes,
        builtin_routes: builtin_routes(),
        disabled_sources,
        twitter_cookies_path,
        twitter_env_overrides,
        active_sources,
        status: status.into(),
        message,
    }
}
