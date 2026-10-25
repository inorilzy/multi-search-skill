//! Allowlisted desktop credential operations. Overview is non-secret; read returns one source
//! only when its editor is expanded. All native persistence is SQLite/DPAPI, never legacy fallback.
#![cfg_attr(not(feature = "native-window"), allow(dead_code))]
use crate::credential::{self, CredentialBackend, CredentialStatus};
use crate::provider::{self, ProviderEntry};

const KEYS_FILE_NAME: &str = ".search-keys.json";
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Source-side view of a provider manifest row, used by credential commands and
/// tests that address sources by `cli_source` (the `--source` / UI spelling).
/// Aliases are resolved by `provider::resolve` before reaching this type, so
/// `source` here is always the canonical `cli_source` form.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct SourceEntry {
    /// `cli_source` spelling used in IPC and CLI arguments.
    pub source: &'static str,
    /// Credential store target. `None` for non-keyed sources; `resolve_source`
    /// filters those out so `provider` is always `Some` for keyed entries.
    pub provider: &'static str,
    /// Settings-side canonical name (underscore form). Used where callers care
    /// about route/disabled_sources semantics rather than CLI spelling.
    pub canonical: &'static str,
    pub label: &'static str,
}

fn as_source_entry(entry: &'static ProviderEntry) -> SourceEntry {
    SourceEntry {
        source: entry.cli_source,
        provider: entry.provider.unwrap_or(""),
        canonical: entry.source,
        label: entry.label,
    }
}

/// Resolve a UI/CLI source name or alias to its SourceEntry. Only keyed
/// providers resolve through `resolve_source`; non-keyed sources must go
/// through `resolve_test_source`. The returned entry borrows the static
/// PROVIDERS row, so there is no per-call allocation.
fn find_source(name: &str, keyed_only: bool) -> Result<SourceEntry, String> {
    let trimmed = name.trim();
    let entry = provider::entries()
        .iter()
        .find(|entry| {
            entry.cli_source == trimmed
                || entry.source == trimmed
                || entry.aliases.contains(&trimmed)
        })
        .ok_or_else(|| "不支持的搜索源".to_string())?;
    if (keyed_only && !entry.keyed) || (!keyed_only && !entry.search) {
        return Err("不支持的搜索源".into());
    }
    Ok(as_source_entry(entry))
}

pub(crate) fn resolve_source(name: &str) -> Result<SourceEntry, String> {
    find_source(name, true)
}
pub(crate) fn resolve_test_source(name: &str) -> Result<SourceEntry, String> {
    find_source(name, false)
}
#[derive(Clone, Debug, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CredentialOverview {
    pub source: String,
    pub store: CredentialStatus,
    /// Effective source Core reports: env | credential_store | file | none | unavailable, or
    /// sqlite when only the local store is known. New values may appear; UI falls back to a raw string.
    pub effective_source: String,
    /// True when Core reports that an environment variable overrides the saved key.
    /// Absent unless Core's `doctor` report supplied a row for this provider.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub env_overrides_store: Option<bool>,
    /// Name (never value) of the environment variable Core found set. Absent without a Core row.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub env_var: Option<String>,
    /// Count of keys Core found in the legacy keys file. Values are never returned. Absent
    /// without a Core row.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub file_key_count: Option<usize>,
    pub key_application_available: bool,
}

/// One row of Core's `doctor --format json` -> `key_sources` report.
///
/// The desktop never derives the effective source itself: the command boundary
/// asks the CLI, which is the same code that loads keys for a real search. This
/// keeps the credential page, `doctor`, and `search` from disagreeing.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Eq)]
pub struct CoreKeySource {
    #[serde(default)]
    pub effective_source: String,
    #[serde(default)]
    pub env_vars_set: Vec<String>,
    #[serde(default)]
    pub env_overrides_store: bool,
    #[serde(default)]
    pub credential_store: String,
    #[serde(default)]
    pub file_key_count: usize,
    #[serde(default)]
    pub credential_store_error: Option<String>,
}

