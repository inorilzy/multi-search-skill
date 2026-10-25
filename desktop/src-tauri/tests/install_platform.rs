//! Non-Windows platforms install the CLI outside the app.
//!
//! The managed bundle is a Windows launcher plus a bundled CPython, so the
//! in-app installer must report `unsupported` and must not render Windows
//! artifact paths (`bin/multi-search.exe`) that cannot exist here.
#![cfg(not(windows))]
mod common;

use multi_search_desktop::DesktopManager;

#[test]
fn bundled_installer_reports_unsupported_without_windows_paths() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    let plan = manager.install_plan();
    assert_eq!(plan.status, "unsupported", "{}", plan.reason);
    assert!(plan.reason.contains("Windows"), "reason names the platform: {}", plan.reason);
    assert!(plan.root.is_empty(), "no install root is invented: {}", plan.root);
    assert!(plan.bin.is_empty(), "no Windows artifact path: {}", plan.bin);
    assert!(!plan.bin.contains(".exe"));
    assert!(plan.path_hint.is_empty(), "no PATH hint for a bundle that is not installed");
    assert_eq!(plan.compatibility, "unknown");
}

#[test]
fn install_and_uninstall_refuse_instead_of_touching_files() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    for outcome in [manager.install(), manager.uninstall()] {
        assert_eq!(outcome.status, "unsupported", "{}", outcome.reason);
        assert!(outcome.steps.is_empty(), "nothing is attempted: {:?}", outcome.steps);
    }
    // The isolated profile only ever receives the fixture CLI copied by common::Profile.
    assert_eq!(
        std::fs::read_dir(&profile.root).unwrap().count(),
        1,
        "no install directory was created"
    );
}
