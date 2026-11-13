//! Native dashboard sessions. Cookie values stay in this module and the private OAuth store;
//! the management webview receives only completion/cancellation, never a credential.
use serde_json::{Map, Value};
use std::{collections::BTreeMap, path::Path, sync::Mutex};

#[derive(Clone, Copy)]
struct Dashboard {
    provider: &'static str,
    label: &'static str,
    title: &'static str,
    url: &'static str,
    host: &'static str,
    path: &'static str,
    entry: &'static str,
    required_cookies: &'static [&'static str],
}

const BRAVE: Dashboard = Dashboard {
    provider: "brave",
    label: "dashboard-login-brave",
    title: "Brave · 登录管理后台",
    url: "https://api-dashboard.search.brave.com/app/dashboard",
    host: "api-dashboard.search.brave.com",
    path: "/app/dashboard",
    entry: "brave_dashboard",
    required_cookies: &["search_api_users_auth"],
};
const EXA: Dashboard = Dashboard {
    provider: "exa",
    label: "dashboard-login-exa",
    title: "Exa · 登录管理后台",
    url: "https://dashboard.exa.ai/home",
    host: "dashboard.exa.ai",
    path: "/home",
    entry: "exa_admin",
    required_cookies: &[
        "__Secure-next-auth.session-token",
        "next-auth.session-token",
    ],
};

fn allowlisted(provider: &str) -> Result<Dashboard, String> {
    match provider {
        "brave" => Ok(BRAVE),
        "exa" => Ok(EXA),
        _ => Err("不支持此服务商的后台登录".into()),
    }
}

// Keep the fixed native allowlist and the catalog's declaration as independent requirements.
fn configured<'a>(
    provider: &str,
    methods: impl Iterator<Item = &'a str>,
) -> Result<Dashboard, String> {
    let dashboard = allowlisted(provider)?;
    if !methods.into_iter().any(|method| method == "web") {
        return Err("此服务商未声明后台网页登录方式".into());
    }
    Ok(dashboard)
}

fn trusted_location(dashboard: Dashboard, location: &str) -> bool {
    if location
        .chars()
        .any(|c| c.is_control() || c.is_whitespace())
    {
        return false;
    }
    let Some(rest) = location.strip_prefix("https://") else {
        return false;
    };
    let end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    if !rest[..end].eq_ignore_ascii_case(dashboard.host) {
        return false;
    }
    let path = rest[end..].split(['?', '#']).next().unwrap_or_default();
    // Reject ambiguous escapes even in pure tests; the runtime supplies a parsed/canonical URL.
    if path.contains(['%', '\\']) || path.split('/').any(|part| matches!(part, "." | "..")) {
        return false;
    }
    match dashboard.provider {
        "brave" => path.starts_with("/app/"),
        "exa" => matches!(path, "/home" | "/home/"),
        _ => false,
    }
}

fn cookie_matches_target(dashboard: Dashboard, domain: Option<&str>, path: Option<&str>) -> bool {
    let Some(domain) = domain else { return false };
    let domain = domain.strip_prefix('.').unwrap_or(domain);
    let host_matches = dashboard.host.eq_ignore_ascii_case(domain)
        || match dashboard.provider {
            "brave" => ["search.brave.com", "brave.com"]
                .iter()
                .any(|allowed| domain.eq_ignore_ascii_case(allowed)),
            "exa" => domain.eq_ignore_ascii_case("exa.ai"),
            _ => false,
        };
    let path = path.filter(|path| path.starts_with('/')).unwrap_or("/");
    host_matches
        && (dashboard.path == path
            || (dashboard.path.starts_with(path)
                && (path.ends_with('/')
                    || dashboard.path.as_bytes().get(path.len()) == Some(&b'/'))))
}

struct Credential {
    header: String,
    session_id: String,
}

