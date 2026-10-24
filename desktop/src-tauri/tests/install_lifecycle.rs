//! CLI update and uninstall lifecycle (ticket 08). Isolated: test boundary build only.
#![cfg(all(windows, feature = "install-test-boundary"))]
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

fn runtime_source(profile: &common::Profile, name: &str, version: &str) -> PathBuf {
    let dir = source(profile, name, version);
    fs::create_dir_all(dir.join("runtime")).unwrap();
    fs::write(dir.join("runtime/data.txt"), version).unwrap();
    let (digest, size) = hex(&dir.join("runtime/data.txt"));
    let mut manifest: serde_json::Value = serde_json::from_slice(&fs::read(dir.join("manifest.json")).unwrap()).unwrap();
    manifest["files"].as_array_mut().unwrap().insert(0, serde_json::json!({"path":"runtime/data.txt", "size":size, "sha256":digest}));
    fs::write(dir.join("manifest.json"), serde_json::to_vec(&manifest).unwrap()).unwrap();
    dir
}

fn snapshot(root: &Path) -> Vec<Vec<u8>> {
    ["manifest.json", "active.json", "bin/multi-search.exe", "runtime/data.txt"]
        .iter().map(|p| fs::read(root.join(p)).unwrap()).collect()
}

#[cfg(windows)]
#[test]
fn update_backup_locks_restore_every_old_file_and_active_record() {
    use std::{fs::OpenOptions, os::windows::fs::OpenOptionsExt};
    for locked in ["bin/multi-search.exe", "runtime/data.txt"] {
        let mut profile = common::Profile::new();
        let root = profile.root.join("managed");
        let v1 = runtime_source(&profile, "v1", "0.4.0");
        let old = DesktopManager::new(env(&profile, &root, &v1));
        assert_eq!(old.install().status, "installed");
        let before = snapshot(&root);
        let v2 = runtime_source(&profile, "v2", "0.5.0");
        profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
        let holder = OpenOptions::new().read(true).share_mode(1).open(root.join(locked)).unwrap();
        let next = DesktopManager::new(env(&profile, &root, &v2));
        let outcome = next.update();
        assert_eq!(outcome.status, "failed", "{}", outcome.reason);
        assert_eq!(snapshot(&root), before);
        assert_eq!(old.install_plan().status, "installed");
        drop(holder);
        assert_eq!(next.update().status, "installed");
        assert_eq!(next.uninstall().status, "uninstalled");
    }
}

#[test]
fn activated_probe_failure_restores_exact_old_lifecycle() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("managed");
    let v1 = runtime_source(&profile, "v1", "0.4.0");
    let old = DesktopManager::new(env(&profile, &root, &v1));
    assert_eq!(old.install().status, "installed");
    let before = snapshot(&root);
    let v2 = runtime_source(&profile, "v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    profile.environment.variables.insert("FIXTURE_FAIL_ACTIVE_ROOT".into(), root.to_string_lossy().into_owned());
    let outcome = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(outcome.status, "failed", "{}", outcome.reason);
    assert_eq!(snapshot(&root), before);
    assert_eq!(old.install_plan().status, "installed");
    profile.environment.variables.remove("FIXTURE_FAIL_ACTIVE_ROOT");
    let next = DesktopManager::new(env(&profile, &root, &v2));
    assert_eq!(next.update().status, "installed");
    assert_eq!(next.uninstall().status, "uninstalled");
}

