//! 桌面搜索设置只保存在 config.sqlite 的 settings JSON 中；旧 JSON/env/dev 文件不参与日常读取。
//! 保存前完整校验动态路由，并在 Immediate 事务内保留所有未知字段。

use crate::provider;
use crate::RuntimeEnvironment;
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

pub const CONFIG_ENV: &str = crate::config_db::DB_ENV;

/// Canonical source name lookup; routes and disabled_sources are stored under
/// the underscore form (`github_repos`, `sov2ex`). Aliases accepted on save
/// are owned by `provider::PROVIDERS` — adding an alias only requires editing
/// that table.
fn source_name(raw: &str) -> Result<&'static str, String> {
    provider::resolve(raw).map(|entry| entry.source)
}

const MAX_PATH_BYTES: usize = 1024;

/// Smallest timeout the desktop accepts.
pub const TIMEOUT_MIN: u32 = 1;
/// Largest timeout the desktop accepts: the longest route default the CLI itself uses (`all`).
/// Keep equal to `max(ROUTE_META[*]["timeout"])`; a Python contract test checks the two agree.
pub const TIMEOUT_MAX: u32 = 90;

/// 通用网页抓取后端的出厂 fallback 链；顺序即默认尝试顺序。
pub const SCRAPE_BACKENDS: &[&str] = &["jina", "exa", "tavily", "firecrawl"];

/// 模型重排的可编辑边界（与 core 的 `ranking` 配置键一致）。
/// mode 只允许 "rrf" / "rrf_model"；profile 见 RERANKER_PROFILES。
pub const RANKING_MODES: &[&str] = &["rrf", "rrf_model"];
pub const RERANKER_PROFILES: &[&str] = &["jev_default"];
pub const RANKING_CANDIDATE_LIMIT_MIN: u32 = 10;
pub const RANKING_CANDIDATE_LIMIT_MAX: u32 = 200;
pub const RANKING_BATCH_SIZE_MIN: u32 = 1;
pub const RANKING_BATCH_SIZE_MAX: u32 = 50;
pub const RANKING_RERANK_TIMEOUT_MIN: u32 = 1;
pub const RANKING_RERANK_TIMEOUT_MAX: u32 = 60;

/// core 的出厂 `ranking` 块；配置缺失或整体非法时作为回退值展示。
fn default_ranking() -> RankingState {
    RankingState {
        mode: "rrf".into(),
        reranker_profile_id: "jev_default".into(),
        candidate_limit: 50,
        batch_size: 20,
        rerank_timeout: 5,
    }
}

fn reranker_profile_label(id: &str) -> &'static str {
    match id {
        "jev_default" => "JEV 默认重排",
        _ => "",
    }
}

fn reranker_profile_options() -> Vec<RerankerProfileOption> {
    RERANKER_PROFILES
        .iter()
        .map(|id| RerankerProfileOption {
            id: (*id).into(),
            label: reranker_profile_label(id).into(),
        })
        .collect()
}

/// 宽容读取已保存的 `ranking`：块缺失或为 null 时回落默认且不报错；
/// 块存在但任一键非法时回落默认并标记 invalid，供 UI 提示而不是假装有效。
/// 未知的同级键不属错误，由 merge 原样保留。
fn ranking_state(object: &Map<String, Value>) -> (RankingState, bool) {
    let value = match object.get("ranking") {
        None | Some(Value::Null) => return (default_ranking(), false),
        Some(value) => value,
    };
    let Some(map) = value.as_object() else {
        return (default_ranking(), true);
    };
    let mode = map.get("mode").and_then(Value::as_str);
    let profile = map.get("reranker_profile_id").and_then(Value::as_str);
    let candidate_limit = map.get("candidate_limit").and_then(Value::as_u64);
    let batch_size = map.get("batch_size").and_then(Value::as_u64);
    let rerank_timeout = map.get("rerank_timeout").and_then(Value::as_u64);
    let valid = mode.is_some_and(|m| RANKING_MODES.contains(&m))
        && profile.is_some_and(|p| RERANKER_PROFILES.contains(&p))
        && candidate_limit.is_some_and(|v| v >= RANKING_CANDIDATE_LIMIT_MIN as u64 && v <= RANKING_CANDIDATE_LIMIT_MAX as u64)
        && batch_size.is_some_and(|v| v >= RANKING_BATCH_SIZE_MIN as u64 && v <= RANKING_BATCH_SIZE_MAX as u64)
        && rerank_timeout.is_some_and(|v| v >= RANKING_RERANK_TIMEOUT_MIN as u64 && v <= RANKING_RERANK_TIMEOUT_MAX as u64);
    if !valid {
        return (default_ranking(), true);
    }
    (
        RankingState {
            mode: mode.unwrap_or_default().to_string(),
            reranker_profile_id: profile.unwrap_or_default().to_string(),
            candidate_limit: candidate_limit.unwrap_or_default() as u32,
            batch_size: batch_size.unwrap_or_default() as u32,
            rerank_timeout: rerank_timeout.unwrap_or_default() as u32,
        },
        false,
    )
}

