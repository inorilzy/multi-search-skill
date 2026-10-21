//! Allowlisted desktop credential operations. Overview is non-secret; read returns one source
//! only when its editor is expanded. All native persistence is SQLite/DPAPI, never legacy fallback.
#![cfg_attr(not(feature = "native-window"), allow(dead_code))]
use crate::credential::{self, CredentialBackend, CredentialStatus};
use crate::provider::{self, ProviderEntry};
use serde::Serialize;
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
    let entry = provider::PROVIDERS
        .iter()
        .find(|entry| {
            entry.cli_source == trimmed
                || entry.source == trimmed
                || entry.aliases.contains(&trimmed)
        })
        .ok_or_else(|| "不支持的搜索源".to_string())?;
    if keyed_only && !entry.keyed {
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
pub struct CredentialOverview {
    pub source: String,
    pub store: CredentialStatus,
    pub effective_source: String,
    pub key_application_available: bool,
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
    let effective_source = match store.state.as_str() {
        "present" => "sqlite",
        "absent" => "none",
        _ => "unavailable",
    }
    .into();
    CredentialOverview {
        source: entry.source.into(),
        store,
        effective_source,
        key_application_available: application_url(entry.source).is_some(),
    }
}
#[derive(Serialize)]
pub struct CredentialValue {
    pub value: String,
}
pub(crate) fn read(
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
            .filter_map(Value::as_str)
            .collect::<Vec<_>>()
            .join("\n"),
        Some(_) => return Err("此凭据结构不能作为搜索 API Key 编辑".into()),
    };
    Ok(CredentialValue { value })
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

// User has not supplied application URLs. This is the sole fixed mapping; never accept UI URLs.
const APPLICATION_URLS: &[(&str, Option<&str>)] = &[
    ("baidu", None),
    ("brave", None),
    ("parallel", None),
    ("tavily", None),
    ("exa", None),
    ("firecrawl", None),
    ("serpapi", None),
    ("github-repos", None),
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
pub struct TestOutcome {
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
        "--no-scrape".into(),
    ]
}
const TEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);
pub(crate) fn supports_storage(payload: &Value) -> bool {
    payload.get("config_storage").is_some_and(|v| {
        v.get("backend").and_then(Value::as_str) == Some("sqlite-dpapi")
            && v.get("schema_version").and_then(Value::as_i64) == Some(1)
    })
}
impl crate::DesktopManager {
    pub(crate) fn require_storage_cli(&self, cli: &Path) -> Result<(), String> {
        let output = crate::process::bounded(
            cli,
            &[
                "doctor".into(),
                "--no-keys".into(),
                "--format".into(),
                "json".into(),
            ],
            &self.environment,
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
    pub(crate) fn test_source(
        &self,
        cli: PathBuf,
        entry: &SourceEntry,
        query: &str,
    ) -> Result<TestOutcome, String> {
        self.require_storage_cli(&cli)?;
        let output = crate::process::bounded(
            &cli,
            &test_args(query, entry),
            &self.environment,
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

#[cfg(test)]
mod tests {
    use super::*;

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
        assert_eq!(open_application("tavily").unwrap_err(), "申请链接待配置");
    }
}
