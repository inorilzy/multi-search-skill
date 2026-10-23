use multi_search_desktop::{DesktopManager, RuntimeEnvironment, SearchOptions};
use serde_json::Value;
use std::{
    thread,
    time::{Duration, Instant},
};

#[test]
#[ignore = "run via scripts/desktop_native_acceptance.py with a disposable installed CLI and controlled HTTP"]
fn rust_child_bootstrap_active_proof() {
    assert_eq!(std::env::var("MULTI_SEARCH_TEST_ISOLATION").unwrap(), "1");
    let marker = std::env::var("MULTI_SEARCH_TEST_BOOTSTRAP_MARK").unwrap();
    let selector = std::env::var("MULTI_SEARCH_TEST_PYTHONPATH").unwrap();
    let environment = RuntimeEnvironment::system();
    let manager = DesktopManager::new(environment.clone());
    let detection = manager.detect_cli(None);
    assert_eq!(detection.app.status, "ready", "{}", detection.app.reason);
    assert!(detection.app.path.as_ref().unwrap().contains(".wheel-venv"));
    let path = detection.app.path.unwrap();

    std::fs::remove_file(&marker).ok();
    let output = multi_search_desktop::process_fixture::run(
        std::path::Path::new(&path),
        &["--version".to_string()],
        environment.variables.clone(),
        environment.cwd.clone(),
    )
    .unwrap();
    assert!(
        !output.trim().is_empty(),
        "process_fixture::run returned no version output"
    );
    let proof: Value = serde_json::from_slice(&std::fs::read(&marker).unwrap()).unwrap();
    assert_eq!(proof["isolation"], "1");
    assert_eq!(proof["sitecustomize"], true);
    assert_eq!(proof["guard_active"], true);
    assert_eq!(proof["pythonpath"], selector);
    assert_ne!(proof["pid"], std::process::id());
    assert!(
        proof["http"]
            .as_str()
            .unwrap()
            .contains("site-packages")
    );
    let first_arg = proof["argv"]
        .as_array()
        .and_then(|argv| argv.first())
        .and_then(Value::as_str)
        .unwrap_or_default();
    assert!(first_arg.contains("multi-search.exe"));
}

#[test]
#[ignore = "run via scripts/desktop_native_acceptance.py with a disposable installed CLI and controlled HTTP"]
fn actual_installed_cli_detection_search_partial_failure_and_cancellation() {
    assert_eq!(std::env::var("MULTI_SEARCH_TEST_ISOLATION").unwrap(), "1");
    let environment = RuntimeEnvironment::system();
    let manager = DesktopManager::new(environment.clone());
    let detection = manager.detect_cli(None);
    assert_eq!(detection.app.status, "ready", "{}", detection.app.reason);
    assert_eq!(detection.user.status, "ready", "{}", detection.user.reason);
    assert_eq!(detection.app.version.as_deref(), Some("0.4.0"));
    assert!(detection.app.path.as_ref().unwrap().contains(".wheel-venv"));
    let fresh = std::process::Command::new("C:\\Windows\\System32\\where.exe").arg("multi-search.exe").env_clear().envs(&environment.variables).env("PATH", std::env::join_paths(&environment.user_path).unwrap()).current_dir(&environment.cwd).output().unwrap();
    assert!(fresh.status.success());
    assert!(
        String::from_utf8_lossy(&fresh.stdout).contains(detection.app.path.as_ref().unwrap()),
        "where stdout={:?} app_path={:?}",
        String::from_utf8_lossy(&fresh.stdout),
        detection.app.path
    );
    for (query, sources, expected) in [
        ("fixture", vec!["hackernews"], "success"),
        ("empty", vec!["hackernews"], "empty"),
        ("fixture", vec!["hackernews", "brave"], "partial"),
        ("failure", vec!["hackernews", "brave"], "failed"),
    ] {
        let id = manager
            .start_search(
                None,
                SearchOptions {
                    query: query.into(),
                    route: "dev".into(),
                    sources: sources.into_iter().map(str::to_string).collect(),
                    timeout: 5,
                },
            )
            .unwrap();
        let started = Instant::now();
        let state = loop {
            let state = manager.execution(id).unwrap();
            if state.status != "running" {
                break state;
            }
            assert!(started.elapsed() < Duration::from_secs(20));
            thread::sleep(Duration::from_millis(20));
        };
        assert_eq!(
            state.status,
            expected,
            "{}",
            serde_json::to_string_pretty(&state.payload).unwrap()
        );
        let payload = state.payload.unwrap();
        if expected == "success" || expected == "partial" {
            assert!(payload["results"][0]["source_id"]
                .as_str()
                .unwrap()
                .starts_with("src_"));
            assert!(payload["scrapes"][0]["markdown"]
                .as_str()
                .unwrap()
                .contains("Fixture article"));
        }
        if expected == "partial" || expected == "failed" {
            assert!(payload["errors"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["source"] == "brave"));
        }
    }
    let id = manager
        .start_search(
            None,
            SearchOptions {
                query: "hang".into(),
                route: "dev".into(),
                sources: vec!["hackernews".into()],
                timeout: 30,
            },
        )
        .unwrap();
    assert_eq!(manager.cancel_search(id).unwrap().status, "cancelled");
    manager.shutdown();
    let output = std::process::Command::new(detection.app.path.unwrap())
        .args(["search", "fixture", "--source", "hackernews"])
        .env_clear()
        .envs(environment.variables)
        .current_dir(environment.cwd)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap()["outcome"],
        "success"
    );
}