#[test]
fn failed_restore_keeps_recovery_record_and_reports_its_location() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("managed");
    let v1 = runtime_source(&profile, "v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let active = fs::read(root.join("active.json")).unwrap();
    let v2 = runtime_source(&profile, "v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    profile.environment.variables.insert("FIXTURE_FAIL_ACTIVE_ROOT".into(), root.to_string_lossy().into_owned());
    profile.environment.variables.insert("FIXTURE_BLOCK_RESTORE".into(), "1".into());
    let manager = DesktopManager::new(env(&profile, &root, &v2));
    let out = manager.update();
    assert_eq!(out.status, "failed");
    assert!(out.reason.contains("回滚未完成"), "{}", out.reason);
    let recovery = fs::read_dir(&root).unwrap().map(|e| e.unwrap().path())
        .find(|p| p.file_name().unwrap().to_string_lossy().starts_with("backup-")).unwrap();
    assert!(out.reason.contains(recovery.to_string_lossy().as_ref()));
    assert_eq!(fs::read(recovery.join("active.json")).unwrap(), active);
    assert_eq!(fs::read_to_string(root.join("active.json/concurrent-user-file")).unwrap(), "preserve");
    assert_eq!(manager.install_plan().status, "unverified");
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
fn update_and_uninstall_preserve_unknown_nested_files_and_remove_only_old_owned_files() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("managed");
    let v1 = runtime_source(&profile, "v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    fs::create_dir_all(root.join("runtime/user")).unwrap();
    fs::write(root.join("runtime/user/notes.txt"), "keep runtime").unwrap();
    fs::write(root.join("bin/user-notes.txt"), "keep bin").unwrap();
    // Version two drops runtime/data.txt; it must not infer ownership of runtime/user.
    let v2 = source(&profile, "v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    let next = DesktopManager::new(env(&profile, &root, &v2));
    assert_eq!(next.update().status, "installed");
    assert_eq!(fs::read_to_string(root.join("bin/user-notes.txt")).unwrap(), "keep bin");
    assert_eq!(fs::read_to_string(root.join("runtime/user/notes.txt")).unwrap(), "keep runtime");
    assert!(!root.join("runtime/data.txt").exists());
    assert_eq!(next.uninstall().status, "uninstalled");
    assert_eq!(fs::read_to_string(root.join("bin/user-notes.txt")).unwrap(), "keep bin");
    assert_eq!(fs::read_to_string(root.join("runtime/user/notes.txt")).unwrap(), "keep runtime");
}

#[cfg(windows)]
#[test]
fn update_refuses_linked_destination_without_touching_external_content() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("managed");
    let v1 = source(&profile, "v1", "0.4.0");
    let old = DesktopManager::new(env(&profile, &root, &v1));
    assert_eq!(old.install().status, "installed");
    let external = profile.root.join("external");
    fs::create_dir(&external).unwrap();
    fs::write(external.join("data.txt"), "outside").unwrap();
    let result = std::process::Command::new("cmd").args(["/C", "mklink", "/J"])
        .arg(root.join("runtime")).arg(&external).output().unwrap();
    assert!(result.status.success());
    let v2 = runtime_source(&profile, "v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    let out = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(out.status, "unknown_existing", "{}", out.reason);
    assert_eq!(fs::read_to_string(external.join("data.txt")).unwrap(), "outside");
    assert_eq!(old.install_plan().status, "installed");
    fs::remove_dir(root.join("runtime")).unwrap();
}

#[test]
fn update_refuses_new_owned_path_that_collides_with_unknown_file() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("managed");
    let v1 = source(&profile, "v1", "0.4.0");
    let old = DesktopManager::new(env(&profile, &root, &v1));
    assert_eq!(old.install().status, "installed");
    fs::create_dir_all(root.join("runtime")).unwrap();
    fs::write(root.join("runtime/data.txt"), "user content").unwrap();
    let v2 = runtime_source(&profile, "v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    let outcome = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(outcome.status, "unknown_existing", "{}", outcome.reason);
    assert_eq!(fs::read_to_string(root.join("runtime/data.txt")).unwrap(), "user content");
    assert_eq!(old.install_plan().status, "installed");
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

#[test]
fn update_plan_shows_current_and_target_versions_and_the_source() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("plan-versions");
    let v1 = source(&profile, "src-pv-v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let v2 = source(&profile, "src-pv-v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    let plan = DesktopManager::new(env(&profile, &root, &v2)).install_plan();
    assert_eq!(plan.status, "update_available", "{}", plan.reason);
    assert_eq!(plan.current_version.as_deref(), Some("0.4.0"));
    assert_eq!(plan.version.as_deref(), Some("0.5.0"));
    assert_eq!(plan.source.as_deref(), Some(v2.to_string_lossy().as_ref()));
}

#[test]
fn update_refuses_an_unknown_install_and_never_touches_it() {
    let profile = common::Profile::new();
    let root = profile.root.join("update-unknown");
    fs::create_dir_all(root.join("bin")).unwrap();
    fs::write(root.join("bin").join("multi-search.exe"), b"user copy").unwrap();
    let v2 = source(&profile, "src-uu-v2", "0.5.0");
    let outcome = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(outcome.status, "not_installed", "{}", outcome.reason);
    assert_eq!(fs::read(root.join("bin").join("multi-search.exe")).unwrap(), b"user copy");
    assert!(!root.join("active.json").exists());
}

#[test]
fn update_to_a_cli_that_lacks_the_skill_flags_is_refused_and_keeps_the_previous_cli() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("update-compat");
    let v1 = source(&profile, "src-compat-v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let before = fs::read(root.join("bin").join("multi-search.exe")).unwrap();
    let v2 = source(&profile, "src-compat-v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    profile.environment.variables.insert("FIXTURE_HELP".into(), "stale".into());
    let outcome = DesktopManager::new(env(&profile, &root, &v2)).update();
    assert_eq!(outcome.status, "failed", "{}", outcome.reason);
    assert!(outcome.reason.contains("--expand"), "{}", outcome.reason);
    assert_eq!(fs::read(root.join("bin").join("multi-search.exe")).unwrap(), before);
    let active: serde_json::Value = serde_json::from_str(&fs::read_to_string(root.join("active.json")).unwrap()).unwrap();
    assert_eq!(active["version"], "0.4.0");
}

#[test]
fn uninstall_reports_a_kept_skill_whose_cli_dependency_is_now_missing() {
    let profile = common::Profile::new();
    let root = profile.root.join("uninstall-skill-kept");
    let v1 = source(&profile, "src-usk", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let skills = profile.root.join(".claude").join("skills").join("multi-search");
    fs::create_dir_all(&skills).unwrap();
    fs::write(skills.join(".multi-search-install.json"), "{}").unwrap();
    let outcome = DesktopManager::new(env(&profile, &root, &v1)).uninstall();
    assert_eq!(outcome.status, "uninstalled", "{}", outcome.reason);
    assert!(
        outcome.steps.iter().any(|s| !s.ok && s.name.contains("Skill") && s.detail.contains("CLI")),
        "kept Skill must be reported with its missing CLI dependency"
    );
    assert!(skills.join(".multi-search-install.json").is_file());
}

#[cfg(windows)]
#[test]
fn uninstall_of_an_in_use_file_reports_a_clear_lock_error_and_keeps_the_install_unchanged() {
    use std::{fs::OpenOptions, os::windows::fs::OpenOptionsExt};
    let profile = common::Profile::new();
    let root = profile.root.join("uninstall-locked");
    let v1 = source(&profile, "src-lock", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let before = fs::read(root.join("bin").join("multi-search.exe")).unwrap();
    // Lock the owned executable: unrelated user files are no longer moved or deleted.
    let in_use = root.join("bin").join("multi-search.exe");
    // Share READ only (no FILE_SHARE_DELETE), like a running program holding its executable: deletion is refused.
    const FILE_SHARE_READ: u32 = 0x1;
    let _holder = OpenOptions::new().read(true).share_mode(FILE_SHARE_READ).open(&in_use).unwrap();

    let outcome = DesktopManager::new(env(&profile, &root, &v1)).uninstall();
    assert_eq!(outcome.status, "failed", "{}", outcome.reason);
    assert!(outcome.reason.contains("未强制终止进程"), "{}", outcome.reason);
    assert_eq!(fs::read(root.join("bin").join("multi-search.exe")).unwrap(), before);
    assert!(root.join("active.json").is_file());
    assert!(in_use.is_file());
    assert!(root.join("manifest.json").is_file());
    let entries: Vec<String> = fs::read_dir(&root).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
    assert!(!entries.iter().any(|n| n.starts_with("removing-")), "{entries:?}");
    let active: serde_json::Value = serde_json::from_str(&fs::read_to_string(root.join("active.json")).unwrap()).unwrap();
    assert_eq!(active["version"], "0.4.0");
    // Still recognised and still able to verify: the lock refusal changed nothing durable.
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install_plan().status, "installed");
}

#[test]
fn corrupt_or_unknown_managed_skill_blocks_update_and_preview() {
    for marker in ["{invalid", r#"{"managed_by":"multi-search-desktop","skill":"multi-search","skill_version":"unknown"}"#] {
        let mut profile = common::Profile::new();
        let root = profile.root.join("managed");
        let v1 = runtime_source(&profile, "v1", "0.4.0");
        assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
        let before = snapshot(&root);
        let skill = profile.root.join(".claude/skills/multi-search");
        fs::create_dir_all(&skill).unwrap();
        fs::write(skill.join(".multi-search-install.json"), marker).unwrap();
        let v2 = runtime_source(&profile, "v2", "0.5.0");
        profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
        let next = DesktopManager::new(env(&profile, &root, &v2));
        assert_eq!(next.install_plan().compatibility, "unverified");
        assert_eq!(next.update().status, "unverified");
        assert_eq!(snapshot(&root), before);
    }
}

#[test]
fn registered_project_skill_and_legacy_v1_requirements_are_checked_before_cli_update() {
    let mut profile = common::Profile::new();
    let project = profile.root.join("project");
    fs::create_dir(&project).unwrap();
    let skill_manager = DesktopManager::new(profile.environment.clone());
    assert_eq!(skill_manager.skill_install("project", Some(project.clone())).status, "installed");
    let marker_path = project.join(".claude/skills/multi-search/.multi-search-install.json");
    let mut marker: serde_json::Value = serde_json::from_slice(&fs::read(&marker_path).unwrap()).unwrap();
    assert_eq!(marker["requirements"]["doctor"], serde_json::json!(["--no-keys", "--format"]));
    let root = profile.root.join("managed");
    let v1 = runtime_source(&profile, "v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let before = snapshot(&root);
    let v2 = runtime_source(&profile, "v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());
    marker["requirements"]["search"].as_array_mut().unwrap().push(serde_json::json!("--project-required"));
    fs::write(&marker_path, serde_json::to_vec(&marker).unwrap()).unwrap();
    let next = DesktopManager::new(env(&profile, &root, &v2));
    assert!(next.install_plan().compatibility_reason.contains("--project-required"));
    assert_eq!(next.update().status, "failed");
    assert_eq!(snapshot(&root), before);
    marker.as_object_mut().unwrap().remove("requirements");
    fs::write(&marker_path, serde_json::to_vec(&marker).unwrap()).unwrap();
    assert_eq!(next.install_plan().compatibility, "compatible");
    assert_eq!(next.update().status, "installed");
    assert_eq!(skill_manager.skill_remove("project", Some(project), true).status, "removed");
    assert_eq!(fs::read_to_string(profile.root.join(".multi-search/managed-skills.json")).unwrap(), "[]");
}

#[test]
fn update_plan_previews_skill_compatibility_before_any_change() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("plan-compat");
    let v1 = source(&profile, "src-pc-v1", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    let before = fs::read(root.join("bin").join("multi-search.exe")).unwrap();
    let v2 = source(&profile, "src-pc-v2", "0.5.0");
    profile.environment.variables.insert("FIXTURE_VERSION".into(), "0.5.0".into());

    let ok = DesktopManager::new(env(&profile, &root, &v2)).install_plan();
    assert_eq!(ok.status, "update_available", "{}", ok.reason);
    assert_eq!(ok.compatibility, "compatible", "{}", ok.compatibility_reason);

    profile.environment.variables.insert("FIXTURE_HELP".into(), "stale".into());
    let stale = DesktopManager::new(env(&profile, &root, &v2)).install_plan();
    assert_eq!(stale.status, "update_available", "{}", stale.reason);
    assert_eq!(stale.compatibility, "incompatible");
    assert!(stale.compatibility_reason.contains("--expand"), "{}", stale.compatibility_reason);

    // Previewing never activates or changes the installed CLI.
    assert_eq!(fs::read(root.join("bin").join("multi-search.exe")).unwrap(), before);
    let active: serde_json::Value = serde_json::from_str(&fs::read_to_string(root.join("active.json")).unwrap()).unwrap();
    assert_eq!(active["version"], "0.4.0");
}

#[test]
fn fresh_install_plan_previews_compatibility_and_an_unrunnable_candidate_is_unknown() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("plan-fresh-compat");
    let v1 = source(&profile, "src-fc", "0.4.0");
    profile.environment.variables.insert("FIXTURE_HELP".into(), "stale".into());
    let plan = DesktopManager::new(env(&profile, &root, &v1)).install_plan();
    assert_eq!(plan.status, "ready", "{}", plan.reason);
    assert_eq!(plan.compatibility, "incompatible", "{}", plan.compatibility_reason);
    assert!(!root.exists() || !root.join("active.json").exists());
}

#[test]
fn unverified_record_shows_no_compatibility_claim() {
    let profile = common::Profile::new();
    let root = profile.root.join("plan-unverified-compat");
    let v1 = source(&profile, "src-puc", "0.4.0");
    assert_eq!(DesktopManager::new(env(&profile, &root, &v1)).install().status, "installed");
    fs::write(root.join("active.json"), "{not json").unwrap();
    let plan = DesktopManager::new(env(&profile, &root, &v1)).install_plan();
    assert_eq!(plan.status, "unverified");
    assert_eq!(plan.compatibility, "unknown");
}
