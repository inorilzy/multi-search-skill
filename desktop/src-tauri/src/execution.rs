use crate::diagnostics::CliDiscovery;
use crate::install::InstallManager;
use crate::{process::OwnedProcess, provider, RuntimeEnvironment};
use std::sync::atomic::{AtomicBool, AtomicU64};
use std::sync::Arc as StdArc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

#[derive(Clone, Deserialize)]
pub struct SearchOptions {
    pub query: String,
    pub route: String,
    pub sources: Vec<String>,
    pub timeout: u32,
}
/// Whether `name` may be passed to CLI `--source`. The allowlist is the union
/// of every canonical source, its `cli_source` spelling, and its registered
/// aliases — all derived from `provider::PROVIDERS`. Mirrors the Python
/// `ALL_SOURCE_NAMES` ∪ `SOURCE_ALIASES` set; a contract test asserts parity.
pub(crate) fn is_allowed_source(name: &str) -> bool {
    provider::is_allowed_source(name)
}

#[derive(Clone, Serialize)]
pub struct ExecutionStatus {
    pub id: u64,
    pub status: String,
    pub exit_code: Option<i32>,
    pub payload: Option<Value>,
    pub error: String,
}
pub(crate) struct Execution {
    pub state: ExecutionStatus,
    process: Option<OwnedProcess>,
    started: Instant,
    timeout: Duration,
    secrets: Vec<String>,
}

impl Execution {
    fn complete(&mut self, code: i32) {
        let output = self.process.take().unwrap().finish(Some(code), false);
        self.state.exit_code = Some(code);
        match serde_json::from_str::<Value>(&output.stdout) {
            Ok(mut payload) if payload.is_object() => {
                crate::redaction::scrub_json(&mut payload, &self.secrets);
                let outcome = payload["outcome"].as_str().unwrap_or("failed");
                self.state.status = if code != 0 {
                    "failed"
                } else if ["success", "empty", "partial"].contains(&outcome) {
                    outcome
                } else {
                    "failed"
                }
                .into();
                self.state.payload = Some(payload);
            }
            _ => {
                self.state.status = "failed".into();
                self.state.error = "CLI did not return a valid JSON response".into();
            }
        }
        if !output.stderr.trim().is_empty() {
            self.state.error = crate::redaction::scrub(&output.stderr, &self.secrets);
        }
    }
}
/// Shared execution state owned by `DesktopManager` (the slot, id counter and
/// closed flag). The manager itself lives in `manager.rs`; this type only
/// holds the state its methods need.
pub(crate) struct ExecutionManager<'a> {
    pub(crate) environment: &'a RuntimeEnvironment,
    pub(crate) execution_slot: &'a Mutex<Option<StdArc<Mutex<Execution>>>>,
    pub(crate) next_id: &'a AtomicU64,
    pub(crate) closed: &'a AtomicBool,
    pub(crate) discovery: CliDiscovery<'a>,
    pub(crate) install: InstallManager<'a>,
}