/// Parse the per-provider section of a `doctor --format json` payload.
/// A payload without `key_sources` (e.g. `doctor --no-keys`) yields an empty map.
pub(crate) fn core_key_sources(payload: &Value) -> BTreeMap<String, CoreKeySource> {
    payload
        .get("key_sources")
        .and_then(|sources| serde_json::from_value(sources.clone()).ok())
        .unwrap_or_default()
}

/// Overwrite the fields Core owns with Core's answer. Only called at the command
/// boundary; unit tests may omit it and use the local-store answer below.
pub(crate) fn apply_core_source(overview: &mut CredentialOverview, core: Option<&CoreKeySource>) {
    let Some(core) = core else { return };
    overview.env_overrides_store = Some(core.env_overrides_store);
    overview.env_var = Some(core.env_vars_set.last().cloned().unwrap_or_default());
    overview.file_key_count = Some(core.file_key_count);
    if !core.effective_source.is_empty() {
        overview.effective_source = core.effective_source.clone();
    }
}

/// Legacy keys file location derived from the given variables only (never the
/// process environment). Only the migration command needs it.
pub(crate) fn keys_file_path(variables: &BTreeMap<String, String>) -> Option<PathBuf> {
    variables
        .get("USERPROFILE")
        .or_else(|| variables.get("HOME"))
        .filter(|home| !home.is_empty())
        .map(|home| PathBuf::from(home).join(KEYS_FILE_NAME))
}

/// Local-store answer, used until (or unless) Core's `doctor` report arrives.
fn local_effective_source(store_state: &str) -> &'static str {
    match store_state {
        "present" => "sqlite",
        "absent" => "none",
        _ => "unavailable",
    }
}

pub(crate) fn overview(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
) -> CredentialOverview {
    let store = credential::status_of(credential::load(
        backend,
        &credential::namespace(variables),
        entry.provider,
    ));
    // Locally only the store is known. Env precedence and the legacy file count are Core's
    // answer (`apply_core_source`); the desktop never re-derives them, so they start empty.
    let effective_source = local_effective_source(&store.state).to_string();
    CredentialOverview {
        source: entry.source.into(),
        env_overrides_store: None,
        env_var: None,
        file_key_count: None,
        store,
        effective_source,
        key_application_available: application_url(entry.source).is_some(),
    }
}
#[derive(Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CredentialValue {
    /// `credential_read` masks every row (first 4 + last 4, fully masked at <= 8);
    /// `credential_reveal` returns the editable plaintext on explicit request only.
    pub value: String,
    /// SHA-256 of the plaintext editor snapshot; pass it back to `credential_remove`.
    pub snapshot: String,
}
pub(crate) fn reveal(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
) -> Result<CredentialValue, String> {
    let value = credential::load(backend, &credential::namespace(variables), entry.provider)
        .map_err(|e| e.to_string())?;
    let value = match value {
        None => String::new(),
        Some((Value::String(s), _)) => s,
        Some((Value::Array(a), _)) => a
            .iter()
            .filter_map(|item| item.as_str().or_else(|| {
                (entry.provider == "jina").then(|| item.get("key").and_then(Value::as_str)).flatten()
            }))
            .collect::<Vec<_>>()
            .join("\n"),
        Some((Value::Object(map), _)) if entry.provider == "jina" => map
            .get("key").and_then(Value::as_str).unwrap_or_default().to_string(),
        Some(_) => return Err("此凭据结构不能作为 API Key 编辑".into()),
    };
    let snapshot = credential::snapshot(&value);
    Ok(CredentialValue { value, snapshot })
}
pub(crate) fn read(backend: &dyn CredentialBackend, variables: &BTreeMap<String, String>, entry: &SourceEntry) -> Result<CredentialValue, String> {
    let mut result = reveal(backend, variables, entry)?;
    result.value = result.value.lines().map(|line| {
        let chars: Vec<char> = line.chars().collect();
        if chars.len() <= 8 { "********".to_string() }
        else { format!("{}********{}", chars[..4].iter().collect::<String>(), chars[chars.len()-4..].iter().collect::<String>()) }
    }).collect::<Vec<_>>().join("\n");
    Ok(result)
}
pub(crate) fn save(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
    key: &str,
    now: f64,
) -> Result<CredentialOverview, String> {
    credential::save(
        backend,
        &credential::namespace(variables),
        entry.provider,
        key,
        now,
    )
    .map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}