pub fn scrape_backend_label(name: &str) -> &'static str {
    match name {
        "jina" => "Jina Reader",
        "exa" => "Exa",
        "tavily" => "Tavily",
        "firecrawl" => "Firecrawl",
        _ => "",
    }
}

fn default_scrape_backends() -> Vec<String> {
    SCRAPE_BACKENDS.iter().map(|name| (*name).into()).collect()
}

fn scrape_backend_options() -> Vec<ScrapeBackendOption> {
    SCRAPE_BACKENDS
        .iter()
        .map(|name| ScrapeBackendOption {
            name: (*name).into(),
            label: scrape_backend_label(name).into(),
        })
        .collect()
}

/// 宽容读取已保存的链：忽略未知/重复项；全部无效或缺失时回落出厂默认。
/// 第二个返回值标记“已保存值非法”，供 UI 显示警示，而不是假装是有效设置。
fn scrape_chain(object: &Map<String, Value>) -> (Vec<String>, bool) {
    let value = match object.get("scrape_backends") {
        None | Some(Value::Null) => return (default_scrape_backends(), false),
        Some(value) => value,
    };
    let Value::Array(items) = value else {
        return (default_scrape_backends(), true);
    };
    let mut chain = Vec::new();
    let mut invalid = false;
    for item in items {
        let Some(raw) = item.as_str() else {
            invalid = true;
            continue;
        };
        let name = raw.trim();
        if !SCRAPE_BACKENDS.contains(&name) {
            invalid = true;
            continue;
        }
        if !chain.iter().any(|saved| saved == name) {
            chain.push(name.to_string());
        }
    }
    if items.is_empty() {
        invalid = true;
    }
    if chain.is_empty() {
        (default_scrape_backends(), invalid)
    } else {
        (chain, invalid)
    }
}

#[derive(Clone, Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct ScrapeBackendOption {
    pub name: String,
    pub label: String,
}

/// 模型重排的可选 profile；v1 只有 `jev_default`。密钥只走后端环境变量，UI 不持有。
#[derive(Clone, Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct RerankerProfileOption {
    pub id: String,
    pub label: String,
}

/// 保存时提交的 `ranking` 块；字段名与 core 的配置键严格一致。
#[derive(Clone, Debug, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct RankingInput {
    /// 只允许 "rrf" / "rrf_model"。
    pub mode: String,
    pub reranker_profile_id: String,
    pub candidate_limit: u32,
    pub batch_size: u32,
    pub rerank_timeout: u32,
}

