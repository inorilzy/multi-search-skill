//! Desktop OAuth login sessions. The managed CLI owns the provider flow
//! (`login <provider> --method oauth --format jsonl --no-browser`); this module only starts,
//! follows and cancels that child. URL events are opened with the same system-browser boundary as
//! the credential page, and only for the two hosts the plugin catalog declares.
//!
//! Lifecycle mirrors `execution.rs`: one owned child process per session, a monitor thread that
//! polls it, and an id-based status/cancel protocol. `OwnedProcess` owns the platform cleanup
//! (Windows Job Object / Unix process group), so cancel and app shutdown end the whole CLI tree.
use crate::process::OwnedProcess;
use crate::{credential_commands, RuntimeEnvironment};
use serde::Serialize;
use serde_json::Value;
use std::{
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

/// The CLI enforces its own 300-second authorization limit; extra room covers interpreter startup
/// and the final event.
const LOGIN_TIMEOUT: Duration = Duration::from_secs(330);
const POLL_INTERVAL: Duration = Duration::from_millis(20);
/// Only hosts the plugin catalog declares for its OAuth flow may be handed to the OS browser.
const OAUTH_HOSTS: &[&str] = &["www.firecrawl.dev", "platform.parallel.ai"];

pub(crate) type BrowserOpener = Arc<dyn Fn(&str) -> Result<(), String> + Send + Sync>;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct OAuthLoginStatus {
    pub id: u64,
    pub provider: String,
    /// `starting`, `waiting`, `complete`, `error` or `cancelled`; UI must fall back to the raw string.
    pub phase: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub user_code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub message: Option<String>,
}

struct OAuthLogin {
    state: OAuthLoginStatus,
    process: Option<OwnedProcess>,
    started: Instant,
    /// Byte offset of the last complete stdout line already parsed.
    cursor: usize,
    secrets: Vec<String>,
}

/// The id-counter and single-session slot live with `DesktopManager`, like the test-search
/// execution slot. One login may run at a time; a finished session stays readable until the next
/// start replaces it.
pub struct OAuthLogins {
    slot: Mutex<Option<Arc<Mutex<OAuthLogin>>>>,
    next_id: AtomicU64,
    closed: AtomicBool,
    opener: BrowserOpener,
}

impl Default for OAuthLogins {
    fn default() -> Self {
        Self::with_opener(Arc::new(|url: &str| credential_commands::open_browser(url)))
    }
}

impl OAuthLogins {
    pub(crate) fn with_opener(opener: BrowserOpener) -> Self {
        Self {
            slot: Mutex::new(None),
            next_id: AtomicU64::new(1),
            closed: AtomicBool::new(false),
            opener,
        }
    }

    /// Start one login. `provider` is a plugin id resolved by the shared catalog; the caller has
    /// already resolved the managed CLI path (never a frontend value).
    pub(crate) fn start(
        &self,
        environment: &RuntimeEnvironment,
        cli: &Path,
        provider: &str,
    ) -> Result<u64, String> {
        if self.closed.load(Ordering::Acquire) {
            return Err("桌面管理器已关闭".into());
        }
        let provider = validate_provider(provider)?;
        let mut slot = self
            .slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // Shutdown may have landed while this caller waited for the slot lock: never spawn a
        // child that the app no longer knows about.
        if self.closed.load(Ordering::Acquire) {
            return Err("桌面管理器已关闭".into());
        }
        if slot.as_ref().is_some_and(|login| {
            is_active_phase(
                &login
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .state
                    .phase,
            )
        }) {
            return Err("已有浏览器登录正在进行".into());
        }
        let process = OwnedProcess::spawn(cli, &login_args(&provider), environment, &[])
            .map_err(|_| "无法启动 CLI")?;
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let login = Arc::new(Mutex::new(OAuthLogin {
            state: OAuthLoginStatus {
                id,
                provider: provider.clone(),
                phase: "starting".into(),
                url: None,
                user_code: None,
                message: None,
            },
            process: Some(process),
            started: Instant::now(),
            cursor: 0,
            secrets: crate::redaction::secrets(environment),
        }));
        *slot = Some(login.clone());
        drop(slot);
        let opener = self.opener.clone();
        thread::spawn(move || monitor(login, opener));
        Ok(id)
    }

    pub(crate) fn poll(&self, id: u64) -> Result<OAuthLoginStatus, String> {
        let login = self
            .slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_ref()
            .cloned()
            .ok_or("没有正在进行的浏览器登录")?;
        let run = login.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if run.state.id != id {
            return Err("未知的登录".into());
        }
        Ok(run.state.clone())
    }

    /// Cancel is also the app-shutdown path: taking the process under the state lock makes the
    /// monitor stop without a second owner, and `finish` reaps the whole owned process tree.
    pub(crate) fn cancel(&self, id: u64) -> Result<OAuthLoginStatus, String> {
        let login = self
            .slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_ref()
            .cloned()
            .ok_or("没有正在进行的浏览器登录")?;
        let mut run = login.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if run.state.id != id {
            return Err("未知的登录".into());
        }
        if !is_active_phase(&run.state.phase) {
            return Ok(run.state.clone());
        }
        run.state.phase = "cancelled".into();
        run.state.message = None;
        let process = run.process.take();
        drop(run);
        if let Some(process) = process {
            let _ = process.finish(None, false);
        }
        let run = login.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        Ok(run.state.clone())
    }

    pub(crate) fn shutdown(&self) {
        self.closed.store(true, Ordering::Release);
        let login = self
            .slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_ref()
            .cloned();
        if let Some(login) = login {
            let id = login
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .state
                .id;
            let _ = self.cancel(id);
        }
    }
}

/// Provider ids are the plugin ids from the shared catalog, and only those that declare an
/// `oauth` auth method are accepted. This runs before a child is spawned.
pub(crate) fn validate_provider(provider: &str) -> Result<String, String> {
    let trimmed = provider.trim();
    let plugin = crate::source_catalog::catalog()
        .plugin(trimmed)
        .ok_or("不支持浏览器登录的服务商")?;
    if !plugin.auth_methods.iter().any(|method| method.method_type == "oauth") {
        return Err("不支持浏览器登录的服务商".into());
    }
    Ok(plugin.id.clone())
}

/// The exact argv for one login session. Fixed here; the frontend supplies only the provider id.
pub(crate) fn login_args(provider: &str) -> Vec<String> {
    vec![
        "login".into(),
        provider.into(),
        "--method".into(),
        "oauth".into(),
        "--format".into(),
        "jsonl".into(),
        "--no-browser".into(),
    ]
}

/// Only `https://` URLs on the two catalog-declared hosts may reach the OS browser. Rejecting
/// userinfo and ports keeps `https://evil.example@www.firecrawl.dev/` from passing a host check.
pub(crate) fn validate_open_url(url: &str) -> Result<(), String> {
    if !url.starts_with("https://") {
        return Err("登录地址必须为 HTTPS".into());
    }
    if url.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return Err("登录地址包含无效字符".into());
    }
    let authority = url[8..].split(['/', '?', '#']).next().unwrap_or_default();
    if authority.is_empty() || authority.contains('@') || authority.contains(':') {
        return Err("登录地址无效".into());
    }
    if !OAUTH_HOSTS
        .iter()
        .any(|host| authority.eq_ignore_ascii_case(host))
    {
        return Err("登录地址的主机不在允许清单中".into());
    }
    Ok(())
}

