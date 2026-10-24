mod common;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use std::{collections::BTreeMap, path::PathBuf};

#[test]
fn absent_cli_reports_both_discovery_boundaries_without_touching_user_profile() {
    let environment = RuntimeEnvironment {
        app_path: vec![],
        user_path: vec![],
        variables: BTreeMap::new(),
        cwd: PathBuf::from(env!("CARGO_MANIFEST_DIR")),
    };
    let manager = DesktopManager::new(environment);
    let status = manager.detect_cli();
    assert_eq!(status.app.status, "missing");
    assert_eq!(status.user.status, "missing");
    assert!(status.app.path.is_none());
    assert!(status.app.reason.contains(multi_search_desktop::CLI_FILE_NAME));
    assert!(!status.restart_required);
}

#[test]
fn detected_cli_has_actual_path_and_version_but_does_not_imply_user_discovery() {
    let mut profile = common::Profile::new();
    profile.environment.user_path.clear();
    let manager = DesktopManager::new(profile.environment.clone());
    let status = manager.detect_cli();
    assert_eq!(status.app.status, "ready");
    assert_eq!(status.app.version.as_deref(), Some("0.4.0"));
    assert!(status.app.path.unwrap().ends_with(multi_search_desktop::CLI_FILE_NAME));
    assert_eq!(status.user.status, "missing");
}

#[test]
fn user_discovery_without_app_discovery_requires_a_host_restart() {
    let mut profile = common::Profile::new();
    profile.environment.app_path.clear();
    let manager = DesktopManager::new(profile.environment.clone());
    let status = manager.detect_cli();
    assert_eq!(status.app.status, "missing");
    assert_eq!(status.user.status, "ready");
    assert!(status.restart_required);
}

#[test]
fn invalid_executable_and_failed_version_have_distinct_reasons() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_VERSION".into(), "fail".into());
    let status = DesktopManager::new(profile.environment.clone()).detect_cli();
    assert_eq!(status.app.status, "version_failed");
    let exe = profile.root.join(multi_search_desktop::CLI_FILE_NAME);
    std::fs::write(&exe, "not an executable").unwrap();
    // Windows refuses to launch a non-PE file. On Unix the copied fixture keeps its execute bit and
    // a text file with +x falls back to the shell (exit 127 = "version failed"), so drop the bit to
    // model the same "cannot launch at all" case the app must distinguish.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&exe, std::fs::Permissions::from_mode(0o644)).unwrap();
    }
    let status = DesktopManager::new(profile.environment.clone()).detect_cli();
    assert_eq!(status.app.status, "not_executable");
}

#[test]
fn legacy_cli_reports_version_failure_with_exit_code_and_update_guidance() {
    let mut profile = common::Profile::new();
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "legacy".into());
    let status = DesktopManager::new(profile.environment.clone()).detect_cli();
    for row in [&status.app, &status.user] {
        assert_eq!(row.status, "version_failed");
        assert!(row.reason.contains("退出码 2"), "{}", row.reason);
        assert!(row.reason.contains("command"), "{}", row.reason);
        assert!(row.reason.contains("更新"), "{}", row.reason);
    }
}

#[test]
fn failed_version_output_is_redacted_before_returning_to_callers() {
    let mut profile = common::Profile::new();
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "secret".into());
    profile.environment.variables.insert("EXA_API_KEY".into(), "synthetic-detection-secret".into());
    // The child echoes this value back; the parent knows it as EXA_API_KEY and must scrub it.
    profile.environment.variables.insert("FIXTURE_SECRET_ECHO".into(), "synthetic-detection-secret".into());
    let status = DesktopManager::new(profile.environment.clone()).detect_cli();
    assert!(!status.app.reason.contains("synthetic-detection-secret"));
    assert!(status.app.reason.contains("REDACTED"), "{}", status.app.reason);
    // The version probe gets the minimal environment: provider keys are never handed to it.
    assert!(status.app.reason.contains("exa_key_present=false"), "{}", status.app.reason);
}

#[test]
fn version_timeout_is_bounded() {
    let mut profile = common::Profile::new();
    profile.environment.user_path.clear();
    profile
        .environment
        .variables
        .insert("FIXTURE_VERSION".into(), "hang".into());
    let started = std::time::Instant::now();
    let status = DesktopManager::new(profile.environment.clone()).detect_cli();
    assert_eq!(status.app.status, "version_failed");
    assert!(started.elapsed() < std::time::Duration::from_secs(5));
}
