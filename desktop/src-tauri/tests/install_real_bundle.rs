//! Acceptance: the real shipped bundle, installed the way the app installs it.
//!
//! Every other install test uses a synthetic fixture bundle. This one takes the
//! bundle actually produced by `scripts/build_cli_release.py` (the app resource
//! directory) and drives the same `install_plan`/`install`/`update`/`uninstall`
//! transaction, so a bundle that is structurally valid but unusable — wrong
//! interpreter path, missing execute bit, bytecode written into the tree —
//! fails here rather than on a user's machine.
//!
//! Ignored by default: it needs a built `resources/cli-bundle`, and it copies
//! the whole runtime. Run it after building the bundle (see README "macOS"):
//!
//! ```text
//! cargo test --no-default-features --features install-test-boundary \
//!   --test install_real_bundle -- --ignored
//! ```
#![cfg(not(windows))]
#![cfg(feature = "install-test-boundary")]
mod common;

use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

/// The bundle the desktop build would ship.
///
/// `MULTI_SEARCH_ACCEPTANCE_BUNDLE` points at an already packaged copy (for
/// example `<app>/Contents/Resources/cli-bundle`) so the acceptance can prove
/// the *shipped* bytes install, not just the build directory.
fn shipped_bundle() -> Option<PathBuf> {
    let dir = std::env::var_os("MULTI_SEARCH_ACCEPTANCE_BUNDLE")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("resources")
                .join("cli-bundle")
        });
    (dir.join("manifest.json").is_file() && dir.join("bin").is_dir()).then_some(dir)
}

fn anchor_of(bundle: &Path) -> String {
    Sha256::digest(fs::read(bundle.join("manifest.json")).unwrap())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn isolated(
    profile: &common::Profile,
    root: &Path,
    source: &Path,
    anchor: &str,
) -> RuntimeEnvironment {
    let mut environment = profile.environment.clone();
    environment
        .variables
        .insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    for (name, value) in [
        ("MULTI_SEARCH_DESKTOP_INSTALL_ROOT", root),
        ("MULTI_SEARCH_DESKTOP_INSTALL_SOURCE", source),
    ] {
        environment
            .variables
            .insert(name.into(), value.to_string_lossy().into_owned());
    }
    environment
        .variables
        .insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), anchor.to_string());
    environment
}

/// Run the installed CLI from a directory and environment that share nothing with this checkout.
fn run_installed(bin: &Path, home: &Path, args: &[&str]) -> std::process::Output {
    Command::new(bin)
        .args(args)
        .env_clear()
        .env("HOME", home)
        .env("PATH", "/usr/bin:/bin")
        .current_dir(home)
        .output()
        .expect("installed CLI must be executable")
}

fn tree_hashing(root: &Path) -> Vec<(PathBuf, String)> {
    let mut entries: Vec<(PathBuf, String)> = fs::read_dir(root)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .collect::<Vec<_>>()
        .into_iter()
        .filter(|path| path.is_file())
        .map(|path| {
            let digest = Sha256::digest(fs::read(&path).unwrap())
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect();
            (path, digest)
        })
        .collect();
    entries.sort();
    entries
}

#[test]
#[ignore = "needs a built resources/cli-bundle; run with --ignored after building it"]
fn shipped_bundle_installs_probes_updates_and_uninstalls_standalone() {
    let Some(source) = shipped_bundle() else {
        panic!("build the bundle first: python scripts/build_cli_release.py --target macos ...");
    };
    let profile = common::Profile::new();
    let root = profile.root.join("managed-real");
    let anchor = anchor_of(&source);
    let manager = DesktopManager::new(isolated(&profile, &root, &source, &anchor));

    // -- plan ------------------------------------------------------------
    let plan = manager.install_plan();
    assert_eq!(plan.status, "ready", "{}", plan.reason);
    assert!(plan.bin.ends_with("bin/multi-search"), "{}", plan.bin);
    // The bundle's own manifest is the authority for the version it ships.
    let bundled_version: serde_json::Value =
        serde_json::from_slice(&fs::read(source.join("manifest.json")).unwrap()).unwrap();
    let bundled_version = bundled_version["version"].as_str().unwrap().to_string();
    assert_eq!(plan.version.as_deref(), Some(bundled_version.as_str()));

    // -- install ---------------------------------------------------------
    let outcome = manager.install();
    assert_eq!(outcome.status, "installed", "{}", outcome.reason);
    let bin = root.join("bin").join("multi-search");
    assert!(bin.is_file(), "installed artifact exists");

    // The installed CLI must work with no repository, no venv, no PYTHON* variables.
    let version = run_installed(&bin, &root, &["--version"]);
    assert!(
        version.status.success(),
        "installed CLI failed: {}",
        String::from_utf8_lossy(&version.stderr)
    );
    let printed = String::from_utf8_lossy(&version.stdout);
    assert!(printed.starts_with("multi-search "), "{printed:?}");

    let doctor = run_installed(&bin, &root, &["doctor", "--no-keys", "--format", "json"]);
    assert!(
        doctor.status.success(),
        "installed CLI doctor failed: {}",
        String::from_utf8_lossy(&doctor.stderr)
    );
    let payload: serde_json::Value = serde_json::from_slice(&doctor.stdout).unwrap();
    assert!(payload.is_object(), "doctor printed structured output");

    // Running the installed copy must not mutate it: bytecode written back into
    // an installed tree would silently produce an install that no longer verifies.
    let before = tree_hashing(&root.join("bin"));
    let again = run_installed(&bin, &root, &["--version"]);
    assert!(again.status.success());
    assert_eq!(before, tree_hashing(&root.join("bin")), "installed tree stays immutable");
    assert_eq!(manager.install_plan().status, "installed", "still verifies after use");

    // -- update with the same version is a no-op, not a corruption ---------
    let update = manager.update();
    assert!(
        matches!(update.status.as_str(), "already_installed" | "installed"),
        "unexpected update status {}: {}",
        update.status,
        update.reason
    );
    let version = run_installed(&bin, &root, &["--version"]);
    assert!(version.status.success(), "CLI still works after a repeated update");

    // -- uninstall -------------------------------------------------------
    let removed = manager.uninstall();
    assert_eq!(removed.status, "uninstalled", "{}", removed.reason);
    assert!(!bin.exists(), "artifact removed");
    assert!(!root.join("runtime").exists(), "bundled runtime removed with it");
    // The bundle resource is still in the app, so the page correctly offers a
    // fresh install again — but nothing may still claim to be installed.
    assert_eq!(manager.install_plan().status, "ready");
    assert!(!manager.detect_cli().managed, "no managed CLI remains after uninstall");
    assert!(!bin.exists(), "uninstall does not leave an executable behind");
}
