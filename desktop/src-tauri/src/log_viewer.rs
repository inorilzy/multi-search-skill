//! 本机搜索日志页面：桌面端用受管 CLI 在后台运行 `multi-search logs serve --port 0`，
//! 从它的 stderr 读出实际地址后交给系统浏览器。服务只监听 127.0.0.1、只读日志；
//! 同一时间只保留一个，窗口关闭时随 `DesktopManager::shutdown` 一起结束。
use crate::process::OwnedProcess;
use crate::RuntimeEnvironment;
use serde::Serialize;
use std::{
    path::Path,
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

const START_TIMEOUT: Duration = Duration::from_secs(10);
const BANNER: &str = "serving http://127.0.0.1:";

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct LogViewerInfo {
    /// 固定为 `http://127.0.0.1:<port>/`。
    pub url: String,
    /// true 表示复用了本窗口之前启动、仍在运行的服务。
    pub reused: bool,
}

struct Running {
    process: OwnedProcess,
    url: String,
}

#[derive(Default)]
pub(crate) struct LogViewerSlot(Mutex<Option<Running>>);

/// Only a loopback URL the CLI printed is ever opened; nothing from the UI reaches this.
pub(crate) fn parse_url(stderr: &str) -> Option<String> {
    let start = stderr.find(BANNER)? + "serving ".len();
    let rest = &stderr[start..];
    let end = rest.find(|c: char| c.is_whitespace()).unwrap_or(rest.len());
    let url = &rest[..end];
    let port = url.strip_prefix("http://127.0.0.1:")?.strip_suffix('/')?;
    if port.is_empty() || port.len() > 5 || !port.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let number: u32 = port.parse().ok()?;
    (1..=65535).contains(&number).then(|| url.to_string())
}

fn start_error(stderr: &str, secrets: &[String]) -> String {
    if stderr.contains("invalid choice: 'logs'") {
        return "当前安装的 CLI 版本不支持日志页面，请先到「02 安装 CLI」更新。".into();
    }
    let tail: String = stderr.trim().chars().rev().take(300).collect::<Vec<_>>().into_iter().rev().collect();
    if tail.is_empty() {
        "日志页面启动失败，CLI 没有给出原因。".into()
    } else {
        format!("日志页面启动失败：{}", crate::redaction::scrub(&tail, secrets))
    }
}

impl LogViewerSlot {
    /// Start (or reuse) the viewer service and return its URL. Opening the browser is the caller's job.
    pub(crate) fn ensure(&self, cli: &Path, environment: &RuntimeEnvironment) -> Result<LogViewerInfo, String> {
        let mut slot = self.0.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(running) = slot.as_mut() {
            if matches!(running.process.poll(), Ok(None)) {
                return Ok(LogViewerInfo { url: running.url.clone(), reused: true });
            }
        }
        // A previous service that exited is dropped (and its process group reaped) here.
        *slot = None;
        let args = ["logs", "serve", "--port", "0"].map(String::from);
        let mut process = OwnedProcess::spawn(cli, &args, environment, &[])
            .map_err(|_| "无法启动 CLI 日志服务".to_string())?;
        let started = Instant::now();
        loop {
            if let Some(url) = parse_url(&process.stderr_text()) {
                *slot = Some(Running { process, url: url.clone() });
                return Ok(LogViewerInfo { url, reused: false });
            }
            if let Ok(Some(code)) = process.poll() {
                let output = process.finish(Some(code), false);
                return Err(start_error(&output.stderr, &crate::redaction::secrets(environment)));
            }
            if started.elapsed() >= START_TIMEOUT {
                // Dropping the process terminates its whole group.
                return Err("日志页面启动超时（10 秒内没有就绪）".into());
            }
            thread::sleep(Duration::from_millis(50));
        }
    }

    pub(crate) fn stop(&self) {
        let mut slot = self.0.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        *slot = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_the_printed_loopback_url() {
        assert_eq!(
            parse_url("multi-search logs: serving http://127.0.0.1:53124/ (Ctrl+C to stop)\n"),
            Some("http://127.0.0.1:53124/".into()),
        );
        for bad in [
            "",
            "serving http://127.0.0.1:/",
            "serving http://127.0.0.1:0/",
            "serving http://127.0.0.1:99999/",
            "serving http://127.0.0.1:80/evil",
            "serving http://127.0.0.1:80",
            "serving http://example.com:80/",
        ] {
            assert_eq!(parse_url(bad), None, "{bad}");
        }
    }

    #[test]
    fn old_cli_gets_an_update_hint() {
        assert!(start_error("usage error: argument command: invalid choice: 'logs' (choose from search)", &[]).contains("02 安装 CLI"));
    }
}