fn cookie_header<'a>(
    dashboard: Dashboard,
    cookies: impl Iterator<Item = (&'a str, &'a str)>,
) -> Result<Option<Credential>, String> {
    let mut pairs = BTreeMap::new();
    let mut size = 0usize;
    for (name, value) in cookies {
        let valid_name = !name.is_empty()
            && name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b));
        // RFC 6265 cookie-octet: no header delimiters, whitespace, controls or non-ASCII.
        let valid_value = value
            .bytes()
            .all(|b| matches!(b, 0x21 | 0x23..=0x2b | 0x2d..=0x3a | 0x3c..=0x5b | 0x5d..=0x7e));
        size = size
            .saturating_add(name.len())
            .saturating_add(value.len())
            .saturating_add(3);
        if !valid_name || !valid_value || size > 65_536 {
            return Err("后台 Cookie 格式无效，未保存凭据".into());
        }
        if pairs
            .insert(name, value)
            .is_some_and(|previous| previous != value)
        {
            return Err("后台 Cookie 存在重复名称，未保存凭据".into());
        }
    }
    let Some(session) = dashboard
        .required_cookies
        .iter()
        .filter_map(|name| pairs.get(name))
        .find(|value| !value.is_empty())
    else {
        return Ok(None);
    };
    Ok(Some(Credential {
        header: pairs
            .iter()
            .map(|(name, value)| format!("{name}={value}"))
            .collect::<Vec<_>>()
            .join("; "),
        session_id: crate::credential::snapshot(session),
    }))
}

// Only the short read/modify/replace transaction is serialized, never the interactive login.
// Other native credential writers use keys.json; this file also follows Core's atomic contract.
static STORE_LOCK: Mutex<()> = Mutex::new(());

fn save(path: &Path, dashboard: Dashboard, credential: &Credential) -> Result<(), String> {
    let _guard = STORE_LOCK.lock().map_err(|_| "后台凭据保存锁不可用")?;
    if let Ok(metadata) = std::fs::symlink_metadata(path) {
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err("后台凭据文件不是普通文件，未保存".into());
        }
    }
    let mut records: Map<String, Value> = match std::fs::read_to_string(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Map::new(),
        Err(_) => return Err("无法读取 ~/.multi-search/oauth.json，未保存".into()),
        Ok(text) => match serde_json::from_str(text.trim_start_matches('\u{feff}')) {
            Ok(Value::Object(records)) => records,
            _ => {
                return Err(
                    "~/.multi-search/oauth.json 不是有效的 JSON 对象，未保存；请先修复文件".into(),
                )
            }
        },
    };
    let mut record = match records.get(dashboard.entry) {
        None => Map::new(),
        Some(Value::Object(record)) => record.clone(),
        Some(_) => return Err("后台凭据记录不是有效的 JSON 对象，未保存".into()),
    };
    // This is an explicit fresh login, not a token refresh: a different session must get its own
    // account/history reference, while repeated captures of the same session keep the same hash.
    let login_id = credential.session_id.clone();
    record.insert(
        "cookie_header".into(),
        Value::String(credential.header.clone()),
    );
    record.insert("login_id".into(), Value::String(login_id));
    records.insert(dashboard.entry.into(), Value::Object(record));
    let parent = path.parent().ok_or("无法定位后台凭据目录")?;
    std::fs::create_dir_all(parent).map_err(|_| "无法创建 ~/.multi-search 目录")?;
    let mut body = serde_json::to_vec_pretty(&records).map_err(|_| "无法序列化后台凭据")?;
    body.push(b'\n');
    crate::secure_temp::replace_private_file(path, &body)
        .map_err(|_| "无法保存 ~/.multi-search/oauth.json".into())
}

#[cfg(feature = "native-window")]
mod native {
    use super::*;
    use crate::DesktopManager;
    use std::{
        sync::{
            atomic::{AtomicBool, Ordering},
            Arc, Condvar,
        },
        time::{Duration, Instant},
    };
    use tauri::{webview::PageLoadEvent, Manager};

    const TIMEOUT: Duration = Duration::from_secs(300);
    const POLL: Duration = Duration::from_millis(300);
    const TIMED_OUT: &str = "后台登录已超时（300 秒），请重新登录";

    #[derive(Default)]
    struct Progress {
        outcome: Option<Result<bool, String>>,
        generation: u64,
        loaded: bool,
    }

    #[derive(Default)]
    struct Session {
        progress: Mutex<Progress>,
        changed: Condvar,
    }

    impl Session {
        fn lock(&self) -> std::sync::MutexGuard<'_, Progress> {
            self.progress
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        }

        fn finish(&self, result: Result<bool, String>) {
            let mut progress = self.lock();
            if progress.outcome.is_none() {
                progress.outcome = Some(result);
                self.changed.notify_all();
            }
        }

