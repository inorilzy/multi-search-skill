//! Boolean dashboard IPC over the existing owned CLI login sessions. Core owns Chrome/CDP and
//! credential storage; native code retains only the provider's session id for polling/cancellation.
use crate::{DesktopManager, OAuthLoginStatus};
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};

#[derive(Default)]
pub(crate) struct DashboardLogins {
    sessions: Mutex<BTreeMap<String, u64>>,
    closed: AtomicBool,
}

impl DashboardLogins {
    // Both IPC callers run on blocking workers; the UI thread never waits on a CLI process.
    pub(crate) fn login(&self, manager: &DesktopManager, provider: &str) -> Result<bool, String> {
        let provider = crate::oauth_login::validate_chrome_provider(provider)?;
        let id = {
            let mut sessions = self
                .sessions
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if self.closed.load(Ordering::Acquire) {
                return Err("桌面管理器已关闭".into());
            }
            if sessions.contains_key(&provider) {
                return Err("此服务商已有 Chrome 登录正在进行".into());
            }
            // Keep cancellation ordered with startup, including managed-CLI discovery.
            let id = manager.chrome_login_start(&provider)?;
            sessions.insert(provider.clone(), id);
            id
        };
        let result = loop {
            if self.closed.load(Ordering::Acquire) {
                let _ = manager.oauth_login_cancel(id);
                break Ok(false);
            }
            match manager.oauth_login_poll(id) {
                Ok(status) => {
                    if let Some(result) = terminal_result(&status) {
                        break result;
                    }
                }
                Err(error) => break Err(error),
            }
            std::thread::sleep(Duration::from_millis(50));
        };
        let mut sessions = self
            .sessions
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if sessions.get(&provider) == Some(&id) {
            sessions.remove(&provider);
        }
        drop(sessions);
        if result == Ok(true) {
            manager.invalidate_key_sources();
        }
        result
    }

    pub(crate) fn cancel(&self, manager: &DesktopManager, provider: &str) -> Result<(), String> {
        let provider = crate::oauth_login::validate_chrome_provider(provider)?;
        let sessions = self
            .sessions
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(id) = sessions.get(&provider) {
            manager.oauth_login_cancel(*id)?;
        }
        Ok(())
    }

    pub(crate) fn shutdown(&self) {
        self.closed.store(true, Ordering::Release);
        // Pollers exit/cancel their owned id. DesktopManager::shutdown also reaps the shared child.
    }
}

fn terminal_result(status: &OAuthLoginStatus) -> Option<Result<bool, String>> {
    match status.phase.as_str() {
        "starting" | "waiting" => None,
        "complete" => Some(Ok(true)),
        "cancelled" => Some(Ok(false)),
        "error" => Some(Err(status
            .message
            .clone()
            .unwrap_or_else(|| "Chrome 登录失败，请重试。".into()))),
        _ => Some(Err("CLI 返回了未知的 Chrome 登录状态。".into())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn manager() -> DesktopManager {
        DesktopManager::new(crate::RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables: BTreeMap::new(),
            cwd: std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")),
        })
    }

    fn status(phase: &str) -> OAuthLoginStatus {
        OAuthLoginStatus {
            id: 1,
            provider: "brave".into(),
            phase: phase.into(),
            url: None,
            user_code: None,
            message: None,
        }
    }

    #[test]
    fn completion_and_cancellation_keep_the_boolean_contract() {
        assert_eq!(terminal_result(&status("starting")), None);
        assert_eq!(terminal_result(&status("waiting")), None);
        assert_eq!(terminal_result(&status("complete")), Some(Ok(true)));
        assert_eq!(terminal_result(&status("cancelled")), Some(Ok(false)));
        let mut error = status("error");
        error.message = Some("Chrome 连接授权被拒绝。".into());
        assert_eq!(
            terminal_result(&error),
            Some(Err("Chrome 连接授权被拒绝。".into()))
        );
        assert!(terminal_result(&status("unknown")).unwrap().is_err());
    }

    #[test]
    fn cancel_is_provider_scoped_and_never_shuts_down_the_app() {
        let manager = manager();
        let logins = DashboardLogins::default();
        logins.sessions.lock().unwrap().insert("brave".into(), 7);
        assert!(logins.cancel(&manager, "unknown").is_err());
        assert!(logins.cancel(&manager, "exa").is_ok());
        assert_eq!(logins.sessions.lock().unwrap().get("brave"), Some(&7));
        assert!(!manager.closed.load(Ordering::Acquire));
    }

    #[test]
    fn duplicate_and_closed_sessions_fail_before_cli_discovery() {
        let manager = manager();
        let logins = DashboardLogins::default();
        logins.sessions.lock().unwrap().insert("brave".into(), 7);
        assert_eq!(
            logins.login(&manager, "brave").unwrap_err(),
            "此服务商已有 Chrome 登录正在进行"
        );
        logins.shutdown();
        assert_eq!(
            logins.login(&manager, "exa").unwrap_err(),
            "桌面管理器已关闭"
        );
        assert!(!manager.closed.load(Ordering::Acquire));
    }
}