#[derive(Debug, PartialEq, Eq)]
enum LoginEvent {
    OpenUrl { url: String, user_code: Option<String> },
    Waiting,
    Complete,
    Error { message: String },
    /// Something the user should read that does not end the login (e.g. a key could not be created).
    Notice { message: String },
}

fn parse_event(line: &str) -> Result<Option<LoginEvent>, String> {
    let line = line.trim();
    if line.is_empty() {
        return Ok(None);
    }
    let invalid = || "CLI 返回了无法解析的登录事件。".to_string();
    let value: Value = serde_json::from_str(line).map_err(|_| invalid())?;
    let kind = value.get("event").and_then(Value::as_str).ok_or_else(invalid)?;
    let text = |name: &str| {
        value
            .get(name)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|text| !text.is_empty())
            .map(str::to_string)
    };
    match kind {
        "open_url" => {
            let url = text("url").ok_or_else(|| "CLI 返回的登录事件缺少地址。".to_string())?;
            Ok(Some(LoginEvent::OpenUrl {
                url,
                user_code: text("user_code"),
            }))
        }
        "waiting" => Ok(Some(LoginEvent::Waiting)),
        "complete" => Ok(Some(LoginEvent::Complete)),
        "notice" => Ok(text("message").map(|message| LoginEvent::Notice { message })),
        "error" => Ok(Some(LoginEvent::Error {
            message: text("message").unwrap_or_else(|| "登录失败。".into()),
        })),
        // Forward compatibility: an event this desktop does not know yet is ignored.
        _ => Ok(None),
    }
}