pub(crate) fn delete(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
) -> Result<CredentialOverview, String> {
    credential::remove(backend, &credential::namespace(variables), entry.provider)
        .map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}
/// Per-row append for `credential_append`: merges `keys` into the CURRENT
/// stored rows (never a whole-list replacement), then returns the same
/// non-secret overview as `credential_save`.
pub(crate) fn append(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
    keys: &[String],
    now: f64,
) -> Result<CredentialOverview, String> {
    credential::append_keys(
        backend,
        &credential::namespace(variables),
        entry.provider,
        keys,
        now,
    )
    .map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}
/// Per-row remove for `credential_remove`: `expected` is the exact
/// `credential_read.value` snapshot the caller saw, `index` is the 0-based
/// editor row to delete (duplicate keys remove the exact occurrence, raw Jina
/// metadata included). Removing the last row deletes the credentials row.
pub(crate) fn remove_row(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
    index: usize,
    expected: &str,
    now: f64,
) -> Result<CredentialOverview, String> {
    credential::remove_at(
        backend,
        &credential::namespace(variables),
        entry.provider,
        index,
        expected,
        now,
    )
    .map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) fn with_native<T>(
    variables: &BTreeMap<String, String>,
    operation: impl FnOnce(&dyn CredentialBackend) -> T,
) -> T {
    struct MissingDatabase;
    impl CredentialBackend for MissingDatabase {
        fn read(&self, _: &str) -> Result<Option<Vec<u8>>, credential::CredentialError> {
            Err(credential::CredentialError::Unavailable(
                "无法定位配置数据库".into(),
            ))
        }
        fn write(&self, _: &str, _: &[u8]) -> Result<(), credential::CredentialError> {
            Err(credential::CredentialError::Unavailable(
                "无法定位配置数据库".into(),
            ))
        }
        fn delete(&self, _: &str) -> Result<bool, credential::CredentialError> {
            Err(credential::CredentialError::Unavailable(
                "无法定位配置数据库".into(),
            ))
        }
    }
    match crate::config_db::path(variables) {
        Some(path) => operation(&credential::SqliteCredentialBackend { path }),
        None => operation(&MissingDatabase),
    }
}

