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
#[cfg(feature = "native-window")]
use crate::{DesktopManager, RuntimeEnvironment};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;
use std::{collections::BTreeMap, path::{Path, PathBuf}};

#[cfg(feature = "native-window")]
const CONFIG_ENV: &str = "MULTI_SEARCH_CONFIG";
const KEYS_FILE_NAME: &str = ".search-keys.json";

/// One catalog entry the desktop may manage. Names, key providers, env aliases,
/// and labels all come from the shared generated catalog; this module only maps
/// the UI name to them.
pub(crate) use crate::source_catalog::Source as SourceEntry;

/// Map a keyed UI source name or CLI alias to its catalog entry. Unknown or
/// keyless names are rejected before any store access; the error never echoes
/// the input. A missing name is an error, not a default.
pub(crate) fn resolve_source(name: &str) -> Result<&'static SourceEntry, String> {
    crate::source_catalog::catalog()
        .source(name)
        .filter(|entry| entry.keyed)
        .ok_or_else(|| "不支持的搜索源".to_string())
}

/// Keyed sources plus keyless search sources, which have an explicit test path.
pub(crate) fn resolve_test_source(name: &str) -> Result<&'static SourceEntry, String> {
    crate::source_catalog::catalog()
        .source(name)
        .filter(|entry| entry.searchable)
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

/// One row of Core's `doctor --format json` → `key_sources` report.
///
/// The desktop never derives the effective source itself: `window::credential_status`
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
/// boundary; unit tests may omit it and use the test-fixtures fallback below.
pub(crate) fn apply_core_source(overview: &mut CredentialOverview, core: Option<&CoreKeySource>) {
    let Some(core) = core else { return };
    overview.effective_source = core.effective_source.clone();
    overview.env_overrides_store = core.env_overrides_store;
    overview.env_var = core.env_vars_set.last().cloned().unwrap_or_default();
    overview.file_key_count = core.file_key_count;
}