        fn wait(&self, deadline: Instant) -> Result<bool, String> {
            let mut progress = self.lock();
            loop {
                if let Some(result) = progress.outcome.as_ref() {
                    return result.clone();
                }
                let Some(remaining) = deadline.checked_duration_since(Instant::now()) else {
                    progress.outcome = Some(Err(TIMED_OUT.into()));
                    self.changed.notify_all();
                    return Err(TIMED_OUT.into());
                };
                progress = self
                    .changed
                    .wait_timeout(progress, remaining)
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .0;
            }
        }
    }

    #[derive(Default)]
    pub(crate) struct DashboardLogins {
        slots: Mutex<BTreeMap<&'static str, Arc<Session>>>,
        closed: AtomicBool,
    }

    struct Reservation {
        logins: Arc<DashboardLogins>,
        dashboard: Dashboard,
        session: Arc<Session>,
    }

    impl Drop for Reservation {
        fn drop(&mut self) {
            let mut slots = self
                .logins
                .slots
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if slots
                .get(self.dashboard.provider)
                .is_some_and(|session| Arc::ptr_eq(session, &self.session))
            {
                slots.remove(self.dashboard.provider);
            }
        }
    }

    fn resolve(provider: &str) -> Result<Dashboard, String> {
        let plugin = crate::source_catalog::catalog()
            .plugin(provider)
            .ok_or("不支持此服务商的后台登录")?;
        configured(
            provider,
            plugin
                .auth_methods
                .iter()
                .map(|method| method.method_type.as_str()),
        )
    }

    impl DashboardLogins {
        // Called by an async command's blocking worker, never from the UI event thread.
        pub(crate) fn login(
            self: &Arc<Self>,
            app: tauri::AppHandle,
            manager: Arc<DesktopManager>,
            provider: &str,
        ) -> Result<bool, String> {
            let dashboard = resolve(provider)?;
            let path = crate::keys_file::path(&manager.environment.variables)
                .ok_or("无法定位用户目录")?
                .with_file_name("oauth.json");
            let session = Arc::new(Session::default());
            {
                let mut slots = self
                    .slots
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if self.closed.load(Ordering::Acquire) || manager.closed.load(Ordering::Acquire) {
                    return Err("桌面管理器已关闭".into());
                }
                if slots.contains_key(dashboard.provider)
                    || app.get_webview_window(dashboard.label).is_some()
                {
                    return Err("此服务商已有后台登录正在进行".into());
                }
                slots.insert(dashboard.provider, session.clone());
            }
            let _reservation = Reservation {
                logins: self.clone(),
                dashboard,
                session: session.clone(),
            };
            let deadline = Instant::now() + TIMEOUT;
            let navigation = session.clone();
            let loaded = session.clone();
            let url = tauri::Url::parse(dashboard.url).map_err(|_| "后台登录地址无效")?;
            let window = tauri::WebviewWindowBuilder::new(
                &app,
                dashboard.label,
                tauri::WebviewUrl::External(url.clone()),
            )
            .title(dashboard.title)
            .inner_size(1000.0, 780.0)
            .incognito(true)
            .on_navigation(move |url| {
                // HTTPS redirects may be necessary for SSO; none of those origins is read.
                let allowed = url.scheme() == "https"
                    && url.username().is_empty()
                    && url.password().is_none();
                if allowed {
                    let mut progress = navigation.lock();
                    progress.generation = progress.generation.wrapping_add(1);
                    progress.loaded = false;
                }
                allowed
            })
            .on_page_load(move |_, payload| {
                let mut progress = loaded.lock();
                progress.generation = progress.generation.wrapping_add(1);
                // SPA sign-in pages may reach the dashboard with history.pushState rather than
                // another load event. The poller validates the actual URL before and after reading.
                progress.loaded = payload.event() == PageLoadEvent::Finished;
            })
            .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
            .on_download(|_, _| false)
            .build()
            .map_err(|_| "无法打开后台登录窗口")?;
            let closed = session.clone();
            window.on_window_event(move |event| {
                if matches!(
                    event,
                    tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed
                ) {
                    closed.finish(Ok(false));
                }
            });
            let worker_session = session.clone();
            let worker_window = window.clone();
            let started = std::thread::Builder::new()
                .name("dashboard-cookie-login".into())
                .spawn(move || {
                    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        monitor(
                            &worker_window,
                            &worker_session,
                            &manager,
                            dashboard,
                            &path,
                            url,
                            deadline,
                        );
                    }));
                    if result.is_err() {
                        worker_session.finish(Err("后台登录读取失败，请重新登录".into()));
                    }
                });
            if started.is_err() {
                session.finish(Err("无法启动后台登录读取任务".into()));
            }
            // An independent deadline can close the window even while a cookie API is waiting.
            let result = session.wait(deadline);
            let _ = window.close();
            result
        }

        pub(crate) fn cancel(&self, app: &tauri::AppHandle, provider: &str) -> Result<(), String> {
            let dashboard = resolve(provider)?;
            let slots = self
                .slots
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(session) = slots.get(dashboard.provider) {
                session.finish(Ok(false));
                if let Some(window) = app.get_webview_window(dashboard.label) {
                    window.close().map_err(|_| "无法关闭后台登录窗口")?;
                }
            }
            Ok(())
        }

        pub(crate) fn shutdown(&self) {
            self.closed.store(true, Ordering::Release);
            let slots = self
                .slots
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            for session in slots.values() {
                session.finish(Ok(false));
            }
        }
    }

    fn monitor(
        window: &tauri::WebviewWindow,
        session: &Session,
        manager: &DesktopManager,
        dashboard: Dashboard,
        path: &Path,
        target: tauri::Url,
        deadline: Instant,
    ) {
        loop {
            let generation = {
                let progress = session.lock();
                if progress.outcome.is_some() {
                    return;
                }
                progress.loaded.then_some(progress.generation)
            };
            if let Some(generation) = generation {
                let current = match window.url() {
                    Ok(url) => url,
                    Err(_) => {
                        session.finish(Ok(false));
                        return;
                    }
                };
                if trusted_location(dashboard, current.as_str()) {
                    // Always query the fixed dashboard URL; never query the current SSO/external URL.
                    let cookies = match window.cookies_for_url(target.clone()) {
                        Ok(cookies) => cookies,
                        Err(_) => {
                            session.finish(Err("无法读取后台登录 Cookie".into()));
                            return;
                        }
                    };
                    #[cfg(target_os = "macos")]
                    let cookies = if cookies.iter().any(|cookie| {
                        dashboard.required_cookies.contains(&cookie.name())
                            && !cookie.value().is_empty()
                            && cookie_matches_target(dashboard, cookie.domain(), cookie.path())
                    }) {
                        cookies
                    } else {
                        // Wry 0.54's WKWebView cookies_for_url compares domains for equality and
                        // drops valid parent-domain cookies (Exa uses .exa.ai). This window owns
                        // an isolated incognito store; filter every cookie before building a header.
                        match window.url() {
                            Ok(url) if trusted_location(dashboard, url.as_str()) => {}
                            Ok(_) => continue,
                            Err(_) => {
                                session.finish(Ok(false));
                                return;
                            }
                        }
                        {
                            let progress = session.lock();
                            if progress.outcome.is_some() {
                                return;
                            }
                            if !progress.loaded || progress.generation != generation {
                                continue;
                            }
                        }
                        match window.cookies() {
                            Ok(cookies) => cookies,
                            Err(_) => {
                                session.finish(Err("无法读取后台登录 Cookie".into()));
                                return;
                            }
                        }
                    };
                    let credential = match cookie_header(
                        dashboard,
                        cookies
                            .iter()
                            .filter(|cookie| {
                                cookie_matches_target(dashboard, cookie.domain(), cookie.path())
                            })
                            .map(|cookie| (cookie.name(), cookie.value())),
                    ) {
                        Ok(credential) => credential,
                        Err(error) => {
                            session.finish(Err(error));
                            return;
                        }
                    };
                    if let Some(credential) = credential {
                        let current = match window.url() {
                            Ok(url) => url,
                            Err(_) => {
                                session.finish(Ok(false));
                                return;
                            }
                        };
                        let mut progress = session.lock();
                        if progress.outcome.is_some() {
                            return;
                        }
                        if Instant::now() >= deadline {
                            progress.outcome = Some(Err(TIMED_OUT.into()));
                            session.changed.notify_all();
                            return;
                        }
                        if progress.loaded
                            && generation == progress.generation
                            && trusted_location(dashboard, current.as_str())
                        {
                            // No Tauri calls while this lock is held: close/navigation and save are
                            // ordered here, so a cancellation that won the lock cannot persist data.
                            let saved = save(path, dashboard, &credential).map(|()| true);
                            let complete = saved == Ok(true);
                            progress.outcome = Some(saved);
                            session.changed.notify_all();
                            drop(progress);
                            if complete {
                                manager.invalidate_key_sources();
                            }
                            return;
                        }
                    }
                }
            }
            std::thread::sleep(POLL);
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn generated_catalog_declares_the_allowlisted_web_logins() {
            assert_eq!(resolve("brave").unwrap().entry, "brave_dashboard");
            assert_eq!(resolve("exa").unwrap().entry, "exa_admin");
            for provider in ["unknown", "parallel", "exa_admin", "brave_dashboard"] {
                assert!(resolve(provider).is_err());
            }
        }

        #[test]
        fn parent_domain_http_only_cookie_is_included_and_other_sites_are_filtered() {
            let cookie =
                tauri::webview::Cookie::build((EXA.required_cookies[0], "synthetic-session"))
                    .domain(".exa.ai")
                    .path("/")
                    .http_only(true)
                    .secure(true)
                    .build();
            assert_eq!(cookie.http_only(), Some(true));
            let cookies = [
                cookie,
                tauri::webview::Cookie::build(("external", "not-for-dashboard"))
                    .domain(".google.com")
                    .path("/")
                    .build(),
                tauri::webview::Cookie::build(("wrong_path", "not-for-dashboard"))
                    .domain(EXA.host)
                    .path("/login")
                    .build(),
            ];
            let credential = cookie_header(
                EXA,
                cookies
                    .iter()
                    .filter(|cookie| cookie_matches_target(EXA, cookie.domain(), cookie.path()))
                    .map(|cookie| (cookie.name(), cookie.value())),
            )
            .unwrap()
            .unwrap();
            assert_eq!(
                credential.header,
                "__Secure-next-auth.session-token=synthetic-session"
            );
        }

        #[test]
        fn cancellation_and_deadline_are_terminal() {
            let cancelled = Session::default();
            cancelled.finish(Ok(false));
            cancelled.finish(Ok(true));
            assert_eq!(cancelled.wait(Instant::now()), Ok(false));
            let timed_out = Session::default();
            assert_eq!(timed_out.wait(Instant::now()), Err(TIMED_OUT.into()));
            timed_out.finish(Ok(true));
            assert_eq!(timed_out.wait(Instant::now()), Err(TIMED_OUT.into()));
        }
    }
}