// Fixed provider consoles only; never accept a URL from the WebView.
// Baidu's Qianfan AI Search key is created on the official Baidu Cloud IAM
// API Key page: https://cloud.baidu.com/doc/qianfan-docs/s/Fm9l6ocai
const APPLICATION_URLS: &[(&str, Option<&str>)] = &[
    (
        "baidu",
        Some("https://console.bce.baidu.com/iam/#/iam/apikey/list"),
    ),
    ("jina", Some("https://jina.ai/")),
    ("brave", Some("https://api.search.brave.com/app/keys")),
    ("parallel", Some("https://platform.parallel.ai/")),
    ("tavily", Some("https://app.tavily.com/")),
    ("exa", Some("https://dashboard.exa.ai/api-keys")),
    ("firecrawl", Some("https://www.firecrawl.dev/app/api-keys")),
    ("serpapi", Some("https://serpapi.com/manage-api-key")),
    ("github-repos", Some("https://github.com/settings/tokens")),
];
fn application_url(source: &str) -> Option<&'static str> {
    APPLICATION_URLS
        .iter()
        .find(|(s, _)| *s == source)
        .and_then(|(_, u)| *u)
}
pub(crate) fn open_application_with(
    source: &str,
    lookup: impl FnOnce(&str) -> Option<String>,
    open: impl FnOnce(&str) -> Result<(), String>,
) -> Result<(), String> {
    let entry = resolve_source(source)?;
    let url = lookup(entry.source).ok_or("申请链接待配置")?;
    if !url.starts_with("https://")
        || url[8..].is_empty()
        || url.chars().any(|c| c.is_control() || c.is_whitespace())
        || url[8..].starts_with('/')
    {
        return Err("申请链接必须为固定 HTTPS 地址".into());
    }
    open(&url)
}
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) fn open_application(source: &str) -> Result<(), String> {
    open_application_with(
        source,
        |s| application_url(s).map(str::to_string),
        open_browser,
    )
}
#[cfg(windows)]
fn open_browser(url: &str) -> Result<(), String> {
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    let operation: Vec<u16> = "open".encode_utf16().chain(Some(0)).collect();
    let target: Vec<u16> = url.encode_utf16().chain(Some(0)).collect();
    let result = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            operation.as_ptr(),
            target.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
        )
    };
    if result as isize <= 32 {
        Err("无法打开系统浏览器".into())
    } else {
        Ok(())
    }
}
#[cfg(not(windows))]
fn open_browser(_: &str) -> Result<(), String> {
    Err("系统浏览器入口仅支持 Windows".into())
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct TestOutcome {
    /// success | auth_failed | quota | rate_limited | network | timeout | missing_key | cli_failed | error, or a new value added later; UI must fall back to a raw string.
    pub result: String,
    pub message: String,
}
pub(crate) fn classify(error_type: &str, label: &str) -> TestOutcome {
    let (result, message) = match error_type {
        "invalid" => ("auth_failed", format!("{label} 认证失败，请替换有效 Key。")),
        "quota_exhausted" => ("quota", format!("{label} 额度已用尽。")),
        "rate_limit" => ("rate_limited", format!("{label} 触发频率限制。")),
        "network" => ("network", format!("无法连接 {label}，请检查网络。")),
        "timeout" => ("timeout", format!("{label} 请求超时。")),
        "missing_key" => (
            "missing_key",
            format!("未找到可用的 {label} Key，请先保存。"),
        ),
        "credential_store" => (
            "credential_store",
            format!("无法读取凭据库中 {label} 的 Key。请重新保存该来源的 Key。"),
        ),
        _ => ("error", format!("{label} 测试失败，请查看 CLI 输出。")),
    };
    TestOutcome {
        result: result.into(),
        message,
    }
}
pub(crate) fn interpret_source(payload: &Value, entry: &SourceEntry) -> TestOutcome {
    let row = payload
        .get("provider_status")
        .and_then(Value::as_array)
        .and_then(|rows| {
            rows.iter().find(|r| {
                r.get("source")
                    .and_then(Value::as_str)
                    .is_some_and(|s| s.replace('-', "_") == entry.source.replace('-', "_"))
            })
        });
    let Some(row) = row else {
        return classify("error", entry.label);
    };
    if matches!(
        row.get("status").and_then(Value::as_str),
        Some("ok" | "partial")
    ) {
        return TestOutcome {
            result: "success".into(),
            message: format!("{} 测试成功。", entry.label),
        };
    }
    classify(
        row.get("errors")
            .and_then(Value::as_array)
            .and_then(|a| a.first())
            .and_then(|e| e.get("error_type"))
            .and_then(Value::as_str)
            .unwrap_or("error"),
        entry.label,
    )
}
pub(crate) fn test_args(query: &str, entry: &SourceEntry) -> Vec<String> {
    // Options first, then `--`: a query starting with `-` stays a query. `--no-fetch` keeps the
    // probe candidate-only, so a credential test never fetches page bodies.
    vec![
        "search".into(),
        "--route".into(),
        "default".into(),
        "--source".into(),
        entry.source.into(),
        "--no-fetch".into(),
        "--timeout".into(),
        "15".into(),
        "--format".into(),
        "json".into(),
        "--".into(),
        query.into(),
    ]
}
const TEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);
pub(crate) fn supports_storage(payload: &Value) -> bool {
    payload.get("config_storage").is_some_and(|v| {
        v.get("backend").and_then(Value::as_str) == Some("sqlite-dpapi")
            && v.get("schema_version").and_then(Value::as_i64) == Some(1)
    })
}
/// Credential-domain operations. Stateless: the environment is passed in so
/// `DesktopManager` need not be involved and no domain state leaks into it.
pub(crate) struct CredentialManager<'a> {
    pub(crate) environment: &'a crate::RuntimeEnvironment,
}

