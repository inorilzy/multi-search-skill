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
    tauri_build::build();
}