#[cfg(feature = "native-window")]
pub(crate) use native::DashboardLogins;

#[cfg(test)]
mod tests {
    use super::*;

    struct Sandbox(std::path::PathBuf);
    impl Sandbox {
        fn new() -> Self {
            let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("target");
            std::fs::create_dir_all(&root).unwrap();
            Self(crate::secure_temp::create_dir(&root, "dashboard-login-test-").unwrap())
        }
        fn path(&self) -> std::path::PathBuf {
            self.0.join("oauth.json")
        }
    }
    impl Drop for Sandbox {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn credential(dashboard: Dashboard, value: &str) -> Credential {
        cookie_header(
            dashboard,
            [(dashboard.required_cookies[0], value)].into_iter(),
        )
        .unwrap()
        .unwrap()
    }
    fn records(path: &Path) -> Value {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }

    #[test]
    fn native_allowlist_and_web_declaration_are_both_required() {
        for provider in ["brave", "exa"] {
            assert_eq!(
                configured(provider, ["api", "web"].into_iter())
                    .unwrap()
                    .provider,
                provider
            );
            assert!(configured(provider, ["api", "oauth"].into_iter()).is_err());
        }
        for provider in [
            "",
            "Brave",
            " brave",
            "exa_admin",
            "brave_dashboard",
            "parallel",
            "../exa",
        ] {
            assert!(configured(provider, ["web"].into_iter()).is_err());
        }
        assert_ne!(BRAVE.label, EXA.label);
        assert!(trusted_location(BRAVE, BRAVE.url));
        assert!(trusted_location(EXA, EXA.url));
        assert!(!BRAVE.title.is_empty() && !EXA.title.is_empty());
    }

