mod common;
use multi_search_desktop::{DesktopManager, SearchOptions};
use std::{
    thread,
    time::{Duration, Instant},
};

#[test]
fn search_preserves_literal_arguments_and_reports_real_success() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    let request = SearchOptions {
        query: "words ; & literal".into(),
        route: "dev".into(),
        sources: vec!["hackernews".into()],
        timeout: 5,
    };
    let id = manager.start_search(request).unwrap();
    let started = Instant::now();
    let result = loop {
        let status = manager.execution(id).unwrap();
        if status.status != "running" {
            break status;
        }
        assert!(started.elapsed() < Duration::from_secs(5));
        thread::sleep(Duration::from_millis(10));
    };
    assert_eq!(result.status, "success");
    assert_eq!(result.exit_code, Some(0));
    assert_eq!(
        result.payload.unwrap()["results"][0]["title"],
        "words ; & literal"
    );
}

#[test]
fn partial_failure_is_visible_and_known_credentials_are_redacted() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("EXA_API_KEY".into(), "fixture-private-key".into());
    let manager = DesktopManager::new(profile.environment.clone());
    let id = manager
        .start_search(SearchOptions {
                query: "partial".into(),
                route: "default".into(),
                sources: vec![],
                timeout: 5,
            },
        )
        .unwrap();
    let started = Instant::now();
    let result = loop {
        let status = manager.execution(id).unwrap();
        if status.status != "running" {
            break status;
        }
        assert!(started.elapsed() < Duration::from_secs(5));
        thread::sleep(Duration::from_millis(10));
    };
    assert_eq!(result.status, "partial");
    let payload = serde_json::to_string(&result.payload).unwrap();
    assert!(payload.contains("unavailable"));
    assert!(!payload.contains("fixture-private-key"));
}

#[test]
fn zero_and_failed_searches_have_distinct_outcomes_and_failure_exit_code() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    for (query, expected, code) in [("empty", "empty", 0), ("failure", "failed", 1)] {
        let id = manager
            .start_search(SearchOptions {
                    query: query.into(),
                    route: "dev".into(),
                    sources: vec![],
                    timeout: 5,
                },
            )
            .unwrap();
        let started = Instant::now();
        let result = loop {
            let state = manager.execution(id).unwrap();
            if state.status != "running" {
                break state;
            }
            assert!(started.elapsed() < Duration::from_secs(5));
            thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(result.status, expected);
        assert_eq!(result.exit_code, Some(code));
        if code != 0 {
            assert!(result.error.contains("provider unavailable"));
        }
    }
}

#[test]
fn cancellation_stops_owned_descendants_but_not_unrelated_processes() {
    use std::process::{Command, Stdio};
    let mut profile = common::Profile::new();
    let child_pid = profile.root.join("child.pid");
    profile.environment.variables.insert(
        "FIXTURE_CHILD_PID".into(),
        child_pid.to_string_lossy().into_owned(),
    );
    let mut unrelated = Command::new(profile.root.join("multi-search.exe"))
        .arg("descendant")
        .stdout(Stdio::null())
        .spawn()
        .unwrap();
    let manager = DesktopManager::new(profile.environment.clone());
    let id = manager
        .start_search(SearchOptions {
                query: "hang".into(),
                route: "dev".into(),
                sources: vec![],
                timeout: 5,
            },
        )
        .unwrap();
    let started = Instant::now();
    while !child_pid.is_file() {
        assert!(started.elapsed() < Duration::from_secs(5));
        thread::sleep(Duration::from_millis(10));
    }
    let pid: u32 = std::fs::read_to_string(child_pid).unwrap().parse().unwrap();
    let cancelled = manager.cancel_search(id).unwrap();
    assert_eq!(cancelled.status, "cancelled");
    assert!(unrelated.try_wait().unwrap().is_none());
    assert!(!common::process_alive(pid));
    let again = manager.cancel_search(id).unwrap();
    assert_eq!(again.status, "cancelled");
    unrelated.kill().unwrap();
    unrelated.wait().unwrap();
}

#[test]
fn completion_cancellation_races_do_not_relabel_completed_runs_or_cancel_unknown_ids() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    for _ in 0..10 {
        let id = manager
            .start_search(SearchOptions {
                    query: "fixture".into(),
                    route: "dev".into(),
                    sources: vec![],
                    timeout: 5,
                },
            )
            .unwrap();
        assert!(manager.cancel_search(id + 1).is_err());
        let started = Instant::now();
        loop {
            let status = manager.execution(id).unwrap();
            if status.status != "running" {
                assert_eq!(manager.cancel_search(id).unwrap().status, status.status);
                break;
            }
            assert!(started.elapsed() < Duration::from_secs(5));
            thread::sleep(Duration::from_millis(10));
        }
    }
}

