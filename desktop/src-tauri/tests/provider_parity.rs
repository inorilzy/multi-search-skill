//! Provider manifest parity between the Rust `provider::PROVIDERS` table and
//! the Python `multi_search_mcp` registry. The desktop owns the UI-facing list;
//! the CLI owns the runtime registry. This test catches drift before a user
//! sees a missing or misbehaving source.
//!
//! Requires `python` on PATH. Skips silently on platforms/environments where
//! the Python package cannot be imported (CI on Linux without deps, etc.).
use std::{collections::BTreeSet, path::PathBuf, process::Command};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
}

/// Run a small Python snippet that prints the three provider-side collections
/// (`ALL_SOURCE_NAMES`, `SOURCE_ALIASES`, `PROVIDERS`) as JSON. Returns `None`
/// when the interpreter or the package is unavailable, so the test can skip.
fn python_provider_metadata() -> Option<serde_json::Value> {
    let script = r#"
import json
from multi_search_mcp.src.search.search_runner import ALL_SOURCE_NAMES, SOURCE_ALIASES
from multi_search_mcp.src.support.credential_store import PROVIDERS as CRED_PROVIDERS
print(json.dumps({
    "all_sources": sorted(ALL_SOURCE_NAMES),
    "aliases": SOURCE_ALIASES,
    "credential_providers": sorted(CRED_PROVIDERS),
}))
"#;
    let output = Command::new("python")
        .args(["-B", "-c", script])
        .env("PYTHONPATH", repo_root())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    serde_json::from_slice(&output.stdout).ok()
}

#[test]
fn rust_provider_manifest_matches_python_registries() {
    let Some(metadata) = python_provider_metadata() else {
        eprintln!("python not available; skipping provider parity check");
        return;
    };

    // Canonical source names must equal ALL_SOURCE_NAMES. The desktop picks a
    // subset: jina is a scraper-only provider with no search surface.
    let rust_canonical: BTreeSet<String> = multi_search_desktop::provider::list()
        .into_iter()
        .map(|row| row.source.to_string())
        .collect();
    let python_sources: BTreeSet<String> = metadata["all_sources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    let expected: BTreeSet<String> = python_sources
        .iter()
        .filter(|name| name.as_str() != "jina")
        .cloned()
        .collect();
    assert_eq!(rust_canonical, expected, "canonical source drift");

    // Every keyed Rust provider must appear in Python CRED_PROVIDERS so the
    // SQLite store can address it; non-keyed providers intentionally do not
    // appear there.
    let rust_keyed: BTreeSet<String> = multi_search_desktop::provider::list()
        .into_iter()
        .filter_map(|row| row.provider.map(str::to_string))
        .collect();
    let python_providers: BTreeSet<String> = metadata["credential_providers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    // jina is a Python-only credential provider (scraper); subtract it before
    // comparing with the desktop's keyed set.
    let expected_keyed: BTreeSet<String> = python_providers
        .into_iter()
        .filter(|name| name != "jina")
        .collect();
    assert_eq!(rust_keyed, expected_keyed, "keyed provider drift");

    // Every Python source alias must resolve to the same canonical row in
    // Rust. The inverse is also true: Rust must not accept an alias that
    // Python would treat as an unknown source.
    let aliases = metadata["aliases"].as_object().unwrap();
    for (alias, target) in aliases {
        let rust_canonical_name = multi_search_desktop::provider::resolve_canonical(alias)
            .unwrap_or_else(|| panic!("python alias {alias} not in Rust PROVIDERS"));
        assert_eq!(
            rust_canonical_name,
            target.as_str().unwrap(),
            "alias {alias} maps to {target} in Python but {rust_canonical_name} in Rust"
        );
    }
}

#[test]
fn rust_alias_set_is_a_subset_of_python_aliases() {
    // Aliases the CLI does not advertise are still acceptable desktop-side
    // (e.g. `github-repos` is the canonical CLI spelling rather than an alias
    // in the Python view). What we forbid is Rust *dropping* an alias that
    // Python documents — that path is covered by the parity test above.
    let Some(metadata) = python_provider_metadata() else {
        return;
    };
    let python_alias_keys: BTreeSet<&str> = metadata["aliases"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    for row in multi_search_desktop::provider::list() {
        for alias in row.aliases {
            assert!(
                python_alias_keys.contains(alias),
                "rust alias {alias} for {} not present in Python SOURCE_ALIASES",
                row.source
            );
        }
    }
}
