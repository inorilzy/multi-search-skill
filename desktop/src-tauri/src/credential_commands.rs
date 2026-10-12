//! Search-source credential management: UI-facing status, save, delete, and an explicit test.
//!
//! The UI names a source; only allowlisted names are accepted, and the backend maps each one
//! to its key provider before any credential target is built. The UI never supplies a target.
//! The key is accepted once from the UI for `save`, written only to the Windows credential
//! store, and never returned, logged, put in argv, or placed in the child environment.
//! The CLI reads the store itself during `test`.

use crate::credential::{self, CredentialBackend, CredentialStatus};
#[cfg(not(windows))]
use crate::credential::CredentialError;
use crate::{DesktopManager, RuntimeEnvironment};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, path::{Path, PathBuf}, time::Duration};

const CONFIG_ENV: &str = "MULTI_SEARCH_CONFIG";
const KEYS_FILE_NAME: &str = ".search-keys.json";

/// One key-based search source the desktop may manage. Mirrors `KEY_ENV_PAIRS` and
/// `CREDENTIAL_STORE_PROVIDERS` in keys.py; change both together.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct SourceEntry {
    /// Public source name: the UI value and the CLI `--source` value.
    pub source: &'static str,
    /// Key provider: store entry `<namespace>/<provider>` and the keys-file key.
    pub provider: &'static str,
    /// Environment variables that override the store (names only, never values).
    pub env: &'static [&'static str],
    /// Other accepted UI names for the same source. Nothing else is accepted.
    pub aliases: &'static [&'static str],
    pub label: &'static str,
}

pub(crate) const SOURCES: &[SourceEntry] = &[
    SourceEntry { source: "baidu", provider: "baidu", env: &["BAIDU_QIANFAN_API_KEY", "QIANFAN_API_KEY", "APPBUILDER_API_KEY"], aliases: &[], label: "Baidu AI 搜索" },
    SourceEntry { source: "brave", provider: "brave", env: &["BRAVE_SEARCH_API_KEY", "BRAVE_API_KEY"], aliases: &[], label: "Brave 搜索" },
    SourceEntry { source: "parallel", provider: "parallel", env: &["PARALLEL_API_KEY"], aliases: &[], label: "Parallel" },
    SourceEntry { source: "tavily", provider: "tavily", env: &["TAVILY_API_KEY"], aliases: &[], label: "Tavily" },
    SourceEntry { source: "exa", provider: "exa", env: &["EXA_API_KEY"], aliases: &[], label: "Exa" },
    SourceEntry { source: "firecrawl", provider: "firecrawl", env: &["FIRECRAWL_API_KEY"], aliases: &[], label: "Firecrawl" },
    SourceEntry { source: "serpapi", provider: "serpapi", env: &["SERPAPI_API_KEY", "SERPAPI_KEY"], aliases: &[], label: "SerpAPI" },
    SourceEntry { source: "github-repos", provider: "github", env: &["GITHUB_TOKEN", "GH_TOKEN"], aliases: &["github_repos"], label: "GitHub 仓库" },
];

/// Map a UI source name to its allowlisted entry. Unknown names are rejected before any
/// store access; the error never echoes the input. A missing name is an error, not a default.
pub(crate) fn resolve_source(name: &str) -> Result<&'static SourceEntry, String> {
    let name = name.trim();
    SOURCES
        .iter()
        .find(|entry| entry.source == name || entry.aliases.contains(&name))
        .ok_or_else(|| "不支持的搜索源".to_string())
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct CredentialOverview {
    /// Public source name this overview describes.
    pub source: String,
    pub store: CredentialStatus,
    /// Effective source: "env" | "credential_store" | "file" | "none" | "unavailable".
    pub effective_source: String,
    /// True when an environment variable overrides the saved key.
    pub env_overrides_store: bool,
    /// Name (never value) of the environment variable that is set, or "".
    pub env_var: String,
    /// Count of keys in the existing keys file for this provider. Values are never returned.
    pub file_key_count: usize,
}

