//! Allowlisted desktop credential operations. Overview is non-secret; read returns one source
//! only when its editor is expanded. All native persistence is SQLite/DPAPI, never legacy fallback.
#![cfg_attr(not(feature = "native-window"), allow(dead_code))]
use crate::credential::{self, CredentialBackend, CredentialStatus};
#[cfg(feature = "native-window")]
use crate::DesktopManager;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct SourceEntry {
    pub source: &'static str,
    pub provider: &'static str,
    pub aliases: &'static [&'static str],
    pub label: &'static str,
}
pub(crate) const SOURCES: &[SourceEntry] = &[
    SourceEntry {
        source: "baidu",
        provider: "baidu",
        aliases: &[],
        label: "Baidu AI 搜索",
    },
    SourceEntry {
        source: "brave",
        provider: "brave",
        aliases: &[],
        label: "Brave 搜索",
    },
    SourceEntry {
        source: "parallel",
        provider: "parallel",
        aliases: &[],
        label: "Parallel",
    },
    SourceEntry {
        source: "tavily",
        provider: "tavily",
        aliases: &[],
        label: "Tavily",
    },
    SourceEntry {
        source: "exa",
        provider: "exa",
        aliases: &[],
        label: "Exa",
    },
    SourceEntry {
        source: "firecrawl",
        provider: "firecrawl",
        aliases: &[],
        label: "Firecrawl",
    },
    SourceEntry {
        source: "serpapi",
        provider: "serpapi",
        aliases: &[],
        label: "SerpAPI",
    },
    SourceEntry {
        source: "github-repos",
        provider: "github",
        aliases: &["github_repos"],
        label: "GitHub 仓库",
    },
];
pub(crate) fn resolve_source(name: &str) -> Result<&'static SourceEntry, String> {
    SOURCES
        .iter()
        .find(|e| e.source == name.trim() || e.aliases.contains(&name.trim()))
        .ok_or_else(|| "不支持的搜索源".into())
}
const NON_KEY_SOURCES: &[SourceEntry] = &[
    SourceEntry {
        source: "hackernews",
        provider: "hackernews",
        aliases: &[],
        label: "Hacker News",
    },
    SourceEntry {
        source: "stackoverflow",
        provider: "stackoverflow",
        aliases: &[],
        label: "Stack Overflow",
    },
    SourceEntry {
        source: "sov2ex",
        provider: "sov2ex",
        aliases: &[],
        label: "V2EX",
    },
    SourceEntry {
        source: "twitter",
        provider: "twitter",
        aliases: &[],
        label: "Twitter",
    },
];
pub(crate) fn resolve_test_source(name: &str) -> Result<&'static SourceEntry, String> {
    resolve_source(name).or_else(|_| {
        NON_KEY_SOURCES
            .iter()
            .find(|e| e.source == name)
            .ok_or_else(|| "不支持的搜索源".into())
    })
}
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct CredentialOverview {
    pub source: String,
    pub store: CredentialStatus,
    pub effective_source: String,
    pub key_application_available: bool,
}
#[cfg(feature = "native-window")]
pub(crate) fn keys_file_path(variables: &BTreeMap<String, String>) -> Option<PathBuf> {
    variables
        .get("USERPROFILE")
        .or_else(|| variables.get("HOME"))
        .filter(|v| !v.is_empty())
        .map(|h| PathBuf::from(h).join(".search-keys.json"))
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
        fn read(&self, _: &str) -> Result<Option<Vec<u8>>,credential::CredentialError> { Err(credential::CredentialError::Unavailable("无法定位配置数据库".into())) }
        fn write(&self, _: &str, _: &[u8]) -> Result<(),credential::CredentialError> { Err(credential::CredentialError::Unavailable("无法定位配置数据库".into())) }
        fn delete(&self, _: &str) -> Result<bool,credential::CredentialError> { Err(credential::CredentialError::Unavailable("无法定位配置数据库".into())) }
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
            &["doctor".into(), "--no-keys".into(), "--format".into(), "json".into()],
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
        if payload.get("config_error").is_some() || payload.get("keys_error").is_some() || output.code != Some(0) {
            return Err("CLI 支持 SQLite/DPAPI，但当前配置数据库或凭据无法读取，请检查数据库。".into());
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
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationSource {
    pub source: String,
    #[serde(default)]
    pub preview: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationItem {
    pub provider: String,
    pub action: String,
    #[serde(default)]
    pub preview: Value,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub sources: Vec<MigrationSource>,
    #[serde(default)]
    pub source_conflict: bool,
    #[serde(default)]
    pub target_conflict: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationPlan {
    pub plan_token: String,
    pub items: Vec<MigrationItem>,
    pub migratable: Vec<String>,
    pub skipped: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MigrationResult {
    pub written: Vec<String>,
    pub kept: Vec<String>,
    pub unchanged: Vec<String>,
    pub failed: Vec<String>,
    pub not_done: Vec<String>,
    pub complete: bool,
}
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub(crate) struct MigrationRequest {
    pub plan_token: String,
    pub approved: Vec<String>,
    pub choices: BTreeMap<String, String>,
    pub sources: BTreeMap<String, String>,
}
#[derive(Clone, Debug, Default, Deserialize)]
pub struct MigrationSelection {
    #[serde(default)]
    pub keys_file: bool,
    #[serde(default)]
    pub credentials: bool,
    #[serde(default)]
    pub environment: bool,
    #[serde(default)]
    pub settings: bool,
}
fn migration_provider(source: &str) -> Result<String, String> {
    if source == "settings" || source == "jina" {
        Ok(source.into())
    } else {
        Ok(resolve_source(source)?.provider.into())
    }
}
pub(crate) fn migration_request(
    plan_token: &str,
    approved_sources: &[String],
    choices_by_source: &BTreeMap<String, String>,
    sources_by_source: &BTreeMap<String, String>,
) -> Result<MigrationRequest, String> {
    if plan_token.len() != 64 || !plan_token.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("迁移预览无效，请重新预览".into());
    }
    let mut approved = approved_sources
        .iter()
        .map(|s| migration_provider(s))
        .collect::<Result<Vec<_>, _>>()?;
    approved.sort();
    approved.dedup();
    let mut choices = BTreeMap::new();
    for (s, c) in choices_by_source {
        let p = migration_provider(s)?;
        if !approved.contains(&p) || !matches!(c.as_str(), "keep" | "replace") {
            return Err("冲突选择无效".into());
        }
        choices.insert(p, c.clone());
    }
    let mut sources = BTreeMap::new();
    for (s, c) in sources_by_source {
        let p = migration_provider(s)?;
        if !approved.contains(&p)
            || !(matches!(c.as_str(), "file" | "credentials" | "settings_file")
                || c.starts_with("environment:")
                    && c[12..]
                        .chars()
                        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_'))
        {
            return Err("导入来源选择无效".into());
        }
        sources.insert(p, c.clone());
    }
    Ok(MigrationRequest {
        plan_token: plan_token.into(),
        approved,
        choices,
        sources,
    })
}
#[cfg(feature = "native-window")]
fn migration_args(
    variables: &BTreeMap<String, String>,
    selection: &MigrationSelection,
) -> Result<Vec<String>, String> {
    let mut args = vec![];
    if selection.keys_file {
        args.extend([
            "--keys-file".into(),
            keys_file_path(variables)
                .ok_or("无法定位旧 Key 文件")?
                .to_string_lossy()
                .into_owned(),
        ]);
    }
    if selection.settings {
        let home = variables
            .get("USERPROFILE")
            .or_else(|| variables.get("HOME"))
            .ok_or("无法定位旧配置文件")?;
        let path = variables
            .get("MULTI_SEARCH_CONFIG")
            .filter(|s| !s.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(home)
                    .join(".multi-search")
                    .join("multi-search-config.json")
            });
        args.extend([
            "--settings-file".into(),
            path.to_string_lossy().into_owned(),
        ]);
    }
    if selection.credentials {
        args.push("--include-credentials".into());
    }
    if selection.environment {
        args.push("--include-environment".into());
    }
    if args.is_empty() {
        return Err("请选择至少一个旧配置来源".into());
    }
    Ok(args)
}
#[cfg(feature = "native-window")]
struct RequestFile(PathBuf);
#[cfg(feature = "native-window")]
impl Drop for RequestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
#[cfg(feature = "native-window")]
impl DesktopManager {
    fn run_migration(&self, cli: &Path, args: &[String]) -> Result<crate::process::Output, String> {
        self.require_storage_cli(cli)?;
        let output = crate::process::bounded(cli, args, &self.environment, TEST_TIMEOUT)
            .map_err(|_| "无法启动 CLI".to_string())?;
        if output.timed_out || output.code != Some(0) {
            return Err("迁移未完成，请重新预览后再试。".into());
        }
        Ok(output)
    }
    pub(crate) fn migration_plan(
        &self,
        cli: PathBuf,
        selection: &MigrationSelection,
    ) -> Result<MigrationPlan, String> {
        let mut args = vec!["migrate-legacy".into(), "plan".into()];
        args.extend(migration_args(&self.environment.variables, selection)?);
        args.extend(["--format".into(), "json".into()]);
        serde_json::from_str(&self.run_migration(&cli, &args)?.stdout)
            .map_err(|_| "无法解析迁移预览".into())
    }
    pub(crate) fn migration_apply(
        &self,
        cli: PathBuf,
        selection: &MigrationSelection,
        request: &MigrationRequest,
    ) -> Result<MigrationResult, String> {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let path = std::env::temp_dir().join(format!(
            "migration-request-{}-{nanos}.json",
            std::process::id()
        ));
        let file = RequestFile(path);
        std::fs::write(
            &file.0,
            serde_json::to_vec(request).map_err(|_| "无法准备迁移请求")?,
        )
        .map_err(|_| "无法准备迁移请求")?;
        let mut args = vec!["migrate-legacy".into(), "apply".into()];
        args.extend(migration_args(&self.environment.variables, selection)?);
        args.extend([
            "--request".into(),
            file.0.to_string_lossy().into_owned(),
            "--format".into(),
            "json".into(),
        ]);
        serde_json::from_str(&self.run_migration(&cli, &args)?.stdout)
            .map_err(|_| "无法解析迁移结果".into())
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
    #[test]
    fn real_python_cli_migration_plan_preserves_masked_multi_key_and_jina_shapes() {
        let root = std::env::temp_dir().join(format!("ms-plan-contract-{}",std::process::id()));
        let _ = std::fs::remove_dir_all(&root); std::fs::create_dir_all(&root).unwrap();
        struct Cleanup(PathBuf); impl Drop for Cleanup { fn drop(&mut self) { let _=std::fs::remove_dir_all(&self.0); } }
        let _cleanup=Cleanup(root.clone()); let keys=root.join("keys.json");
        std::fs::write(&keys, serde_json::to_vec(&serde_json::json!({"tavily":["synthetic-plan-key-0001","synthetic-plan-key-0002"],"jina":[{"key":"synthetic-plan-jina-0001","exhausted":true},{"key":"synthetic-plan-jina-0002","exhausted":false}]})).unwrap()).unwrap();
        let output=std::process::Command::new("python").args(["-B","-m","multi_search_mcp.cli","migrate-legacy","plan","--keys-file"]).arg(&keys).args(["--format","json"])
            .env("PYTHONPATH",PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
            .env("USERPROFILE",&root).env("HOME",&root).env("MULTI_SEARCH_CONFIG_DB",root.join("config.sqlite")).env("MULTI_SEARCH_STATE_DB",root.join("state.sqlite")).output().unwrap();
        assert!(output.status.success(),"{}",String::from_utf8_lossy(&output.stderr));
        let plan:MigrationPlan=serde_json::from_slice(&output.stdout).unwrap();
        let tavily=plan.items.iter().find(|i|i.provider=="tavily").unwrap();let jina=plan.items.iter().find(|i|i.provider=="jina").unwrap();
        assert!(tavily.preview.is_array());assert!(tavily.sources[0].preview.is_array());
        assert!(jina.preview.is_array());assert!(jina.preview[0].is_object());assert_eq!(jina.preview[0]["exhausted"],true);
        assert_eq!(jina.sources[0].preview,jina.preview);
        let raw=String::from_utf8(output.stdout).unwrap();for key in ["synthetic-plan-key-0001","synthetic-plan-jina-0001"] {assert!(!raw.contains(key));}
    }
    #[test]
    fn migration_request_handles_jina_settings_and_source_conflicts() {
        let token = "a".repeat(64);
        let req = migration_request(
            &token,
            &["jina".into(), "settings".into()],
            &BTreeMap::from([("settings".into(), "replace".into())]),
            &BTreeMap::from([("jina".into(), "file".into())]),
        )
        .unwrap();
        assert_eq!(req.approved, vec!["jina", "settings"]);
        assert_eq!(req.sources["jina"], "file");
        assert!(migration_request(
            &token,
            &["../key".into()],
            &BTreeMap::new(),
            &BTreeMap::new()
        )
        .is_err());
    }
}
