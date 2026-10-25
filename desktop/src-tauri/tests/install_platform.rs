//! Platform-specific managed install behavior.
//!
//! macOS installs the in-app managed bundle as `bin/multi-search` plus its
//! bundled runtime; Windows keeps its own lifecycle tests. Linux remains
//! unsupported and must refuse without inventing paths. Every fixture here is
//! isolated behind `install-test-boundary` and uses the disposable
//! `common::Profile`, never the real home directory.
#![cfg(not(windows))]
mod common;

#[cfg(target_os = "macos")]
mod macos {
    use super::common;
    use multi_search_desktop::{DesktopManager, RuntimeEnvironment, CLI_FILE_NAME};
    use sha2::{Digest, Sha256};
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        path::{Path, PathBuf},
    };

    const ARTIFACT: &str = "bin/multi-search";
    const RUNTIME_PYTHON: &str = "runtime/bin/python3.12";
    const RUNTIME_DATA: &str = "runtime/lib/data.txt";

    fn hex(path: &Path) -> (String, u64) {
        let bytes = fs::read(path).unwrap();
        let digest = Sha256::digest(&bytes);
        (
            digest.iter().map(|byte| format!("{byte:02x}")).collect(),
            bytes.len() as u64,
        )
    }

    fn anchor_of(source: &Path) -> String {
        hex(&source.join("manifest.json")).0
    }

    /// A macOS-shaped bundle: executable launcher, executable bundled
    /// interpreter, and non-executable runtime data. `fs::copy` must retain
    /// the modes and the installer must refuse a source that is not executable.
    fn bundle(profile: &common::Profile, name: &str, version: &str) -> PathBuf {
        let dir = profile.root.join(name);
        fs::create_dir_all(dir.join("bin")).unwrap();
        fs::create_dir_all(dir.join("runtime/bin")).unwrap();
        fs::create_dir_all(dir.join("runtime/lib")).unwrap();

        let launcher = dir.join(ARTIFACT);
        fs::copy(profile.root.join(CLI_FILE_NAME), &launcher).unwrap();
        fs::set_permissions(&launcher, fs::Permissions::from_mode(0o755)).unwrap();

        let python = dir.join(RUNTIME_PYTHON);
        fs::copy(profile.root.join(CLI_FILE_NAME), &python).unwrap();
        fs::set_permissions(&python, fs::Permissions::from_mode(0o755)).unwrap();

        let data = dir.join(RUNTIME_DATA);
        fs::write(&data, version).unwrap();
        fs::set_permissions(&data, fs::Permissions::from_mode(0o644)).unwrap();

        let entries: Vec<serde_json::Value> = [
            (ARTIFACT, &launcher),
            (RUNTIME_PYTHON, &python),
            (RUNTIME_DATA, &data),
        ]
        .into_iter()
        .map(|(rel, path)| {
            let (sha256, size) = hex(path);
            serde_json::json!({"path": rel, "size": size, "sha256": sha256})
        })
        .collect();
        let manifest = serde_json::to_vec_pretty(&serde_json::json!({
            "schema": 1,
            "version": version,
            "files": entries,
        }))
        .unwrap();
        fs::write(dir.join("manifest.json"), manifest).unwrap();
        dir
    }

    /// Extends a valid bundle with one more manifest-listed file, so an update can be
    /// made to collide with content the tool does not own.
    fn bundle_with_extra_file(
        profile: &common::Profile,
        name: &str,
        version: &str,
        rel: &str,
        contents: &[u8],
    ) -> PathBuf {
        let dir = bundle(profile, name, version);
        let path = dir.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, contents).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        let (sha256, size) = hex(&path);
        let mut manifest: serde_json::Value =
            serde_json::from_slice(&fs::read(dir.join("manifest.json")).unwrap()).unwrap();
        manifest["files"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::json!({"path": rel, "size": size, "sha256": sha256}));
        fs::write(
            dir.join("manifest.json"),
            serde_json::to_vec_pretty(&manifest).unwrap(),
        )
        .unwrap();
        dir
    }

    fn env(profile: &common::Profile, root: &Path, source: Option<&Path>) -> RuntimeEnvironment {
        let mut environment = profile.environment.clone();
        environment
            .variables
            .insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
        environment.variables.insert(
            "MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(),
            root.to_string_lossy().into_owned(),
        );
        if let Some(source) = source {
            environment.variables.insert(
                "MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(),
                source.to_string_lossy().into_owned(),
            );
            environment
                .variables
                .insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), anchor_of(source));
        }
        environment
    }

    fn mode(path: &Path) -> u32 {
        fs::metadata(path).unwrap().permissions().mode() & 0o777
    }

    fn assert_installed_bundle(root: &Path, version: &str) {
        assert_eq!(mode(&root.join(ARTIFACT)), 0o755, "launcher mode");
        assert_eq!(mode(&root.join(RUNTIME_PYTHON)), 0o755, "runtime mode");
        assert_eq!(mode(&root.join(RUNTIME_DATA)), 0o644, "data mode");
        assert_eq!(
            fs::read_to_string(root.join(RUNTIME_DATA)).unwrap(),
            version,
            "runtime data belongs to the active version"
        );
    }

    fn snapshot(root: &Path) -> Vec<(String, Vec<u8>, u32)> {
        [
            "manifest.json",
            "active.json",
            ARTIFACT,
            RUNTIME_PYTHON,
            RUNTIME_DATA,
        ]
        .into_iter()
        .map(|rel| {
            let path = root.join(rel);
            (rel.into(), fs::read(&path).unwrap(), mode(&path))
        })
        .collect()
    }

    #[test]
    fn installs_platform_artifact_and_retains_executable_modes() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-install");
        let source = bundle(&profile, "src-install", "0.4.0");
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));

        let plan = manager.install_plan();
        assert_eq!(plan.status, "ready", "{}", plan.reason);
        assert_eq!(plan.root, root.to_string_lossy());
        assert_eq!(plan.bin, root.join(ARTIFACT).to_string_lossy());
        assert!(!plan.bin.ends_with(".exe"), "{}", plan.bin);
        assert!(plan.path_hint.contains("bin"), "{}", plan.path_hint);

        let outcome = manager.install();
        assert_eq!(outcome.status, "installed", "{}", outcome.reason);
        assert_eq!(outcome.version.as_deref(), Some("0.4.0"));
        assert_eq!(
            outcome.bin.as_deref(),
            Some(root.join(ARTIFACT).to_string_lossy().as_ref())
        );
        assert!(
            outcome.steps.iter().all(|step| step.ok),
            "every successful step is reported: {:?}",
            outcome
                .steps
                .iter()
                .map(|step| (step.name.as_str(), step.ok))
                .collect::<Vec<_>>()
        );

        assert_installed_bundle(&root, "0.4.0");
        assert!(root.join("active.json").is_file());
        assert_eq!(manager.install_plan().status, "installed");
        assert_eq!(manager.execution_cli().unwrap(), root.join(ARTIFACT));
        assert!(manager.detect_cli().managed);
    }

    #[test]
    fn update_replaces_the_bundle_and_keeps_executable_modes() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-update");
        let v1 = bundle(&profile, "src-update-v1", "0.4.0");
        assert_eq!(
            DesktopManager::new(env(&profile, &root, Some(&v1)))
                .install()
                .status,
            "installed"
        );

        let v2 = bundle(&profile, "src-update-v2", "0.5.0");
        let mut environment = env(&profile, &root, Some(&v2));
        environment
            .variables
            .insert("FIXTURE_VERSION".into(), "0.5.0".into());
        let manager = DesktopManager::new(environment);

        let plan = manager.install_plan();
        assert_eq!(plan.status, "update_available", "{}", plan.reason);
        assert_eq!(plan.current_version.as_deref(), Some("0.4.0"));
        assert_eq!(plan.version.as_deref(), Some("0.5.0"));

        let outcome = manager.update();
        assert_eq!(outcome.status, "installed", "{}", outcome.reason);
        assert_eq!(outcome.version.as_deref(), Some("0.5.0"));
        assert_installed_bundle(&root, "0.5.0");
        let active: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join("active.json")).unwrap()).unwrap();
        assert_eq!(active["version"], "0.5.0");
        assert!(
            !fs::read_dir(&root).unwrap().any(|entry| entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("backup-")),
            "a successful update removes its recovery directory"
        );
    }

    #[test]
    fn failed_activation_rolls_back_to_the_exact_previous_bundle() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-rollback");
        let v1 = bundle(&profile, "src-rollback-v1", "0.4.0");
        let old = DesktopManager::new(env(&profile, &root, Some(&v1)));
        assert_eq!(old.install().status, "installed");
        let before = snapshot(&root);

        let v2 = bundle(&profile, "src-rollback-v2", "0.5.0");
        let mut environment = env(&profile, &root, Some(&v2));
        environment
            .variables
            .insert("FIXTURE_VERSION".into(), "0.5.0".into());
        // The fixture fails only when executed from <root>/bin, so staging succeeds and the
        // post-activation probe is the failure the rollback must repair.
        environment.variables.insert(
            "FIXTURE_FAIL_ACTIVE_ROOT".into(),
            root.to_string_lossy().into_owned(),
        );
        let outcome = DesktopManager::new(environment.clone()).update();
        assert_eq!(outcome.status, "failed", "{}", outcome.reason);
        assert_eq!(
            snapshot(&root),
            before,
            "every old file and mode is restored"
        );
        assert_eq!(old.install_plan().status, "installed");

        environment.variables.remove("FIXTURE_FAIL_ACTIVE_ROOT");
        let retried = DesktopManager::new(environment).update();
        assert_eq!(retried.status, "installed", "{}", retried.reason);
        assert_installed_bundle(&root, "0.5.0");
    }

    #[test]
    fn update_refuses_to_overwrite_unknown_content_inside_the_owned_root() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-update-unknown");
        let v1 = bundle(&profile, "src-update-unknown-v1", "0.4.0");
        assert_eq!(
            DesktopManager::new(env(&profile, &root, Some(&v1)))
                .install()
                .status,
            "installed"
        );
        let unknown = root.join("runtime/lib/notes.txt");
        fs::write(&unknown, b"user content").unwrap();

        let v2 = bundle_with_extra_file(
            &profile,
            "src-update-unknown-v2",
            "0.5.0",
            "runtime/lib/notes.txt",
            b"new version",
        );
        let mut environment = env(&profile, &root, Some(&v2));
        environment
            .variables
            .insert("FIXTURE_VERSION".into(), "0.5.0".into());
        let outcome = DesktopManager::new(environment).update();

        assert_eq!(outcome.status, "unknown_existing", "{}", outcome.reason);
        assert_eq!(fs::read(&unknown).unwrap(), b"user content");
        assert_installed_bundle(&root, "0.4.0");
        let active: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join("active.json")).unwrap()).unwrap();
        assert_eq!(active["version"], "0.4.0");
    }

    #[test]
    fn installed_artifact_that_loses_its_execute_bit_reports_unverified() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-tampered-mode");
        let source = bundle(&profile, "src-tampered", "0.4.0");
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));
        assert_eq!(manager.install().status, "installed");

        let artifact = root.join(ARTIFACT);
        fs::set_permissions(&artifact, fs::Permissions::from_mode(0o644)).unwrap();

        // A damaged install must not keep advertising itself as usable.
        assert_eq!(manager.install_plan().status, "unverified");
        assert!(!manager.detect_cli().managed, "a damaged install is never the execution path");
        let outcome = manager.install();
        assert_eq!(outcome.status, "unverified", "{}", outcome.reason);
        assert_eq!(
            fs::metadata(&artifact).unwrap().permissions().mode() & 0o111,
            0,
            "refusal leaves the file untouched"
        );
    }

    #[test]
    fn uninstall_removes_only_owned_files_and_keeps_config_and_skills() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-uninstall");
        let source = bundle(&profile, "src-uninstall", "0.4.0");
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));
        assert_eq!(manager.install().status, "installed");

        fs::create_dir_all(root.join("config")).unwrap();
        fs::write(root.join("config/settings.json"), "{\"kept\":true}").unwrap();
        let skill = profile.root.join(".claude/skills/multi-search");
        fs::create_dir_all(&skill).unwrap();
        fs::write(skill.join("SKILL.md"), "keep").unwrap();

        let outcome = manager.uninstall();
        assert_eq!(outcome.status, "uninstalled", "{}", outcome.reason);
        assert!(!root.join(ARTIFACT).exists());
        assert!(!root.join(RUNTIME_PYTHON).exists());
        assert!(!root.join("manifest.json").exists());
        assert!(!root.join("active.json").exists());
        assert!(
            root.join("multi-search-install.json").is_file(),
            "the ownership marker survives so a reinstall is still ours"
        );
        assert_eq!(
            fs::read_to_string(root.join("config/settings.json")).unwrap(),
            "{\"kept\":true}"
        );
        assert_eq!(fs::read_to_string(skill.join("SKILL.md")).unwrap(), "keep");
        assert!(
            outcome
                .steps
                .iter()
                .any(|step| !step.ok && step.name.contains("Skill")),
            "the kept Skill is reported with its now-missing CLI dependency: {:?}",
            outcome
                .steps
                .iter()
                .map(|step| (step.name.as_str(), step.ok, step.detail.as_str()))
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn linked_managed_root_is_never_followed_or_written_through() {
        let profile = common::Profile::new();
        let external = profile.root.join("external-empty");
        fs::create_dir(&external).unwrap();
        let root = profile.root.join("managed-linked-root");
        std::os::unix::fs::symlink(&external, &root).unwrap();
        let source = bundle(&profile, "src-linked-root", "0.4.0");
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));

        assert_eq!(manager.install_plan().status, "unknown_existing");
        let outcome = manager.install();
        assert_eq!(outcome.status, "unknown_existing", "{}", outcome.reason);
        assert!(
            fs::read_dir(&external).unwrap().next().is_none(),
            "nothing is written through the root link"
        );
        assert_eq!(manager.uninstall().status, "not_installed");
        assert!(
            fs::symlink_metadata(&root)
                .unwrap()
                .file_type()
                .is_symlink(),
            "the link is reported, never replaced"
        );
    }

    #[test]
    fn unknown_existing_root_is_refused_without_changes() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-unknown");
        fs::create_dir_all(root.join("bin")).unwrap();
        let foreign = root.join(ARTIFACT);
        fs::write(&foreign, b"user managed copy").unwrap();
        let source = bundle(&profile, "src-unknown", "0.4.0");
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));

        assert_eq!(manager.install_plan().status, "unknown_existing");
        let outcome = manager.install();
        assert_eq!(outcome.status, "unknown_existing", "{}", outcome.reason);
        assert_eq!(fs::read(&foreign).unwrap(), b"user managed copy");
        assert!(!root.join("active.json").exists());
        assert!(!root.join("multi-search-install.json").exists());
    }

    #[test]
    fn non_executable_launcher_is_refused_before_the_root_is_created() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-bad-launcher-mode");
        let source = bundle(&profile, "src-bad-launcher-mode", "0.4.0");
        fs::set_permissions(source.join(ARTIFACT), fs::Permissions::from_mode(0o644)).unwrap();
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));

        let plan = manager.install_plan();
        assert_eq!(plan.status, "integrity_failed", "{}", plan.reason);
        assert!(plan.reason.contains("执行权限"), "{}", plan.reason);
        let outcome = manager.install();
        assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
        assert!(outcome.reason.contains("执行权限"), "{}", outcome.reason);
        assert!(
            !root.exists(),
            "a bad source never creates the install root"
        );
    }

    #[test]
    fn non_executable_bundled_runtime_is_refused_before_the_root_is_created() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-bad-runtime-mode");
        let source = bundle(&profile, "src-bad-runtime-mode", "0.4.0");
        fs::set_permissions(
            source.join(RUNTIME_PYTHON),
            fs::Permissions::from_mode(0o644),
        )
        .unwrap();
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));

        let outcome = manager.install();
        assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
        assert!(outcome.reason.contains("执行权限"), "{}", outcome.reason);
        assert!(
            !root.exists(),
            "a bad source never creates the install root"
        );
    }

    #[test]
    fn linked_source_artifact_is_refused_without_following_it() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-linked-source");
        let source = bundle(&profile, "src-linked-source", "0.4.0");
        let artifact = source.join(ARTIFACT);
        fs::remove_file(&artifact).unwrap();
        std::os::unix::fs::symlink(profile.root.join(CLI_FILE_NAME), &artifact).unwrap();
        let manager = DesktopManager::new(env(&profile, &root, Some(&source)));

        let outcome = manager.install();
        assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
        assert!(outcome.reason.contains("链接"), "{}", outcome.reason);
        assert!(!root.exists());
    }

    #[test]
    fn explicit_test_anchor_is_enforced_before_any_file_is_written() {
        let profile = common::Profile::new();
        let root = profile.root.join("managed-bad-anchor");
        let source = bundle(&profile, "src-bad-anchor", "0.4.0");
        let mut environment = env(&profile, &root, Some(&source));
        environment
            .variables
            .insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), "0".repeat(64));
        let outcome = DesktopManager::new(environment).install();
        assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
        assert!(outcome.reason.contains("信任锚点"), "{}", outcome.reason);
        assert!(!root.exists());
    }

    #[test]
    fn platform_root_uses_absolute_home_or_userprofile_and_rejects_relative_values() {
        let profile = common::Profile::new();
        let cases: Vec<(Option<String>, Option<String>, PathBuf)> = vec![
            (
                Some("relative/home".into()),
                Some(
                    profile
                        .root
                        .join("userprofile-root")
                        .to_string_lossy()
                        .into_owned(),
                ),
                profile.root.join("userprofile-root"),
            ),
            (
                Some(
                    profile
                        .root
                        .join("home-root")
                        .to_string_lossy()
                        .into_owned(),
                ),
                Some("relative/userprofile".into()),
                profile.root.join("home-root"),
            ),
            (
                Some(String::new()),
                Some(
                    profile
                        .root
                        .join("empty-home-root")
                        .to_string_lossy()
                        .into_owned(),
                ),
                profile.root.join("empty-home-root"),
            ),
            (
                None,
                Some(
                    profile
                        .root
                        .join("missing-home-root")
                        .to_string_lossy()
                        .into_owned(),
                ),
                profile.root.join("missing-home-root"),
            ),
        ];
        for (home, userprofile, expected_home) in cases {
            let mut environment = profile.environment.clone();
            match home {
                Some(value) => {
                    environment.variables.insert("HOME".into(), value);
                }
                None => {
                    environment.variables.remove("HOME");
                }
            }
            match userprofile {
                Some(value) => {
                    environment.variables.insert("USERPROFILE".into(), value);
                }
                None => {
                    environment.variables.remove("USERPROFILE");
                }
            }
            let plan = DesktopManager::new(environment).install_plan();
            assert_eq!(plan.status, "prerequisite_missing", "{}", plan.reason);
            assert_eq!(
                PathBuf::from(&plan.root),
                expected_home
                    .join("Library")
                    .join("Application Support")
                    .join("MultiSearch")
                    .join("cli")
            );
            assert_eq!(
                PathBuf::from(&plan.bin),
                PathBuf::from(&plan.root).join(ARTIFACT)
            );
        }
    }

    #[test]
    fn missing_home_is_unavailable_without_invented_root_or_artifact_paths() {
        let profile = common::Profile::new();
        let mut environment = profile.environment.clone();
        environment.variables.remove("HOME");
        environment.variables.remove("USERPROFILE");
        let manager = DesktopManager::new(environment);

        let plan = manager.install_plan();
        assert_eq!(plan.status, "unavailable", "{}", plan.reason);
        assert!(plan.root.is_empty(), "{}", plan.root);
        assert!(plan.bin.is_empty(), "{}", plan.bin);
        assert!(plan.path_hint.is_empty(), "{}", plan.path_hint);
        let outcome = manager.install();
        assert_eq!(outcome.status, "unavailable", "{}", outcome.reason);
        assert!(outcome.steps.is_empty());
    }
}

