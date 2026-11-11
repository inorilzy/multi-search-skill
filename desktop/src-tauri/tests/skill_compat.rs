mod common;
use multi_search_desktop::DesktopManager;

#[test]
fn cli_without_routes_subcommand_is_reported_incompatible() {
    let profile = common::Profile::new();
    let mut environment = profile.environment.clone();
    environment
        .variables
        .insert("FIXTURE_HELP".into(), "no-routes".into());
    let manager = DesktopManager::new(environment);
    let plan = manager.skill_plan("claude-code", "global", None);
    assert_eq!(plan.status, "cli_incompatible", "{}", plan.reason);
    assert!(plan.reason.contains("routes"), "{}", plan.reason);
    assert!(!plan.can_install);
}
