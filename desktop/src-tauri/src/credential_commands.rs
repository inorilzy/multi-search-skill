//! Allowlisted desktop credential operations. Overview is non-secret; read returns one source
//! only when its editor is expanded. Keys live in `~/.multi-search/keys.json` (see `keys_file`).
#![cfg_attr(not(feature = "native-window"), allow(dead_code))]
use crate::credential::{self, CredentialStatus};
use crate::provider::{self, ProviderEntry};
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
/// Cookie status is readable without granting access to the API-key mutation commands.
pub(crate) fn resolve_overview_source(name: &str) -> Result<SourceEntry, String> {
    if name.trim() == "twitter" {
        return Ok(SourceEntry { provider: "twitter", ..resolve_test_source(name)? });
    }
    resolve_source(name)
}
pub(crate) fn resolve_test_source(name: &str) -> Result<SourceEntry, String> {
    find_source(name, false)
}
#[derive(Clone, Debug, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CredentialOverview {
    pub source: String,
    /// This provider's entry in `~/.multi-search/keys.json`.
    pub store: CredentialStatus,
    /// Effective source Core reports: env | file | none. Before Core answers it is `file` when the
    /// keys file has this provider, else `none`. New values may appear; UI falls back to a raw string.
    pub effective_source: String,
    /// Name (never value) of the environment variable Core found set. Absent without a Core row.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub env_var: Option<String>,
    /// Count of keys Core found in the keys file. Values are never returned. Absent
    /// without a Core row.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub file_key_count: Option<usize>,
    pub key_application_available: bool,
    /// Whether this build can hand the fixed HTTPS link to the system browser:
    /// Windows (`ShellExecuteW`), macOS (`/usr/bin/open`) and Linux (`xdg-open`)
    /// implement it; other platforms fall back to manual copying.
    pub key_application_open_supported: bool,
    /// Read-only copy of the single trusted mapping so the page can offer manual
    /// copying when direct opening is unavailable. Absent when the source has no
    /// configured link; opening still accepts only the source name, never this URL.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub key_application_url: Option<String>,
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
    pub file_present: bool,
    #[serde(default)]
    pub file_key_count: usize,
}

/// Parse Core's `doctor --format json` credential report. Non-row entries
/// (`env`, `file`, `state`) are skipped; Cookie references come from `configured_keys`.
pub(crate) fn core_key_sources(payload: &Value) -> BTreeMap<String, CoreKeySource> {
    let mut sources: BTreeMap<String, CoreKeySource> = payload
        .get("key_sources")
        .and_then(Value::as_object)
        .map(|rows| {
            rows.iter()
                .filter(|(_, row)| row.is_object())
                .filter_map(|(name, row)| {
                    serde_json::from_value(row.clone()).ok().map(|row| (name.clone(), row))
                })
                .collect()
        })
        .unwrap_or_default();
    // Core reports Cookie references as configured booleans, outside the API-key provider rows.
    // This includes env, config and keys-file references without exposing Cookie contents.
    if let Some(configured) = payload.get("configured_keys").and_then(Value::as_object) {
        let present = ["twitter", "twitter_cookies"].iter()
            .any(|name| configured.get(*name).and_then(Value::as_bool) == Some(true));
        sources.entry("twitter".into()).or_insert_with(|| CoreKeySource {
            effective_source: if present { "configured" } else { "none" }.into(),
            ..CoreKeySource::default()
        });
    }
    sources
}

/// Overwrite the fields Core owns with Core's answer. Only called at the command
/// boundary; unit tests may omit it and use the local answer below.
pub(crate) fn apply_core_source(overview: &mut CredentialOverview, core: Option<&CoreKeySource>) {
    let Some(core) = core else { return };
    overview.env_var = Some(core.env_vars_set.last().cloned().unwrap_or_default());
    overview.file_key_count = Some(core.file_key_count);
    if !core.effective_source.is_empty() {
        overview.effective_source = core.effective_source.clone();
    }
}

/// Local answer, used until (or unless) Core's `doctor` report arrives.
fn local_effective_source(store_state: &str) -> &'static str {
    match store_state {
        "present" | "unreadable" => "file",
        _ => "none",
    }
}

