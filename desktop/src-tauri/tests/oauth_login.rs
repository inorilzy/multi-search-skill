//! OAuth login session boundary: provider allowlist, fixed CLI argv, incremental JSONL events,
//! URL whitelist and cancellation/shutdown of the owned child process. The fixture CLI stands in
//! for the managed CLI; its browser opener is injected, so no real browser is launched.
mod common;

use multi_search_desktop::oauth_login::OAuthLoginStatus;
use multi_search_desktop::oauth_login_fixture as oauth;
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

fn wait_for(
    logins: &multi_search_desktop::oauth_login::OAuthLogins,
    id: u64,
    predicate: impl Fn(&OAuthLoginStatus) -> bool,
) -> OAuthLoginStatus {
    let started = Instant::now();
    loop {
        let state = oauth::poll(logins, id).unwrap();
        if predicate(&state) {
            return state;
        }
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "timed out waiting for login {id}; last state: {state:?}"
        );
        thread::sleep(Duration::from_millis(10));
    }
}

fn read_pid(path: &PathBuf) -> u32 {
    let started = Instant::now();
    loop {
        if let Ok(text) = std::fs::read_to_string(path) {
            if let Ok(pid) = text.trim().parse() {
                return pid;
            }
        }
        assert!(started.elapsed() < Duration::from_secs(5), "fixture never wrote its pid");
        thread::sleep(Duration::from_millis(10));
    }
}

fn wait_dead(pid: u32) {
    let started = Instant::now();
    while common::process_alive(pid) {
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "fixture process {pid} is still alive"
        );
        thread::sleep(Duration::from_millis(10));
    }
}

fn setup(mode: &str) -> (common::Profile, PathBuf, Arc<Mutex<Vec<String>>>, multi_search_desktop::oauth_login::OAuthLogins) {
    let mut profile = common::Profile::new();
    profile.environment.variables.insert("FIXTURE_OAUTH".into(), mode.into());
    let cli = profile.root.join(multi_search_desktop::CLI_FILE_NAME);
    let opened = Arc::new(Mutex::new(Vec::new()));
    let logins = oauth::manager(opened.clone());
    (profile, cli, opened, logins)
}

#[test]
fn only_oauth_providers_and_the_fixed_argv_are_accepted() {
    let (profile, cli, opened, logins) = setup("firecrawl");
    let environment = profile.environment.clone();
    for bad in ["", "tavily", "exa", "../firecrawl", "github_repos", "unknown"] {
        assert_eq!(
            oauth::start(&logins, &environment, &cli, bad).unwrap_err(),
            "不支持浏览器登录的服务商"
        );
    }
    assert_eq!(
        oauth::args("parallel"),
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

    let args_path = profile.root.join("login-args.json");
    let mut environment = environment;
    environment
        .variables
        .insert("FIXTURE_ARGS_PATH".into(), args_path.to_string_lossy().into_owned());
    let id = oauth::start(&logins, &environment, &cli, "firecrawl").unwrap();
    wait_for(&logins, id, |state| state.phase == "complete");
    let args: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(args_path).unwrap()).unwrap();
    assert_eq!(
        args,
        serde_json::json!(["login", "firecrawl", "--method", "oauth", "--format", "jsonl", "--no-browser"])
    );
    assert_eq!(
        opened.lock().unwrap().as_slice(),
        ["https://www.firecrawl.dev/cli-auth?code_challenge=synthetic"]
    );
}

#[test]
fn only_allowlisted_https_urls_may_be_opened() {
    assert!(oauth::validate_url("https://www.firecrawl.dev/cli-auth?code_challenge=x#session").is_ok());
    assert!(oauth::validate_url("https://platform.parallel.ai/device").is_ok());
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
        assert!(oauth::validate_url(bad).is_err(), "{bad} must be rejected");
    }
}

