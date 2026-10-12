mod common;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use sha2::{Digest, Sha256};
use std::{fs, path::{Path, PathBuf}};

fn hex(path: &Path) -> (String, u64) {
    let bytes = fs::read(path).unwrap();
    let digest = Sha256::digest(&bytes);
    (digest.iter().map(|b| format!("{b:02x}")).collect(), bytes.len() as u64)
}

/// Writes a source directory: the fixture CLI plus a manifest matching it.
fn source(profile: &common::Profile, name: &str, version: &str, sha: Option<&str>) -> PathBuf {
    let dir = profile.root.join(name);
    fs::create_dir_all(&dir).unwrap();
    let artifact = dir.join("multi-search.exe");
    fs::copy(profile.root.join("multi-search.exe"), &artifact).unwrap();
    let (digest, size) = hex(&artifact);
    let digest = sha.map(str::to_string).unwrap_or(digest);
    fs::write(
        dir.join("manifest.json"),
        format!(r#"{{"version":"{version}","sha256":"{digest}","size":{size}}}"#),
    )
    .unwrap();
    dir
}

fn env(profile: &common::Profile, root: &Path, source: Option<&Path>) -> RuntimeEnvironment {
    let mut environment = profile.environment.clone();
    environment.variables.insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    environment.variables.insert(
        "MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(),
        root.to_string_lossy().into_owned(),
    );
    if let Some(source) = source {
        environment.variables.insert(
            "MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(),
            source.to_string_lossy().into_owned(),
        );
    }
    environment
}

#[test]
fn production_without_controlled_source_changes_nothing() {
    let profile = common::Profile::new();
    let localappdata = profile.root.join("localappdata");
    let mut environment = profile.environment.clone();
    environment
        .variables
        .insert("LOCALAPPDATA".into(), localappdata.to_string_lossy().into_owned());
    let manager = DesktopManager::new(environment);
    let plan = manager.install_plan();
    assert_eq!(plan.status, "unconfigured");
    let outcome = manager.install();
    assert_eq!(outcome.status, "unconfigured");
    assert!(outcome.steps.is_empty());
    assert!(!localappdata.exists());
}

#[test]
fn isolated_first_install_verifies_activates_and_is_idempotent() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-a");
    let src = source(&profile, "src-ok", "0.4.0", None);
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "ready");

    let outcome = manager.install();
    assert_eq!(outcome.status, "installed", "{}", outcome.reason);
    assert_eq!(outcome.version.as_deref(), Some("0.4.0"));
    let bin = root.join("bin").join("multi-search.exe");
    assert!(bin.is_file());
    assert!(outcome.path_hint.contains("PATH"));
    assert!(outcome.steps.iter().all(|s| s.ok));
    assert!(!fs::read_dir(&root).unwrap().any(|e| e.unwrap().file_name().to_string_lossy().starts_with("staging-")));

    assert_eq!(manager.install_plan().status, "installed");
    let again = manager.install();
    assert_eq!(again.status, "already_installed", "{}", again.reason);
    assert!(again.reason.contains("0.4.0"));
    assert!(bin.is_file());
}

#[test]
fn checksum_mismatch_refuses_before_touching_the_install_root() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-bad");
    let src = source(&profile, "src-bad", "0.4.0", Some(&"0".repeat(64)));
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    let outcome = manager.install();
    assert_eq!(outcome.status, "integrity_failed");
    assert!(outcome.bin.is_none());
    assert!(!root.exists());
}

#[test]
fn missing_manifest_is_a_prerequisite_failure() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-missing");
    let src = profile.root.join("src-no-manifest");
    fs::create_dir_all(&src).unwrap();
    fs::copy(profile.root.join("multi-search.exe"), src.join("multi-search.exe")).unwrap();
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "prerequisite_missing");
    assert_eq!(manager.install().status, "prerequisite_missing");
    assert!(!root.exists());
}

#[test]
fn unknown_existing_installation_is_never_overwritten() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-unknown");
    fs::create_dir_all(root.join("bin")).unwrap();
    let foreign = root.join("bin").join("multi-search.exe");
    fs::write(&foreign, b"user managed copy").unwrap();
    let src = source(&profile, "src-unknown", "0.4.0", None);
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "unknown_existing");
    let outcome = manager.install();
    assert_eq!(outcome.status, "unknown_existing");
    assert_eq!(fs::read(&foreign).unwrap(), b"user managed copy");
    assert!(!root.join("active.json").exists());
    assert!(!root.join("multi-search-install.json").exists());
}

#[test]
fn version_probe_failure_keeps_no_active_install_and_retry_succeeds() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("install-retry");
    let src = source(&profile, "src-retry", "0.4.0", None);

    profile.environment.variables.insert("FIXTURE_VERSION".into(), "fail".into());
    let failing = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(failing.status, "failed");
    assert!(failing.bin.is_none());
    assert!(!root.join("bin").join("multi-search.exe").exists());
    assert!(!root.join("active.json").exists());
    assert_eq!(DesktopManager::new(env(&profile, &root, Some(&src))).install_plan().status, "ready");

    profile.environment.variables.remove("FIXTURE_VERSION");
    let retried = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(retried.status, "installed", "{}", retried.reason);
    assert!(root.join("active.json").is_file());
}

#[test]
fn manifest_version_must_match_the_probed_cli() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-version");
    let src = source(&profile, "src-version", "0.5.0", None);
    let outcome = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(outcome.status, "failed");
    assert!(!root.join("active.json").exists());
    assert!(!root.join("bin").join("multi-search.exe").exists());
}