pub(crate) fn overview(variables: &BTreeMap<String, String>, entry: &SourceEntry) -> CredentialOverview {
    let store = credential::status_of(credential::load(variables, entry.provider));
    // Env precedence and the key count are Core's answer (`apply_core_source`); the desktop
    // never re-derives them, so they start empty.
    let effective_source = local_effective_source(&store.state).to_string();
    // Availability, the manual-copy link and the direct-open capability all come
    // from the same fixed mapping / platform facts, never from the WebView.
    let application = application_url(entry.source);
    CredentialOverview {
        source: entry.source.into(),
        env_var: None,
        file_key_count: None,
        store,
        effective_source,
        key_application_available: application.is_some(),
        key_application_open_supported: browser_open_supported(),
        key_application_url: application.map(str::to_string),
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
pub(crate) fn reveal(variables: &BTreeMap<String, String>, entry: &SourceEntry) -> Result<CredentialValue, String> {
    let value = credential::load(variables, entry.provider).map_err(|e| e.to_string())?;
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
pub(crate) fn read(variables: &BTreeMap<String, String>, entry: &SourceEntry) -> Result<CredentialValue, String> {
    let mut result = reveal(variables, entry)?;
    result.value = result.value.lines().map(|line| {
        let chars: Vec<char> = line.chars().collect();
        if chars.len() <= 8 { "********".to_string() }
        else { format!("{}********{}", chars[..4].iter().collect::<String>(), chars[chars.len()-4..].iter().collect::<String>()) }
    }).collect::<Vec<_>>().join("\n");
    Ok(result)
}
/// Whole-editor save into the keys file; returns the non-secret overview.
pub(crate) fn save(variables: &BTreeMap<String, String>, entry: &SourceEntry, key: &str) -> Result<CredentialOverview, String> {
    credential::save(variables, entry.provider, key).map_err(|e| e.to_string())?;
    Ok(overview(variables, entry))
}
/// Remove the provider's whole entry from the keys file.
pub(crate) fn delete(variables: &BTreeMap<String, String>, entry: &SourceEntry) -> Result<CredentialOverview, String> {
    credential::remove(variables, entry.provider).map_err(|e| e.to_string())?;
    Ok(overview(variables, entry))
}
/// Per-row append for `credential_append`: merges `keys` into the CURRENT
/// stored rows (never a whole-list replacement), then returns the same
/// non-secret overview as `credential_save`.
pub(crate) fn append(variables: &BTreeMap<String, String>, entry: &SourceEntry, keys: &[String]) -> Result<CredentialOverview, String> {
    credential::append_keys(variables, entry.provider, keys).map_err(|e| e.to_string())?;
    Ok(overview(variables, entry))
}
/// Per-row remove for `credential_remove`: `expected` is the snapshot hash from
/// `credential_read`, `index` is the 0-based editor row to delete (duplicate keys
/// remove the exact occurrence, raw Jina metadata included). Removing the last row
/// deletes the provider's entry.
pub(crate) fn remove_row(
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
    index: usize,
    expected: &str,
) -> Result<CredentialOverview, String> {
    credential::remove_at(variables, entry.provider, index, expected).map_err(|e| e.to_string())?;
    Ok(overview(variables, entry))
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
    // github-code shares the `github` token entry with github-repos.
    ("github-code", Some("https://github.com/settings/tokens")),
    // Optional: a Stack Apps key only raises the anonymous daily quota.
    ("stackoverflow", Some("https://stackapps.com/apps/oauth/register")),
];
fn application_url(source: &str) -> Option<&'static str> {
    APPLICATION_URLS
        .iter()
        .find(|(s, _)| *s == source)
        .and_then(|(_, u)| *u)
}
/// Platform fact: whether this build can hand a validated HTTPS application link
/// to the system browser (`ShellExecuteW` on Windows, `/usr/bin/open` on macOS,
/// `xdg-open` on Linux). Other platforms fall back to manual copying, and the page
/// disables the open button up front from this same flag instead of failing only
/// after a click.
pub(crate) fn browser_open_supported() -> bool {
    cfg!(any(windows, target_os = "macos", target_os = "linux"))
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
pub(crate) fn open_browser(url: &str) -> Result<(), String> {
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
/// Hand the already-validated URL to `program` as a single argv entry. The address is
/// never interpreted by a shell, so `&`/spaces cannot split it into another command.
#[cfg(any(target_os = "macos", target_os = "linux"))]
pub(crate) fn launch_browser(program: &std::path::Path, url: &str) -> Result<(), String> {
    let status = std::process::Command::new(program)
        .arg(url)
        .status()
        .map_err(|_| "无法打开系统浏览器".to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err("无法打开系统浏览器".into())
    }
}
/// macOS hands the already-validated HTTPS URL to LaunchServices through the absolute
/// `/usr/bin/open` binary.
#[cfg(target_os = "macos")]
pub(crate) fn open_browser(url: &str) -> Result<(), String> {
    launch_browser(std::path::Path::new("/usr/bin/open"), url)
}
/// Linux delegates to the desktop's `xdg-open` helper, resolved through PATH; the URL is
/// one argv entry, never interpreted by a shell.
#[cfg(target_os = "linux")]
pub(crate) fn open_browser(url: &str) -> Result<(), String> {
    launch_browser(std::path::Path::new("xdg-open"), url)
}
#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
pub(crate) fn open_browser(_: &str) -> Result<(), String> {
    Err("系统浏览器入口仅支持 Windows、macOS 和 Linux".into())
}
/// Test seam for the browser launcher. Not a supported public API.
#[cfg(feature = "test-fixtures")]
#[doc(hidden)]
pub mod browser_fixture {
    /// Run the same single-argv launcher as production with a synthetic program.
    #[cfg(any(target_os = "macos", target_os = "linux"))]
    pub fn launch(program: &std::path::Path, url: &str) -> Result<(), String> {
        super::launch_browser(program, url)
    }
    /// The platform browser command the production path invokes.
    pub fn launcher() -> &'static str {
        if cfg!(windows) {
            "ShellExecuteW"
        } else if cfg!(target_os = "macos") {
            "/usr/bin/open"
        } else if cfg!(target_os = "linux") {
            "xdg-open"
        } else {
            "unsupported"
        }
    }
    /// Invoke the real platform browser opener (Linux CI uses a fake `xdg-open` on PATH).
    #[cfg(target_os = "linux")]
    pub fn open(url: &str) -> Result<(), String> {
        super::open_browser(url)
    }
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
        "--no-state".into(),
        "--timeout".into(),
        "15".into(),
        "--format".into(),
        "json".into(),
        "--".into(),
        query.into(),
    ]
}
const TEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);
/// Protocol handshake with the CLI. `keys-file` means API keys live in `~/.multi-search/keys.json`;
/// an older DPAPI-era CLI (`sqlite-dpapi`) would not read that file, so it is refused.
pub(crate) fn supports_storage(payload: &Value) -> bool {
    payload.get("config_storage").is_some_and(|v| {
        v.get("backend").and_then(Value::as_str) == Some("keys-file")
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
        self.test_key(cli, entry, query, None, None)
    }

    pub(crate) fn test_key(
        &self,
        cli: PathBuf,
        entry: &SourceEntry,
        query: &str,
        index: Option<usize>,
        expected: Option<&str>,
    ) -> Result<TestOutcome, String> {
        if index.is_none() && expected.is_some() {
            return Err("请选择待测 Key 后重试。".into());
        }
        let source = crate::source_catalog::catalog().source(entry.canonical)
            .ok_or("不支持的搜索源")?;
        let names: Vec<&str> = source.env.iter().map(String::as_str).collect();
        let key = if source.keyed {
            if let Some(index) = index {
                let saved = reveal(&self.environment.variables, entry)?;
                if expected != Some(saved.snapshot.as_str()) {
                    return Err("凭据已变化，请刷新后再测试。".into());
                }
                Some(saved.value.lines().nth(index).ok_or("待测 Key 已不存在，请刷新。")?.to_string())
            } else {
                // Match Core's alias priority; a file-backed default selects the newest saved row.
                let env_key = names.iter().rev().find_map(|name| self.environment.variables.get(*name)
                    .filter(|value| !value.is_empty()).cloned());
                Some(match env_key {
                    Some(key) => key,
                    None => reveal(&self.environment.variables, entry)?.value
                        .lines().last().unwrap_or("").to_string(),
                })
            }
        } else {
            if index.is_some() || expected.is_some() {
                return Err("此搜索源不支持选择 API Key。".into());
            }
            None
        };
        if source.keyed && key.as_deref().is_none_or(str::is_empty) && !source.key_optional {
            return Ok(classify("missing_key", entry.label));
        }
        let home = ProbeHome(crate::secure_temp::create_dir(&std::env::temp_dir(), "multi-search-key-test-")
            .map_err(|_| "无法创建凭据测试目录".to_string())?);
        let mut isolated = self.environment.clone();
        isolated.variables = crate::process::child_variables(self.environment, &[]);
        for name in ["MULTI_SEARCH_CONFIG", "MULTI_SEARCH_CONFIG_DB", "MULTI_SEARCH_STATE", "MULTI_SEARCH_STATE_DB", "MULTI_SEARCH_CREDENTIAL_NAMESPACE"] {
            isolated.variables.retain(|key, _| !key.eq_ignore_ascii_case(name));
        }
        for name in ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"] {
            isolated.variables.insert(name.into(), home.0.to_string_lossy().into_owned());
        }
        let config = home.0.join("config.json");
        std::fs::write(&config, b"{}")
            .map_err(|_| "无法创建凭据测试配置".to_string())?;
        isolated.variables.insert("MULTI_SEARCH_CONFIG".into(), config.to_string_lossy().into_owned());
        if let Some(key) = key.filter(|value| !value.is_empty()) {
            let name = names.last().ok_or("此搜索源没有可用的 Key 环境变量")?;
            isolated.variables.insert((*name).into(), key);
        }
        // Doctor may create its state store even with --no-keys: keep the handshake isolated too.
        require_storage_cli(&isolated, &cli)?;
        let environment = if source.keyed { &isolated } else { self.environment };
        let output = crate::process::bounded_with(
            &cli,
            &test_args(query, entry),
            environment,
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

/// An empty profile keeps Core from loading any saved Key pool or writing the user's state.
struct ProbeHome(PathBuf);
impl Drop for ProbeHome {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
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
            "此 CLI 不支持当前的配置协议，请更新 CLI 后重试。"
                .into(),
        );
    }
    let payload = payload.unwrap();
    if payload.get("config_error").is_some()
        || payload.get("keys_error").is_some()
        || output.code != Some(0)
    {
        return Err(
            "CLI 无法读取当前的配置数据库或 Key 文件（~/.multi-search/keys.json），请检查后重试。".into(),
        );
    }
    Ok(())
}

#[cfg(test)]
#[path = "credential_commands_t05.rs"]
mod sources_t05;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn storage_capability_rejects_old_cli() {
        assert!(!supports_storage(&serde_json::json!({})));
        assert!(supports_storage(
            &serde_json::json!({"config_storage":{"backend":"keys-file","schema_version":1}})
        ));
        // A DPAPI-era CLI does not read ~/.multi-search/keys.json.
        assert!(!supports_storage(
            &serde_json::json!({"config_storage":{"backend":"sqlite-dpapi","schema_version":1}})
        ));
        assert!(!supports_storage(
            &serde_json::json!({"config_storage":{"backend":"keys-file","schema_version":2}})
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
            "https://example.invalid/a b",
            "https://example.invalid/\u{7}bell",
            "   ",
            "",
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

    #[test]
    fn overview_application_metadata_comes_from_the_fixed_mapping() {
        for name in [
            "baidu",
            "jina",
            "brave",
            "parallel",
            "tavily",
            "exa",
            "firecrawl",
            "serpapi",
            "github-repos",
            "github-code",
            "stackoverflow",
        ] {
            let entry = resolve_source(name).expect("mapped source is keyed");
            let view = overview(&BTreeMap::new(), &entry);
            assert!(view.key_application_available, "{name} has a configured link");
            assert_eq!(view.key_application_url.as_deref(), application_url(entry.source));
            assert!(view
                .key_application_url
                .as_deref()
                .is_some_and(|u| u.starts_with("https://")));
        }
        // The direct-open capability is a platform fact reported independently of
        // the keys file and of whether a link exists.
        let view = overview(&BTreeMap::new(), &resolve_source("tavily").unwrap());
        assert_eq!(view.key_application_open_supported, browser_open_supported());
    }

    /// A launch the system refuses must come back as an error (never a swallowed success),
    /// and the address actually handed to the browser stays the one the read-only overview
    /// publishes — that is the link the page shows for manual copying, so a failure can never
    /// point the user at a different target than the trusted mapping used.
    #[test]
    fn failed_launch_reports_the_same_trusted_link_the_page_can_copy() {
        let mut attempted: Option<String> = None;
        let failure = open_application_with(
            "brave",
            |source| application_url(source).map(str::to_string),
            |url| {
                attempted = Some(url.to_string());
                Err("无法打开系统浏览器".to_string())
            },
        );
        assert!(failure.is_err(), "a refused launch is reported, not swallowed");
        assert_eq!(failure.unwrap_err(), "无法打开系统浏览器");
        let view = overview(&BTreeMap::new(), &resolve_source("brave").unwrap());
        assert_eq!(attempted.as_deref(), view.key_application_url.as_deref());
        assert_eq!(attempted.as_deref(), application_url("brave"));
        // A source without a mapping fails before anything is launched.
        let mut launched = 0usize;
        let missing = open_application_with(
            "jina",
            |_| None,
            |_| {
                launched += 1;
                Ok(())
            },
        );
        assert!(missing.is_err());
        assert_eq!(launched, 0, "no link means no launch and no substitute address");
    }
}