fn is_active_phase(phase: &str) -> bool {
    matches!(phase, "starting" | "waiting")
}

/// Apply one parsed event. Returns true when it ends the session.
fn apply_event(run: &mut OAuthLogin, event: LoginEvent, opener: &BrowserOpener) -> bool {
    match event {
        LoginEvent::OpenUrl { url, user_code } => {
            run.state.url = Some(url.clone());
            if user_code.is_some() {
                run.state.user_code = user_code;
            }
            // Whitelist rejection is a terminal error: never fall back to another address.
            if let Err(message) = validate_open_url(&url) {
                run.state.phase = "error".into();
                run.state.message = Some(message);
                return true;
            }
            if let Err(message) = opener(&url) {
                run.state.phase = "error".into();
                run.state.message = Some(format!("无法打开系统浏览器：{message}"));
                return true;
            }
            false
        }
        LoginEvent::Waiting => {
            if run.state.phase == "starting" {
                run.state.phase = "waiting".into();
            }
            false
        }
        LoginEvent::Complete => {
            run.state.phase = "complete".into();
            true
        }
        LoginEvent::Error { message } => {
            run.state.phase = "error".into();
            run.state.message = Some(message);
            true
        }
        LoginEvent::Notice { message } => {
            run.state.message = Some(message);
            false
        }
    }
}

fn monitor(login: Arc<Mutex<OAuthLogin>>, opener: BrowserOpener) {
    loop {
        let mut run = login.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if run.process.is_none() {
            break;
        }
        if run.started.elapsed() >= LOGIN_TIMEOUT {
            run.state.phase = "error".into();
            run.state.message = Some("登录超时，请重试。".into());
            let process = run.process.take();
            drop(run);
            if let Some(process) = process {
                let _ = process.finish(None, false);
            }
            break;
        }
        let lines = {
            let run = &mut *run;
            let Some(process) = run.process.as_ref() else {
                break;
            };
            process.take_stdout_lines(&mut run.cursor)
        };
        let mut terminal = false;
        for line in lines {
            match parse_event(&line) {
                Ok(Some(event)) => {
                    if apply_event(&mut run, event, &opener) {
                        terminal = true;
                        break;
                    }
                }
                Ok(None) => {}
                Err(message) => {
                    run.state.phase = "error".into();
                    run.state.message = Some(message);
                    terminal = true;
                    break;
                }
            }
        }
        if terminal {
            let process = run.process.take();
            drop(run);
            if let Some(process) = process {
                let _ = process.finish(None, false);
            }
            break;
        }
        let finished = run.process.as_mut().expect("checked above").poll();
        match finished {
            Ok(Some(code)) => {
                let process = run.process.take().expect("checked above");
                drop(run);
                // Join both readers before deciding: the complete event may be the last line
                // written before the child exited.
                let output = process.finish(Some(code), false);
                let mut run = login.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
                if !is_active_phase(&run.state.phase) {
                    break;
                }
                let mut terminal = false;
                let mut cursor = run.cursor;
                for line in finish_lines(output.stdout.as_bytes(), &mut cursor) {
                    match parse_event(&line) {
                        Ok(Some(event)) => {
                            if apply_event(&mut run, event, &opener) {
                                terminal = true;
                                break;
                            }
                        }
                        Ok(None) => {}
                        Err(message) => {
                            run.state.phase = "error".into();
                            run.state.message = Some(message);
                            terminal = true;
                            break;
                        }
                    }
                }
                run.cursor = cursor;
                if !terminal && is_active_phase(&run.state.phase) {
                    run.state.phase = "error".into();
                    run.state.message = Some(exit_message(code, &output, &run.secrets));
                }
                break;
            }
            Ok(None) => {}
            Err(_) => {
                run.state.phase = "error".into();
                run.state.message = Some("无法读取登录进程状态".into());
                let process = run.process.take();
                drop(run);
                if let Some(process) = process {
                    let _ = process.finish(None, false);
                }
                break;
            }
        }
        drop(run);
        thread::sleep(POLL_INTERVAL);
    }
}