/// Pure resolution of the effective source, matching `key_sources` in keys.py.
pub(crate) fn effective_source(env_set: bool, store: &CredentialStatus, file_keys: usize) -> String {
    if env_set {
        "env".into()
    } else if store.state == "present" {
        "credential_store".into()
    } else if store.state == "unavailable" || store.state == "unreadable" {
        "unavailable".into()
    } else if file_keys > 0 {
        "file".into()
    } else {
        "none".into()
    }
}

/// Keys file location derived from the given variables only (never the process environment).
pub(crate) fn keys_file_path(variables: &BTreeMap<String, String>) -> Option<PathBuf> {
    variables
        .get("USERPROFILE")
        .or_else(|| variables.get("HOME"))
        .filter(|home| !home.is_empty())
        .map(|home| PathBuf::from(home).join(KEYS_FILE_NAME))
}

/// Read-only count of the file keys for one provider. Mirrors keys.py `_file_key_count`.
/// Returns 0 for a missing or unparsable file; never returns or logs a value.
pub(crate) fn file_key_count(path: Option<&Path>, provider: &str) -> usize {
    let Some(path) = path else { return 0 };
    let Ok(text) = std::fs::read_to_string(path) else { return 0 };
    let Ok(Value::Object(map)) = serde_json::from_str::<Value>(text.trim_start_matches('\u{feff}')) else {
        return 0;
    };
    match map.get(provider) {
        Some(Value::String(value)) => usize::from(!value.is_empty()),
        Some(Value::Array(items)) => items
            .iter()
            .filter(|item| item.as_str().is_some_and(|value| !value.is_empty()))
            .count(),
        _ => 0,
    }
}

pub(crate) fn overview(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
) -> CredentialOverview {
    let namespace = credential::namespace(variables);
    let store = credential::status_of(credential::load(backend, &namespace, entry.provider));
    let env_var = entry
        .env
        .iter()
        .find(|name| variables.get(**name).is_some_and(|value| !value.is_empty()))
        .map(|name| name.to_string())
        .unwrap_or_default();
    let file_keys = file_key_count(keys_file_path(variables).as_deref(), entry.provider);
    CredentialOverview {
        source: entry.source.into(),
        effective_source: effective_source(!env_var.is_empty(), &store, file_keys),
        env_overrides_store: !env_var.is_empty() && store.state == "present",
        env_var,
        store,
        file_key_count: file_keys,
    }
}

/// Save a key to the store. Returns the new overview. The key is never echoed.
pub(crate) fn save(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
    key: &str,
    now: f64,
) -> Result<CredentialOverview, String> {
    let namespace = credential::namespace(variables);
    credential::save(backend, &namespace, entry.provider, key, now).map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}

pub(crate) fn delete(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
) -> Result<CredentialOverview, String> {
    let namespace = credential::namespace(variables);
    credential::remove(backend, &namespace, entry.provider).map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}

/// Classification of a source test run, derived from the CLI's `provider_status`.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct TestOutcome {
    /// "success" | "auth_failed" | "quota" | "rate_limited" | "network" | "timeout" | "error" | "missing_key" | "cli_failed"
    pub result: String,
    pub message: String,
}

/// Map one provider error_type to a user-facing test result. Messages never echo secrets.
pub(crate) fn classify(error_type: &str, label: &str) -> TestOutcome {
    let (result, message) = match error_type {
        "invalid" => ("auth_failed", format!("{label} 拒绝了这个 key（认证失败）。请替换为有效的 key。")),
        "quota_exhausted" => ("quota", format!("{label} 额度已用尽。请检查账户额度。")),
        "rate_limit" => ("rate_limited", format!("{label} 触发了频率限制，请稍后再试。")),
        "network" => ("network", format!("无法连接 {label}，请检查网络连接。")),
        "timeout" => ("timeout", format!("{label} 请求超时，请稍后重试。")),
        "missing_key" => ("missing_key", format!("未找到可用的 {label} key，请先保存。")),
        _ => ("error", format!("{label} 测试失败，请查看 CLI 输出。")),
    };
    TestOutcome {
        result: result.into(),
        message,
    }
}

