use crate::user_path::PathStore;
use serde::Serialize;
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};
use ts_rs::TS;

/// Explicit system boundary: production snapshots the environment; tests supply a disposable one.
#[derive(Clone)]
pub struct RuntimeEnvironment {
    pub app_path: Vec<PathBuf>,
    pub user_path: Vec<PathBuf>,
    pub variables: BTreeMap<String, String>,
    pub cwd: PathBuf,
}

#[derive(Clone, Serialize, TS)]
#[ts(export_to = "types.d.ts")]
pub struct Discovery {
    /// One of `ready`, `missing`, `not_executable`, `version_failed`, `unavailable`, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub path: Option<String>,
    pub version: Option<String>,
    pub reason: String,
}

#[derive(Clone, Serialize, TS)]
#[ts(export_to = "types.d.ts")]
pub struct CliStatus {
    pub app: Discovery,
    pub user: Discovery,
    pub restart_required: bool,
}

fn find_cli(paths: &[PathBuf]) -> Option<PathBuf> {
    paths
        .iter()
        .filter(|p| p.is_absolute())
        .map(|p| p.join("multi-search.exe"))
        .find(|p| p.is_file())
}

/// CLI discovery and execution-path selection. Stateless: every method takes
/// the environment it should inspect, so this domain owns no shared state.
pub(crate) struct CliDiscovery<'a> {
    pub(crate) environment: &'a RuntimeEnvironment,
    pub(crate) user_path_store: Option<&'a Arc<dyn PathStore>>,
}

impl<'a> CliDiscovery<'a> {
    pub(crate) fn new(
        environment: &'a RuntimeEnvironment,
        user_path_store: Option<&'a Arc<dyn PathStore>>,
    ) -> Self {
        Self {
            environment,
            user_path_store,
        }
    }

    pub(crate) fn detect(&self, explicit_path: Option<PathBuf>) -> CliStatus {
        let app = self.probe(explicit_path.or_else(|| find_cli(&self.environment.app_path)));
        let paths = self.current_user_paths();
        let mut user_environment = self.environment.clone();
        if let Ok(path) = std::env::join_paths(&paths) {
            user_environment
                .variables
                .insert("PATH".into(), path.to_string_lossy().into_owned());
        }
        let user = CliDiscovery::new(&user_environment, None).probe(find_cli(&paths));
        let restart_required = app.status != "ready" && user.status == "ready";
        CliStatus {
            app,
            user,
            restart_required,
        }
    }

    /// Keep diagnostics truthful about the old app PATH, while UI commands can use the
    /// newly verified user PATH immediately. An explicitly selected bad executable never falls back.
    pub(crate) fn execution_path(&self, explicit_path: Option<PathBuf>) -> Result<PathBuf, String> {
        let explicit = explicit_path.is_some();
        let detected = self.detect(explicit_path);
        let selected = if detected.app.status == "ready" || explicit {
            detected.app
        } else {
            detected.user
        };
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

    fn probe(&self, path: Option<PathBuf>) -> Discovery {
        let Some(path) = path else {
            return Discovery {
                status: "missing".into(),
                path: None,
                version: None,
                reason: "multi-search.exe was not found on this environment's PATH".into(),
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
                .map(|s| s.eq_ignore_ascii_case("multi-search.exe"))
                != Some(true)
        {
            result.reason = "Select the absolute path to multi-search.exe".into();
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
                    result.version = version.map(|value| {
                        crate::redaction::scrub(
                            &value,
                            &crate::redaction::secrets(self.environment),
                        )
                    });
                } else {
                    result.status = "version_failed".into();
                    result.reason = if output.timed_out {
                        "已找到 CLI，但版本检查超过 3 秒。请检查 CLI 运行时，或更新 CLI 后重新检测。".into()
                    } else {
                        let detail = crate::redaction::scrub(
                            output.stderr.trim(),
                            &crate::redaction::secrets(self.environment),
                        );
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