/// Test-only mirror of Core's rule, so the fixture tests can exercise the
/// desktop without spawning the CLI. Product builds never evaluate this: the
/// source always comes from `CoreKeySource`.
#[cfg(feature = "test-fixtures")]
fn fallback_effective_source(env_set: bool, store: &CredentialStatus, file_keys: usize) -> String {
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

/// Without Core data and without the test fixture, report "unavailable" rather
/// than guessing from local state: fail visible, never contradict Core.
#[cfg(not(feature = "test-fixtures"))]
fn fallback_effective_source(_env_set: bool, _store: &CredentialStatus, _file_keys: usize) -> String {
    "unavailable".into()
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
    let store = credential::status_of(credential::load(backend, &namespace, &entry.key_provider));
    // The catalog lists env aliases in load_keys application order, so the last
    // non-empty value wins (mirrors Python and scripts/export_source_catalog.py).
    let env_var = entry
        .env
        .iter()
        .rev()
        .find(|name| variables.get(name.as_str()).is_some_and(|value| !value.is_empty()))
        .cloned()
        .unwrap_or_default();
    let file_keys = file_key_count(keys_file_path(variables).as_deref(), &entry.key_provider);
    CredentialOverview {
        source: entry.name.clone(),
        effective_source: fallback_effective_source(!env_var.is_empty(), &store, file_keys),
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
    credential::save(backend, &namespace, &entry.key_provider, key, now).map_err(|e| e.to_string())?;
    Ok(overview(backend, variables, entry))
}

pub(crate) fn delete(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    entry: &SourceEntry,
) -> Result<CredentialOverview, String> {
    let namespace = credential::namespace(variables);
    credential::remove(backend, &namespace, &entry.key_provider).map_err(|e| e.to_string())?;
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
        "credential_store" => (
            "credential_store",
            format!("无法读取凭据库中 {label} 的 key。请重新保存该来源的 key。"),
        ),
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
    let wanted = entry.name.replace('-', "_");
    let row = rows.iter().find(|row| {
        row.get("source")
            .and_then(|s| s.as_str())
            .is_some_and(|s| s.replace('-', "_") == wanted)
    });
    let Some(row) = row else {
        return classify("error", &entry.label);
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
    classify(error_type, &entry.label)
}

/// Search budget the isolated test run hands to the CLI via `--timeout`.
pub(crate) const TEST_SEARCH_TIMEOUT_SECS: u64 = 15;
/// Allowance for process start, Python import, CLI output and exit.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) const TEST_PROCESS_OVERHEAD_SECS: u64 = 10;
/// Whole-process deadline for one test run: Core's search budget plus the fixed
/// process overhead. The test run is candidate-only (`--no-fetch`), so there is
/// deliberately no 60s body-fetch stage to cover here.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) const TEST_TIMEOUT: Duration =
    Duration::from_secs(TEST_SEARCH_TIMEOUT_SECS + TEST_PROCESS_OVERHEAD_SECS);

/// Arguments for the isolated CLI test run. Key material is never included.
///
/// `--no-fetch` makes Core fuse candidates and stop: the test spends one search
/// budget, contacts no scraper, and writes no body cache. `--timeout` must stay
/// the same budget [`TEST_TIMEOUT`] was derived from.
pub(crate) fn test_args(query: &str, entry: &SourceEntry) -> Vec<String> {
    // Options first, then `--`: a query starting with `-` stays a query.
    vec![
        "search".into(),
        "--route".into(),
        "default".into(),
        "--source".into(),
        entry.name.clone(),
        "--no-fetch".into(),
        "--timeout".into(),
        TEST_SEARCH_TIMEOUT_SECS.to_string(),
        "--format".into(),
        "json".into(),
        "--".into(),
        query.into(),
    ]
}

/// Keep a temp config path for one test run; removed on drop.
#[cfg(feature = "native-window")]
pub(crate) struct TestConfig(pub PathBuf);
#[cfg(feature = "native-window")]
impl TestConfig {
    /// The config is written to a fresh, randomly named file created with `create_new`, so a file
    /// planted in a shared temp directory can never be read by the CLI as its config.
    pub fn create(dir: &Path, entry: &SourceEntry, environment: &RuntimeEnvironment) -> std::io::Result<Self> {
        let view = crate::settings::view(environment);
        if view.status == "config_unreadable" {
            return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, "无法读取搜索设置"));
        }
        // The test run does not rely on `no_scrape`: Core ignores it, and
        // `--no-fetch` expresses candidates-only directly. The temp config only
        // carries the user's disabled sources and Twitter cookie path.
        let mut config = serde_json::json!({});
        config["disabled_sources"] = serde_json::json!(view.disabled_sources);
        if let Some(cookies) = view.twitter_cookies_path { config["twitter_cookies_path"] = Value::String(cookies); }
        let path = crate::secure_temp::create_file(dir, &format!("multi-search-{}-test-", entry.key_provider), ".json", &serde_json::to_vec(&config)?)?;
        Ok(Self(path))
    }
}
#[cfg(feature = "native-window")]
impl Drop for TestConfig {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[cfg(feature = "native-window")]
pub(crate) fn test_environment(base: &RuntimeEnvironment, config: &TestConfig) -> RuntimeEnvironment {
    let mut environment = base.clone();
    environment
        .variables
        .insert(CONFIG_ENV.into(), config.0.to_string_lossy().into_owned());
    environment
}

/// Only the native window's explicit source test uses the isolated config path above.
#[cfg(feature = "native-window")]
impl DesktopManager {
    /// Run one explicit test of an allowlisted source through the CLI, which reads the store itself.
    pub(crate) fn test_source(&self, cli: PathBuf, entry: &SourceEntry, query: &str) -> Result<TestOutcome, String> {
        let dir = std::env::temp_dir();
        let config = TestConfig::create(&dir, entry, &self.environment).map_err(|_| "无法准备测试配置".to_string())?;
        let environment = test_environment(&self.environment, &config);
        // Only this source's own key variables (and the fetch-stage keys) reach the child.
        let credentials = crate::execution::search_credentials("default", &[entry.name.clone()]);
        let output = crate::process::bounded_with(&cli, &test_args(query, entry), &environment, &credentials, TEST_TIMEOUT)
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
        approved.push(resolve_source(source)?.key_provider.to_string());
    }
    approved.sort();
    approved.dedup();
    let mut choices = BTreeMap::new();
    for (source, choice) in choices_by_source {
        let provider = resolve_source(source)?.key_provider.to_string();
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

#[cfg(feature = "native-window")]
fn run_migration_cli(
    manager: &DesktopManager,
    cli: &Path,
    args: &[String],
) -> Result<crate::process::Output, String> {
    // Legacy migration is local file/state work and has no network stage.
    const MIGRATION_TIMEOUT: Duration = Duration::from_secs(30);
    let output = crate::process::bounded(cli, args, &manager.environment, MIGRATION_TIMEOUT)
        .map_err(|_| "无法启动 CLI".to_string())?;
    if output.timed_out {
        return Err("迁移操作超时，请稍后重试。".into());
    }
    if output.code != Some(0) {
        return Err("迁移操作未完成，请重新预览后再试。".into());
    }
    Ok(output)
}

#[cfg(feature = "native-window")]
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
mod test_run_budget {
    use super::*;

    #[test]
    fn test_run_is_candidates_only_and_uses_the_same_search_budget() {
        let entry = resolve_test_source("tavily").unwrap();
        let args = test_args("synthetic connectivity", entry);
        assert!(
            args.iter().any(|argument| argument.as_str() == "--no-fetch"),
            "a test run must never fetch page bodies: {args:?}"
        );
        let index = args
            .iter()
            .position(|argument| argument.as_str() == "--timeout")
            .expect("the test run always passes an explicit search budget");
        let budget: u64 = args[index + 1].parse().expect("an integer search budget");
        assert_eq!(budget, TEST_SEARCH_TIMEOUT_SECS);
        assert!(
            TEST_TIMEOUT.as_secs() >= budget + 5,
            "the process deadline must cover the search budget plus real process overhead"
        );
    }
}

#[cfg(test)]
mod migration_tests {
    use super::*;

    const TOKEN: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    #[cfg(feature = "native-window")]
    #[test]
    fn source_test_config_keeps_twitter_path_and_disabled_sources_without_cookie_contents() {
        let root = std::env::temp_dir().join(format!("ms-test-settings-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let cookies = root.join("cookies.json");
        std::fs::write(&cookies, "synthetic-cookie-secret").unwrap();
        let settings = root.join("settings.json");
        std::fs::write(&settings, serde_json::to_vec(&serde_json::json!({"twitter_cookies_path": cookies, "disabled_sources": ["brave"]})).unwrap()).unwrap();
        let environment = RuntimeEnvironment { variables: BTreeMap::from([
            ("HOME".into(), root.to_string_lossy().into_owned()),
            ("USERPROFILE".into(), root.to_string_lossy().into_owned()),
            (CONFIG_ENV.into(), settings.to_string_lossy().into_owned()),
        ]), app_path: vec![], user_path: vec![], cwd: root.clone() };
        let entry = resolve_test_source("twitter").unwrap();
        let config = TestConfig::create(&root, entry, &environment).unwrap();
        let raw = std::fs::read_to_string(&config.0).unwrap();
        let value: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(value["twitter_cookies_path"], serde_json::json!(cookies));
        assert_eq!(value["disabled_sources"], serde_json::json!(["brave"]));
        assert!(
            value.get("no_scrape").is_none(),
            "the test run must not rely on the no_scrape key Core ignores"
        );
        assert!(!raw.contains("synthetic-cookie-secret"));
        drop(config);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn migration_request_file_has_an_unpredictable_name_and_never_reuses_a_planted_file() {
        let dir = std::env::temp_dir().join(format!("ms-request-{}", crate::secure_temp::token()));
        std::fs::create_dir_all(&dir).unwrap();
        // The old, guessable name pattern: a file planted there must stay untouched and unused.
        let planted = dir.join(format!("migrate-request-{}-0.json", std::process::id()));
        std::fs::write(&planted, b"attacker").unwrap();
        let request = migration_request(TOKEN, &["tavily".into()], &BTreeMap::new()).unwrap();
        let first = RequestFile::create(&dir, &request).unwrap();
        let second = RequestFile::create(&dir, &request).unwrap();
        assert_ne!(first.0, second.0);
        assert_ne!(first.0, planted);
        let name = first.0.file_name().unwrap().to_string_lossy().into_owned();
        assert!(!name.contains(&std::process::id().to_string()), "{name} must not embed the PID");
        assert_eq!(std::fs::read(&planted).unwrap(), b"attacker");
        let written: Value = serde_json::from_slice(&std::fs::read(&first.0).unwrap()).unwrap();
        assert_eq!(written["approved"], serde_json::json!(["tavily"]));
        let path = first.0.clone();
        drop(first);
        assert!(!path.exists(), "the request file is removed on drop");
        drop(second);
        std::fs::remove_dir_all(dir).unwrap();
    }

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
        let json = r#"{"plan_token":"abc","items":[{"provider":"tavily","action":"migrate","preview":"sha256:1a2b3c4d","extra":1}],"migratable":["tavily"],"skipped":[]}"#;
        let plan: MigrationPlan = serde_json::from_str(json).unwrap();
        assert_eq!(plan.items[0].preview, "sha256:1a2b3c4d");
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
        assert_eq!(credential::load(&backend, &namespace, &entry.key_provider).unwrap().unwrap().0, "synthetic-native-key-0007");

        let replaced = save(&backend, &vars, entry, "synthetic-native-key-0008", 1700000003.0).unwrap();
        assert_eq!(replaced.store.saved_at, Some(1700000003.0));
        assert_eq!(credential::load(&backend, &namespace, &entry.key_provider).unwrap().unwrap().0, "synthetic-native-key-0008");

        let mut with_env = vars.clone();
        with_env.insert("TAVILY_API_KEY".into(), "synthetic-native-env-0009".into());
        let overridden = overview(&backend, &with_env, entry);
        assert_eq!(overridden.effective_source, "env");
        assert!(overridden.env_overrides_store);

        let cleared = delete(&backend, &vars, entry).unwrap();
        assert_eq!(cleared.store.state, "absent");
        assert_eq!(cleared.effective_source, "none");
        assert_eq!(credential::remove(&backend, &namespace, &entry.key_provider), Ok(false));
    }
}