    #[test]
    fn dashboard_location_requires_exact_https_origin_and_safe_path() {
        for url in [
            BRAVE.url,
            "https://api-dashboard.search.brave.com/app/account?tab=1#key",
        ] {
            assert!(trusted_location(BRAVE, url));
        }
        for url in [
            "http://api-dashboard.search.brave.com/app/dashboard",
            "https://api-dashboard.search.brave.com.evil.test/app/dashboard",
            "https://evil.test@api-dashboard.search.brave.com/app/dashboard",
            "https://api-dashboard.search.brave.com:444/app/dashboard",
            "https://api-dashboard.search.brave.com/login",
            "https://api-dashboard.search.brave.com/application/dashboard",
            "https://api-dashboard.search.brave.com/app/../login",
            "https://api-dashboard.search.brave.com/app/%2e%2e/login",
            "https://api-dashboard.search.brave.com/app/\\login",
            "https://api-dashboard.search.brave.com/app/dashboard\r\n",
            EXA.url,
        ] {
            assert!(!trusted_location(BRAVE, url), "{url}");
        }
        assert!(trusted_location(
            EXA,
            "https://dashboard.exa.ai/home/?tab=billing"
        ));
        for url in [
            "https://dashboard.exa.ai/",
            "https://dashboard.exa.ai/home-evil",
            "https://dashboard.exa.ai/home/evil",
            BRAVE.url,
        ] {
            assert!(!trusted_location(EXA, url));
        }
    }

