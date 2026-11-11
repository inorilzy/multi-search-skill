//! Linux: the desktop has no supported user-PATH registration backend, so CLI discovery must
//! fall back to the process PATH and Skill installation must accept a verified managed CLI.
//!
//! The fallback and Skill-plan cases run on every platform because they only inject the
//! unsupported PATH store; the verified-managed-install case uses the production Unix layout.
mod common;

use multi_search_desktop::user_path::UnsupportedPathStore;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment, CLI_FILE_NAME};
use std::sync::Arc;

/// The production Linux build connects this store: registration is unsupported, so every
/// read reports why instead of returning a registered user PATH.
fn linux_manager(environment: RuntimeEnvironment) -> DesktopManager {
    DesktopManager::with_user_path_store(
        environment,
        Arc::new(UnsupportedPathStore("当前平台不支持用户 PATH 注册".into())),
    )
}

#[test]
fn unavailable_user_path_store_falls_back_to_the_process_path() {
    let profile = common::Profile::new();
    let mut environment = profile.environment.clone();
    environment.app_path.clear();
    let manager = linux_manager(environment);

    let status = manager.detect_cli();

    assert_eq!(status.user.status, "ready", "{}", status.user.reason);
    assert_eq!(
        status.user.path.as_deref(),
        Some(profile.root.join(CLI_FILE_NAME).to_str().unwrap())
    );
    assert_eq!(
        status.execution.status, "ready",
        "{}",
        status.execution.reason
    );
}

#[test]
fn process_path_cli_is_accepted_by_the_skill_install_plan() {
    let profile = common::Profile::new();
    let mut environment = profile.environment.clone();
    // Keep app discovery out of the picture so the Skill plan itself must find the user CLI.
    environment.app_path.clear();
    let manager = linux_manager(environment);

    let plan = manager.skill_plan("claude-code", "global", None);

    assert_eq!(plan.status, "ready", "{}", plan.reason);
    assert!(plan.can_install);
}

#[test]
fn unreadable_store_does_not_pretend_a_user_path_was_registered() {
    let profile = common::Profile::new();
    let mut environment = profile.environment.clone();
    environment.app_path.clear();
    let manager = linux_manager(environment);

    let status = manager.detect_cli();

    assert_eq!(status.user.status, "ready", "{}", status.user.reason);
    assert!(
        !status.user.reason.contains("已注册的用户 PATH"),
        "{}",
        status.user.reason
    );
}

#[cfg(not(windows))]
mod managed_cli {
    use super::*;
    use multi_search_desktop::user_path::{MemoryPathStore, PathValue};
    use sha2::{Digest, Sha256};
    use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};

    fn sha256(bytes: &[u8]) -> String {
        Sha256::digest(bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    /// Write a verified managed install in the production Unix layout. The real installer
    /// transaction is covered by `install_platform`; discovery only needs its recorded state.
    fn write_managed_cli(profile: &common::Profile, version: &str) -> PathBuf {
        #[cfg(target_os = "macos")]
        let root = profile
            .root
            .join("Library/Application Support/MultiSearch/cli");
        #[cfg(target_os = "linux")]
        let root = profile.root.join(".local/share/MultiSearch/cli");
        let bin = root.join("bin").join(CLI_FILE_NAME);
        fs::create_dir_all(bin.parent().unwrap()).unwrap();
        fs::copy(profile.root.join(CLI_FILE_NAME), &bin).unwrap();
        fs::set_permissions(&bin, fs::Permissions::from_mode(0o755)).unwrap();

        let artifact = fs::read(&bin).unwrap();
        let manifest = serde_json::to_vec(&serde_json::json!({
            "schema": 1,
            "version": version,
            "files": [{
                "path": format!("bin/{CLI_FILE_NAME}"),
                "size": artifact.len(),
                "sha256": sha256(&artifact),
            }],
        }))
        .unwrap();
        fs::write(root.join("manifest.json"), &manifest).unwrap();
        fs::write(
            root.join("active.json"),
            serde_json::to_vec(&serde_json::json!({
                "version": version,
                "manifest_sha256": sha256(&manifest),
            }))
            .unwrap(),
        )
        .unwrap();
        fs::write(
            root.join("multi-search-install.json"),
            serde_json::to_vec(&serde_json::json!({"owner": "multi-search-desktop", "schema": 1}))
                .unwrap(),
        )
        .unwrap();
        bin
    }

    #[test]
    fn verified_managed_cli_allows_skill_install_without_a_user_path() {
        let profile = common::Profile::new();
        let managed = write_managed_cli(&profile, "0.4.0");
        let mut environment = profile.environment.clone();
        environment.app_path.clear();
        environment.user_path.clear();
        let manager = linux_manager(environment);

        let status = manager.detect_cli();
        assert!(status.managed);
        assert_eq!(
            status.execution.path.as_deref(),
            Some(managed.to_str().unwrap())
        );

        let plan = manager.skill_plan("claude-code", "global", None);
        assert_eq!(plan.status, "ready", "{}", plan.reason);
        let installed = manager.skill_install("claude-code", "global", None);
        assert_eq!(installed.status, "installed", "{}", installed.reason);
        assert!(profile
            .root
            .join(".claude/skills/multi-search/SKILL.md")
            .is_file());
    }

    #[test]
    fn managed_cli_still_requires_a_user_path_when_registration_is_available() {
        let profile = common::Profile::new();
        write_managed_cli(&profile, "0.4.0");
        let mut environment = profile.environment.clone();
        environment.app_path.clear();
        environment.user_path.clear();
        let store = Arc::new(MemoryPathStore::new(PathValue::expandable("")));
        let manager = DesktopManager::with_user_path_store(environment, store);

        let plan = manager.skill_plan("claude-code", "global", None);

        assert_eq!(plan.status, "cli_missing", "{}", plan.reason);
    }
}
