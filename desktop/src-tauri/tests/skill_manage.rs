mod common;
use multi_search_desktop::{skill_version, DesktopManager, RuntimeEnvironment};
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
fn release_06_marker_without_hashes_remains_managed() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    fs::write(
        target.join(".multi-search-install.json"),
        format!(
            r#"{{"managed_by":"multi-search-desktop","skill":"multi-search","skill_version":"{}","files":["SKILL.md","agents/interface.yaml","references/cli.md","references/search.md","references/subagents.md","references/verification.md"]}}"#, skill_version()
        ),
    )
    .unwrap();
    assert_eq!(
        manager(&profile)
            .skill_status("global", None)
            .unwrap()
            .state,
        multi_search_desktop::InstallState::Current
    );
    fs::write(target.join("SKILL.md"), "06 local edit").unwrap();
    let updated = manager(&profile).skill_update("global", None, true);
    assert_eq!(updated.status, "updated", "{}", updated.reason);
    assert_eq!(
        read(&PathBuf::from(updated.backup.unwrap()).join("SKILL.md")),
        "06 local edit"
    );
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
    assert!(update.reason.contains("已是最新版本"), "{}", update.reason);
}

#[test]
fn outdated_skill_updates_without_confirmation_when_unmodified() {
    let profile = common::Profile::new();
    install_global(&profile);
    // Simulate an older release: same content, older marker version, unmodified files.
    let marker = skill_dir(&profile.root).join(".multi-search-install.json");
    let text = read(&marker).replace(
        &format!("\"skill_version\":\"{}\"", skill_version()),
        "\"skill_version\":\"0\"",
    );
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
    assert_eq!(installed, include_str!("../../../skills/multi-search/SKILL.md"));
    assert_eq!(
        read(&skill_dir(&profile.root).join("references/cli.md")),
        include_str!("../../../skills/multi-search/references/cli.md")
    );
    assert_eq!(
        read(&skill_dir(&profile.root).join("references/verification.md")),
        include_str!("../../../skills/multi-search/references/verification.md")
    );
}

#[test]
fn update_preserves_unknown_files_and_nested_user_content() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    fs::write(target.join("SKILL.md"), "local edit").unwrap();
    fs::write(target.join("notes.bin"), [0, 255, 19]).unwrap();
    fs::create_dir_all(target.join("references/user/nested")).unwrap();
    fs::write(
        target.join("references/user/nested/notes.txt"),
        "keep nested notes",
    )
    .unwrap();
    let update = manager(&profile).skill_update("global", None, true);
    assert_eq!(update.status, "updated", "{}", update.reason);
    assert_eq!(fs::read(target.join("notes.bin")).unwrap(), [0, 255, 19]);
    assert_eq!(
        read(&target.join("references/user/nested/notes.txt")),
        "keep nested notes"
    );
    assert_eq!(
        manager(&profile)
            .skill_status("global", None)
            .unwrap()
            .state,
        multi_search_desktop::InstallState::Current
    );
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
    assert!(
        blocked.reason.contains("需要确认"),
        "{}",
        blocked.reason
    );
    assert_eq!(read(&target.join("SKILL.md")), "my local customization");

    // With confirmation: the edit is backed up, then replaced by the release.
    let update = manager(&profile).skill_update("global", None, true);
    assert_eq!(update.status, "updated", "{}", update.reason);
    let backup = PathBuf::from(update.backup.expect("backup path"));
    assert_eq!(read(&backup.join("SKILL.md")), "my local customization");
    assert_eq!(
        backup.parent(),
        Some(profile.root.join(".claude").as_path()),
        "backup must not be discoverable as an installed skill"
    );
    // Release files are stored with CRLF; compare the normalized header so the check is line-ending neutral.
    let restored = read(&target.join("SKILL.md")).replace("\r\n", "\n");
    assert!(
        restored.starts_with("---\nname: multi-search\n"),
        "{restored:.60}"
    );
    assert_ne!(read(&target.join("SKILL.md")), "my local customization");
}