impl ExecutionManager<'_> {
    pub fn start_search(
        &self,
        path: Option<PathBuf>,
        mut options: SearchOptions,
    ) -> Result<u64, String> {
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("Desktop manager is closed".into());
        }
        if options.query.trim().is_empty()
            || options.query.len() > 2000
            || options.query.contains('\0')
        {
            return Err("Enter a query of 1–2000 bytes".into());
        }
        // `web` 继续作为内置 `default` 的兼容别名，但不能被定义为路由 ID。
        // 其他 ID 必须存在于 CLI 当前读取的配置中，既支持自定义分组，也避免任意路由参数。
        if options.route == "web" {
            options.route = "default".into();
        }
        let settings = crate::settings::view(&self.environment);
        // 没有全局超时的配置仍可能得到 CLI 旧版 `all=90` 实际值。诊断页可以显式传入
        // 这一精确预览值，但其他超出可编辑 1..=60 范围的任意值仍会被拒绝。
        let legacy_preview_timeout = !settings.timeout_configured
            && settings.effective_timeouts.get(&options.route) == Some(&options.timeout);
        if settings.status == "config_unreadable"
            || !settings.routes.contains_key(&options.route)
            || (!(1..=60).contains(&options.timeout) && !legacy_preview_timeout)
            || options.sources.len() > 16
            || options.sources.iter().any(|s| !is_allowed_source(s))
        {
            return Err("Unsupported search options".into());
        }
        let cli = self.discovery.execution_path(path)?;
        crate::credential_commands::require_storage_cli(self.environment, &cli)?;
        let mut slot = self
            .execution_slot
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("Desktop manager is closed".into());
        }
        if slot
            .as_ref()
            .is_some_and(|s| s.lock().unwrap().state.status == "running")
        {
            return Err("A test search is already running".into());
        }
        let id = self
            .next_id
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let mut args = vec![
            "search".into(),
            options.query,
            format!("--route={}", options.route),
            "--timeout".into(),
            options.timeout.to_string(),
            "--format".into(),
            "json".into(),
        ];
        for source in options.sources {
            args.push("--source".into());
            args.push(source);
        }
        let process = OwnedProcess::spawn(&cli, &args, &self.environment)
            .map_err(|_| "Could not start the CLI")?;
        let execution = Arc::new(Mutex::new(Execution {
            state: ExecutionStatus {
                id,
                status: "running".into(),
                exit_code: None,
                payload: None,
                error: String::new(),
            },
            process: Some(process),
            started: Instant::now(),
            timeout: Duration::from_secs((options.timeout + 10) as u64),
            secrets: crate::redaction::secrets(&self.environment),
        }));
        *slot = Some(execution.clone());
        thread::spawn(move || loop {
            {
                let mut run = execution.lock().unwrap();
                if run.state.status != "running" {
                    break;
                }
                let finished = run.process.as_mut().unwrap().poll();
                let timed_out = run.started.elapsed() >= run.timeout;
                match finished {
                    Ok(Some(code)) => run.complete(code),
                    Ok(None) if !timed_out => (),
                    _ => {
                        let _output = run.process.take().unwrap().finish(None, timed_out);
                        run.state.status = if timed_out { "timed_out" } else { "failed" }.into();
                        run.state.error = if timed_out {
                            "CLI exceeded the test execution deadline"
                        } else {
                            "CLI process could not be observed"
                        }
                        .into();
                    }
                }
            }
            thread::sleep(Duration::from_millis(20));
        });
        Ok(id)
    }
    pub fn cancel_search(&self, id: u64) -> Result<ExecutionStatus, String> {
        let slot = self
            .execution_slot
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        let mut run = slot
            .as_ref()
            .ok_or("No execution")?
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        if run.state.id != id {
            return Err("Unknown execution".into());
        }
        if run.state.status == "running" {
            let code = run
                .process
                .as_mut()
                .unwrap()
                .poll()
                .map_err(|_| "Cannot observe execution")?;
            if let Some(code) = code {
                run.complete(code);
            } else {
                let _ = run.process.take().unwrap().finish(None, false);
                run.state.status = "cancelled".into();
            }
        }
        Ok(run.state.clone())
    }

    pub fn shutdown(&self) {
        self.closed
            .store(true, std::sync::atomic::Ordering::Release);
        if let Ok(slot) = self.execution_slot.lock() {
            if let Some(execution) = slot.as_ref() {
                if let Ok(mut run) = execution.lock() {
                    if let Some(process) = run.process.take() {
                        let _ = process.finish(None, false);
                        run.state.status = "cancelled".into();
                    }
                }
            }
        }
    }

    pub fn execution(&self, id: u64) -> Result<ExecutionStatus, String> {
        let slot = self
            .execution_slot
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        let state = slot
            .as_ref()
            .ok_or("No execution")?
            .lock()
            .map_err(|_| "Execution state unavailable")?
            .state
            .clone();
        if state.id != id {
            return Err("Unknown execution".into());
        }
        Ok(state)
    }
}
