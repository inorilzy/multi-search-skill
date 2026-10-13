mod common;
use multi_search_desktop::{DesktopManager, RuntimeEnvironment};
use sha2::{Digest, Sha256};
use std::{fs, path::{Path, PathBuf}};

fn hex(path: &Path) -> (String, u64) {
    let bytes = fs::read(path).unwrap();
    let digest = Sha256::digest(&bytes);
    (digest.iter().map(|b| format!("{b:02x}")).collect(), bytes.len() as u64)
}

/// Writes a directory-runtime bundle: `bin/multi-search.exe` plus a manifest listing it.
/// `sha` overrides the listed digest to model a corrupt artifact.
fn source(profile: &common::Profile, name: &str, version: &str, sha: Option<&str>) -> PathBuf {
    let dir = profile.root.join(name);
    fs::create_dir_all(dir.join("bin")).unwrap();
    let artifact = dir.join("bin").join("multi-search.exe");
    fs::copy(profile.root.join("multi-search.exe"), &artifact).unwrap();
    let (digest, size) = hex(&artifact);
    let digest = sha.map(str::to_string).unwrap_or(digest);
    fs::write(
        dir.join("manifest.json"),
        format!(
            r#"{{"schema":1,"version":"{version}","files":[{{"path":"bin/multi-search.exe","size":{size},"sha256":"{digest}"}}]}}"#
        ),
    )
    .unwrap();
    dir
}

/// Test anchor for a source: the SHA-256 of its raw manifest bytes, injected only in tests.
fn anchor_of(source: &Path) -> String {
    let (digest, _) = hex(&source.join("manifest.json"));
    digest
}

fn env(profile: &common::Profile, root: &Path, source: Option<&Path>) -> RuntimeEnvironment {
    let mut environment = profile.environment.clone();
    environment.variables.insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    environment.variables.insert(
        "MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(),
        root.to_string_lossy().into_owned(),
    );
    if let Some(source) = source {
        environment.variables.insert(
            "MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(),
            source.to_string_lossy().into_owned(),
        );
        if source.join("manifest.json").is_file() {
            environment.variables.insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), anchor_of(source));
        }
    }
    environment
}

#[test]
fn production_without_controlled_source_changes_nothing() {
    let profile = common::Profile::new();
    let localappdata = profile.root.join("localappdata");
    let mut environment = profile.environment.clone();
    environment
        .variables
        .insert("LOCALAPPDATA".into(), localappdata.to_string_lossy().into_owned());
    let manager = DesktopManager::new(environment);
    let plan = manager.install_plan();
    assert_eq!(plan.status, "prerequisite_missing");
    let outcome = manager.install();
    assert_eq!(outcome.status, "prerequisite_missing");
    assert!(outcome.steps.is_empty());
    assert!(!localappdata.exists());
}

#[test]
fn isolated_first_install_verifies_activates_and_is_idempotent() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-a");
    let src = source(&profile, "src-ok", "0.4.0", None);
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "ready");

    let outcome = manager.install();
    assert_eq!(outcome.status, "installed", "{}", outcome.reason);
    assert_eq!(outcome.version.as_deref(), Some("0.4.0"));
    let bin = root.join("bin").join("multi-search.exe");
    assert!(bin.is_file());
    assert!(outcome.path_hint.contains("PATH"));
    assert!(outcome.steps.iter().all(|s| s.ok));
    assert!(!fs::read_dir(&root).unwrap().any(|e| e.unwrap().file_name().to_string_lossy().starts_with("staging-")));

    assert_eq!(manager.install_plan().status, "installed");
    let again = manager.install();
    assert_eq!(again.status, "already_installed", "{}", again.reason);
    assert!(again.reason.contains("0.4.0"));
    assert!(bin.is_file());
}

