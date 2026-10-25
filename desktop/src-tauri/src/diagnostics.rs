use crate::user_path::PathStore;
use serde::Serialize;
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};

/// Explicit system boundary: production snapshots the environment; tests supply a disposable one.
#[derive(Clone)]
pub struct RuntimeEnvironment {
    pub app_path: Vec<PathBuf>,
    pub user_path: Vec<PathBuf>,
    pub variables: BTreeMap<String, String>,
    pub cwd: PathBuf,
}

#[derive(Clone, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct Discovery {
    /// One of `ready`, `missing`, `not_executable`, `version_failed`, `unavailable`, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub path: Option<String>,
    pub version: Option<String>,
    pub reason: String,
}

#[derive(Clone, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct CliStatus {
    pub app: Discovery,
    pub user: Discovery,
    pub restart_required: bool,
    /// The CLI the desktop itself will run for searches, tests and migration: the verified managed
    /// install first, then the app PATH, then the fresh user PATH. The UI enables actions from this
    /// row only, so its ready state always matches what will actually execute.
    pub execution: Discovery,
    /// True when `execution` is the verified managed install.
    pub managed: bool,
}

/// The CLI's file name on this platform. The managed bundle ships a Windows executable; on Unix
/// the same CLI is installed as a plain `multi-search` script, so discovery must look for that.
pub const CLI_FILE_NAME: &str = if cfg!(windows) { "multi-search.exe" } else { "multi-search" };

fn find_cli(paths: &[PathBuf]) -> Option<PathBuf> {
    paths
        .iter()
        .filter(|p| p.is_absolute())
        .map(|p| p.join(CLI_FILE_NAME))
        .find(|p| p.is_file())
}

/// CLI discovery and execution-path selection. Stateless: every method takes
/// the environment it should inspect, so this domain owns no shared state.
pub(crate) struct CliDiscovery<'a> {
    pub(crate) environment: &'a RuntimeEnvironment,
    pub(crate) user_path_store: Option<&'a Arc<dyn PathStore>>,
    /// The verified managed install, when this tool installed one. Discovery never accepts a
    /// caller-supplied executable: the frontend cannot pick a program.
    pub(crate) managed: Option<PathBuf>,
}

impl<'a> CliDiscovery<'a> {
    pub(crate) fn new(
        environment: &'a RuntimeEnvironment,
        user_path_store: Option<&'a Arc<dyn PathStore>>,
        managed: Option<PathBuf>,
    ) -> Self {
        Self {
            environment,
            user_path_store,
            managed,
        }
    }

    /// Discovery never takes a caller-supplied executable: the UI can only observe the managed
    /// install and what the app and user PATH resolve to.
    pub(crate) fn detect(&self) -> CliStatus {
        let secrets = crate::redaction::secrets(self.environment);
        let app = self.probe(find_cli(&self.environment.app_path), &secrets);
        let paths = self.current_user_paths();
        let mut user_environment = self.environment.clone();
        if let Ok(path) = std::env::join_paths(&paths) {
            user_environment
                .variables
                .insert("PATH".into(), path.to_string_lossy().into_owned());
        }
        let user = CliDiscovery::new(&user_environment, None, None).probe(find_cli(&paths), &secrets);
        let restart_required = app.status != "ready" && user.status == "ready";
        let (execution, managed) = match &self.managed {
            // A verified managed install always wins, so a same-named file earlier on PATH
            // cannot shadow it.
            Some(path) if path.is_file() => (self.probe(Some(path.clone()), &secrets), true),
            _ if app.status == "ready" => (app.clone(), false),
            _ if user.status == "ready" => (user.clone(), false),
            _ => (app.clone(), false),
        };
        CliStatus {
            app,
            user,
            restart_required,
            execution,
            managed,
        }
    }

