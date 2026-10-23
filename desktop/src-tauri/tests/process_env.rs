//! Ticket 06: the CLI child process must receive a curated environment.
//!
//! The desktop process usually holds provider credentials exported by other
//! tools (`TAVILY_API_KEY`, `GITHUB_TOKEN`, ...). Those must never reach the
//! CLI child, which reads credentials from `config.sqlite` + DPAPI instead.
mod common;

use multi_search_desktop::process_fixture;
use std::collections::BTreeMap;

fn env(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs
        .iter()
        .map(|(name, value)| ((*name).to_string(), (*value).to_string()))
        .collect()
}

#[test]
fn secret_variables_never_reach_the_child_environment() {
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("USERPROFILE", "C:/Users/synthetic"),
        ("TAVILY_API_KEY", "synthetic-tavily-secret"),
        ("BRAVE_SEARCH_API_KEY", "synthetic-brave-secret"),
        ("EXA_API_KEY", "synthetic-exa-secret"),
        ("GITHUB_TOKEN", "synthetic-github-token"),
        ("GH_TOKEN", "synthetic-gh-token"),
        ("FIRECRAWL_API_KEY", "synthetic-firecrawl"),
        ("SERPAPI_KEY", "synthetic-serpapi"),
        ("JINA_KEY", "synthetic-jina"),
        ("MY_APP_SECRET", "synthetic-app-secret"),
        ("DB_PASSWORD", "synthetic-db-password"),
        ("AWS_ACCESS_KEY", "synthetic-aws"),
        ("CLIENT_SECRET", "synthetic-client-secret"),
    ]);
    let child = process_fixture::child_environment(&parent);
    for (name, value) in &parent {
        if name == "PATH" || name == "USERPROFILE" {
            assert_eq!(child.get(name), Some(value), "{name} must be forwarded");
        } else {
            assert!(
                !child.contains_key(name),
                "{name} must not reach the CLI child"
            );
        }
    }
    assert!(child
        .values()
        .all(|value| !value.contains("synthetic-tavily-secret")
            && !value.contains("synthetic-github-token")));
}

#[test]
fn allowlisted_runtime_and_desktop_configuration_variables_are_forwarded() {
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("PATHEXT", ".EXE;.CMD"),
        ("COMSPEC", "C:/Windows/system32/cmd.exe"),
        ("SYSTEMROOT", "C:/Windows"),
        ("SYSTEMDRIVE", "C:"),
        ("WINDIR", "C:/Windows"),
        ("USERPROFILE", "C:/Users/synthetic"),
        ("HOME", "C:/Users/synthetic"),
        ("HOMEDRIVE", "C:"),
        ("HOMEPATH", "\\Users\\synthetic"),
        ("TEMP", "C:/Temp"),
        ("TMP", "C:/Temp"),
        ("TMPDIR", "C:/Temp"),
        ("PYTHONIOENCODING", "utf-8"),
        ("MULTI_SEARCH_CONFIG_DB", "C:/synthetic/config.sqlite"),
        (
            "MULTI_SEARCH_CREDENTIAL_NAMESPACE",
            "synthetic-namespace",
        ),
        ("MULTI_SEARCH_TEST_ISOLATION", "1"),
    ]);
    let child = process_fixture::child_environment(&parent);
    assert_eq!(child, parent, "every allowlisted entry must pass through");
}

#[cfg(feature = "install-test-boundary")]
#[test]
fn acceptance_pythonpath_selector_is_the_only_pythonpath_boundary() {
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("PYTHONPATH", "C:/untrusted/injected"),
        (
            "MULTI_SEARCH_TEST_PYTHONPATH",
            "C:/guarded/bootstrap;C:/guarded/scripts",
        ),
        ("MULTI_SEARCH_TEST_ISOLATION", "1"),
    ]);
    let child = process_fixture::child_environment(&parent);
    assert_eq!(
        child.get("PYTHONPATH").map(String::as_str),
        Some("C:/guarded/bootstrap;C:/guarded/scripts")
    );
    // The desktop-owned selector itself is intentionally forwarded like every
    // existing MULTI_SEARCH_* entry; the protected result is that only its
    // value may become PYTHONPATH.
    assert_eq!(
        child
            .get("MULTI_SEARCH_TEST_PYTHONPATH")
            .map(String::as_str),
        Some("C:/guarded/bootstrap;C:/guarded/scripts")
    );
}