/// Interpret the CLI JSON payload from `search --source <name>` for one allowlisted source.
pub(crate) fn interpret_source(payload: &Value, entry: &SourceEntry) -> TestOutcome {
    let rows = payload
        .get("provider_status")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let wanted = entry.source.replace('-', "_");
    let row = rows.iter().find(|row| {
        row.get("source")
            .and_then(|s| s.as_str())
            .is_some_and(|s| s.replace('-', "_") == wanted)
    });
    let Some(row) = row else {
        return classify("error", entry.label);
    };
    let status = row.get("status").and_then(|s| s.as_str()).unwrap_or("");
    if status == "ok" || status == "partial" {
        return TestOutcome {
            result: "success".into(),
            message: format!("{} 测试成功。", entry.label),
        };
    }
    let error_type = row
        .get("errors")
        .and_then(|e| e.as_array())
        .and_then(|errors| errors.first())
        .and_then(|e| e.get("error_type"))
        .and_then(|t| t.as_str())
        .unwrap_or("error");
    classify(error_type, entry.label)
}

/// Config file content for a test run: no body scraping, so only one search is made.
pub(crate) fn test_config_json() -> String {
    serde_json::json!({ "no_scrape": true }).to_string()
}

/// Arguments for the isolated CLI test run. Key material is never included.
pub(crate) fn test_args(query: &str, entry: &SourceEntry) -> Vec<String> {
    vec![
        "search".into(),
        query.into(),
        "--route".into(),
        "default".into(),
        "--source".into(),
        entry.source.into(),
        "--timeout".into(),
        "15".into(),
        "--format".into(),
        "json".into(),
    ]
}

