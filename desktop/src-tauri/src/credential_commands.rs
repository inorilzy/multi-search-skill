//! Tavily credential management: UI-facing status, save, delete, and an explicit test.
//!
//! The key is accepted once from the UI for `save`, written only to the Windows
//! credential store, and never returned, logged, put in argv, or placed in the
//! child environment. The CLI reads the store itself during `test`.

use crate::credential::{self, CredentialBackend, CredentialStatus};
#[cfg(not(windows))]
use crate::credential::CredentialError;
use crate::{DesktopManager, RuntimeEnvironment};
use serde::Serialize;
use std::{collections::BTreeMap, path::PathBuf, time::Duration};

/// Environment override that wins over the stored key (see `load_keys` priority).
const ENV_OVERRIDE: &str = "TAVILY_API_KEY";
const CONFIG_ENV: &str = "MULTI_SEARCH_CONFIG";

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct CredentialOverview {
    pub store: CredentialStatus,
    /// Effective source for the Tavily key: "env" | "credential_store" | "none" | "unavailable".
    pub effective_source: String,
    /// True when a TAVILY_API_KEY env var overrides the saved UI key.
    pub env_overrides_store: bool,
}

/// Pure resolution of the effective source, matching `key_sources` in keys.py.
pub(crate) fn effective_source(env_set: bool, store: &CredentialStatus) -> String {
    if env_set {
        "env".into()
    } else if store.state == "present" {
        "credential_store".into()
    } else if store.state == "unavailable" || store.state == "unreadable" {
        "unavailable".into()
    } else {
        "none".into()
    }
}

pub(crate) fn overview(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
) -> CredentialOverview {
    let namespace = credential::namespace(variables);
    let store = credential::status_of(credential::load(backend, &namespace));
    let env_set = variables.get(ENV_OVERRIDE).is_some_and(|v| !v.is_empty());
    CredentialOverview {
        effective_source: effective_source(env_set, &store),
        env_overrides_store: env_set && store.state == "present",
        store,
    }
}

/// Save a key to the store. Returns the new overview. The key is never echoed.
pub(crate) fn save(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
    key: &str,
    now: f64,
) -> Result<CredentialOverview, String> {
    let namespace = credential::namespace(variables);
    credential::save(backend, &namespace, key, now).map_err(|e| e.to_string())?;
    Ok(overview(backend, variables))
}

pub(crate) fn delete(
    backend: &dyn CredentialBackend,
    variables: &BTreeMap<String, String>,
) -> Result<CredentialOverview, String> {
    let namespace = credential::namespace(variables);
    credential::remove(backend, &namespace).map_err(|e| e.to_string())?;
    Ok(overview(backend, variables))
}

/// Classification of a Tavily test run, derived from the CLI's `provider_status`.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct TestOutcome {
    /// "success" | "auth_failed" | "quota" | "rate_limited" | "network" | "timeout" | "error" | "missing_key" | "cli_failed"
    pub result: String,
    pub message: String,
}

/// Map one provider error_type to a user-facing test result. Messages never echo secrets.
pub(crate) fn classify_tavily(error_type: &str) -> TestOutcome {
    let (result, message) = match error_type {
        "invalid" => ("auth_failed", "Tavily 拒绝了这个 key（认证失败）。请替换为有效的 key。"),
        "quota_exhausted" => ("quota", "Tavily 额度已用尽。请检查账户额度。"),
        "rate_limit" => ("rate_limited", "Tavily 触发了频率限制，请稍后再试。"),
        "network" => ("network", "无法连接 Tavily，请检查网络连接。"),
        "timeout" => ("timeout", "Tavily 请求超时，请稍后重试。"),
        "missing_key" => ("missing_key", "未找到可用的 Tavily key，请先保存。"),
        _ => ("error", "Tavily 测试失败，请查看 CLI 输出。"),
    };
    TestOutcome {
        result: result.into(),
        message: message.into(),
    }
}

