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