#[test]
fn status_exposes_target_release_requirements_and_blocks_incompatible_update() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    fs::write(target.join("SKILL.md"), "edited").unwrap();
    let mut environment = profile.environment.clone();
    environment
        .variables
        .insert("FIXTURE_HELP".into(), "stale".into());
    let status = serde_json::to_value(
        DesktopManager::new(environment)
            .skill_status("global", None)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(status["can_update"], false);
    assert_eq!(status["cli_compatible"], false);
    assert!(status["cli_requirements"]
        .as_str()
        .unwrap()
        .contains("--expand"));
    assert!(status["compatibility_reason"]
        .as_str()
        .unwrap()
        .contains("--expand"));
}

#[cfg(windows)]
#[test]
fn filesystem_update_failure_keeps_old_skill_and_retry_succeeds() {
    use std::os::windows::fs::OpenOptionsExt;
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let marker = target.join(".multi-search-install.json");
    fs::write(
        &marker,
        read(&marker).replace(
            &format!("\"skill_version\":\"{}\"", skill_version()),
            "\"skill_version\":\"0\"",
        ),
    )
    .unwrap();
    let before = read(&target.join("SKILL.md"));
    let locked = fs::OpenOptions::new()
        .read(true)
        .share_mode(1)
        .open(target.join("SKILL.md"))
        .unwrap();
    let failed = manager(&profile).skill_update("global", None, false);
    assert_eq!(failed.status, "failed");
    assert!(!failed.verified);
    assert_eq!(read(&target.join("SKILL.md")), before);
    assert_eq!(
        manager(&profile)
            .skill_status("global", None)
            .unwrap()
            .installed_version
            .as_deref(),
        Some("0")
    );
    drop(locked);
    assert_eq!(
        manager(&profile).skill_update("global", None, false).status,
        "updated"
    );
}

#[test]
fn failed_update_keeps_the_old_usable_skill() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let marker = target.join(".multi-search-install.json");
    let text = read(&marker).replace(
        &format!("\"skill_version\":\"{}\"", skill_version()),
        "\"skill_version\":\"0\"",
    );
    fs::write(&marker, text).unwrap();
    // Make the CLI incompatible so the update is refused before any write happens.
    let mut environment: RuntimeEnvironment = profile.environment.clone();
    environment
        .variables
        .insert("FIXTURE_HELP".into(), "stale".into());
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
    let text = read(&marker).replace(
        &format!("\"skill_version\":\"{}\"", skill_version()),
        "\"skill_version\":\"0\"",
    );
    fs::write(&marker, text).unwrap();
    let mut environment: RuntimeEnvironment = profile.environment.clone();
    environment
        .variables
        .insert("FIXTURE_HELP".into(), "stale".into());
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
    assert!(
        target.join("SKILL.md").is_file(),
        "nothing deleted without confirmation"
    );

    let removed = manager(&profile).skill_remove("global", None, true);
    assert_eq!(removed.status, "removed", "{}", removed.reason);
    assert!(!target.join("SKILL.md").exists());
    assert!(!target.join(".multi-search-install.json").exists());
    assert_eq!(read(&target.join("notes.md")), "my notes", "user file kept");
    assert_eq!(
        read(&profile.root.join(".claude/skills/other/SKILL.md")),
        "other",
        "other skill kept"
    );
    assert!(
        profile.root.join(".claude/skills").is_dir(),
        "skills folder never deleted"
    );
}

/// The UI reads these exact JSON keys; a rename on either side would silently break the panel.
#[test]
fn outcomes_serialize_the_field_names_the_ui_reads() {
    let profile = common::Profile::new();
    let manager = manager(&profile);
    let status = serde_json::to_value(manager.skill_status("global", None).unwrap()).unwrap();
    for key in [
        "state",
        "installed_version",
        "release_version",
        "modified_files",
        "unknown_entries",
        "reason",
        "target",
    ] {
        assert!(
            status.get(key).is_some(),
            "status is missing {key}: {status}"
        );
    }
    let update = serde_json::to_value(manager.skill_update("global", None, false)).unwrap();
    for key in ["status", "reason", "backup", "verified"] {
        assert!(
            update.get(key).is_some(),
            "update outcome is missing {key}: {update}"
        );
    }
    let plan = serde_json::to_value(manager.skill_remove_plan("global", None).unwrap()).unwrap();
    for key in ["will_delete", "will_keep", "can_remove", "reason"] {
        assert!(
            plan.get(key).is_some(),
            "remove plan is missing {key}: {plan}"
        );
    }
    let removed = serde_json::to_value(manager.skill_remove("global", None, false)).unwrap();
    for key in ["status", "deleted", "kept", "reason"] {
        assert!(
            removed.get(key).is_some(),
            "remove outcome is missing {key}: {removed}"
        );
    }
}