/// Keep a temp config path for one test run; removed on drop.
pub(crate) struct TestConfig(pub PathBuf);
impl TestConfig {
    pub fn create(dir: &Path, entry: &SourceEntry) -> std::io::Result<Self> {
        let path = dir.join(format!("{}-test-{}.json", entry.provider, std::process::id()));
        std::fs::write(&path, test_config_json())?;
        Ok(Self(path))
    }
}
impl Drop for TestConfig {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

pub(crate) fn test_environment(base: &RuntimeEnvironment, config: &TestConfig) -> RuntimeEnvironment {
    let mut environment = base.clone();
    environment
        .variables
        .insert(CONFIG_ENV.into(), config.0.to_string_lossy().into_owned());
    environment
}

pub(crate) const TEST_TIMEOUT: Duration = Duration::from_secs(30);

impl DesktopManager {
    /// Run one explicit test of an allowlisted source through the CLI, which reads the store itself.
    pub(crate) fn test_source(&self, cli: PathBuf, entry: &SourceEntry, query: &str) -> Result<TestOutcome, String> {
        let dir = std::env::temp_dir();
        let config = TestConfig::create(&dir, entry).map_err(|_| "无法准备测试配置".to_string())?;
        let environment = test_environment(&self.environment, &config);
        let output = crate::process::bounded(&cli, &test_args(query, entry), &environment, TEST_TIMEOUT)
            .map_err(|_| "无法启动 CLI".to_string())?;
        if output.timed_out {
            return Ok(TestOutcome {
                result: "timeout".into(),
                message: "测试超时，请稍后重试。".into(),
            });
        }
        match serde_json::from_str::<Value>(&output.stdout) {
            Ok(payload) if payload.is_object() => Ok(interpret_source(&payload, entry)),
            _ => Ok(TestOutcome {
                result: "cli_failed".into(),
                message: "CLI 未返回有效结果。".into(),
            }),
        }
    }
}

/// Non-Windows hosts have no Credential Manager; every operation fails explicitly.
#[cfg(not(windows))]
struct UnavailableBackend;
#[cfg(not(windows))]
impl CredentialBackend for UnavailableBackend {
    fn read(&self, _target: &str) -> Result<Option<Vec<u8>>, CredentialError> {
        Err(CredentialError::Unavailable(
            "Windows Credential Manager is only available on Windows".into(),
        ))
    }
    fn write(&self, _target: &str, _blob: &[u8]) -> Result<(), CredentialError> {
        Err(CredentialError::Unavailable(
            "Windows Credential Manager is only available on Windows".into(),
        ))
    }
    fn delete(&self, _target: &str) -> Result<bool, CredentialError> {
        Err(CredentialError::Unavailable(
            "Windows Credential Manager is only available on Windows".into(),
        ))
    }
}

/// Run an operation against the real platform store. No plaintext fallback exists.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) fn with_native<T>(operation: impl FnOnce(&dyn CredentialBackend) -> T) -> T {
    #[cfg(windows)]
    {
        operation(&credential::WindowsCredentialBackend)
    }
    #[cfg(not(windows))]
    {
        operation(&UnavailableBackend)
    }
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
struct RequestFile(PathBuf);
impl RequestFile {
    fn create(dir: &Path, request: &MigrationRequest) -> Result<Self, String> {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let path = dir.join(format!("migrate-request-{}-{nanos}.json", std::process::id()));
        let body = serde_json::to_string(request).map_err(|_| "无法准备迁移请求".to_string())?;
        std::fs::write(&path, body).map_err(|_| "无法准备迁移请求".to_string())?;
        Ok(Self(path))
    }
}
impl Drop for RequestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn run_migration_cli(
    manager: &DesktopManager,
    cli: &Path,
    args: &[String],
) -> Result<crate::process::Output, String> {
    let output = crate::process::bounded(cli, args, &manager.environment, TEST_TIMEOUT)
        .map_err(|_| "无法启动 CLI".to_string())?;
    if output.timed_out {
        return Err("迁移操作超时，请稍后重试。".into());
    }
    if output.code != Some(0) {
        return Err("迁移操作未完成，请重新预览后再试。".into());
    }
    Ok(output)
}

impl DesktopManager {
    /// Masked preview of the legacy keys file via the CLI.
    pub(crate) fn migration_plan(&self, cli: PathBuf, keys_file: &Path) -> Result<MigrationPlan, String> {
        let args = vec![
            "migrate-legacy".into(),
            "plan".into(),
            "--keys-file".into(),
            keys_file.to_string_lossy().into_owned(),
            "--format".into(),
            "json".into(),
        ];
        let output = run_migration_cli(self, &cli, &args)?;
        serde_json::from_str::<MigrationPlan>(&output.stdout)
            .map_err(|_| "无法解析迁移预览".to_string())
    }

    /// Apply an approved request via the CLI, which re-checks the file and store itself.
    pub(crate) fn migration_apply(
        &self,
        cli: PathBuf,
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
        let output = run_migration_cli(self, &cli, &args)?;
        serde_json::from_str::<MigrationResult>(&output.stdout)
            .map_err(|_| "无法解析迁移结果".to_string())
    }
}

#[cfg(test)]
mod migration_tests {
    use super::*;

    const TOKEN: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    #[test]
    fn github_repos_maps_to_github_provider_and_duplicates_collapse() {
        let request = migration_request(TOKEN, &["github-repos".into(), "github_repos".into()], &BTreeMap::new()).unwrap();
        assert_eq!(request.approved, vec!["github".to_string()]);
    }

    #[test]
    fn unknown_source_and_bad_token_are_rejected_before_any_cli_call() {
        assert!(migration_request(TOKEN, &["jina".into()], &BTreeMap::new()).is_err());
        assert!(migration_request("not-a-token", &["tavily".into()], &BTreeMap::new()).is_err());
    }

