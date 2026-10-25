//! Release boundary: without `install-test-boundary`, the test keys must have no effect.
//!
//! The managed install is supported on Windows and macOS. These tests verify
//! that a default build derives the real platform root and never adopts the
//! disposable acceptance keys. The root is derived from `common::Profile`'s
//! disposable environment, so the real home directory is never touched.
#![cfg(not(feature = "install-test-boundary"))]
mod common;

#[cfg(any(windows, target_os = "macos"))]
mod managed {
    use super::common;
    use multi_search_desktop::{DesktopManager, RuntimeEnvironment, CLI_FILE_NAME};
    use std::{fs, path::PathBuf};

    #[cfg(windows)]
    fn platform_environment(profile: &common::Profile) -> (RuntimeEnvironment, PathBuf) {
        let mut environment = profile.environment.clone();
        let localappdata = profile.root.join("localappdata");
        environment.variables.insert(
            "LOCALAPPDATA".into(),
            localappdata.to_string_lossy().into_owned(),
        );
        let root = localappdata.join("MultiSearch").join("cli");
        (environment, root)
    }

    #[cfg(target_os = "macos")]
    fn platform_environment(profile: &common::Profile) -> (RuntimeEnvironment, PathBuf) {
        let environment = profile.environment.clone();
        let root = profile
            .root
            .join("Library")
            .join("Application Support")
            .join("MultiSearch")
            .join("cli");
        (environment, root)
    }

    #[test]
    fn default_build_ignores_isolation_and_anchor_test_keys() {
        let profile = common::Profile::new();
        let (mut environment, platform_root) = platform_environment(&profile);
        // On macOS LOCALAPPDATA is not the managed-install base; setting it must not move the root.
        #[cfg(target_os = "macos")]
        environment.variables.insert(
            "LOCALAPPDATA".into(),
            profile
                .root
                .join("ignored-localappdata")
                .to_string_lossy()
                .into_owned(),
        );
        let isolation_root = profile.root.join("release-root");
        let isolation_source = profile.root.join("src-release");
        fs::create_dir_all(isolation_source.join("bin")).unwrap();
        fs::copy(
            profile.root.join(CLI_FILE_NAME),
            isolation_source.join("bin").join(CLI_FILE_NAME),
        )
        .unwrap();
        environment
            .variables
            .insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
        environment.variables.insert(
            "MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(),
            isolation_root.to_string_lossy().into_owned(),
        );
        environment.variables.insert(
            "MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(),
            isolation_source.to_string_lossy().into_owned(),
        );
        environment
            .variables
            .insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), "0".repeat(64));
        let manager = DesktopManager::new(environment);

        let plan = manager.install_plan();
        assert_eq!(plan.status, "prerequisite_missing", "{}", plan.reason);
        assert_eq!(plan.root, platform_root.to_string_lossy());
        assert_eq!(
            plan.bin,
            platform_root
                .join("bin")
                .join(CLI_FILE_NAME)
                .to_string_lossy()
        );
        assert!(plan.source.is_none(), "the test source key is ignored");

        let outcome = manager.install();
        assert_eq!(outcome.status, "prerequisite_missing", "{}", outcome.reason);
        assert!(outcome.steps.is_empty());
        assert!(!isolation_root.exists(), "the test root key is ignored");
        assert!(
            !platform_root.exists(),
            "a missing bundle creates nothing under the real platform root"
        );
    }

    #[test]
    fn default_build_plan_derives_the_platform_root_without_creating_it() {
        let profile = common::Profile::new();
        let (mut environment, platform_root) = platform_environment(&profile);
        let isolation_root = profile.root.join("release-root-plan");
        environment
            .variables
            .insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
        environment.variables.insert(
            "MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(),
            isolation_root.to_string_lossy().into_owned(),
        );
        let plan = DesktopManager::new(environment).install_plan();
        assert_eq!(plan.status, "prerequisite_missing", "{}", plan.reason);
        assert_eq!(plan.root, platform_root.to_string_lossy());
        assert_eq!(
            plan.bin,
            platform_root
                .join("bin")
                .join(CLI_FILE_NAME)
                .to_string_lossy()
        );
        assert!(plan.path_hint.contains("bin"), "{}", plan.path_hint);
        assert!(!isolation_root.exists());
        assert!(!platform_root.exists());
    }
}
