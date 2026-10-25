//! Release boundary: without `install-test-boundary`, the test keys must have no effect.
#![cfg(not(feature = "install-test-boundary"))]
mod common;
use multi_search_desktop::DesktopManager;
use std::fs;

// Windows release boundary: the managed install bundle is Windows-only.
#[cfg(windows)]
#[test]
fn default_build_ignores_isolation_and_anchor_test_keys() {
    let profile = common::Profile::new();
    let root = profile.root.join("release-root");
    let localappdata = profile.root.join("localappdata");
    let source = profile.root.join("src-release");
    fs::create_dir_all(source.join("bin")).unwrap();
    fs::copy(profile.root.join(multi_search_desktop::CLI_FILE_NAME), source.join("bin").join("multi-search.exe")).unwrap();
    let mut environment = profile.environment.clone();
    environment.variables.insert("LOCALAPPDATA".into(), localappdata.to_string_lossy().into_owned());
    environment.variables.insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    environment.variables.insert("MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(), root.to_string_lossy().into_owned());
    environment.variables.insert("MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(), source.to_string_lossy().into_owned());
    environment.variables.insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), "0".repeat(64));
    let manager = DesktopManager::new(environment);
    let outcome = manager.install();
    assert_eq!(outcome.status, "prerequisite_missing", "{}", outcome.reason);
    assert!(outcome.steps.is_empty());
    assert!(!root.exists());
    assert!(!localappdata.exists());
}

// Windows release boundary: the managed install bundle is Windows-only.
#[cfg(windows)]
#[test]
fn default_build_plan_ignores_isolation_keys() {
    let profile = common::Profile::new();
    let root = profile.root.join("release-root-plan");
    let mut environment = profile.environment.clone();
    environment.variables.insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    environment.variables.insert("MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(), root.to_string_lossy().into_owned());
    environment.variables.insert("LOCALAPPDATA".into(), profile.root.join("localappdata-plan").to_string_lossy().into_owned());
    let plan = DesktopManager::new(environment).install_plan();
    assert_eq!(plan.status, "prerequisite_missing");
    assert!(!root.exists());
}