/// Interpret the CLI JSON payload from `search --source tavily`.
pub(crate) fn interpret_payload(payload: &serde_json::Value) -> TestOutcome {
    let rows = payload
        .get("provider_status")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let tavily = rows
        .iter()
        .find(|row| row.get("source").and_then(|s| s.as_str()) == Some("tavily"));
    let Some(row) = tavily else {
        return classify_tavily("error");
    };
    let status = row.get("status").and_then(|s| s.as_str()).unwrap_or("");
    if status == "ok" || status == "partial" {
        return TestOutcome {
            result: "success".into(),
            message: "Tavily 测试成功。".into(),
        };
    }
    let error_type = row
        .get("errors")
        .and_then(|e| e.as_array())
        .and_then(|errors| errors.first())
        .and_then(|e| e.get("error_type"))
        .and_then(|t| t.as_str())
        .unwrap_or("error");
    classify_tavily(error_type)
}

/// Config file content for a test run: no body scraping, so only one Tavily search is made.
pub(crate) fn test_config_json() -> String {
    serde_json::json!({ "no_scrape": true }).to_string()
}

/// Arguments for the isolated CLI test run. Key material is never included.
pub(crate) fn test_args(query: &str) -> Vec<String> {
    vec![
        "search".into(),
        query.into(),
        "--route".into(),
        "default".into(),
        "--source".into(),
        "tavily".into(),
        "--timeout".into(),
        "15".into(),
        "--format".into(),
        "json".into(),
    ]
}

/// Keep a temp config path for one test run; removed on drop.
pub(crate) struct TestConfig(pub PathBuf);
impl TestConfig {
    pub fn create(dir: &std::path::Path) -> std::io::Result<Self> {
        let path = dir.join(format!("tavily-test-{}.json", std::process::id()));
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
    /// Run one explicit Tavily test through the CLI process, which reads the store itself.
    pub fn test_tavily(&self, cli: PathBuf, query: &str) -> Result<TestOutcome, String> {
        let dir = std::env::temp_dir();
        let config = TestConfig::create(&dir).map_err(|_| "无法准备测试配置".to_string())?;
        let environment = test_environment(&self.environment, &config);
        let output = crate::process::bounded(&cli, &test_args(query), &environment, TEST_TIMEOUT)
            .map_err(|_| "无法启动 CLI".to_string())?;
        if output.timed_out {
            return Ok(TestOutcome {
                result: "timeout".into(),
                message: "测试超时，请稍后重试。".into(),
            });
        }
        match serde_json::from_str::<serde_json::Value>(&output.stdout) {
            Ok(payload) if payload.is_object() => Ok(interpret_payload(&payload)),
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
            let _ = credential::remove(self.backend, &self.namespace);
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

        assert_eq!(overview(&backend, &vars).store.state, "absent");

        let saved = save(&backend, &vars, "  synthetic-native-key-0007  ", 1700000002.0).unwrap();
        assert_eq!(saved.store.state, "present");
        assert_eq!(saved.effective_source, "credential_store");
        assert_eq!(credential::load(&backend, &namespace).unwrap().unwrap().0, "synthetic-native-key-0007");

        let replaced = save(&backend, &vars, "synthetic-native-key-0008", 1700000003.0).unwrap();
        assert_eq!(replaced.store.saved_at, Some(1700000003.0));
        assert_eq!(credential::load(&backend, &namespace).unwrap().unwrap().0, "synthetic-native-key-0008");

        let mut with_env = vars.clone();
        with_env.insert(ENV_OVERRIDE.into(), "synthetic-native-env-0009".into());
        let overridden = overview(&backend, &with_env);
        assert_eq!(overridden.effective_source, "env");
        assert!(overridden.env_overrides_store);

        let cleared = delete(&backend, &vars).unwrap();
        assert_eq!(cleared.store.state, "absent");
        assert_eq!(cleared.effective_source, "none");
        assert_eq!(credential::remove(&backend, &namespace), Ok(false));
    }
}
