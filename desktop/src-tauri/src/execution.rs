use crate::diagnostics::CliDiscovery;
use crate::install::InstallManager;
use crate::{process::OwnedProcess, provider, RuntimeEnvironment};
use std::sync::atomic::{AtomicBool, AtomicU64};
use std::sync::Arc as StdArc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
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

/// Keys the CLI's body-fetch stage may use for any search (Jina reader plus the scrape backends).
const FETCH_CREDENTIALS: &[&str] = &[
    "JINA_API_KEY", "JINA_KEY", "EXA_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY",
];

/// Credential variable names one search may receive: the selected sources' own keys (or the
/// route's sources when none are selected) plus the fetch-stage keys. Every other key stays out
/// of the child environment. Source names, aliases and env names come from the shared catalog.
pub(crate) fn search_credentials(route: &str, sources: &[String]) -> Vec<&'static str> {
    let catalog = crate::source_catalog::catalog();
    let selected: Vec<&'static str> = if sources.is_empty() {
        catalog
            .route(route)
            .map(|entry| entry.sources.iter().map(String::as_str).collect())
            .unwrap_or_default()
    } else {
        sources
            .iter()
            .filter_map(|name| catalog.source(name))
            .map(|entry| entry.name.as_str())
            .collect()
    };
    let mut names: Vec<&'static str> = FETCH_CREDENTIALS.to_vec();
    for source in selected {
        if source == "twitter" {
            names.push("TWITTER_COOKIES_PATH");
        }
        if let Some(entry) = catalog.source(source) {
            names.extend(entry.env.iter().map(String::as_str));
        }
    }
    names.sort_unstable();
    names.dedup();
    names
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
            self.state.error = "CLI 输出超过 4 MiB 上限，已被截断".into();
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
                self.state.error = "CLI 未返回有效的 JSON 结果".into();
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
    pub fn start_search(&self, mut options: SearchOptions) -> Result<u64, String> {
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("桌面管理器已关闭".into());
        }
        if options.query.trim().is_empty()
            || options.query.len() > 2000
            || options.query.contains('\0')
        {
            return Err("请输入 1 到 2000 字节的搜索词".into());
        }
        // `web` 继续作为内置 `default` 的兼容别名，但不能被定义为路由 ID。
        // 其他 ID 必须存在于 CLI 当前读取的配置中，既支持自定义分组，也避免任意路由参数。
        if options.route == "web" {
            options.route = "default".into();
        }
        let settings = crate::settings::view(&self.environment);
        // 可编辑范围与 CLI 最长路由默认值一致（`all=90`）；没有全局超时时，诊断页显式传入
        // 当前路由的精确预览值也接受。其他超出范围的值一律拒绝。
        let legacy_preview_timeout = !settings.timeout_configured
            && settings.effective_timeouts.get(&options.route) == Some(&options.timeout);
        if settings.status == "config_unreadable"
            || !settings.routes.contains_key(&options.route)
            || (!(crate::settings::TIMEOUT_MIN..=crate::settings::TIMEOUT_MAX).contains(&options.timeout)
                && !legacy_preview_timeout)
            || options.sources.len() > 16
            || options.sources.iter().any(|s| !is_allowed_source(s))
        {
            return Err("不支持的搜索选项".into());
        }
        // Never a caller-supplied executable: discovery resolves the managed install, then PATH.
        let cli = self.discovery.execution_path()?;
        crate::credential_commands::require_storage_cli(self.environment, &cli)?;
        let mut slot = self
            .execution_slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("桌面管理器已关闭".into());
        }
        if slot
            .as_ref()
            .is_some_and(|s| s.lock().unwrap_or_else(std::sync::PoisonError::into_inner).state.status == "running")
        {
            return Err("已有测试搜索正在运行".into());
        }
        let credentials = search_credentials(&options.route, &options.sources);
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
        let process = OwnedProcess::spawn(&cli, &args, &self.environment, &credentials)
            .map_err(|_| "无法启动 CLI")?;
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
                run.state.error = if timed_out { "CLI 超过测试执行时限" } else { "无法读取 CLI 进程状态" }.into();
            }
            break;
        });
        Ok(id)
    }
    pub fn cancel_search(&self, id: u64) -> Result<ExecutionStatus, String> {
        let execution = self.execution_slot.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_ref().cloned().ok_or("没有正在执行的搜索")?;
        loop {
            let mut run = execution.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if run.state.id != id { return Err("未知的执行".into()); }
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
            .ok_or("没有正在执行的搜索")?
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .state
            .clone();
        if state.id != id {
            return Err("未知的执行".into());
        }
        Ok(state)
    }
}