#[test]
fn explicit_user_path_consent_enables_discovery_and_skill_without_restarting_app() {
    use multi_search_desktop::user_path::{MemoryPathStore, PathValue};
    use std::sync::Arc;
    let profile = common::Profile::new();
    let root = profile.root.join("onboarding");
    let src = source(&profile, "onboarding-source", "0.4.0", None);
    let mut environment = env(&profile, &root, Some(&src));
    environment.app_path.clear();
    environment.user_path.clear();
    let store = Arc::new(MemoryPathStore::new(PathValue::expandable("%SystemRoot%\\System32")));
    let manager = DesktopManager::with_user_path_store(environment, store.clone());
    assert_eq!(manager.install().status, "installed");
    assert_eq!(manager.skill_plan("global", None).status, "cli_missing");
    assert_eq!(manager.user_path_change(false, false).unwrap().status, "confirmation_required");
    assert_eq!(store.value().text, "%SystemRoot%\\System32");
    assert_eq!(manager.user_path_change(false, true).unwrap().status, "added");
    assert_eq!(manager.detect_cli(None).user.status, "ready");
    assert_eq!(manager.detect_cli(None).app.status, "missing");
    assert_eq!(manager.execution_cli(None).unwrap(), root.join("bin/multi-search.exe"));
    assert!(manager.detect_cli(None).restart_required);
    assert_eq!(manager.skill_plan("global", None).status, "ready");
    assert_eq!(manager.skill_install("global", None).status, "installed");
    assert_eq!(manager.user_path_change(true, true).unwrap().status, "removed");
    assert_eq!(store.value().text, "%SystemRoot%\\System32");
    assert_eq!(manager.detect_cli(None).user.status, "missing");
}

#[test]
fn path_registration_preserves_existing_spelling_type_and_user_changes() {
    use multi_search_desktop::user_path::{MemoryPathStore, PathStore, PathValue};
    use std::sync::Arc;
    let profile = common::Profile::new();
    let root = profile.root.join("path-owned");
    let src = source(&profile, "path-source", "0.4.0", None);
    let mut environment = env(&profile, &root, Some(&src));
    environment.variables.insert("OUR_CLI".into(), root.join("bin").to_string_lossy().into_owned());
    let original = PathValue { text: "%SystemRoot%\\System32;%our_cli%\\;C:\\Keep".into(), kind: 1, exists: true };
    let store = Arc::new(MemoryPathStore::new(original.clone()));
    let manager = DesktopManager::with_user_path_store(environment, store.clone());
    assert_eq!(manager.install().status, "installed");
    assert_eq!(manager.user_path_change(false, true).unwrap().status, "existing");
    assert_eq!(store.value(), original);
    assert!(manager.user_path_change(true, true).is_err());
    let before = PathValue { text: "C:\\Keep;;%SystemRoot%\\System32;".into(), kind: 1, exists: true };
    store.compare_write(&original, &before, None).unwrap();
    assert_eq!(manager.user_path_change(false, true).unwrap().status, "added");
    assert_eq!(store.value().kind, 1);
    assert_eq!(store.value().text, format!("{};{}", before.text, root.join("bin").display()));
    let owned = store.value();
    let mut changed = owned.clone(); changed.text.push_str(";C:\\UserAdded");
    store.compare_write(&owned, &changed, store.receipt().unwrap().as_ref()).unwrap();
    assert!(!manager.user_path_plan().unwrap().can_remove);
    assert!(manager.user_path_change(true, true).is_err());
    assert_eq!(store.value(), changed);
    assert!(store.compare_write(&owned, &before, None).is_err());
    assert_eq!(store.value(), changed);
}

#[test]
fn native_registry_path_roundtrip_uses_only_a_dedicated_acceptance_key() {
    use multi_search_desktop::user_path::{NativePathStore, PathStore, PathValue};
    use windows_sys::Win32::System::Registry::*;
    let key = format!("Software\\MultiSearchAcceptance\\path-{}", std::process::id());
    let store = NativePathStore::isolated_key(&key).unwrap();
    let before = store.read().unwrap();
    assert!(!before.exists);
    let desired = PathValue { text: "%SystemRoot%\\System32;;C:\\Keep;".into(), kind: 1, exists: true };
    store.compare_write(&before, &desired, None).unwrap();
    assert_eq!(store.read().unwrap(), desired);
    assert!(store.compare_write(&before, &before, None).is_err());
    store.compare_write(&desired, &before, None).unwrap();
    assert_eq!(store.read().unwrap(), before);
    let key: Vec<u16> = key.encode_utf16().chain(Some(0)).collect();
    assert_eq!(unsafe { RegDeleteTreeW(HKEY_CURRENT_USER, key.as_ptr()) }, 0);
}