fn finish_lines(bytes: &[u8], cursor: &mut usize) -> Vec<String> {
    if *cursor >= bytes.len() {
        return Vec::new();
    }
    let chunk = &bytes[*cursor..];
    *cursor = bytes.len();
    String::from_utf8_lossy(chunk)
        .lines()
        .map(str::to_string)
        .collect()
}

fn exit_message(code: i32, output: &crate::process::Output, secrets: &[String]) -> String {
    let stderr = output.stderr.trim();
    if stderr.is_empty() {
        format!("登录进程已退出（退出码 {code}），未返回完成事件。")
    } else {
        crate::redaction::scrub(stderr, secrets)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_declared_oauth_providers_are_accepted() {
        assert_eq!(validate_provider(" firecrawl ").unwrap(), "firecrawl");
        assert_eq!(validate_provider("parallel").unwrap(), "parallel");
        for bad in ["", "tavily", "exa", "../firecrawl", "github_repos", "unknown"] {
            assert_eq!(validate_provider(bad).unwrap_err(), "不支持浏览器登录的服务商");
        }
    }

    #[test]
    fn argv_is_fixed_and_never_opens_a_browser_in_the_cli() {
        assert_eq!(
            login_args("parallel"),
            vec![
                "login",
                "parallel",
                "--method",
                "oauth",
                "--format",
                "jsonl",
                "--no-browser"
            ]
        );
    }

    #[test]
    fn only_allowlisted_https_urls_may_be_opened() {
        assert!(validate_open_url("https://www.firecrawl.dev/cli-auth?code_challenge=x#session").is_ok());
        assert!(validate_open_url("https://platform.parallel.ai/device").is_ok());
        for bad in [
            "http://www.firecrawl.dev/cli-auth",
            "https://evil.example/cli-auth",
            "https://www.firecrawl.dev.evil.example/cli-auth",
            "https://user@www.firecrawl.dev/cli-auth",
            "https://platform.parallel.ai:8443/device",
            "https:///missing-host",
            "file:///tmp/login",
            "",
            " https://www.firecrawl.dev/cli-auth",
        ] {
            assert!(validate_open_url(bad).is_err(), "{bad} must be rejected");
        }
    }

    #[test]
    fn jsonl_events_are_parsed_and_unknown_ones_are_ignored() {
        assert_eq!(
            parse_event(r#"{"event":"open_url","url":"https://www.firecrawl.dev/x","user_code":"AB-12"}"#)
                .unwrap(),
            Some(LoginEvent::OpenUrl {
                url: "https://www.firecrawl.dev/x".into(),
                user_code: Some("AB-12".into())
            })
        );
        assert_eq!(parse_event(r#"{"event":"waiting"}"#).unwrap(), Some(LoginEvent::Waiting));
        assert_eq!(
            parse_event(r#"{"event":"notice","message":"已登录，但自动创建搜索 Key 失败"}"#).unwrap(),
            Some(LoginEvent::Notice { message: "已登录，但自动创建搜索 Key 失败".into() })
        );
        assert_eq!(parse_event(r#"{"event":"notice"}"#).unwrap(), None, "an empty notice is ignored");
        assert_eq!(parse_event(r#"{"event":"complete","credential":"firecrawl"}"#).unwrap(), Some(LoginEvent::Complete));
        assert_eq!(
            parse_event(r#"{"event":"error","error_kind":"provider","message":"授权被拒绝。"}"#)
                .unwrap(),
            Some(LoginEvent::Error { message: "授权被拒绝。".into() })
        );
        assert_eq!(parse_event(r#"{"event":"future","value":1}"#).unwrap(), None);
        assert_eq!(parse_event("").unwrap(), None);
        assert!(parse_event("not-json").is_err());
        assert!(parse_event(r#"{"event":"open_url"}"#).is_err());
    }
}
