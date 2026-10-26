use std::{env, fs, path::PathBuf};

/// Binds the CLI bundle trust anchor for this build.
///
/// The anchor is the SHA-256 of the bundle's raw `manifest.json`, written by `scripts/build_cli_bundle.py`
/// (`--anchor-out`). Source of truth, in order: `MULTI_SEARCH_CLI_BUNDLE_ANCHOR` (64 hex), then
/// `resources/cli-bundle.anchor` next to this crate. When neither exists the anchor is empty and the
/// installer reports `prerequisite_missing` at runtime instead of trusting a stale or guessed value.
fn main() {
    if env::var("PROFILE").as_deref() == Ok("release") && env::var_os("CARGO_FEATURE_INSTALL_TEST_BOUNDARY").is_some() {
        panic!("install-test-boundary is acceptance-only and cannot be packaged in a release build");
    }
    if env::var("PROFILE").as_deref() == Ok("release") && env::var_os("CARGO_FEATURE_TEST_FIXTURES").is_some() {
        panic!("test-fixtures exposes test-only seams and cannot be packaged in a release build");
    }
    println!("cargo:rerun-if-env-changed=MULTI_SEARCH_CLI_BUNDLE_ANCHOR");
    println!("cargo:rerun-if-changed=resources/cli-bundle.anchor");
    let anchor = match env::var("MULTI_SEARCH_CLI_BUNDLE_ANCHOR") {
        Ok(value) => value,
        Err(_) => fs::read_to_string(PathBuf::from("resources").join("cli-bundle.anchor")).unwrap_or_default(),
    };
    let anchor = anchor.trim().to_ascii_lowercase();
    if !anchor.is_empty() && (anchor.len() != 64 || !anchor.bytes().all(|b| b.is_ascii_hexdigit())) {
        panic!("CLI bundle anchor must be 64 hex characters");
    }
    println!("cargo:rustc-env=MULTI_SEARCH_CLI_BUNDLE_ANCHOR={anchor}");

    #[cfg(feature = "native-window")]
    {
        // Declaring the app manifest turns on ACL checks for app commands: the main window may only
        // call what `capabilities/management.json` grants, and nothing outside this list exists.
        let attributes = tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(APP_COMMANDS));
        tauri_build::try_build(attributes).expect("failed to run tauri-build");
    }
}

/// Every `#[tauri::command]` registered in `src/window.rs`. `desktop/tests/ipc-boundary.test.js` keeps this,
/// the handler list and the capability file in step.
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
const APP_COMMANDS: &[&str] = &[
    "cookie_status",
    "cookie_import",
    "cookie_delete",
    "detect_cli",
    "start_test_search",
    "poll_execution",
    "cancel_test_search",
    "skill_plan",
    "skill_install",
    "install_plan",
    "install_cli",
    "skill_status",
    "skill_update",
    "skill_remove_plan",
    "skill_remove",
    "update_cli",
    "uninstall_cli",
    "user_path_plan",
    "user_path_change",
    "credential_status",
    "credential_read",
    "credential_reveal",
    "credential_application_open",
    "credential_save",
    "credential_delete",
    "credential_test",
    "credential_append",
    "credential_remove",
    "migration_plan",
    "migration_apply",
    "settings_view",
    "settings_save",
    "scrape_settings_save",
    "rerank_key_save",
    "provider_list",
    "scrape_memory_view",
    "scrape_memory_pin",
    "scrape_memory_reset",
];
