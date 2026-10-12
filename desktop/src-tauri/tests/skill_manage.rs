mod common;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use std::{fs, path::PathBuf};

fn manager(profile: &common::Profile) -> DesktopManager {
    DesktopManager::new(profile.environment.clone())
}

fn skill_dir(home: &std::path::Path) -> PathBuf {
    home.join(".claude").join("skills").join("multi-search")
}

fn read(path: &std::path::Path) -> String {
    fs::read_to_string(path).unwrap()
}

/// Installs through the 06 path so the 07 tests start from a real, verified install.
fn install_global(profile: &common::Profile) {
    let result = manager(profile).skill_install("global", None);
    assert_eq!(result.status, "installed", "{}", result.reason);
}

#[test]
fn unmodified_install_reports_current_and_update_is_not_needed() {
    let profile = common::Profile::new();
    install_global(&profile);
    let status = manager(&profile).skill_status("global", None).unwrap();
    assert_eq!(status.state, multi_search_desktop::InstallState::Current);
    assert!(status.modified_files.is_empty());
    assert!(status.unknown_entries.is_empty());
    let update = manager(&profile).skill_update("global", None, false);
    assert_eq!(update.status, "blocked");
    assert!(update.reason.contains("up to date"), "{}", update.reason);
}

#[test]
fn outdated_skill_updates_without_confirmation_when_unmodified() {
    let profile = common::Profile::new();
    install_global(&profile);
    // Simulate an older release: same content, older marker version, unmodified files.
    let marker = skill_dir(&profile.root).join(".multi-search-install.json");
    let text = read(&marker).replace("\"skill_version\":\"1\"", "\"skill_version\":\"0\"");
    fs::write(&marker, text).unwrap();
    let status = manager(&profile).skill_status("global", None).unwrap();
    assert_eq!(status.state, multi_search_desktop::InstallState::Outdated);
    let update = manager(&profile).skill_update("global", None, false);
    assert_eq!(update.status, "updated", "{}", update.reason);
    assert!(update.verified);
    assert!(update.backup.is_none());
    // The updated skill still tells Claude to call the CLI.
    let installed = read(&skill_dir(&profile.root).join("SKILL.md"));
    assert!(installed.contains("multi-search search"));
    assert!(!installed.contains("MCP"));
}

#[test]
fn local_modification_requires_confirmation_and_is_backed_up_before_overwrite() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    fs::write(target.join("SKILL.md"), "my local customization").unwrap();

    let status = manager(&profile).skill_status("global", None).unwrap();
    assert_eq!(status.state, multi_search_desktop::InstallState::Modified);
    assert_eq!(status.modified_files, vec!["SKILL.md".to_string()]);

    // Without confirmation nothing is overwritten.
    let blocked = manager(&profile).skill_update("global", None, false);
    assert_eq!(blocked.status, "blocked");
    assert!(blocked.reason.contains("Confirmation required"), "{}", blocked.reason);
    assert_eq!(read(&target.join("SKILL.md")), "my local customization");

    // With confirmation: the edit is backed up, then replaced by the release.
    let update = manager(&profile).skill_update("global", None, true);
    assert_eq!(update.status, "updated", "{}", update.reason);
    let backup = PathBuf::from(update.backup.expect("backup path"));
    assert_eq!(read(&backup.join("SKILL.md")), "my local customization");
    // Release files are stored with CRLF; compare the normalized header so the check is line-ending neutral.
    let restored = read(&target.join("SKILL.md")).replace("\r\n", "\n");
    assert!(restored.starts_with("---\nname: multi-search\n"), "{restored:.60}");
    assert_ne!(read(&target.join("SKILL.md")), "my local customization");
}