#[cfg(feature = "install-test-boundary")]
#[test]
fn acceptance_pythonpath_requires_the_isolation_marker() {
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("PYTHONPATH", "C:/untrusted/injected"),
        (
            "MULTI_SEARCH_TEST_PYTHONPATH",
            "C:/guarded/bootstrap;C:/guarded/scripts",
        ),
    ]);
    let child = process_fixture::child_environment(&parent);
    assert!(!child.contains_key("PYTHONPATH"));
    assert_eq!(
        child
            .get("MULTI_SEARCH_TEST_PYTHONPATH")
            .map(String::as_str),
        Some("C:/guarded/bootstrap;C:/guarded/scripts")
    );
}

#[cfg(not(feature = "install-test-boundary"))]
#[test]
fn acceptance_pythonpath_selector_does_not_bypass_default_scrub() {
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("PYTHONPATH", "C:/untrusted/injected"),
        (
            "MULTI_SEARCH_TEST_PYTHONPATH",
            "C:/guarded/bootstrap;C:/guarded/scripts",
        ),
        ("MULTI_SEARCH_TEST_ISOLATION", "1"),
    ]);
    let child = process_fixture::child_environment(&parent);
    assert!(!child.contains_key("PYTHONPATH"));
    // MULTI_SEARCH_* is an existing desktop namespace prefix and still passes
    // unchanged; the acceptance-only PYTHONPATH translation is what must not
    // exist in a production/default build.
    assert_eq!(
        child
            .get("MULTI_SEARCH_TEST_PYTHONPATH")
            .map(String::as_str),
        Some("C:/guarded/bootstrap;C:/guarded/scripts")
    );
}

#[test]
fn unrelated_environment_entries_are_not_forwarded() {
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("VISUAL_STUDIO_DIR", "C:/VS"),
        ("RUST_BACKTRACE", "1"),
        ("PROXY", "http://user:pass@proxy.invalid"),
        ("HTTPS_PROXY", "http://user:pass@proxy.invalid"),
        ("PYTHONPATH", "C:/injected"),
        ("COMPlus_EnableDiagnostics", "1"),
    ]);
    let child = process_fixture::child_environment(&parent);
    assert_eq!(child.len(), 1);
    assert_eq!(child.get("PATH").map(String::as_str), Some("C:/Windows"));
}

#[test]
fn secret_marker_filter_is_case_insensitive_and_desktop_namespace_is_exempt() {
    let parent = env(&[
        ("path", "C:/Windows"),
        ("userprofile", "C:/Users/synthetic"),
        ("tavily_api_key", "synthetic-lower"),
        ("Some_Token", "synthetic-mixed"),
        ("MULTI_SEARCH_CONFIG_DB", "C:/synthetic/config.sqlite"),
        ("multi_search_credential_namespace", "synthetic"),
    ]);
    let child = process_fixture::child_environment(&parent);
    assert_eq!(child.get("path").map(String::as_str), Some("C:/Windows"));
    assert_eq!(
        child.get("userprofile").map(String::as_str),
        Some("C:/Users/synthetic")
    );
    assert!(!child.contains_key("tavily_api_key"));
    assert!(!child.contains_key("Some_Token"));
    assert_eq!(
        child.get("MULTI_SEARCH_CONFIG_DB").map(String::as_str),
        Some("C:/synthetic/config.sqlite")
    );
    assert_eq!(
        child
            .get("multi_search_credential_namespace")
            .map(String::as_str),
        Some("synthetic")
    );
}