#[test]
fn checksum_mismatch_refuses_before_touching_the_install_root() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-bad");
    let src = source(&profile, "src-bad", "0.4.0", Some(&"0".repeat(64)));
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    let outcome = manager.install();
    assert_eq!(outcome.status, "integrity_failed");
    assert!(outcome.bin.is_none());
    assert!(!root.exists());
}

#[test]
fn missing_manifest_is_a_prerequisite_failure() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-missing");
    let src = profile.root.join("src-no-manifest");
    fs::create_dir_all(&src).unwrap();
    fs::copy(profile.root.join("multi-search.exe"), src.join("multi-search.exe")).unwrap();
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "prerequisite_missing");
    assert_eq!(manager.install().status, "prerequisite_missing");
    assert!(!root.exists());
}

#[test]
fn unknown_existing_installation_is_never_overwritten() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-unknown");
    fs::create_dir_all(root.join("bin")).unwrap();
    let foreign = root.join("bin").join("multi-search.exe");
    fs::write(&foreign, b"user managed copy").unwrap();
    let src = source(&profile, "src-unknown", "0.4.0", None);
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "unknown_existing");
    let outcome = manager.install();
    assert_eq!(outcome.status, "unknown_existing");
    assert_eq!(fs::read(&foreign).unwrap(), b"user managed copy");
    assert!(!root.join("active.json").exists());
    assert!(!root.join("multi-search-install.json").exists());
}

#[test]
fn version_probe_failure_keeps_no_active_install_and_retry_succeeds() {
    let mut profile = common::Profile::new();
    let root = profile.root.join("install-retry");
    let src = source(&profile, "src-retry", "0.4.0", None);

    profile.environment.variables.insert("FIXTURE_VERSION".into(), "fail".into());
    let failing = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(failing.status, "failed");
    assert!(failing.bin.is_none());
    assert!(!root.join("bin").join("multi-search.exe").exists());
    assert!(!root.join("active.json").exists());
    assert_eq!(DesktopManager::new(env(&profile, &root, Some(&src))).install_plan().status, "ready");

    profile.environment.variables.remove("FIXTURE_VERSION");
    let retried = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(retried.status, "installed", "{}", retried.reason);
    assert!(root.join("active.json").is_file());
}

#[test]
fn manifest_version_must_match_the_probed_cli() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-version");
    let src = source(&profile, "src-version", "0.5.0", None);
    let outcome = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(outcome.status, "failed");
    assert!(!root.join("active.json").exists());
    assert!(!root.join("bin").join("multi-search.exe").exists());
}

/// Writes a directory-runtime source whose manifest the test anchor vouches for.
fn bundle_source(profile: &common::Profile, name: &str, anchor: &str) -> (PathBuf, String) {
    let dir = profile.root.join(name);
    fs::create_dir_all(dir.join("bin")).unwrap();
    fs::copy(profile.root.join("multi-search.exe"), dir.join("bin").join("multi-search.exe")).unwrap();
    let (digest, size) = hex(&dir.join("bin").join("multi-search.exe"));
    let manifest = format!(
        r#"{{"schema":1,"version":"0.4.0","files":[{{"path":"bin/multi-search.exe","size":{size},"sha256":"{digest}"}}]}}"#
    );
    fs::write(dir.join("manifest.json"), &manifest).unwrap();
    let _ = anchor;
    (dir, manifest)
}

#[test]
fn manifest_whose_raw_bytes_do_not_match_the_anchor_is_refused_before_parsing() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-anchor");
    let (src, _manifest) = bundle_source(&profile, "src-anchor", "");
    // Wrong anchor: the manifest bytes must be rejected even though they are valid JSON.
    let mut environment = env(&profile, &root, Some(&src));
    environment
        .variables
        .insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), "0".repeat(64));
    let outcome = DesktopManager::new(environment).install();
    assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
    assert!(outcome.reason.contains("信任锚点"), "{}", outcome.reason);
    assert!(!root.exists());
}

/// Independent negative fixtures: the manifest is written by hand (not by `source`), so a bug in
/// the fixture generator cannot hide a bug in the validator.
fn exe_entry(profile: &common::Profile, path: &str) -> serde_json::Value {
    let (sha256, size) = hex(&profile.root.join("multi-search.exe"));
    serde_json::json!({ "path": path, "size": size, "sha256": sha256 })
}