impl CredentialManager<'_> {
    pub(crate) fn require_storage_cli(&self, cli: &Path) -> Result<(), String> {
        crate::credential_commands::require_storage_cli(self.environment, cli)
    }
    pub(crate) fn test_source(
        &self,
        cli: PathBuf,
        entry: &SourceEntry,
        query: &str,
    ) -> Result<TestOutcome, String> {
        self.require_storage_cli(&cli)?;
        // Only this source's own key variables reach the child, so Core sees the same credential
        // the UI page shows (env aliases win over the store in Core's resolution order).
        let names: Vec<&str> = crate::source_catalog::catalog()
            .source(entry.canonical)
            .map(|source| source.env.iter().map(String::as_str).collect())
            .unwrap_or_default();
        let output = crate::process::bounded_with(
            &cli,
            &test_args(query, entry),
            self.environment,
            &names,
            TEST_TIMEOUT,
        )
        .map_err(|_| "无法启动 CLI".to_string())?;
        if output.timed_out {
            return Ok(TestOutcome {
                result: "timeout".into(),
                message: "测试超时，请稍后重试。".into(),
            });
        }
        match serde_json::from_str::<Value>(&output.stdout) {
            Ok(v) if v.is_object() => Ok(interpret_source(&v, entry)),
            _ => Ok(TestOutcome {
                result: "cli_failed".into(),
                message: "CLI 未返回有效结果。".into(),
            }),
        }
    }
}

/// Free function so callers that do not own a manager (install/update) can
/// reuse the same storage-capability gate.
pub(crate) fn require_storage_cli(
    environment: &crate::RuntimeEnvironment,
    cli: &Path,
) -> Result<(), String> {
    let output = crate::process::bounded(
        cli,
        &[
            "doctor".into(),
            "--no-keys".into(),
            "--format".into(),
            "json".into(),
        ],
        environment,
        TEST_TIMEOUT,
    )
    .map_err(|_| "无法检测 CLI 配置协议".to_string())?;
    let payload = serde_json::from_str::<Value>(&output.stdout).ok();
    if output.timed_out || !payload.as_ref().is_some_and(supports_storage) {
        return Err(
            "此 CLI 不支持 SQLite/DPAPI 配置协议，请更新 CLI 后重试；不会读取旧 Key 来源。"
                .into(),
        );
    }
    let payload = payload.unwrap();
    if payload.get("config_error").is_some()
        || payload.get("keys_error").is_some()
        || output.code != Some(0)
    {
        return Err(
            "CLI 支持 SQLite/DPAPI，但当前配置数据库或凭据无法读取，请检查数据库。".into(),
        );
    }
    Ok(())
}

// Legacy migration adapter. The Python CLI (`migrate-legacy`) owns every rule and every store
// access. This layer only maps UI source names to providers, writes a request file that holds
// names and choices (never key values), runs the CLI, and returns its masked output.

/// One planned item from the CLI. Carries masked previews and reasons only.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationItem {
    pub provider: String,
    pub action: String,
    #[serde(default)]
    pub preview: String,
    #[serde(default)]
    pub reason: String,
}

