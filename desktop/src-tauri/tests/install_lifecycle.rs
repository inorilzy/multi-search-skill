//! CLI update and uninstall lifecycle (ticket 08). Isolated: test boundary build only.
#![cfg(feature = "install-test-boundary")]
mod common;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use sha2::{Digest, Sha256};
use std::{fs, path::{Path, PathBuf}};

fn hex(path: &Path) -> (String, u64) {
    let bytes = fs::read(path).unwrap();
    let digest = Sha256::digest(&bytes);
    (digest.iter().map(|b| format!("{b:02x}")).collect(), bytes.len() as u64)
}

fn source(profile: &common::Profile, name: &str, version: &str) -> PathBuf {
    let dir = profile.root.join(name);
    fs::create_dir_all(dir.join("bin")).unwrap();
    let artifact = dir.join("bin").join("multi-search.exe");
    fs::copy(profile.root.join("multi-search.exe"), &artifact).unwrap();
    let (digest, size) = hex(&artifact);
    fs::write(
        dir.join("manifest.json"),
        format!(
            r#"{{"schema":1,"version":"{version}","files":[{{"path":"bin/multi-search.exe","size":{size},"sha256":"{digest}"}}]}}"#
        ),
    )
    .unwrap();
    dir
}

fn env(profile: &common::Profile, root: &Path, source: &Path) -> RuntimeEnvironment {
    let mut environment = profile.environment.clone();
    environment.variables.insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    environment.variables.insert("MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(), root.to_string_lossy().into_owned());
    environment.variables.insert("MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(), source.to_string_lossy().into_owned());
    let (anchor, _) = hex(&source.join("manifest.json"));
    environment.variables.insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), anchor);
    environment
}

#[test]
fn update_to_a_newer_verified_cli_replaces_the_active_install() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("update-ok");
    let v1 = source(&profile, "src-v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");

    let v2 = source(&profile, "src-v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    let plan = DesktopManager::new(env(&profile, &root, &v2)).install_plan();
    assert_eq!(plan.status, "update_available", "{}", plan.reason);
    let outcome = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(outcome.status, "installed", "{}", outcome.reason);
    assert_eq!(outcome.version.as_deref(), Some("0.5.0"));
    assert!(!root.join("backup-0.4.0").exists());
}

#[test]
fn failed_update_probe_restores_the_previous_working_cli() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("update-rollback");
    let v1 = source(&profile, "src-rb-v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let before = fs::read(root.join("bin").join("multi-search.exe")).unwrap();

    let v2 = source(&profile, "src-rb-v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "fail".into());
    let outcome = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(outcome.status, "failed", "{}", outcome.reason);
    assert_eq!(fs::read(root.join("bin").join("multi-search.exe")).unwrap(), before);
    assert!(root.join("active.json").is_file());
    let active: serde_json::Value = serde_json::from_str(&fs::read_to_string(root.join("active.json")).unwrap()).unwrap();
    assert_eq!(active["version"], "0.4.0");
}

#[test]
fn uninstall_removes_only_owned_cli_entries_and_keeps_user_data() {
    let profile = common::Profile::new();
    let root = profile.root.join("uninstall-owned");
    let v1 = source(&profile, "src-un", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    // User-owned data beside the CLI: config, credentials store and Skills must survive.
    fs::create_dir_all(root.join("config")).unwrap();
    fs::write(root.join("config").join("settings.json"), "{}").unwrap();
    let skills = profile.root.join(".claude").join("skills").join("multi-search");
    fs::create_dir_all(&skills).unwrap();
    fs::write(skills.join("SKILL.md"), "keep").unwrap();

    let outcome = DesktopManager::new(env(&profile, &root, &v1)).uninstall();
    assert_eq!(outcome.status, "uninstalled", "{}", outcome.reason);
    assert!(!root.join("bin").join("multi-search.exe").exists());
    assert!(!root.join("active.json").exists());
    assert!(root.join("config").join("settings.json").is_file());
    assert!(skills.join("SKILL.md").is_file());
}

#[test]
fn uninstall_refuses_a_foreign_installation() {
    let profile = common::Profile::new();
    let root = profile.root.join("uninstall-foreign");
    fs::create_dir_all(root.join("bin")).unwrap();
    fs::write(root.join("bin").join("multi-search.exe"), b"user copy").unwrap();
    let v1 = source(&profile, "src-foreign", "0.4.0");
    let outcome = DesktopManager::new(env(&profile, &root, &v1)).uninstall();
    assert_eq!(outcome.status, "not_installed");
    assert_eq!(fs::read(root.join("bin").join("multi-search.exe")).unwrap(), b"user copy");
}

#[test]
fn corrupt_managed_record_is_unverified_and_blocks_update_install_and_uninstall() {
    let profile = common::Profile::new();
    let root = profile.root.join("lifecycle-unverified");
    let v1 = source(&profile, "src-unv", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    // Owned marker stays, but the pointer no longer verifies: must not read as "not installed".
    fs::write(root.join("active.json"), "{not json").unwrap();
    let v2 = source(&profile, "src-unv-v2", "0.5.0");
    let manager = DesktopManager::new(env(&profile, &root, &v2));
    assert_eq!(manager.install_plan().status, "unverified");
    assert_eq!(manager.update().status, "unverified");
    assert_eq!(manager.install().status, "unverified");
    assert_eq!(manager.uninstall().status, "unverified");
    assert!(root.join("bin").join("multi-search.exe").is_file());
}