#[test]
fn empty_environment_produces_empty_child_environment() {
    assert!(process_fixture::child_environment(&BTreeMap::new()).is_empty());
}

/// End-to-end: a real child process is started through `OwnedProcess` with a
/// parent environment full of provider credentials, and the child dumps its
/// own environment. Secrets must be absent; required basics must be present.
#[test]
fn real_child_process_does_not_inherit_provider_credentials() {
    let fixture = common::fixture_cli();
    let fixture = fixture.to_string_lossy().into_owned();

    let root = std::env::temp_dir().join(format!("ms-env-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("USERPROFILE", root.to_str().unwrap()),
        ("HOME", root.to_str().unwrap()),
        ("TEMP", root.to_str().unwrap()),
        ("TMP", root.to_str().unwrap()),
        ("PYTHONIOENCODING", "utf-8"),
        ("MULTI_SEARCH_CONFIG_DB", "C:/synthetic/config.sqlite"),
        ("TAVILY_API_KEY", "synthetic-e2e-tavily"),
        ("GITHUB_TOKEN", "synthetic-e2e-github"),
        ("EXA_API_KEY", "synthetic-e2e-exa"),
    ]);
    let stdout = process_fixture::run(
        std::path::Path::new(&fixture),
        &["env-dump".to_string()],
        parent,
        root.clone(),
    )
    .expect("fixture env-dump must run");
    let child: serde_json::Value = serde_json::from_str(stdout.trim()).unwrap();
    let child = child.as_object().unwrap();

    for (name, value) in [
        ("TAVILY_API_KEY", "synthetic-e2e-tavily"),
        ("GITHUB_TOKEN", "synthetic-e2e-github"),
        ("EXA_API_KEY", "synthetic-e2e-exa"),
    ] {
        assert!(
            !child.contains_key(name),
            "{name} leaked into the real CLI child"
        );
        assert!(
            !child.values().any(|v| v.as_str() == Some(value)),
            "{name} value leaked under another name"
        );
    }
    assert_eq!(child["PYTHONIOENCODING"], "utf-8");
    assert_eq!(child["MULTI_SEARCH_CONFIG_DB"], "C:/synthetic/config.sqlite");
    assert_eq!(child["USERPROFILE"], root.to_str().unwrap());
    assert!(child.contains_key("PATH"));
    assert!(
        !child.contains_key("_"),
        "Windows internal variables are not forwarded"
    );
    let _ = std::fs::remove_dir_all(&root);
}

/// End-to-end in a disabled/default build: `MULTI_SEARCH_TEST_ISOLATION=1`
/// and the desktop-owned selector remain visible, but they cannot become
/// `PYTHONPATH` inside the child. This protects release/default scrubbing
/// even when a test runner accidentally exports the acceptance marker.
#[cfg(not(feature = "install-test-boundary"))]
#[test]
fn real_child_process_default_build_never_maps_acceptance_bootstrap() {
    let fixture = common::fixture_cli();
    let fixture = fixture.to_string_lossy().into_owned();

    let root = std::env::temp_dir().join(format!("ms-env-t2-off-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("USERPROFILE", root.to_str().unwrap()),
        ("HOME", root.to_str().unwrap()),
        ("PYTHONPATH", "C:/must-not-cross"),
        ("MULTI_SEARCH_TEST_ISOLATION", "1"),
        (
            "MULTI_SEARCH_TEST_PYTHONPATH",
            "C:/acceptance/bootstrap;C:/acceptance/scripts",
        ),
    ]);
    let stdout = process_fixture::run(
        std::path::Path::new(&fixture),
        &["env-dump".to_string()],
        parent,
        root.clone(),
    )
    .expect("fixture env-dump must run");
    let child: serde_json::Value = serde_json::from_str(stdout.trim()).unwrap();
    let child = child.as_object().unwrap();

    assert!(!child.contains_key("PYTHONPATH"));
    assert_eq!(child["MULTI_SEARCH_TEST_ISOLATION"], "1");
    assert_eq!(
        child["MULTI_SEARCH_TEST_PYTHONPATH"],
        "C:/acceptance/bootstrap;C:/acceptance/scripts"
    );
    assert!(
        !child.values().any(|value| value.as_str() == Some("C:/must-not-cross")),
        "untrusted PYTHONPATH leaked into the real CLI child"
    );
    let _ = std::fs::remove_dir_all(&root);
}