    #[test]
    fn choice_must_be_keep_or_replace_and_match_an_approved_source() {
        let bad_value = BTreeMap::from([("tavily".to_string(), "overwrite".to_string())]);
        assert!(migration_request(TOKEN, &["tavily".into()], &bad_value).is_err());
        let unapproved = BTreeMap::from([("brave".to_string(), "replace".to_string())]);
        assert!(migration_request(TOKEN, &["tavily".into()], &unapproved).is_err());
        let ok = BTreeMap::from([("tavily".to_string(), "replace".to_string())]);
        assert_eq!(migration_request(TOKEN, &["tavily".into()], &ok).unwrap().choices["tavily"], "replace");
    }

    #[test]
    fn request_never_carries_key_material_fields() {
        let request = migration_request(TOKEN, &["tavily".into()], &BTreeMap::new()).unwrap();
        let body = serde_json::to_string(&request).unwrap();
        assert!(body.contains("plan_token") && body.contains("approved") && body.contains("choices"));
        assert!(!body.contains("api_key") && !body.contains("\"key\""));
    }

    #[test]
    fn plan_parse_keeps_preview_masked_and_ignores_unknown_fields() {
        let json = r#"{"plan_token":"abc","items":[{"provider":"tavily","action":"migrate","preview":"synth…0001","extra":1}],"migratable":["tavily"],"skipped":[]}"#;
        let plan: MigrationPlan = serde_json::from_str(json).unwrap();
        assert_eq!(plan.items[0].preview, "synth…0001");
        assert_eq!(plan.migratable, vec!["tavily".to_string()]);
    }
}

/// Real Windows Credential Manager round trip with a synthetic, unique namespace.
/// Runs only when MULTI_SEARCH_NATIVE_CREDENTIAL_TEST=1 so routine test runs never touch the store.
#[cfg(all(test, windows))]
mod native_store {
    use super::*;

    const OPT_IN: &str = "MULTI_SEARCH_NATIVE_CREDENTIAL_TEST";

    struct Cleanup<'a> {
        backend: &'a credential::WindowsCredentialBackend,
        namespace: String,
    }
    impl Drop for Cleanup<'_> {
        fn drop(&mut self) {
            let _ = credential::remove(self.backend, &self.namespace, "tavily");
        }
    }

    #[test]
    fn synthetic_entry_round_trips_through_windows_credential_manager() {
        if std::env::var(OPT_IN).as_deref() != Ok("1") {
            return;
        }
        let namespace = format!("ticket04-native-{}", std::process::id());
        let backend = credential::WindowsCredentialBackend;
        let _cleanup = Cleanup { backend: &backend, namespace: namespace.clone() };
        let vars = BTreeMap::from([(credential::NAMESPACE_ENV.to_string(), namespace.clone())]);
        let entry = resolve_source("tavily").unwrap();

        assert_eq!(overview(&backend, &vars, entry).store.state, "absent");

        let saved = save(&backend, &vars, entry, "  synthetic-native-key-0007  ", 1700000002.0).unwrap();
        assert_eq!(saved.store.state, "present");
        assert_eq!(saved.effective_source, "credential_store");
        assert_eq!(credential::load(&backend, &namespace, entry.provider).unwrap().unwrap().0, "synthetic-native-key-0007");

        let replaced = save(&backend, &vars, entry, "synthetic-native-key-0008", 1700000003.0).unwrap();
        assert_eq!(replaced.store.saved_at, Some(1700000003.0));
        assert_eq!(credential::load(&backend, &namespace, entry.provider).unwrap().unwrap().0, "synthetic-native-key-0008");

        let mut with_env = vars.clone();
        with_env.insert("TAVILY_API_KEY".into(), "synthetic-native-env-0009".into());
        let overridden = overview(&backend, &with_env, entry);
        assert_eq!(overridden.effective_source, "env");
        assert!(overridden.env_overrides_store);

        let cleared = delete(&backend, &vars, entry).unwrap();
        assert_eq!(cleared.store.state, "absent");
        assert_eq!(cleared.effective_source, "none");
        assert_eq!(credential::remove(&backend, &namespace, entry.provider), Ok(false));
    }
}