fn manifest_bytes(version: &str, files: Vec<serde_json::Value>) -> Vec<u8> {
    serde_json::to_vec_pretty(&serde_json::json!({ "schema": 1, "version": version, "files": files })).unwrap()
}

fn bundle_at(profile: &common::Profile, name: &str, manifest: &[u8]) -> PathBuf {
    let dir = profile.root.join(name);
    fs::create_dir_all(dir.join("bin")).unwrap();
    fs::copy(profile.root.join("multi-search.exe"), dir.join("bin").join("multi-search.exe")).unwrap();
    fs::write(dir.join("manifest.json"), manifest).unwrap();
    dir
}

#[test]
fn tampered_artifact_bound_to_a_correct_manifest_is_refused() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-tamper-file");
    let src = source(&profile, "src-tamper-file", "0.4.0", None);
    let exe = src.join("bin").join("multi-search.exe");
    let mut bytes = fs::read(&exe).unwrap();
    bytes[0] ^= 0xff; // same size, different content: only the SHA-256 check can catch it
    fs::write(&exe, &bytes).unwrap();
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "integrity_failed");
    let outcome = manager.install();
    assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
    assert!(outcome.reason.contains("SHA-256"), "{}", outcome.reason);
    assert!(!root.exists());
}

#[test]
fn manifest_bytes_altered_after_binding_fail_the_anchor_before_parsing() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-tamper-manifest");
    let src = source(&profile, "src-tamper-manifest", "0.4.0", None);
    let bound_anchor = anchor_of(&src);
    let mut bytes = fs::read(src.join("manifest.json")).unwrap();
    bytes.push(b'\n'); // still valid JSON: only the raw-byte anchor can reject it
    fs::write(src.join("manifest.json"), &bytes).unwrap();
    let mut environment = env(&profile, &root, Some(&src));
    environment.variables.insert("MULTI_SEARCH_TEST_INSTALL_ANCHOR".into(), bound_anchor);
    let outcome = DesktopManager::new(environment).install();
    assert_eq!(outcome.status, "integrity_failed", "{}", outcome.reason);
    assert!(outcome.reason.contains("信任锚点"), "{}", outcome.reason);
    assert!(!root.exists());
}

#[test]
fn listed_file_missing_from_a_bound_bundle_is_a_prerequisite_failure() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-missing-listed");
    let src = source(&profile, "src-missing-listed", "0.4.0", None);
    fs::remove_file(src.join("bin").join("multi-search.exe")).unwrap();
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install_plan().status, "prerequisite_missing");
    let outcome = manager.install();
    assert_eq!(outcome.status, "prerequisite_missing", "{}", outcome.reason);
    assert!(!root.exists());
}

#[test]
fn unsafe_or_out_of_bounds_paths_in_a_bound_manifest_are_refused() {
    let profile = common::Profile::new();
    let bad_paths = [
        "../escape.exe",
        "bin/../../escape.exe",
        "/abs/multi-search.exe",
        "C:/multi-search.exe",
        "bin\\multi-search.exe",
        "bin/multi-search.exe:stream",
        "bin//multi-search.exe",
        "./bin/multi-search.exe",
        "bin/CON",
        "bin/multi-search.exe.",
        "\\\\server\\share\\multi-search.exe",
    ];
    for (index, bad) in bad_paths.iter().enumerate() {
        let manifest = manifest_bytes("0.4.0", vec![exe_entry(&profile, bad)]);
        let src = bundle_at(&profile, &format!("src-bad-path-{index}"), &manifest);
        let root = profile.root.join(format!("install-bad-path-{index}"));
        let outcome = DesktopManager::new(env(&profile, &root, Some(&src))).install();
        assert_eq!(outcome.status, "integrity_failed", "path {bad:?}: {}", outcome.reason);
        assert!(!root.exists(), "path {bad:?} touched the install root");
    }
}