    /// Core's own per-provider credential-source report (`doctor --format json`).
    ///
    /// The credential page displays this answer instead of re-deriving the
    /// effective source; the same Core code loads keys for a real search, so the
    /// UI, `doctor`, and `search` cannot disagree. An empty map (CLI missing,
    /// timeout, or CLI without `--format json`) makes callers show `unavailable`
    /// rather than a locally guessed source.
    #[cfg_attr(not(feature = "native-window"), allow(dead_code))]
    pub(crate) fn key_sources(
        &self,
    ) -> BTreeMap<String, crate::credential_commands::CoreKeySource> {
        let Ok(cli) = self.execution_path() else {
            return BTreeMap::new();
        };
        let args = ["doctor", "--format", "json"].map(str::to_string);
        // Forward the same provider key variables the desktop sees, so Core's
        // `env` rows match what this process would load. Values stay in the child
        // environment (never argv) and doctor prints booleans only.
        let names: Vec<String> = crate::source_catalog::catalog()
            .env
            .providers
            .values()
            .flatten()
            .cloned()
            .collect();
        let credentials: Vec<&str> = names.iter().map(String::as_str).collect();
        let Ok(output) = crate::process::bounded_with(
            &cli,
            &args,
            self.environment,
            &credentials,
            std::time::Duration::from_secs(10),
        ) else {
            return BTreeMap::new();
        };
        if output.timed_out {
            return BTreeMap::new();
        }
        serde_json::from_str::<serde_json::Value>(&output.stdout)
            .map(|payload| crate::credential_commands::core_key_sources(&payload))
            .unwrap_or_default()
    }

    /// The executable every UI-triggered CLI run uses. Never chosen by the frontend.
    pub(crate) fn execution_path(&self) -> Result<PathBuf, String> {
        let selected = self.detect().execution;
        if selected.status != "ready" {
            return Err(selected.reason);
        }
        selected
            .path
            .map(PathBuf::from)
            .ok_or_else(|| "CLI 路径不可用".into())
    }

    pub(crate) fn current_user_paths(&self) -> Vec<PathBuf> {
        let Some(store) = self.user_path_store else {
            return self.environment.user_path.clone();
        };
        let Ok(value) = store.read() else {
            return Vec::new();
        };
        let mut paths = self.environment.user_path.clone();
        // The production base is the machine PATH, not a stale snapshot of the user's PATH.
        paths.extend(std::env::split_paths(&crate::windows_util::expand(
            &value.text,
            &self.environment.variables,
        )));
        paths
    }

    fn probe(&self, path: Option<PathBuf>, secrets: &[String]) -> Discovery {
        let Some(path) = path else {
            return Discovery {
                status: "missing".into(),
                path: None,
                version: None,
                reason: format!("当前环境的 PATH 中未找到 {CLI_FILE_NAME}"),
            };
        };
        let mut result = Discovery {
            status: "unavailable".into(),
            path: Some(path.to_string_lossy().into_owned()),
            version: None,
            reason: String::new(),
        };
        if !path.is_absolute()
            || path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|s| s.eq_ignore_ascii_case(CLI_FILE_NAME))
                != Some(true)
        {
            result.reason = format!("请选择 {CLI_FILE_NAME} 的绝对路径");
            return result;
        }
        match crate::process::bounded(
            &path,
            &["--version".into()],
            self.environment,
            std::time::Duration::from_secs(3),
        ) {
            Err(error) => {
                result.status = "not_executable".into();
                result.reason = format!("已找到 CLI，但无法启动：{error}。请检查文件权限与运行时是否完整。");
            }
            Ok(output) => {
                let version = output
                    .stdout
                    .trim()
                    .strip_prefix("multi-search ")
                    .map(str::to_string);
                if !output.timed_out
                    && output.code == Some(0)
                    && version.as_ref().is_some_and(|s| {
                        !s.is_empty() && s.len() < 80 && !s.contains(char::is_whitespace)
                    })
                {
                    result.status = "ready".into();
                    result.version = version.map(|value| crate::redaction::scrub(&value, secrets));
                } else {
                    result.status = "version_failed".into();
                    result.reason = if output.timed_out {
                        "已找到 CLI，但版本检查超过 3 秒。请检查 CLI 运行时，或更新 CLI 后重新检测。".into()
                    } else {
                        let detail = crate::redaction::scrub(output.stderr.trim(), secrets);
                        let detail: String = detail.chars().take(400).collect();
                        format!(
                            "已找到 CLI，但 --version 未返回有效版本（退出码 {}）。请更新 CLI 后重新检测。{}",
                            output.code.map(|code| code.to_string()).unwrap_or_else(|| "未知".into()),
                            if detail.is_empty() { String::new() } else { format!("\n{detail}") },
                        )
                    };
                }
            }
        }
        result
    }
}