/// Masked preview returned to the UI. `plan_token` is an opaque digest pair, not key material.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationPlan {
    pub plan_token: String,
    pub items: Vec<MigrationItem>,
    pub migratable: Vec<String>,
    pub skipped: Vec<String>,
}

/// Provider names only. The CLI never returns values.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationResult {
    pub written: Vec<String>,
    pub kept: Vec<String>,
    pub unchanged: Vec<String>,
    pub failed: Vec<String>,
    pub not_done: Vec<String>,
    pub complete: bool,
    /// Absolute path of the legacy plaintext file. The CLI never edits or deletes it.
    #[serde(default)]
    pub legacy_file: String,
    /// True when that file still contains plaintext secrets after the migration.
    #[serde(default)]
    pub legacy_file_has_plaintext: bool,
    /// Advisory warnings, e.g. a POSIX keys file readable by other users.
    #[serde(default)]
    pub warnings: Vec<String>,
}

/// Request file contents for `apply`. Holds only provider names, choices, and the plan token.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub(crate) struct MigrationRequest {
    pub plan_token: String,
    pub approved: Vec<String>,
    pub choices: BTreeMap<String, String>,
}

/// Validate UI selections against the allowlist before anything reaches the CLI.
pub(crate) fn migration_request(
    plan_token: &str,
    approved_sources: &[String],
    choices_by_source: &BTreeMap<String, String>,
) -> Result<MigrationRequest, String> {
    if plan_token.len() != 64 || !plan_token.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("迁移预览无效，请重新预览".into());
    }
    let mut approved = Vec::new();
    for source in approved_sources {
        approved.push(resolve_source(source)?.provider.to_string());
    }
    approved.sort();
    approved.dedup();
    let mut choices = BTreeMap::new();
    for (source, choice) in choices_by_source {
        let provider = resolve_source(source)?.provider.to_string();
        if choice != "keep" && choice != "replace" {
            return Err("冲突选择无效，请选择保留或替换".into());
        }
        if !approved.contains(&provider) {
            return Err("冲突选择必须对应已批准的源".into());
        }
        choices.insert(provider, choice.clone());
    }
    Ok(MigrationRequest {
        plan_token: plan_token.into(),
        approved,
        choices,
    })
}

/// Request file under the temp directory; removed on drop. Holds no key material.
pub(crate) struct RequestFile(pub(crate) PathBuf);
impl RequestFile {
    pub(crate) fn create(dir: &Path, request: &MigrationRequest) -> Result<Self, String> {
        let body = serde_json::to_string(request).map_err(|_| "无法准备迁移请求".to_string())?;
        // Random name + create_new: a pre-placed request file cannot be swapped in.
        let path = crate::secure_temp::create_file(dir, "multi-search-migrate-request-", ".json", body.as_bytes())
            .map_err(|_| "无法准备迁移请求".to_string())?;
        Ok(Self(path))
    }
}
impl Drop for RequestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

/// Legacy migration is local file/state work and has no network stage.
const MIGRATION_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

fn run_migration_cli(
    environment: &crate::RuntimeEnvironment,
    cli: &Path,
    args: &[String],
) -> Result<crate::process::Output, String> {
    let output = crate::process::bounded(cli, args, environment, MIGRATION_TIMEOUT)
        .map_err(|_| "无法启动 CLI".to_string())?;
    if output.timed_out {
        return Err("迁移操作超时，请稍后重试。".into());
    }
    if output.code != Some(0) {
        return Err("迁移操作未完成，请重新预览后再试。".into());
    }
    Ok(output)
}

/// Masked preview of the legacy keys file via the CLI.
pub(crate) fn migration_plan(
    environment: &crate::RuntimeEnvironment,
    cli: &Path,
    keys_file: &Path,
) -> Result<MigrationPlan, String> {
    let args = vec![
        "migrate-legacy".into(),
        "plan".into(),
        "--keys-file".into(),
        keys_file.to_string_lossy().into_owned(),
        "--format".into(),
        "json".into(),
    ];
    let output = run_migration_cli(environment, cli, &args)?;
    serde_json::from_str::<MigrationPlan>(&output.stdout)
        .map_err(|_| "无法解析迁移预览".to_string())
}