#[cfg(target_os = "linux")]
mod linux {
    use super::common;
    use multi_search_desktop::DesktopManager;
    use std::fs;

    #[test]
    fn bundled_installer_reports_linux_unsupported_without_invented_paths() {
        let profile = common::Profile::new();
        let manager = DesktopManager::new(profile.environment.clone());
        let plan = manager.install_plan();
        assert_eq!(plan.status, "unsupported", "{}", plan.reason);
        assert!(plan.reason.contains("Linux"), "{}", plan.reason);
        assert!(
            plan.root.is_empty(),
            "no install root is invented: {}",
            plan.root
        );
        assert!(
            plan.bin.is_empty(),
            "no artifact path is invented: {}",
            plan.bin
        );
        assert!(!plan.bin.contains(".exe"));
        assert!(
            plan.path_hint.is_empty(),
            "no PATH hint for a bundle that is not installed"
        );
        assert_eq!(plan.compatibility, "unknown");
    }

    #[test]
    fn install_update_and_uninstall_refuse_instead_of_touching_files() {
        let profile = common::Profile::new();
        let manager = DesktopManager::new(profile.environment.clone());
        for outcome in [manager.install(), manager.update(), manager.uninstall()] {
            assert_eq!(outcome.status, "unsupported", "{}", outcome.reason);
            assert!(
                outcome.steps.is_empty(),
                "nothing is attempted: {:?}",
                outcome.steps
            );
        }
        // The isolated profile only ever receives the fixture CLI copied by common::Profile.
        assert_eq!(
            fs::read_dir(&profile.root).unwrap().count(),
            1,
            "no install directory was created"
        );
    }
}