    #[test]
    fn cookie_scope_respects_domain_boundaries_and_paths() {
        assert!(cookie_matches_target(BRAVE, Some(BRAVE.host), Some("/app")));
        assert!(cookie_matches_target(
            BRAVE,
            Some(".search.brave.com"),
            Some("/")
        ));
        assert!(!cookie_matches_target(BRAVE, Some("evil.test"), Some("/")));
        assert!(!cookie_matches_target(
            BRAVE,
            Some("brave.com.evil.test"),
            Some("/")
        ));
        assert!(!cookie_matches_target(
            BRAVE,
            Some(BRAVE.host),
            Some("/app/dash")
        ));
        assert!(!cookie_matches_target(
            BRAVE,
            Some(BRAVE.host),
            Some("/login")
        ));
        assert!(cookie_matches_target(EXA, Some(".exa.ai"), Some("/")));
        assert!(!cookie_matches_target(
            EXA,
            Some("exa.ai.evil.test"),
            Some("/")
        ));
        assert!(!cookie_matches_target(EXA, Some("google.com"), Some("/")));
        assert!(!cookie_matches_target(EXA, Some("auth.exa.ai"), Some("/")));
        assert!(!cookie_matches_target(EXA, Some(".ai"), Some("/")));
        assert!(!cookie_matches_target(BRAVE, Some(".com"), Some("/")));
        assert!(!cookie_matches_target(EXA, None, Some("/")));
    }

