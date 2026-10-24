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
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
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
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct ExecutionStatus {
    pub id: u64,
    /// One of `running`, `success`, `empty`, `partial`, `failed`, `cancelled`, `timed_out`, or a new value added later; UI must fall back to a raw string.
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
    fn complete(&mut self, code: i32, output: crate::process::Output) {
        self.state.exit_code = Some(code);
        if output.truncated {
            self.state.status = "failed".into();
            self.state.error = "CLI output exceeded the 4 MiB limit and was truncated".into();
            return;
        }
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
    #[allow(dead_code)]
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
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("Desktop manager is closed".into());
        }
        if slot
            .as_ref()
            .is_some_and(|s| s.lock().unwrap_or_else(std::sync::PoisonError::into_inner).state.status == "running")
        {
            return Err("A test search is already running".into());
        }
        let id = self
            .next_id
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let mut args = vec![
            "search".into(),
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
        args.push("--".into());
        args.push(options.query);
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
            let mut run = execution.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if run.state.status != "running" { break; }
            let Some(process) = run.process.as_mut() else {
                drop(run);
                thread::sleep(Duration::from_millis(10));
                continue;
            };
            let finished = process.poll();
            let timed_out = run.started.elapsed() >= run.timeout;
            if matches!(finished, Ok(None)) && !timed_out {
                drop(run);
                thread::sleep(Duration::from_millis(20));
                continue;
            }
            let code = finished.ok().flatten();
            let process = run.process.take().unwrap();
            drop(run); // wait/join must never hold the execution state lock.
            let output = process.finish(code, timed_out);
            let mut run = execution.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(code) = code { run.complete(code, output); }
            else {
                run.state.status = if timed_out { "timed_out" } else { "failed" }.into();
                run.state.error = if timed_out { "CLI exceeded the test execution deadline" } else { "CLI process could not be observed" }.into();
            }
            break;
        });
        Ok(id)
    }
    pub fn cancel_search(&self, id: u64) -> Result<ExecutionStatus, String> {
        let execution = self.execution_slot.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_ref().cloned().ok_or("No execution")?;
        loop {
            let mut run = execution.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if run.state.id != id { return Err("Unknown execution".into()); }
            if run.state.status != "running" { return Ok(run.state.clone()); }
            let Some(mut process) = run.process.take() else {
                drop(run);
                thread::sleep(Duration::from_millis(10));
                continue;
            };
            let code = process.poll().ok().flatten();
            drop(run);
            let output = process.finish(code, false);
            let mut run = execution.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(code) = code { run.complete(code, output); }
            else { run.state.status = "cancelled".into(); }
            return Ok(run.state.clone());
        }
    }

    pub fn shutdown(&self) {
        self.closed.store(true, std::sync::atomic::Ordering::Release);
        let execution = self.execution_slot.lock().unwrap_or_else(std::sync::PoisonError::into_inner).as_ref().cloned();
        if let Some(execution) = execution {
            let id = execution.lock().unwrap_or_else(std::sync::PoisonError::into_inner).state.id;
            let _ = self.cancel_search(id);
        }
    }

    pub fn execution(&self, id: u64) -> Result<ExecutionStatus, String> {
        let slot = self
            .execution_slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let state = slot
            .as_ref()
            .ok_or("No execution")?
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .state
            .clone();
        if state.id != id {
            return Err("Unknown execution".into());
        }
        Ok(state)
    }
}
