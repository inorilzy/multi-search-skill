use serde::Serialize;
use std::{collections::BTreeMap, path::PathBuf};

/// Explicit system boundary: production snapshots the environment; tests supply a disposable one.
#[derive(Clone)]
pub struct RuntimeEnvironment {
    pub app_path: Vec<PathBuf>,
    pub user_path: Vec<PathBuf>,
    pub variables: BTreeMap<String, String>,
    pub cwd: PathBuf,
}

#[derive(Clone, Serialize)]
pub struct Discovery {
    pub status: String,
    pub path: Option<String>,
    pub version: Option<String>,
    pub reason: String,
}

#[derive(Clone, Serialize)]
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

pub struct DesktopManager {
    pub(crate) environment: RuntimeEnvironment,
    pub(crate) execution_slot:
        std::sync::Mutex<Option<std::sync::Arc<std::sync::Mutex<crate::execution::Execution>>>>,
    pub(crate) next_id: std::sync::atomic::AtomicU64,
    pub(crate) closed: std::sync::atomic::AtomicBool,
}

impl DesktopManager {
    pub fn new(environment: RuntimeEnvironment) -> Self {
        Self {
            environment,
            execution_slot: std::sync::Mutex::new(None),
            next_id: std::sync::atomic::AtomicU64::new(1),
            closed: std::sync::atomic::AtomicBool::new(false),
        }
    }

    pub fn detect_cli(&self, explicit_path: Option<PathBuf>) -> CliStatus {
        let app = self.probe(explicit_path.or_else(|| find_cli(&self.environment.app_path)));
        let mut user_environment = self.environment.clone();
        if let Ok(path) = std::env::join_paths(&user_environment.user_path) {
            user_environment
                .variables
                .insert("PATH".into(), path.to_string_lossy().into_owned());
        }
        let user_manager = Self::new(user_environment);
        let user = user_manager.probe(find_cli(&self.environment.user_path));
        let restart_required = app.status != "ready" && user.status == "ready";
        CliStatus {
            app,
            user,
            restart_required,
        }
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
            &self.environment,
            std::time::Duration::from_secs(3),
        ) {
            Err(_) => {
                result.status = "not_executable".into();
                result.reason = "CLI cannot be executed at this path".into();
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
                            &crate::redaction::secrets(&self.environment),
                        )
                    });
                } else {
                    result.status = "version_failed".into();
                    result.reason = "CLI version probe failed or timed out; update the CLI if --version is unsupported".into();
                }
            }
        }
        result
    }
}