/// `SettingsView` 回传的当前生效 `ranking`；非法存储值被回退成出厂默认并伴随
/// `ranking_invalid` 标志。
#[derive(Clone, Debug, PartialEq, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct RankingState {
    pub mode: String,
    pub reranker_profile_id: String,
    pub candidate_limit: u32,
    pub batch_size: u32,
    pub rerank_timeout: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[serde(deny_unknown_fields)]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
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
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct SettingsInput {
    pub route: String,
    /// `None` keeps the stored `timeout` exactly as it is (including absent), so a caller that
    /// did not edit the timeout can never rewrite it.
    #[serde(default)]
    pub timeout: Option<u32>,
    #[serde(default)]
    pub disabled_sources: Vec<String>,
    #[serde(default)]
    pub routes: Option<RouteMap>,
    #[serde(default)]
    pub twitter_cookies_path: Option<String>,
    /// `None` 表示本次保存不动该键；`Some(vec)` 才写入。
    #[serde(default)]
    pub scrape_backends: Option<Vec<String>>,
    /// `None` 表示本次保存整块 `ranking` 都不动；`Some` 时按块内已知键合并，
    /// 块里不认识的同级键原样保留。
    #[serde(default)]
    pub ranking: Option<RankingInput>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Validated {
    pub route: String,
    pub timeout: Option<u32>,
    pub disabled_sources: Vec<String>,
    pub routes: Option<RouteMap>,
    pub twitter_cookies_path: Option<String>,
    pub scrape_backends: Option<Vec<String>>,
    pub ranking: Option<RankingState>,
}

#[derive(Clone, Debug, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct SettingsView {
    pub config_path: Option<String>,
    pub path_source: String,
    pub file_present: bool,
    pub read_source: String,
    pub route: String,
    pub timeout: u32,
    pub timeout_configured: bool,
    /// Editable bounds; a stored value outside them is still shown and preserved unchanged.
    pub timeout_min: u32,
    pub timeout_max: u32,
    /// True when the stored timeout is outside `timeout_min..=timeout_max`. Only an edited value
    /// must be in range.
    pub timeout_out_of_range: bool,
    pub effective_timeout: u32,
    pub effective_timeouts: BTreeMap<String, u32>,
    pub routes: RouteMap,
    pub builtin_routes: RouteMap,
    pub disabled_sources: Vec<String>,
    /// Entries in `disabled_sources` the desktop does not recognise. Never dropped on save.
    pub unknown_disabled_sources: Vec<String>,
    pub twitter_cookies_path: Option<String>,
    /// 当前生效的抓取 fallback 链（settings 缺失/非法时回退出厂默认）。
    pub scrape_backends: Vec<String>,
    /// 已保存的 `scrape_backends` 非法（空数组、非数组、含非字符串或未知后端）；
    /// 此时 `scrape_backends` 是回退值，CLI 会报配置错误，UI 必须提示。
    pub scrape_backends_invalid: bool,
    pub builtin_scrape_backends: Vec<String>,
    pub scrape_backend_options: Vec<ScrapeBackendOption>,
    pub active_sources: Vec<String>,
    /// 当前生效的 `ranking` 块（缺失/非法时回退出厂默认）。
    pub ranking: RankingState,
    /// 已保存的 `ranking` 块非法（非对象、未知 mode/profile、数值缺省或越界）；
    /// 此时 `ranking` 是回退值，UI 必须提示而不是假装有效。
    pub ranking_invalid: bool,
    /// `ranking` 数值键的可编辑上下界；越界的已存值仍以原样展示并保留。
    pub ranking_candidate_limit_min: u32,
    pub ranking_candidate_limit_max: u32,
    pub ranking_batch_size_min: u32,
    pub ranking_batch_size_max: u32,
    pub ranking_rerank_timeout_min: u32,
    pub ranking_rerank_timeout_max: u32,
    /// 可选的重排 profile；v1 只有 `jev_default`。
    pub reranker_profiles: Vec<RerankerProfileOption>,
    /// ok | config_unreadable | no_active_source, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub message: String,
}

