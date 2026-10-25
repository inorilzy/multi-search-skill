//! Production-path acceptance: the compiled anchor and the real platform root.
//!
//! Unlike `install_real_bundle` (which overrides the install root and the anchor
//! through the test boundary), this test drives the same call the window makes —
//! `install_plan_from(<app resource>/cli-bundle)` and `install_from(...)` — with
//! **no** test-boundary environment at all. It proves the anchor compiled into
//! the binary accepts the shipped manifest and that the layout resolves to the
//! real per-user directory.
//!
//! The user's home is redirected with HOME/USERPROFILE to a disposable profile,
//! so the production *code path* runs while nothing outside the temp dir changes.
#![cfg(not(windows))]
#![cfg(feature = "install-test-boundary")]
mod common;

use multi_search_desktop::{install_fixture, DesktopManager, RuntimeEnvironment};
use std::path::{Path, PathBuf};

fn shipped_bundle() -> PathBuf {
    let dir = std::env::var_os("MULTI_SEARCH_ACCEPTANCE_BUNDLE")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("resources")
                .join("cli-bundle")
        });
    assert!(
        dir.join("manifest.json").is_file(),
        "build the bundle first: python scripts/build_cli_release.py --target macos ..."
    );
    dir
}

/// The production environment: no test keys, only a redirected home.
fn production_environment(profile: &common::Profile) -> RuntimeEnvironment {
    let mut environment = profile.environment.clone();
    for key in [
        "MULTI_SEARCH_TEST_ISOLATION",
        "MULTI_SEARCH_TEST_INSTALL_ANCHOR",
        "MULTI_SEARCH_DESKTOP_INSTALL_ROOT",
        "MULTI_SEARCH_DESKTOP_INSTALL_SOURCE",
    ] {
        environment.variables.remove(key);
    }
    environment
}

#[test]
#[ignore = "needs a built resources/cli-bundle; run with --ignored after building it"]
fn compiled_anchor_accepts_the_shipped_bundle_at_the_real_platform_root() {
    let bundle = shipped_bundle();
    let profile = common::Profile::new();
    let environment = production_environment(&profile);
    let expected_root = PathBuf::from(environment.variables["HOME"].as_str())
        .join("Library")
        .join("Application Support")
        .join("MultiSearch")
        .join("cli");
    let other = DesktopManager::new(environment.clone());

    // -- plan against the real root, trusting only the compiled anchor ---
    let plan = install_fixture::plan(&other, Some(&bundle));
    assert_eq!(plan.status, "ready", "{}", plan.reason);
    assert_eq!(plan.root, expected_root.to_string_lossy());
    assert!(
        plan.bin.ends_with("bin/multi-search"),
        "macOS artifact name: {}",
        plan.bin
    );
    assert_eq!(
        plan.source.as_deref(),
        Some(bundle.to_string_lossy().as_ref()),
        "the app resource bundle is the source"
    );
    assert!(!expected_root.exists(), "a plan never writes");

    // -- install through the production path ----------------------------
    let outcome = install_fixture::install(&other, Some(&bundle));
    assert_eq!(outcome.status, "installed", "{}", outcome.reason);
    let bin = expected_root.join("bin").join("multi-search");
    assert!(bin.is_file(), "installed at {}", bin.display());
    assert_eq!(install_fixture::plan(&other, Some(&bundle)).status, "installed");

    // -- and it is the CLI the desktop will actually run ----------------
    let detected = other.detect_cli();
    assert!(detected.managed, "managed install wins over PATH");
    assert_eq!(detected.execution.status, "ready", "{}", detected.execution.reason);
    assert_eq!(detected.execution.path.as_deref(), Some(bin.to_string_lossy().as_ref()));
    let version = std::process::Command::new(&bin)
        .arg("--version")
        .env_clear()
        .env("HOME", &profile.root)
        .env("PATH", "/usr/bin:/bin")
        .current_dir(&profile.root)
        .output()
        .unwrap();
    assert!(
        version.status.success(),
        "{}",
        String::from_utf8_lossy(&version.stderr)
    );
    assert!(String::from_utf8_lossy(&version.stdout).starts_with("multi-search "));

    // -- update and uninstall through the production path ---------------
    let updated = install_fixture::update(&other, Some(&bundle));
    assert!(
        matches!(updated.status.as_str(), "already_installed" | "installed"),
        "{}: {}",
        updated.status,
        updated.reason
    );
    let removed = other.uninstall();
    assert_eq!(removed.status, "uninstalled", "{}", removed.reason);
    assert!(!bin.exists());
    assert!(!detect_managed(&environment));
}

fn detect_managed(environment: &RuntimeEnvironment) -> bool {
    DesktopManager::new(environment.clone()).detect_cli().managed
}

#[test]
#[ignore = "needs a built resources/cli-bundle; run with --ignored after building it"]
fn a_tampered_shipped_bundle_is_refused_by_the_compiled_anchor() {
    let source = shipped_bundle();
    let profile = common::Profile::new();
    let environment = production_environment(&profile);

    // Copy the shipped bundle and alter one byte: the anchor must refuse it
    // before anything is written, which is what protects a real install.
    let tampered = profile.root.join("tampered-bundle");
    copy_tree(&source, &tampered);
    let manifest = std::fs::read(tampered.join("manifest.json")).unwrap();
    let mut altered = manifest.clone();
    let position = altered.len() / 2;
    altered[position] ^= 0x01;
    std::fs::write(tampered.join("manifest.json"), &altered).unwrap();

    let manager = DesktopManager::new(environment);
    let plan = install_fixture::plan(&manager, Some(&tampered));
    assert_ne!(plan.status, "ready", "a tampered manifest must not be installable");
    assert!(
        plan.reason.contains("锚点") || plan.status == "integrity_failed",
        "status={} reason={}",
        plan.status,
        plan.reason
    );
    let outcome = install_fixture::install(&manager, Some(&tampered));
    assert_ne!(outcome.status, "installed");
    assert!(!Path::new(&plan.root).join("bin/multi-search").exists());
}

fn copy_tree(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).unwrap();
        }
    }
}