#[test]
fn concurrent_completion_and_cancel_publish_one_terminal_state() {
    let profile = common::Profile::new();
    let manager = std::sync::Arc::new(DesktopManager::new(profile.environment.clone()));
    for _ in 0..20 {
        let id = manager
            .start_search(SearchOptions {
                    query: "fixture".into(),
                    route: "dev".into(),
                    sources: vec![],
                    timeout: 5,
                },
            )
            .unwrap();
        let canceller = manager.clone();
        let thread = thread::spawn(move || canceller.cancel_search(id).unwrap());
        let terminal = thread.join().unwrap();
        assert!(["success", "cancelled"].contains(&terminal.status.as_str()));
        assert_eq!(manager.execution(id).unwrap().status, terminal.status);
    }
}

#[test]
fn shutdown_terminates_its_execution_without_disabling_the_standalone_cli() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    let id = manager
        .start_search(SearchOptions {
                query: "hang".into(),
                route: "dev".into(),
                sources: vec![],
                timeout: 5,
            },
        )
        .unwrap();
    manager.shutdown();
    assert_eq!(manager.execution(id).unwrap().status, "cancelled");
    assert!(manager
        .start_search(SearchOptions {
                query: "fixture".into(),
                route: "dev".into(),
                sources: vec![],
                timeout: 5
            }
        )
        .is_err());
    let output = std::process::Command::new(profile.root.join("multi-search.exe"))
        .arg("--version")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "multi-search 0.4.0"
    );
}


fn finished(manager: &DesktopManager, id: u64) -> multi_search_desktop::ExecutionStatus {
    let started = Instant::now();
    loop {
        let status = manager.execution(id).unwrap();
        if status.status != "running" {
            return status;
        }
        assert!(started.elapsed() < Duration::from_secs(10));
        thread::sleep(Duration::from_millis(20));
    }
}

fn child_env(manager: &DesktopManager, sources: &[&str], route: &str) -> Vec<String> {
    let id = manager
        .start_search(SearchOptions {
            query: "env".into(),
            route: route.into(),
            sources: sources.iter().map(|s| s.to_string()).collect(),
            timeout: 5,
        })
        .unwrap();
    let status = finished(manager, id);
    status.payload.unwrap()["env"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect()
}

#[test]
fn child_process_gets_a_minimal_environment_with_only_the_needed_credentials() {
    let mut profile = common::Profile::new();
    for (name, value) in [
        ("BRAVE_SEARCH_API_KEY", "synthetic-brave"),
        ("GITHUB_TOKEN", "synthetic-github"),
        ("SERPAPI_API_KEY", "synthetic-serpapi"),
        ("AWS_SECRET_ACCESS_KEY", "synthetic-unrelated"),
        ("UNRELATED_PASSWORD", "synthetic-unrelated"),
        ("SystemRoot", "C:\\Windows"),
    ] {
        profile.environment.variables.insert(name.into(), value.into());
    }
    let manager = DesktopManager::new(profile.environment.clone());
    let names = child_env(&manager, &["brave"], "default");
    assert!(names.iter().any(|n| n == "BRAVE_SEARCH_API_KEY"), "the selected source's key is passed: {names:?}");
    assert!(names.iter().any(|n| n.eq_ignore_ascii_case("SYSTEMROOT")), "OS plumbing is kept: {names:?}");
    assert!(names.iter().any(|n| n == "USERPROFILE"));
    for absent in ["GITHUB_TOKEN", "SERPAPI_API_KEY", "AWS_SECRET_ACCESS_KEY", "UNRELATED_PASSWORD"] {
        assert!(!names.iter().any(|n| n == absent), "{absent} must not reach the child: {names:?}");
    }
    let dev = child_env(&manager, &[], "dev");
    assert!(dev.iter().any(|n| n == "GITHUB_TOKEN"), "the dev route's GitHub source gets its token");
    assert!(!dev.iter().any(|n| n == "BRAVE_SEARCH_API_KEY"), "dev route never receives Brave's key");
    assert!(!dev.iter().any(|n| n == "AWS_SECRET_ACCESS_KEY"));
}