#[test]
fn parallel_events_expose_the_device_code_and_finish() {
    let (profile, cli, opened, logins) = setup("parallel");
    let id = oauth::start(&logins, &profile.environment, &cli, "parallel").unwrap();
    let waiting = wait_for(&logins, id, |state| state.phase == "waiting");
    assert_eq!(waiting.provider, "parallel");
    assert_eq!(waiting.user_code.as_deref(), Some("ABCD-EFGH"));
    assert!(waiting
        .url
        .as_deref()
        .is_some_and(|url| url.starts_with("https://platform.parallel.ai/")));
    let complete = wait_for(&logins, id, |state| state.phase == "complete");
    assert_eq!(complete.user_code.as_deref(), Some("ABCD-EFGH"));
    assert_eq!(
        opened.lock().unwrap().as_slice(),
        ["https://platform.parallel.ai/device?user_code=ABCD-EFGH"]
    );
}

#[test]
fn cli_error_events_and_malformed_lines_end_the_session() {
    for (mode, expected) in [
        ("error", "授权被拒绝。"),
        ("invalid-json", "CLI 返回了无法解析的登录事件。"),
    ] {
        let (profile, cli, _opened, logins) = setup(mode);
        let id = oauth::start(&logins, &profile.environment, &cli, "firecrawl").unwrap();
        let state = wait_for(&logins, id, |state| {
            state.phase == "error" || state.phase == "complete"
        });
        assert_eq!(state.phase, "error", "{mode}");
        assert_eq!(state.message.as_deref(), Some(expected), "{mode}");
    }
}

#[test]
fn non_https_and_non_whitelisted_urls_are_rejected_and_terminate_the_child() {
    for mode in ["non-https", "non-whitelisted"] {
        let (profile, cli, opened, logins) = setup(mode);
        let pid_path = profile.root.join("login-pid");
        let mut environment = profile.environment.clone();
        environment.variables.insert(
            "FIXTURE_OAUTH_PID".into(),
            pid_path.to_string_lossy().into_owned(),
        );
        let id = oauth::start(&logins, &environment, &cli, "firecrawl").unwrap();
        let state = wait_for(&logins, id, |state| state.phase == "error");
        let message = state.message.unwrap_or_default();
        assert!(
            message.contains("HTTPS") || message.contains("允许清单"),
            "{mode}: {message}"
        );
        assert!(opened.lock().unwrap().is_empty(), "{mode} must not open anything");
        wait_dead(read_pid(&pid_path));
    }
}

#[test]
fn cancel_terminates_the_cli_child_and_stops_the_session() {
    let (profile, cli, _opened, logins) = setup("hang");
    let pid_path = profile.root.join("login-pid");
    let mut environment = profile.environment.clone();
    environment.variables.insert(
        "FIXTURE_OAUTH_PID".into(),
        pid_path.to_string_lossy().into_owned(),
    );
    let id = oauth::start(&logins, &environment, &cli, "firecrawl").unwrap();
    wait_for(&logins, id, |state| state.phase == "waiting");
    let pid = read_pid(&pid_path);
    assert!(common::process_alive(pid), "fixture should be running before cancel");
    let state = oauth::cancel(&logins, id).unwrap();
    assert_eq!(state.phase, "cancelled");
    wait_dead(pid);
    assert_eq!(oauth::poll(&logins, id).unwrap().phase, "cancelled");
}

#[test]
fn app_shutdown_terminates_an_active_login() {
    let (profile, cli, _opened, logins) = setup("hang");
    let pid_path = profile.root.join("login-pid");
    let mut environment = profile.environment.clone();
    environment.variables.insert(
        "FIXTURE_OAUTH_PID".into(),
        pid_path.to_string_lossy().into_owned(),
    );
    let id = oauth::start(&logins, &environment, &cli, "firecrawl").unwrap();
    wait_for(&logins, id, |state| state.phase == "waiting");
    let pid = read_pid(&pid_path);
    oauth::shutdown(&logins);
    wait_dead(pid);
    assert_eq!(oauth::poll(&logins, id).unwrap().phase, "cancelled");
}