    #[test]
    fn header_requires_session_cookie_and_rejects_injection() {
        assert!(cookie_header(BRAVE, [("other", "value")].into_iter())
            .unwrap()
            .is_none());
        assert!(
            cookie_header(BRAVE, [(BRAVE.required_cookies[0], "")].into_iter())
                .unwrap()
                .is_none()
        );
        let saved = cookie_header(
            BRAVE,
            [("z", "v=1"), (BRAVE.required_cookies[0], "fake-session")].into_iter(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(saved.header, "search_api_users_auth=fake-session; z=v=1");
        for (name, value) in [
            ("bad\r\nName", "v"),
            ("bad=name", "v"),
            ("", "v"),
            ("name", "v\r\nInjected: yes"),
            ("name", "v; injected=x"),
            ("name", "v value"),
            ("name", "\"v\""),
            ("name", "v\\v"),
            ("name", "值"),
        ] {
            assert!(cookie_header(
                BRAVE,
                [(BRAVE.required_cookies[0], "fake-session"), (name, value)].into_iter()
            )
            .is_err());
        }
        assert!(cookie_header(
            BRAVE,
            [
                (BRAVE.required_cookies[0], "a"),
                (BRAVE.required_cookies[0], "b")
            ]
            .into_iter()
        )
        .is_err());
        let huge = "x".repeat(65_536);
        assert!(cookie_header(
            BRAVE,
            [(BRAVE.required_cookies[0], huge.as_str())].into_iter()
        )
        .is_err());
    }

    #[test]
    fn store_preserves_other_entries_and_metadata_but_replaces_login_id() {
        let sandbox = Sandbox::new();
        let path = sandbox.path();
        let before = serde_json::json!({
            "parallel": {"client_id": "fake-client"},
            "exa_admin": {"cookie_header": "old=fake", "login_id": "stable-account", "extra": {"enabled": true}},
            "future_entry": [1, 2, 3]
        });
        std::fs::write(&path, serde_json::to_vec(&before).unwrap()).unwrap();
        save(&path, EXA, &credential(EXA, "fake-session-one")).unwrap();
        let after = records(&path);
        assert_eq!(after["parallel"], before["parallel"]);
        assert_eq!(after["future_entry"], before["future_entry"]);
        assert_eq!(after["exa_admin"]["extra"], before["exa_admin"]["extra"]);
        assert_eq!(
            after["exa_admin"]["login_id"],
            crate::credential::snapshot("fake-session-one")
        );
        assert_ne!(
            after["exa_admin"]["login_id"],
            before["exa_admin"]["login_id"]
        );
        save(&path, BRAVE, &credential(BRAVE, "fake-session-two")).unwrap();
        assert_eq!(records(&path)["exa_admin"], after["exa_admin"]);
        assert!(records(&path).get("brave_dashboard").is_some());
        assert_eq!(std::fs::read_dir(&sandbox.0).unwrap().count(), 1);
    }

    #[test]
    fn store_refuses_corrupt_root_or_record_without_overwriting() {
        let sandbox = Sandbox::new();
        let path = sandbox.path();
        for body in ["{broken", "[]", "null", "{\"brave_dashboard\":\"broken\"}"] {
            std::fs::write(&path, body).unwrap();
            assert!(save(&path, BRAVE, &credential(BRAVE, "fake-session")).is_err());
            assert_eq!(std::fs::read_to_string(&path).unwrap(), body);
        }
        assert_eq!(std::fs::read_dir(&sandbox.0).unwrap().count(), 1);
    }

    #[test]
    fn login_identity_is_a_stable_nonsecret_session_hash() {
        let sandbox = Sandbox::new();
        let path = sandbox.path();
        let first = credential(BRAVE, "fake-session");
        let second = cookie_header(
            BRAVE,
            [
                (BRAVE.required_cookies[0], "fake-session"),
                ("analytics", "changed"),
            ]
            .into_iter(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(first.session_id, second.session_id);
        assert_eq!(first.session_id.len(), 64);
        assert!(first.session_id.bytes().all(|b| b.is_ascii_hexdigit()));
        save(&path, BRAVE, &first).unwrap();
        let login_id = records(&path)[BRAVE.entry]["login_id"].clone();
        save(&path, BRAVE, &second).unwrap();
        assert_eq!(records(&path)[BRAVE.entry]["login_id"], login_id);
    }

    #[test]
    fn different_sessions_receive_different_history_references() {
        let sandbox = Sandbox::new();
        let path = sandbox.path();
        for dashboard in [BRAVE, EXA] {
            save(
                &path,
                dashboard,
                &credential(dashboard, "first-fake-session"),
            )
            .unwrap();
            let before = records(&path)[dashboard.entry]["login_id"].clone();
            save(
                &path,
                dashboard,
                &credential(dashboard, "another-fake-session"),
            )
            .unwrap();
            let after = records(&path)[dashboard.entry]["login_id"].clone();
            assert_ne!(before, after);
            assert_eq!(after, crate::credential::snapshot("another-fake-session"));
        }
    }

    #[test]
    fn exa_accepts_only_the_two_exact_session_cookie_names() {
        for name in [
            "next-auth.session-token",
            "__Secure-next-auth.session-token",
        ] {
            let saved = cookie_header(EXA, [(name, "fake-session")].into_iter())
                .unwrap()
                .unwrap();
            assert_eq!(saved.header, format!("{name}=fake-session"));
            assert_eq!(
                saved.session_id,
                crate::credential::snapshot("fake-session")
            );
        }
        for name in [
            "not-next-auth.session-token",
            "__Host-next-auth.session-token",
            "next-auth.session-token-extra",
            "other.session-token",
        ] {
            assert!(cookie_header(EXA, [(name, "fake-session")].into_iter())
                .unwrap()
                .is_none());
        }
    }

    #[cfg(unix)]
    #[test]
    fn store_is_owner_only_on_creation_and_replacement() {
        use std::os::unix::fs::PermissionsExt;
        let sandbox = Sandbox::new();
        let path = sandbox.path();
        save(&path, BRAVE, &credential(BRAVE, "fake-session")).unwrap();
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        save(&path, EXA, &credential(EXA, "another-fake-session")).unwrap();
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}