#[test]
fn duplicate_and_case_conflicting_paths_in_a_bound_manifest_are_refused() {
    let profile = common::Profile::new();
    let cases = [
        vec![exe_entry(&profile, "bin/multi-search.exe"), exe_entry(&profile, "bin/multi-search.exe")],
        vec![exe_entry(&profile, "bin/multi-search.exe"), exe_entry(&profile, "BIN/Multi-Search.exe")],
    ];
    for (index, files) in cases.into_iter().enumerate() {
        let manifest = manifest_bytes("0.4.0", files);
        let src = bundle_at(&profile, &format!("src-dup-{index}"), &manifest);
        let root = profile.root.join(format!("install-dup-{index}"));
        let outcome = DesktopManager::new(env(&profile, &root, Some(&src))).install();
        assert_eq!(outcome.status, "integrity_failed", "case {index}: {}", outcome.reason);
        assert!(!root.exists(), "case {index} touched the install root");
    }
}

#[test]
fn unrecorded_residue_is_preserved_and_requires_explicit_recovery() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-interrupted");
    fs::create_dir_all(root.join("staging-111").join("bin")).unwrap();
    fs::write(root.join("staging-111").join("bin").join("multi-search.exe"), b"partial").unwrap();
    fs::create_dir_all(root.join("bin")).unwrap();
    fs::write(root.join("bin").join("multi-search.exe"), b"half written").unwrap();
    fs::write(
        root.join("multi-search-install.json"),
        r#"{"owner":"multi-search-desktop","schema":1}"#,
    )
    .unwrap();
    let src = source(&profile, "src-interrupted", "0.4.0", None);
    let outcome = DesktopManager::new(env(&profile, &root, Some(&src))).install();
    assert_eq!(outcome.status, "unknown_existing", "{}", outcome.reason);
    assert_eq!(fs::read(root.join("staging-111/bin/multi-search.exe")).unwrap(), b"partial");
    assert_eq!(fs::read(root.join("bin/multi-search.exe")).unwrap(), b"half written");
    assert!(!root.join("active.json").exists());
}

/// Real-bundle acceptance: run with `MULTI_SEARCH_REAL_BUNDLE=<dir> cargo test -- --ignored`.
/// No anchor override is injected, so the bundle must verify against the compiled-in trust anchor.
#[test]
#[ignore]
fn real_bundle_installs_against_the_compiled_anchor() {
    // Explicit (`--ignored`) runs must never pass vacuously: the bundle path is required.
    let bundle = std::env::var("MULTI_SEARCH_REAL_BUNDLE").unwrap_or_else(|_| {
        panic!(
            "real-bundle acceptance requires MULTI_SEARCH_REAL_BUNDLE=<dir containing manifest.json, bin/, runtime/>; \
             build it with scripts/build_cli_release.py and rerun with --ignored"
        )
    });
    let profile = common::Profile::new();
    let root = profile.root.join("install-real");
    let mut environment = profile.environment.clone();
    environment.variables.insert("MULTI_SEARCH_TEST_ISOLATION".into(), "1".into());
    // Windows CPython needs SYSTEMROOT to initialise TLS; production inherits it via
    // RuntimeEnvironment::system(), so the acceptance profile must carry it too.
    if let Ok(system_root) = std::env::var("SYSTEMROOT") {
        environment.variables.insert("SYSTEMROOT".into(), system_root);
    }
    environment.variables.insert(
        "MULTI_SEARCH_DESKTOP_INSTALL_ROOT".into(),
        root.to_string_lossy().into_owned(),
    );
    environment
        .variables
        .insert("MULTI_SEARCH_DESKTOP_INSTALL_SOURCE".into(), bundle);
    let manager = DesktopManager::new(environment);
    assert_eq!(manager.install_plan().status, "ready");
    let outcome = manager.install();
    assert_eq!(outcome.status, "installed", "{}", outcome.reason);
    assert_eq!(outcome.version.as_deref(), Some("0.4.0"));
    assert!(root.join("runtime").join("python.exe").is_file());
}

#[test]
fn installed_cli_tampered_after_install_is_not_reported_as_installed() {
    let profile = common::Profile::new();
    let root = profile.root.join("install-post-tamper");
    let src = source(&profile, "src-post-tamper", "0.4.0", None);
    let manager = DesktopManager::new(env(&profile, &root, Some(&src)));
    assert_eq!(manager.install().status, "installed");
    let mut bytes = fs::read(root.join("bin").join("multi-search.exe")).unwrap();
    bytes[0] ^= 0xff;
    fs::write(root.join("bin").join("multi-search.exe"), &bytes).unwrap();
    assert_ne!(manager.install_plan().status, "installed");
}