#[test]
fn failed_update_keeps_the_old_usable_skill() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let marker = target.join(".multi-search-install.json");
    let text = read(&marker).replace("\"skill_version\":\"1\"", "\"skill_version\":\"0\"");
    fs::write(&marker, text).unwrap();
    // Make the CLI incompatible so the update is refused before any write happens.
    let mut environment: RuntimeEnvironment = profile.environment.clone();
    environment.variables.insert("FIXTURE_HELP".into(), "stale".into());
    let blocked = DesktopManager::new(environment).skill_update("global", None, false);
    assert_eq!(blocked.status, "blocked");
    assert!(blocked.reason.contains("--expand"), "{}", blocked.reason);
    // Old skill is still in place and still usable.
    assert!(read(&target.join("SKILL.md")).contains("multi-search search"));
    let leftovers: Vec<_> = fs::read_dir(profile.root.join(".claude/skills"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    assert_eq!(leftovers, vec!["multi-search".to_string()]);
}

#[test]
fn retry_after_failed_update_does_not_misreport_completion() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let marker = target.join(".multi-search-install.json");
    let text = read(&marker).replace("\"skill_version\":\"1\"", "\"skill_version\":\"0\"");
    fs::write(&marker, text).unwrap();
    let mut environment: RuntimeEnvironment = profile.environment.clone();
    environment.variables.insert("FIXTURE_HELP".into(), "stale".into());
    let first = DesktopManager::new(environment).skill_update("global", None, false);
    assert_ne!(first.status, "updated");
    // Retry with the compatible CLI: it succeeds for real, not from the earlier attempt.
    let second = manager(&profile).skill_update("global", None, false);
    assert_eq!(second.status, "updated", "{}", second.reason);
    assert!(second.verified);
}

#[test]
fn unknown_folder_is_never_updated_or_removed() {
    let profile = common::Profile::new();
    let target = skill_dir(&profile.root);
    fs::create_dir_all(&target).unwrap();
    fs::write(target.join("SKILL.md"), "hand written, no marker").unwrap();
    let status = manager(&profile).skill_status("global", None).unwrap();
    assert_eq!(status.state, multi_search_desktop::InstallState::Unknown);
    let update = manager(&profile).skill_update("global", None, true);
    assert_eq!(update.status, "blocked");
    let remove = manager(&profile).skill_remove("global", None, true);
    assert_eq!(remove.status, "blocked");
    assert_eq!(read(&target.join("SKILL.md")), "hand written, no marker");
}

#[test]
fn removal_requires_confirmation_and_deletes_only_tool_owned_files() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    // The user added their own file and a sibling skill; both must survive.
    fs::write(target.join("notes.md"), "my notes").unwrap();
    fs::create_dir_all(profile.root.join(".claude/skills/other")).unwrap();
    fs::write(profile.root.join(".claude/skills/other/SKILL.md"), "other").unwrap();

    let plan = manager(&profile).skill_remove_plan("global", None).unwrap();
    assert!(plan.will_delete.contains(&"SKILL.md".to_string()));
    assert!(plan.will_keep.contains(&"notes.md".to_string()));
    assert!(!plan.will_delete.iter().any(|n| n == "notes.md"));

    let unconfirmed = manager(&profile).skill_remove("global", None, false);
    assert_eq!(unconfirmed.status, "blocked");
    assert!(target.join("SKILL.md").is_file(), "nothing deleted without confirmation");

    let removed = manager(&profile).skill_remove("global", None, true);
    assert_eq!(removed.status, "removed", "{}", removed.reason);
    assert!(!target.join("SKILL.md").exists());
    assert!(!target.join(".multi-search-install.json").exists());
    assert_eq!(read(&target.join("notes.md")), "my notes", "user file kept");
    assert_eq!(read(&profile.root.join(".claude/skills/other/SKILL.md")), "other", "other skill kept");
    assert!(profile.root.join(".claude/skills").is_dir(), "skills folder never deleted");
}

#[test]
fn removal_reports_absent_state_without_deleting_anything() {
    let profile = common::Profile::new();
    let plan = manager(&profile).skill_remove_plan("global", None).unwrap();
    assert_eq!(plan.status, "nothing_to_remove");
    assert!(!plan.can_remove);
    let outcome = manager(&profile).skill_remove("global", None, true);
    assert_eq!(outcome.status, "blocked");
}