/// Feature build without the isolation marker: the selector remains visible,
/// but a real Rust-spawned child still receives no PYTHONPATH.
#[cfg(feature = "install-test-boundary")]
#[test]
fn real_child_process_boundary_requires_isolation_marker() {
    let fixture = common::fixture_cli();
    let fixture = fixture.to_string_lossy().into_owned();

    let root = std::env::temp_dir().join(format!("ms-env-t2-noiso-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("USERPROFILE", root.to_str().unwrap()),
        ("HOME", root.to_str().unwrap()),
        ("PYTHONPATH", "C:/must-not-cross"),
        (
            "MULTI_SEARCH_TEST_PYTHONPATH",
            "C:/acceptance/bootstrap;C:/acceptance/scripts",
        ),
    ]);
    let stdout = process_fixture::run(
        std::path::Path::new(&fixture),
        &["env-dump".to_string()],
        parent,
        root.clone(),
    )
    .expect("fixture env-dump must run");
    let child: serde_json::Value = serde_json::from_str(stdout.trim()).unwrap();
    let child = child.as_object().unwrap();

    assert!(!child.contains_key("PYTHONPATH"));
    assert_eq!(
        child["MULTI_SEARCH_TEST_PYTHONPATH"],
        "C:/acceptance/bootstrap;C:/acceptance/scripts"
    );
    assert!(
        !child.values().any(|value| value.as_str() == Some("C:/must-not-cross")),
        "untrusted PYTHONPATH leaked into the real CLI child"
    );
    let _ = std::fs::remove_dir_all(&root);
}

/// End-to-end: the same real child boundary proves the acceptance-only
/// selector becomes PYTHONPATH inside the CLI process. The parent never sets a
/// real PYTHONPATH, so this cannot weaken default environment scrubbing.
#[cfg(feature = "install-test-boundary")]
#[test]
fn real_child_process_maps_acceptance_pythonpath_selector_only() {
    let fixture = common::fixture_cli();
    let fixture = fixture.to_string_lossy().into_owned();

    let root = std::env::temp_dir().join(format!("ms-env-t2-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let parent = env(&[
        ("PATH", "C:/Windows"),
        ("USERPROFILE", root.to_str().unwrap()),
        ("HOME", root.to_str().unwrap()),
        ("PYTHONIOENCODING", "utf-8"),
        ("PYTHONPATH", "C:/must-not-cross"),
        ("MULTI_SEARCH_TEST_ISOLATION", "1"),
        (
            "MULTI_SEARCH_TEST_PYTHONPATH",
            "C:/acceptance/bootstrap;C:/acceptance/scripts",
        ),
    ]);
    let stdout = process_fixture::run(
        std::path::Path::new(&fixture),
        &["env-dump".to_string()],
        parent,
        root.clone(),
    )
    .expect("fixture env-dump must run");
    let child: serde_json::Value = serde_json::from_str(stdout.trim()).unwrap();
    let child = child.as_object().unwrap();

    assert_eq!(
        child["PYTHONPATH"],
        "C:/acceptance/bootstrap;C:/acceptance/scripts"
    );
    assert_eq!(
        child["MULTI_SEARCH_TEST_PYTHONPATH"],
        "C:/acceptance/bootstrap;C:/acceptance/scripts"
    );
    assert!(
        !child.values().any(|value| value.as_str() == Some("C:/must-not-cross")),
        "untrusted PYTHONPATH leaked into the real CLI child"
    );
    let _ = std::fs::remove_dir_all(&root);
}
