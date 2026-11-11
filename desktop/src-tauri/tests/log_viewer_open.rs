//! T03: the log page opens the CLI-printed loopback address with the platform browser.
//!
//! Linux delegates to `xdg-open` with the URL as one argv entry, never through a shell.
//! A failed browser launch must leave the viewer service running and repeat its address in
//! the error, so the page can show it for manual copying; closing the window stops the
//! service through `DesktopManager::shutdown`.
use multi_search_desktop::log_viewer::{log_viewer_fixture, LogViewerInfo};
#[cfg(unix)]
use multi_search_desktop::{DesktopManager, RuntimeEnvironment, CLI_FILE_NAME};
#[cfg(unix)]
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

#[cfg(unix)]
static NEXT: AtomicU64 = AtomicU64::new(0);

#[cfg(unix)]
fn temp_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "multi-search-log-viewer-{}-{}-{tag}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn viewer_info(url: &str) -> LogViewerInfo {
    LogViewerInfo {
        url: url.into(),
        reused: false,
    }
}

#[test]
fn browser_failure_reports_the_running_viewer_address() {
    let info = viewer_info("http://127.0.0.1:50123/");
    let error = log_viewer_fixture::open(info, |url| {
        assert_eq!(url, "http://127.0.0.1:50123/");
        Err("无法打开系统浏览器".into())
    })
    .unwrap_err();
    assert!(
        error.contains("http://127.0.0.1:50123/"),
        "the address must stay available for manual copying: {error}"
    );
    assert!(
        error.contains("无法打开系统浏览器"),
        "the launch failure must be reported: {error}"
    );
}

#[test]
fn browser_success_returns_the_viewer_address() {
    let info = viewer_info("http://127.0.0.1:50123/");
    let opened = log_viewer_fixture::open(info.clone(), |url| {
        assert_eq!(url, "http://127.0.0.1:50123/");
        Ok(())
    })
    .unwrap();
    assert_eq!(opened, info);
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
#[test]
fn browser_launcher_passes_the_url_as_one_argument_without_a_shell() {
    use std::os::unix::fs::PermissionsExt;

    let dir = temp_dir("launcher");
    let record = dir.join("argv");
    let program = dir.join("fake-browser");
    std::fs::write(
        &program,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$#\" \"$@\" > '{}'\n",
            record.display()
        ),
    )
    .unwrap();
    std::fs::set_permissions(&program, std::fs::Permissions::from_mode(0o755)).unwrap();

    // A shell would split this at `&` and the space; one argv entry must reach the program.
    let url = "http://127.0.0.1:50123/?a=1&b=two words";
    multi_search_desktop::credential_commands::browser_fixture::launch(&program, url).unwrap();
    assert_eq!(
        std::fs::read_to_string(&record).unwrap(),
        format!("1\n{url}\n")
    );

    std::fs::remove_dir_all(dir).unwrap();
}

#[cfg(target_os = "linux")]
#[test]
fn linux_opens_the_viewer_with_xdg_open_and_the_url_as_the_only_argument() {
    use std::os::unix::fs::PermissionsExt;

    assert_eq!(
        multi_search_desktop::credential_commands::browser_fixture::launcher(),
        "xdg-open"
    );
    let dir = temp_dir("xdg-open");
    let record = dir.join("argv");
    let program = dir.join("xdg-open");
    std::fs::write(
        &program,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$#\" \"$@\" > '{}'\n",
            record.display()
        ),
    )
    .unwrap();
    std::fs::set_permissions(&program, std::fs::Permissions::from_mode(0o755)).unwrap();

    let original = std::env::var_os("PATH").unwrap_or_default();
    let mut paths = vec![dir.clone()];
    paths.extend(std::env::split_paths(&original));
    std::env::set_var("PATH", std::env::join_paths(paths).unwrap());
    let opened = multi_search_desktop::credential_commands::browser_fixture::open(
        "http://127.0.0.1:50123/",
    );
    std::env::set_var("PATH", original);
    opened.unwrap();
    assert_eq!(
        std::fs::read_to_string(&record).unwrap(),
        "1\nhttp://127.0.0.1:50123/\n"
    );

    std::fs::remove_dir_all(dir).unwrap();
}

#[cfg(unix)]
#[test]
fn viewer_keeps_running_after_a_browser_failure_and_stops_with_the_window() {
    use std::{
        os::unix::fs::PermissionsExt,
        thread,
        time::{Duration, Instant},
    };

    let dir = temp_dir("service");
    let pid_file = dir.join("pid");
    let cli = dir.join(CLI_FILE_NAME);
    std::fs::write(
        &cli,
        format!(
            "#!/bin/sh\n\
             if [ \"$1\" = \"--version\" ]; then echo \"multi-search 0.4.0\"; exit 0; fi\n\
             if [ \"$1\" = \"logs\" ] && [ \"$2\" = \"serve\" ]; then\n\
               echo \"multi-search logs: serving http://127.0.0.1:50123/ (Ctrl+C to stop)\" >&2\n\
               echo \"$$\" > '{}'\n\
               while :; do sleep 1; done\n\
             fi\n\
             exit 2\n",
            pid_file.display()
        ),
    )
    .unwrap();
    std::fs::set_permissions(&cli, std::fs::Permissions::from_mode(0o755)).unwrap();

    let environment = RuntimeEnvironment {
        app_path: vec![dir.clone()],
        user_path: vec![],
        variables: BTreeMap::from([
            ("PATH".into(), "/usr/bin:/bin".into()),
            ("HOME".into(), dir.to_string_lossy().into_owned()),
        ]),
        cwd: dir.clone(),
    };
    let manager = DesktopManager::new(environment);
    let info = manager.log_viewer().unwrap();
    assert_eq!(info.url, "http://127.0.0.1:50123/");
    assert!(!info.reused);

    let error = log_viewer_fixture::open(info.clone(), |_| {
        Err("无法打开系统浏览器".into())
    })
    .unwrap_err();
    assert!(error.contains("http://127.0.0.1:50123/"), "{error}");

    let reused = manager.log_viewer().unwrap();
    assert!(reused.reused, "a failed browser launch must not stop the service");
    assert_eq!(reused.url, info.url);

    let pid: u32 = std::fs::read_to_string(&pid_file)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert!(process_alive(pid), "the service must be running before shutdown");
    manager.shutdown();
    let deadline = Instant::now() + Duration::from_secs(2);
    while process_alive(pid) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert!(!process_alive(pid), "closing the window must stop the log service");

    std::fs::remove_dir_all(dir).unwrap();
}

#[cfg(unix)]
fn process_alive(pid: u32) -> bool {
    std::process::Command::new("kill")
        .args(["-0", &pid.to_string()])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}
