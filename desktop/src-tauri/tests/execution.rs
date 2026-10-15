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
    let id = manager.start_search(None, request).unwrap();
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
fn custom_route_is_validated_from_current_config_and_explicit_timeout_still_wins() {
    let mut profile = common::Profile::new();
    let config = profile.root.join("route-config.json");
    let args_path = profile.root.join("args.json");
    std::fs::write(
        &config,
        r#"{"type":"-focus","timeout":40,"routes":{"-focus":{"label":"Focus","sources":["hackernews"],"timeout":2}}}"#,
    )
    .unwrap();
    profile.environment.variables.insert(
        "MULTI_SEARCH_CONFIG".into(),
        config.to_string_lossy().into_owned(),
    );
    profile.environment.variables.insert(
        "FIXTURE_ARGS_PATH".into(),
        args_path.to_string_lossy().into_owned(),
    );
    let manager = DesktopManager::new(profile.environment.clone());
    let id = manager
        .start_search(
            None,
            SearchOptions {
                query: "custom route".into(),
                route: "-focus".into(),
                sources: vec!["hackernews".into()],
                timeout: 5,
            },
        )
        .unwrap();
    let started = Instant::now();
    while manager.execution(id).unwrap().status == "running" {
        assert!(started.elapsed() < Duration::from_secs(5));
        thread::sleep(Duration::from_millis(10));
    }
    let args: Vec<String> =
        serde_json::from_str(&std::fs::read_to_string(args_path).unwrap()).unwrap();
    assert!(
        args.iter().any(|arg| arg == "--route=-focus"),
        "a legal leading-dash id must stay the value of --route"
    );
    assert_eq!(
        args[args.iter().position(|arg| arg == "--timeout").unwrap() + 1],
        "5",
        "the explicit execution timeout overrides the route preview"
    );

    assert!(
        manager
            .start_search(
                None,
                SearchOptions {
                    query: "removed builtin".into(),
                    route: "dev".into(),
                    sources: vec![],
                    timeout: 5
                },
            )
            .is_err(),
        "an explicitly deleted built-in is no longer accepted"
    );
}

#[test]
fn non_default_legacy_route_timeout_can_be_tested_but_arbitrary_values_above_sixty_are_rejected() {
    let mut profile = common::Profile::new();
    let config = profile.root.join("legacy-all-config.json");
    std::fs::write(&config, r#"{"type":"fast"}"#).unwrap();
    profile.environment.variables.insert(
        "MULTI_SEARCH_CONFIG".into(),
        config.to_string_lossy().into_owned(),
    );
    let manager = DesktopManager::new(profile.environment.clone());
    let id = manager
        .start_search(
            None,
            SearchOptions {
                query: "legacy all".into(),
                route: "all".into(),
                sources: vec!["hackernews".into()],
                timeout: 90,
            },
        )
        .unwrap();
    let started = Instant::now();
    while manager.execution(id).unwrap().status == "running" {
        assert!(started.elapsed() < Duration::from_secs(5));
        thread::sleep(Duration::from_millis(10));
    }
    assert!(manager
        .start_search(
            None,
            SearchOptions {
                query: "bad timeout".into(),
                route: "all".into(),
                sources: vec![],
                timeout: 89,
            },
        )
        .is_err());
}

#[test]
fn unreadable_route_config_blocks_execution_instead_of_falling_back_to_builtins() {
    let mut profile = common::Profile::new();
    let config = profile.root.join("bad-route-config.json");
    std::fs::write(&config, r#"{"type":"missing","routes":{}}"#).unwrap();
    profile.environment.variables.insert(
        "MULTI_SEARCH_CONFIG".into(),
        config.to_string_lossy().into_owned(),
    );
    let manager = DesktopManager::new(profile.environment.clone());
    assert!(manager
        .start_search(
            None,
            SearchOptions {
                query: "must not run".into(),
                route: "default".into(),
                sources: vec![],
                timeout: 5
            },
        )
        .is_err());
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
        .start_search(
            None,
            SearchOptions {
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
            .start_search(
                None,
                SearchOptions {
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
        .start_search(
            None,
            SearchOptions {
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
            .start_search(
                None,
                SearchOptions {
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
            .start_search(
                None,
                SearchOptions {
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
        .start_search(
            None,
            SearchOptions {
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
        .start_search(
            None,
            SearchOptions {
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
