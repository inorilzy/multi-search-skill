mod common;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use std::{fs, path::PathBuf};

fn manager(profile: &common::Profile) -> DesktopManager {
    DesktopManager::new(profile.environment.clone())
}

fn skill_dir(home: &std::path::Path) -> PathBuf {
    home.join(".claude").join("skills").join("multi-search")
}

#[test]
fn fresh_global_install_writes_only_the_isolated_profile_and_verifies() {
    let profile = common::Profile::new();
    let manager = manager(&profile);
    let plan = manager.skill_plan("claude-code", "global", None);
    assert_eq!(plan.status, "ready", "{}", plan.reason);
    assert!(plan.can_install);
    assert_eq!(plan.target.as_deref(), Some(skill_dir(&profile.root).to_str().unwrap()));
    let result = manager.skill_install("claude-code", "global", None);
    assert_eq!(result.status, "installed", "{}", result.reason);
    assert!(result.verified);
    // Checkouts may store the release files as CRLF; compare the normalized header.
    let installed = fs::read_to_string(skill_dir(&profile.root).join("SKILL.md")).unwrap().replace("\r\n", "\n");
    assert!(installed.starts_with("---\nname: multi-search\n"));
    assert!(!installed.contains("MCP"));
    assert!(skill_dir(&profile.root).join("references/cli.md").is_file());
    assert!(skill_dir(&profile.root).join(".multi-search-install.json").is_file());
    // Staging must not remain beside the installed skill.
    let leftovers: Vec<_> = fs::read_dir(profile.root.join(".claude/skills"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    assert_eq!(leftovers, vec!["multi-search".to_string()]);
}

#[test]
fn existing_target_is_never_overwritten_and_local_content_survives() {
    let profile = common::Profile::new();
    let target = skill_dir(&profile.root);
    fs::create_dir_all(&target).unwrap();
    fs::write(target.join("SKILL.md"), "my local customization").unwrap();
    let manager = manager(&profile);
    let plan = manager.skill_plan("claude-code", "global", None);
    assert_eq!(plan.status, "exists");
    assert!(!plan.can_install);
    let result = manager.skill_install("claude-code", "global", None);
    assert_eq!(result.status, "blocked");
    assert!(!result.verified);
    assert_eq!(fs::read_to_string(target.join("SKILL.md")).unwrap(), "my local customization");
}

#[test]
fn project_scope_requires_an_existing_absolute_project_and_writes_only_there() {
    let profile = common::Profile::new();
    let project = profile.root.join("my-project");
    fs::create_dir_all(&project).unwrap();
    let manager = manager(&profile);
    assert_eq!(manager.skill_plan("claude-code", "project", None).status, "invalid_scope");
    assert_eq!(manager.skill_plan("claude-code", "project", Some(PathBuf::from("relative/dir"))).status, "invalid_scope");
    assert_eq!(
        manager.skill_plan("claude-code", "project", Some(profile.root.join("missing"))).status,
        "invalid_scope"
    );
    assert_eq!(manager.skill_plan("claude-code", "bogus", None).status, "invalid_scope");
    let result = manager.skill_install("claude-code", "project", Some(project.clone()));
    assert_eq!(result.status, "installed", "{}", result.reason);
    assert!(project.join(".claude/skills/multi-search/SKILL.md").is_file());
    assert!(!skill_dir(&profile.root).exists(), "global location must stay untouched");
}

#[test]
fn unrelated_skills_in_the_same_folder_are_kept() {
    let profile = common::Profile::new();
    let other = profile.root.join(".claude/skills/other-skill");
    fs::create_dir_all(&other).unwrap();
    fs::write(other.join("SKILL.md"), "other").unwrap();
    let result = manager(&profile).skill_install("claude-code", "global", None);
    assert_eq!(result.status, "installed", "{}", result.reason);
    assert_eq!(fs::read_to_string(other.join("SKILL.md")).unwrap(), "other");
}

#[test]
fn missing_cli_blocks_install_and_writes_nothing() {
    let profile = common::Profile::new();
    let environment = RuntimeEnvironment {
        user_path: vec![],
        ..profile.environment.clone()
    };
    let manager = DesktopManager::new(environment);
    let plan = manager.skill_plan("claude-code", "global", None);
    assert_eq!(plan.status, "cli_missing");
    assert!(!plan.can_install);
    let result = manager.skill_install("claude-code", "global", None);
    assert_eq!(result.status, "blocked");
    assert!(!skill_dir(&profile.root).exists());
}

#[test]
fn incompatible_cli_blocks_install_and_names_the_missing_flag() {
    let profile = common::Profile::new();
    let mut environment = profile.environment.clone();
    environment.variables.insert("FIXTURE_HELP".into(), "stale".into());
    let manager = DesktopManager::new(environment);
    let plan = manager.skill_plan("claude-code", "global", None);
    assert_eq!(plan.status, "cli_incompatible", "{}", plan.reason);
    assert!(plan.reason.contains("--expand"), "{}", plan.reason);
    let result = manager.skill_install("claude-code", "global", None);
    assert_eq!(result.status, "blocked");
    assert!(!skill_dir(&profile.root).exists());
}

#[test]
fn agents_host_installs_into_the_cross_tool_agents_skills_folder() {
    let profile = common::Profile::new();
    let manager = manager(&profile);
    let target = profile.root.join(".agents").join("skills").join("multi-search");
    let plan = manager.skill_plan("agents", "global", None);
    assert_eq!(plan.status, "ready", "{}", plan.reason);
    assert_eq!(plan.host, "agents");
    assert_eq!(plan.target.as_deref(), Some(target.to_str().unwrap()));
    let result = manager.skill_install("agents", "global", None);
    assert_eq!(result.status, "installed", "{}", result.reason);
    assert!(result.reason.contains("Codex"), "{}", result.reason);
    assert!(target.join("SKILL.md").is_file());
    assert!(!profile.root.join(".claude").exists(), "the Claude Code folder is untouched");
    // The two hosts are independent: Claude Code still reports nothing installed.
    let claude = manager.skill_status("claude-code", "global", None).unwrap();
    assert_eq!(claude.state, multi_search_desktop::InstallState::Absent);
    let agents = manager.skill_status("agents", "global", None).unwrap();
    assert_eq!(agents.state, multi_search_desktop::InstallState::Current);
    // Both registered targets pass the managed-registry check on the next install.
    assert_eq!(manager.skill_install("claude-code", "global", None).status, "installed");
    let removed = manager.skill_remove("agents", "global", None, true);
    assert_eq!(removed.status, "removed", "{}", removed.reason);
    assert!(!target.exists());
    assert!(skill_dir(&profile.root).join("SKILL.md").is_file());
}

#[test]
fn unknown_host_is_refused_without_writing() {
    let profile = common::Profile::new();
    let plan = manager(&profile).skill_plan("cursor", "global", None);
    assert_eq!(plan.status, "invalid_scope");
    assert!(!plan.can_install);
    assert!(fs::read_dir(&profile.root).unwrap().all(|e| !e.unwrap().file_name().to_string_lossy().starts_with('.')));
}
