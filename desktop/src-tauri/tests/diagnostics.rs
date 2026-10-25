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
    // The fixture emits FIXTURE_SECRET, but redaction learns the value from
    // EXA_API_KEY. The allowlist must keep EXA_API_KEY out of the child while
    // still letting the fixture emit the same string for scrubbing.
    profile.environment.variables.insert("EXA_API_KEY".into(), "synthetic-detection-secret".into());
    // The child echoes this value back; the parent knows it as EXA_API_KEY and must scrub it.
    profile.environment.variables.insert("FIXTURE_SECRET".into(), "synthetic-detection-secret".into());
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

#[test]
fn unmanaged_executable_outside_path_is_never_selected() {
    // Discovery takes no caller-supplied path (the UI cannot pick a program): a same-named CLI
    // that is neither on PATH nor the managed install is never probed or executed.
    let mut profile = common::Profile::new();
    let outside = profile.root.join("outside");
    std::fs::create_dir(&outside).unwrap();
    let name = multi_search_desktop::CLI_FILE_NAME;
    std::fs::copy(profile.root.join(name), outside.join(name)).unwrap();
    std::fs::remove_file(profile.root.join(name)).unwrap();
    profile.environment.app_path = vec![profile.root.clone()];
    profile.environment.user_path = vec![profile.root.clone()];
    let status = DesktopManager::new(profile.environment.clone()).detect_cli();
    assert_eq!(status.execution.status, "missing");
    assert!(!status.managed);
    let outside_text = outside.to_string_lossy().into_owned();
    for row in [&status.app, &status.user, &status.execution] {
        assert!(row.path.as_deref().is_none_or(|path| !path.starts_with(&outside_text)));
    }
}

// ---- macOS persistent PATH registration (shell-profile block) -------------

#[cfg(target_os = "macos")]
mod macos_path_integration {
    use multi_search_desktop::macos_path::MacOsPathStore;
    use multi_search_desktop::user_path::{PathStore, PathValue};
    use multi_search_desktop::user_path_fixture::receipt as make_receipt;
    use std::collections::BTreeMap;
    use std::path::PathBuf;
    use std::process::Command;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct Home(PathBuf);
    impl Home {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "macos-path-it-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir_all(&root).unwrap();
            Self(root)
        }
        fn env(&self, shell: &str) -> BTreeMap<String, String> {
            BTreeMap::from([
                ("HOME".into(), self.0.to_string_lossy().into_owned()),
                ("SHELL".into(), format!("/bin/{shell}")),
            ])
        }
    }
    impl Drop for Home {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    /// Write a fake `multi-search` executable into `dir` and return its path.
    fn fake_cli(dir: &PathBuf) -> PathBuf {
        std::fs::create_dir_all(dir).unwrap();
        let cli = dir.join("multi-search");
        std::fs::write(&cli, "#!/bin/sh\necho multi-search 9.9.9-test\n").unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&cli, std::fs::Permissions::from_mode(0o755)).unwrap();
        cli
    }

    /// Add via the store exactly as `UserPathManager::change` drives it.
    fn add(store: &MacOsPathStore, dir: &str) {
        let current = store.read().unwrap();
        let desired = PathValue { text: dir.to_string(), kind: 0, exists: true };
        let receipt = make_receipt(&current, &desired, dir);
        store.compare_write(&current, &desired, Some(&receipt)).unwrap();
    }
    fn remove(store: &MacOsPathStore) {
        let current = store.read().unwrap();
        let before = store.receipt().unwrap().unwrap().before().clone();
        store.compare_write(&current, &before, None).unwrap();
    }

    /// `command -v multi-search` inside a real login shell with the isolated
    /// HOME. Returns the resolved path or empty string.
    fn command_v(home: &Home, shell: &str) -> String {
        let bin = format!("/bin/{shell}");
        // -l makes it a login shell so it sources the profile we wrote.
        let output = Command::new(bin)
            .args(["-l", "-c", "command -v multi-search || true"])
            .env_clear()
            .envs(home.env(shell))
            .env("PATH", "/usr/bin:/bin") // minimal base, no inherited PATH
            .output()
            .unwrap();
        String::from_utf8_lossy(&output.stdout).trim().to_string()
    }

    #[test]
    fn zsh_command_v_finds_managed_cli_after_add_and_not_after_remove() {
        let home = Home::new();
        let store = MacOsPathStore::for_environment(&home.env("zsh")).unwrap();
        let dir = home.0.join("Library/Application Support/MultiSearch/cli/bin");
        let cli = fake_cli(&dir);
        // Before registration the shell must not resolve our fake CLI.
        assert_eq!(command_v(&home, "zsh"), "");
        add(&store, &dir.to_string_lossy());
        assert_eq!(command_v(&home, "zsh"), cli.to_string_lossy());
        remove(&store);
        assert_eq!(command_v(&home, "zsh"), "");
    }

    #[test]
    fn bash_command_v_finds_managed_cli_after_add_and_not_after_remove() {
        let home = Home::new();
        let store = MacOsPathStore::for_environment(&home.env("bash")).unwrap();
        let dir = home.0.join("Library/Application Support/MultiSearch/cli/bin");
        let cli = fake_cli(&dir);
        assert_eq!(command_v(&home, "bash"), "");
        add(&store, &dir.to_string_lossy());
        assert_eq!(command_v(&home, "bash"), cli.to_string_lossy());
        remove(&store);
        assert_eq!(command_v(&home, "bash"), "");
    }

    #[test]
    fn registration_is_limited_to_the_marked_block_and_survives_restart() {
        let home = Home::new();
        let profile = home.0.join(".zprofile");
        std::fs::write(&profile, "# user content\nexport EDITOR=vim\n").unwrap();
        let store = MacOsPathStore::for_environment(&home.env("zsh")).unwrap();
        add(&store, "/opt/managed/bin");
        // Fresh store instance (new app run) sees the same registration.
        let reopened = MacOsPathStore::for_environment(&home.env("zsh")).unwrap();
        assert_eq!(reopened.read().unwrap().text, "/opt/managed/bin");
        remove(&reopened);
        assert_eq!(
            std::fs::read_to_string(&profile).unwrap(),
            "# user content\nexport EDITOR=vim\n"
        );
    }

    #[test]
    fn home_with_spaces_and_dollar_signs_resolves_in_shell() {
        // A home whose path needs quoting still produces a working profile.
        let base = std::env::temp_dir().join(format!(
            "macos-path-it space $HOME-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&base).unwrap();
        let home = Home(base);
        let store = MacOsPathStore::for_environment(&home.env("zsh")).unwrap();
        let dir = home.0.join("Library/Application Support/MultiSearch/cli/bin");
        let cli = fake_cli(&dir);
        add(&store, &dir.to_string_lossy());
        assert_eq!(command_v(&home, "zsh"), cli.to_string_lossy());
        remove(&store);
    }
}