/// Apply an approved request via the CLI, which re-checks the file and store itself.
pub(crate) fn migration_apply(
    environment: &crate::RuntimeEnvironment,
    cli: &Path,
    keys_file: &Path,
    request: &MigrationRequest,
) -> Result<MigrationResult, String> {
    let dir = std::env::temp_dir();
    let request_file = RequestFile::create(&dir, request)?;
    let args = vec![
        "migrate-legacy".into(),
        "apply".into(),
        "--keys-file".into(),
        keys_file.to_string_lossy().into_owned(),
        "--request".into(),
        request_file.0.to_string_lossy().into_owned(),
        "--format".into(),
        "json".into(),
    ];
    let output = run_migration_cli(environment, cli, &args)?;
    serde_json::from_str::<MigrationResult>(&output.stdout)
        .map_err(|_| "无法解析迁移结果".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_read_masks_keys_and_returns_nonsecret_revision() {
        struct Memory;
        impl CredentialBackend for Memory {
            fn read(&self, _: &str) -> Result<Option<Vec<u8>>, credential::CredentialError> {
                Ok(Some(credential::encode_blob(&serde_json::json!(["abcd-secret-wxyz", "tiny"]), 1.0)))
            }
            fn write(&self, _: &str, _: &[u8]) -> Result<(), credential::CredentialError> { unreachable!() }
            fn delete(&self, _: &str) -> Result<bool, credential::CredentialError> { unreachable!() }
        }
        let entry = resolve_source("tavily").unwrap();
        let value = read(&Memory, &BTreeMap::new(), &entry).unwrap();
        assert_eq!(value.value, "abcd********wxyz\n********");
        assert_eq!(value.snapshot, credential::snapshot("abcd-secret-wxyz\ntiny"));
        assert_eq!(reveal(&Memory, &BTreeMap::new(), &entry).unwrap().value, "abcd-secret-wxyz\ntiny");
    }

    #[test]
    fn storage_capability_rejects_old_cli() {
        assert!(!supports_storage(&serde_json::json!({})));
        assert!(supports_storage(
            &serde_json::json!({"config_storage":{"backend":"sqlite-dpapi","schema_version":1}})
        ));
        assert!(!supports_storage(
            &serde_json::json!({"config_storage":{"backend":"sqlite-dpapi","schema_version":2}})
        ));
    }

    #[test]
    fn application_entry_requires_allowlist_and_https() {
        let mut opened = String::new();
        open_application_with(
            "github_repos",
            |s| {
                assert_eq!(s, "github-repos");
                Some("https://example.invalid/key".into())
            },
            |u| {
                opened = u.into();
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(opened, "https://example.invalid/key");
        assert!(open_application_with("../tavily", |_| panic!(), |_| panic!()).is_err());
        for url in [
            "http://example.invalid",
            "file:///tmp/key",
            "https://",
            "https:///bad",
            "https://example.invalid\n",
        ] {
            assert!(open_application_with("tavily", |_| Some(url.into()), |_| panic!()).is_err());
        }
        assert!(application_url("tavily").unwrap().starts_with("https://"));
    }

    #[test]
    fn baidu_application_link_is_the_official_iam_key_page() {
        // Baidu's own Qianfan SDK doc points "how to get an API Key" at this page:
        // https://cloud.baidu.com/doc/qianfan-docs/s/Fm9l6ocai
        let expected = "https://console.bce.baidu.com/iam/#/iam/apikey/list";
        assert_eq!(application_url("baidu"), Some(expected));
        let mut opened = String::new();
        open_application_with(
            "baidu",
            |s| {
                assert_eq!(s, "baidu");
                application_url(s).map(str::to_string)
            },
            |url| {
                opened = url.into();
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(opened, expected);
    }
}
