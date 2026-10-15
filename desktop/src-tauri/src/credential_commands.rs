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
use serde::Serialize;
use serde_json::Value;
#[cfg(feature = "native-window")]
use std::time::Duration;
use std::{collections::BTreeMap, path::{Path, PathBuf}};

#[cfg(feature = "native-window")]
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

const NON_KEY_SOURCES: &[SourceEntry] = &[
    SourceEntry { source: "hackernews", provider: "hackernews", env: &[], aliases: &[], label: "Hacker News" },
    SourceEntry { source: "stackoverflow", provider: "stackoverflow", env: &[], aliases: &[], label: "Stack Overflow" },
    SourceEntry { source: "sov2ex", provider: "sov2ex", env: &[], aliases: &[], label: "V2EX" },
    SourceEntry { source: "twitter", provider: "twitter", env: &[], aliases: &[], label: "Twitter" },
];

pub(crate) fn resolve_test_source(name: &str) -> Result<&'static SourceEntry, String> {
    resolve_source(name).or_else(|_| NON_KEY_SOURCES.iter().find(|entry| entry.source == name).ok_or_else(|| "不支持的搜索源".into()))
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
    // Python load_keys applies aliases in declaration order, so the last nonempty value wins.
    let env_var = entry
        .env
        .iter()
        .rev()
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
#[cfg(feature = "native-window")]
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
#[cfg(feature = "native-window")]
pub(crate) struct TestConfig(pub PathBuf);
#[cfg(feature = "native-window")]
impl TestConfig {
    pub fn create(dir: &Path, entry: &SourceEntry, environment: &RuntimeEnvironment) -> std::io::Result<Self> {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let id = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let path = dir.join(format!("{}-test-{}-{id}.json", entry.provider, std::process::id()));
        let view = crate::settings::view(environment);
        if view.status == "config_unreadable" {
            return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, "无法读取搜索设置"));
        }
        let mut config: Value = serde_json::from_str(&test_config_json()).unwrap();
        config["disabled_sources"] = serde_json::json!(view.disabled_sources);
        if let Some(cookies) = view.twitter_cookies_path { config["twitter_cookies_path"] = Value::String(cookies); }
        std::fs::write(&path, serde_json::to_vec(&config)?)?;
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

#[cfg(feature = "native-window")]
pub(crate) const TEST_TIMEOUT: Duration = Duration::from_secs(30);

/// Only the native window's explicit source test uses the isolated config path above.
#[cfg(feature = "native-window")]
impl DesktopManager {
    /// Run one explicit test of an allowlisted source through the CLI, which reads the store itself.
    pub(crate) fn test_source(&self, cli: PathBuf, entry: &SourceEntry, query: &str) -> Result<TestOutcome, String> {
        let dir = std::env::temp_dir();
        let config = TestConfig::create(&dir, entry, &self.environment).map_err(|_| "无法准备测试配置".to_string())?;
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

#[cfg(test)]
mod test_config_tests {
    use super::*;

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
        assert_eq!(value["no_scrape"], true);
        assert!(!raw.contains("synthetic-cookie-secret"));
        drop(config);
        std::fs::remove_dir_all(root).unwrap();
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