#[test]
fn managed_path_replaced_with_user_folder_is_preserved() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    fs::remove_file(target.join("SKILL.md")).unwrap();
    fs::create_dir(target.join("SKILL.md")).unwrap();
    fs::write(target.join("SKILL.md/user.txt"), "user folder").unwrap();
    assert!(
        !manager(&profile)
            .skill_remove_plan("global", None)
            .unwrap()
            .can_remove
    );
    assert_eq!(
        manager(&profile).skill_remove("global", None, true).status,
        "blocked"
    );
    assert_eq!(read(&target.join("SKILL.md/user.txt")), "user folder");
    assert!(target.join(".multi-search-install.json").is_file());
}

#[cfg(windows)]
#[test]
fn linked_references_never_modify_external_files() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let outside = profile.root.join("outside");
    fs::rename(target.join("references"), &outside).unwrap();
    let link = target.join("references");
    let result = std::process::Command::new("cmd.exe")
        .args(["/C", "mklink", "/J"])
        .arg(&link)
        .arg(&outside)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let plan = manager(&profile).skill_remove_plan("global", None).unwrap();
    let outcome = manager(&profile).skill_remove("global", None, true);
    // Remove our junction explicitly before the disposable profile cleanup.
    if fs::symlink_metadata(&link).is_ok() {
        fs::remove_dir(&link).unwrap();
    }
    assert!(!plan.can_remove);
    assert_eq!(outcome.status, "blocked");
    assert!(outside.join("cli.md").is_file());
    assert!(target.join("SKILL.md").is_file());
}

#[test]
fn missing_managed_file_can_be_repaired_after_confirmation() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    fs::remove_file(target.join("references/cli.md")).unwrap();
    assert_eq!(
        manager(&profile).skill_update("global", None, false).status,
        "blocked"
    );
    let repaired = manager(&profile).skill_update("global", None, true);
    assert_eq!(repaired.status, "updated", "{}", repaired.reason);
    assert!(target.join("references/cli.md").is_file());
}

#[cfg(windows)]
#[test]
fn partial_removal_keeps_ownership_for_retry() {
    use std::os::windows::fs::OpenOptionsExt;
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let locked = fs::OpenOptions::new()
        .read(true)
        .share_mode(1)
        .open(target.join("references/cli.md"))
        .unwrap();
    let failed = manager(&profile).skill_remove("global", None, true);
    assert_eq!(failed.status, "failed");
    assert!(
        target.join(".multi-search-install.json").is_file(),
        "ownership must remain for retry"
    );
    drop(locked);
    assert_eq!(
        manager(&profile).skill_remove("global", None, true).status,
        "removed"
    );
    assert_eq!(
        manager(&profile)
            .skill_status("global", None)
            .unwrap()
            .state,
        multi_search_desktop::InstallState::Absent
    );
}

#[test]
fn incomplete_ownership_marker_never_authorizes_delete_or_update() {
    let profile = common::Profile::new();
    install_global(&profile);
    let target = skill_dir(&profile.root);
    let marker_path = target.join(".multi-search-install.json");
    let mut marker: serde_json::Value = serde_json::from_str(&read(&marker_path)).unwrap();
    marker["files"] = serde_json::json!(["references/cli.md", "../other/SKILL.md"]);
    fs::write(&marker_path, marker.to_string()).unwrap();
    assert!(
        !manager(&profile)
            .skill_remove_plan("global", None)
            .unwrap()
            .can_remove
    );
    assert_eq!(
        manager(&profile).skill_remove("global", None, true).status,
        "blocked"
    );
    assert_eq!(
        manager(&profile).skill_update("global", None, true).status,
        "blocked"
    );
    assert!(target.join("SKILL.md").is_file());
    assert!(marker_path.is_file());
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