pub fn config_path(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    crate::config_db::path(&environment.variables)
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

/// Mirrors the per-route `timeout` defaults in `ROUTE_META` (search_runner.py). The CLI uses
/// these when the config has no `timeout`; the desktop reports them so it never invents a value.
pub fn route_default_timeout(route: &str) -> u32 {
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
            .is_some_and(|timeout| !(TIMEOUT_MIN..=TIMEOUT_MAX).contains(&timeout))
        {
            return Err(format!("路由超时时间必须在 {TIMEOUT_MIN} 到 {TIMEOUT_MAX} 秒之间"));
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
    if input
        .timeout
        .is_some_and(|timeout| !(TIMEOUT_MIN..=TIMEOUT_MAX).contains(&timeout))
    {
        return Err(format!("超时时间必须在 {TIMEOUT_MIN} 到 {TIMEOUT_MAX} 秒之间"));
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
    let scrape_backends = match &input.scrape_backends {
        None => None,
        Some(items) => {
            let mut chain: Vec<String> = Vec::new();
            for raw in items {
                let name = raw.trim();
                if !SCRAPE_BACKENDS.contains(&name) {
                    return Err(format!("不支持的抓取后端：{name}"));
                }
                if !chain.iter().any(|saved| saved == name) {
                    chain.push(name.to_string());
                }
            }
            if chain.is_empty() {
                return Err("抓取顺序至少要保留一个后端".into());
            }
            Some(chain)
        }
    };
    let ranking = input.ranking.as_ref().map(validate_ranking).transpose()?;
    Ok(Validated {
        route,
        timeout: input.timeout,
        disabled_sources: disabled,
        routes,
        twitter_cookies_path: twitter,
        scrape_backends,
        ranking,
    })
}

/// 校验提交的 `ranking` 块：mode 白名单、profile 白名单、三个数值各自的上下界。
/// 错误文案与 `timeout` 一样用中文说明合法范围。
fn validate_ranking(input: &RankingInput) -> Result<RankingState, String> {
    let mode = input.mode.trim();
    if !RANKING_MODES.contains(&mode) {
        return Err("重排模式必须是 rrf 或 rrf_model".into());
    }
    let profile = input.reranker_profile_id.trim();
    if !RERANKER_PROFILES.contains(&profile) {
        return Err("不支持的重排模型配置".into());
    }
    if !(RANKING_CANDIDATE_LIMIT_MIN..=RANKING_CANDIDATE_LIMIT_MAX)
        .contains(&input.candidate_limit)
    {
        return Err(format!(
            "候选数必须在 {RANKING_CANDIDATE_LIMIT_MIN} 到 {RANKING_CANDIDATE_LIMIT_MAX} 之间"
        ));
    }
    if !(RANKING_BATCH_SIZE_MIN..=RANKING_BATCH_SIZE_MAX).contains(&input.batch_size) {
        return Err(format!(
            "重排批量必须在 {RANKING_BATCH_SIZE_MIN} 到 {RANKING_BATCH_SIZE_MAX} 之间"
        ));
    }
    if !(RANKING_RERANK_TIMEOUT_MIN..=RANKING_RERANK_TIMEOUT_MAX).contains(&input.rerank_timeout)
    {
        return Err(format!(
            "重排超时必须在 {RANKING_RERANK_TIMEOUT_MIN} 到 {RANKING_RERANK_TIMEOUT_MAX} 秒之间"
        ));
    }
    Ok(RankingState {
        mode: mode.to_string(),
        reranker_profile_id: profile.to_string(),
        candidate_limit: input.candidate_limit,
        batch_size: input.batch_size,
        rerank_timeout: input.rerank_timeout,
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
    if let Some(timeout) = valid.timeout {
        map.insert("timeout".into(), Value::from(timeout));
    }
    // Known entries are replaced by the edit; entries the desktop does not recognise (a newer
    // CLI's source, or a non-string value) are never dropped.
    let unknown: Vec<Value> = map
        .get("disabled_sources")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter(|item| item.as_str().is_none_or(|raw| source_name(raw).is_err()))
                .cloned()
                .collect()
        })
        .unwrap_or_default();
    let mut disabled: Vec<Value> = valid
        .disabled_sources
        .iter()
        .cloned()
        .map(Value::String)
        .collect();
    disabled.extend(unknown);
    map.insert("disabled_sources".into(), Value::Array(disabled));
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
    if let Some(chain) = &valid.scrape_backends {
        map.insert("scrape_backends".into(), serde_json::json!(chain));
    }
    if let Some(ranking) = &valid.ranking {
        // 合并进既有 ranking 对象而不是整块替换：块里不认识的同级键原样保留；
        // 已有值不是对象时由校验后的完整块替换。
        let mut block = match map.get("ranking") {
            Some(Value::Object(existing)) => existing.clone(),
            _ => Map::new(),
        };
        block.insert("mode".into(), Value::String(ranking.mode.clone()));
        block.insert(
            "reranker_profile_id".into(),
            Value::String(ranking.reranker_profile_id.clone()),
        );
        block.insert("candidate_limit".into(), Value::from(ranking.candidate_limit));
        block.insert("batch_size".into(), Value::from(ranking.batch_size));
        block.insert("rerank_timeout".into(), Value::from(ranking.rerank_timeout));
        map.insert("ranking".into(), Value::Object(block));
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

/// Patch only scrape_backends while holding the database write lock.
pub fn save_scrape_backends(environment: &RuntimeEnvironment, backends: &[String]) -> Result<SettingsView, String> {
    let mut chain: Vec<String> = Vec::new();
    for raw in backends {
        let name = raw.trim();
        if !SCRAPE_BACKENDS.contains(&name) { return Err(format!("不支持的抓取后端：{name}")); }
        if !chain.iter().any(|saved| saved == name) { chain.push(name.to_string()); }
    }
    if chain.is_empty() { return Err("抓取顺序至少要保留一个后端".into()); }
    let path = config_path(environment).ok_or("无法定位配置数据库")?;
    let mut connection = crate::config_db::open(&path)?;
    let transaction = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "配置数据库事务失败".to_string())?;
    let mut existing = read_object(&transaction)?;
    config_routes(&existing)?;
    existing.insert("scrape_backends".into(), serde_json::json!(chain));
    let body = serde_json::to_string(&existing).map_err(|_| "无法序列化设置".to_string())?;
    transaction.execute("INSERT INTO settings(id,data) VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data", [body])
        .map_err(|_| "保存失败，原设置未改变".to_string())?;
    transaction.commit().map_err(|_| "保存失败，原设置未改变".to_string())?;
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
        timeout_min: TIMEOUT_MIN,
        timeout_max: TIMEOUT_MAX,
        timeout_out_of_range: false,
        effective_timeout: 60,
        effective_timeouts: BTreeMap::new(),
        routes: RouteMap::new(),
        builtin_routes: builtin_routes(),
        disabled_sources: vec![],
        unknown_disabled_sources: vec![],
        twitter_cookies_path: None,
        scrape_backends: default_scrape_backends(),
        scrape_backends_invalid: false,
        builtin_scrape_backends: default_scrape_backends(),
        scrape_backend_options: scrape_backend_options(),
        active_sources: vec![],
        ranking: default_ranking(),
        ranking_invalid: false,
        ranking_candidate_limit_min: RANKING_CANDIDATE_LIMIT_MIN,
        ranking_candidate_limit_max: RANKING_CANDIDATE_LIMIT_MAX,
        ranking_batch_size_min: RANKING_BATCH_SIZE_MIN,
        ranking_batch_size_max: RANKING_BATCH_SIZE_MAX,
        ranking_rerank_timeout_min: RANKING_RERANK_TIMEOUT_MIN,
        ranking_rerank_timeout_max: RANKING_RERANK_TIMEOUT_MAX,
        reranker_profiles: reranker_profile_options(),
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
        .filter(|timeout| *timeout >= 1 && *timeout <= u32::MAX as u64)
        .map(|timeout| timeout as u32);
    let timeout_configured = configured_timeout.is_some();
    let timeout = configured_timeout.unwrap_or_else(|| route_default_timeout(&route));
    // Non-string entries are reported in their JSON spelling so the UI can show them.
    let raw_disabled: Vec<String> = object
        .get("disabled_sources")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(|item| match item {
                    Value::String(text) => text.clone(),
                    other => other.to_string(),
                })
                .collect()
        })
        .unwrap_or_default();
    let unknown_disabled_sources: Vec<String> = raw_disabled
        .iter()
        .filter(|raw| source_name(raw).is_err())
        .cloned()
        .collect();
    let mut disabled_sources: Vec<String> = raw_disabled
        .iter()
        .filter_map(|raw| source_name(raw).ok().map(str::to_string))
        .collect();
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
                    .unwrap_or_else(|| route_default_timeout(id)),
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
    let (scrape_backends, scrape_backends_invalid) = scrape_chain(&object);
    let (ranking, ranking_invalid) = ranking_state(&object);
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
        timeout_min: TIMEOUT_MIN,
        timeout_max: TIMEOUT_MAX,
        timeout_out_of_range: !(TIMEOUT_MIN..=TIMEOUT_MAX).contains(&timeout),
        route,
        timeout,
        timeout_configured,
        effective_timeout,
        effective_timeouts,
        routes,
        builtin_routes: builtin_routes(),
        disabled_sources,
        unknown_disabled_sources,
        twitter_cookies_path: object
            .get("twitter_cookies_path")
            .and_then(Value::as_str)
            .filter(|path| !path.trim().is_empty())
            .map(str::to_string),
        scrape_backends,
        scrape_backends_invalid,
        builtin_scrape_backends: default_scrape_backends(),
        scrape_backend_options: scrape_backend_options(),
        active_sources,
        ranking,
        ranking_invalid,
        ranking_candidate_limit_min: RANKING_CANDIDATE_LIMIT_MIN,
        ranking_candidate_limit_max: RANKING_CANDIDATE_LIMIT_MAX,
        ranking_batch_size_min: RANKING_BATCH_SIZE_MIN,
        ranking_batch_size_max: RANKING_BATCH_SIZE_MAX,
        ranking_rerank_timeout_min: RANKING_RERANK_TIMEOUT_MIN,
        ranking_rerank_timeout_max: RANKING_RERANK_TIMEOUT_MAX,
        reranker_profiles: reranker_profile_options(),
        status: status.into(),
        message,
    }
}
