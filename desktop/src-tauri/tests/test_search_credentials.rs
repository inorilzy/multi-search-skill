//! T04: the on-demand test search must pass the credentials its current settings route needs.
//!
//! The child gets exactly the keys of the route's sources (resolved from `config.sqlite`, so
//! custom routes and edited built-in routes work), the fetch-stage keys, and the model-rerank key
//! only while model reranking is enabled. Everything else stays out of the child environment.
mod common;

use multi_search_desktop::{DesktopManager, SearchOptions};
use std::{
    path::PathBuf,
    thread,
    time::{Duration, Instant},
};

fn write_settings_db(profile: &mut common::Profile, name: &str, value: serde_json::Value) -> PathBuf {
    let path = profile.root.join(name);
    let connection = rusqlite::Connection::open(&path).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE credentials(provider TEXT PRIMARY KEY, encrypted_value BLOB NOT NULL, saved_at REAL NOT NULL); \
             CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL); \
             PRAGMA user_version=1;",
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO settings(id,data) VALUES(1,?1)",
            [value.to_string()],
        )
        .unwrap();
    profile.environment.variables.insert(
        "MULTI_SEARCH_CONFIG_DB".into(),
        path.to_string_lossy().into_owned(),
    );
    path
}

fn set_variables(profile: &mut common::Profile, pairs: &[(&str, &str)]) {
    for (name, value) in pairs {
        profile
            .environment
            .variables
            .insert((*name).into(), (*value).into());
    }
}

/// Run the fixture CLI through the real test-search path and return the child variable names.
fn child_env(manager: &DesktopManager, route: &str, sources: &[&str]) -> Vec<String> {
    let id = manager
        .start_search(SearchOptions {
            query: "env".into(),
            route: route.into(),
            sources: sources.iter().map(|source| (*source).into()).collect(),
            timeout: 5,
        })
        .unwrap();
    let started = Instant::now();
    let status = loop {
        let status = manager.execution(id).unwrap();
        if status.status != "running" {
            break status;
        }
        assert!(started.elapsed() < Duration::from_secs(5));
        thread::sleep(Duration::from_millis(10));
    };
    assert_eq!(status.status, "success", "fixture search must succeed");
    status.payload.unwrap()["env"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_str().unwrap().to_string())
        .collect()
}

#[test]
fn custom_route_search_receives_each_route_source_key() {
    let mut profile = common::Profile::new();
    write_settings_db(
        &mut profile,
        "custom-route.sqlite",
        serde_json::json!({
            "type": "custom",
            "routes": {
                "custom": {"label": "Custom", "sources": ["serpapi", "github_repos"]}
            }
        }),
    );
    set_variables(
        &mut profile,
        &[
            ("SERPAPI_API_KEY", "synthetic-serpapi"),
            ("GITHUB_TOKEN", "synthetic-github"),
            ("BRAVE_SEARCH_API_KEY", "synthetic-brave"),
        ],
    );
    let manager = DesktopManager::new(profile.environment.clone());

    let names = child_env(&manager, "custom", &[]);

    assert!(
        names.iter().any(|name| name == "SERPAPI_API_KEY"),
        "SerpAPI is a route member and its key must reach the child: {names:?}"
    );
    assert!(
        names.iter().any(|name| name == "GITHUB_TOKEN"),
        "GitHub is a route member and its token must reach the child: {names:?}"
    );
    assert!(
        !names.iter().any(|name| name == "BRAVE_SEARCH_API_KEY"),
        "a source outside the custom route must not receive its key: {names:?}"
    );
}

#[test]
fn builtin_route_with_edited_sources_uses_settings_keys_instead_of_catalog_keys() {
    let mut profile = common::Profile::new();
    write_settings_db(
        &mut profile,
        "edited-builtin-route.sqlite",
        serde_json::json!({
            "type": "dev",
            "routes": {
                "dev": {"label": "Dev", "sources": ["serpapi"]}
            }
        }),
    );
    set_variables(
        &mut profile,
        &[
            ("SERPAPI_API_KEY", "synthetic-serpapi"),
            ("GITHUB_TOKEN", "synthetic-github"),
        ],
    );
    let manager = DesktopManager::new(profile.environment.clone());

    let names = child_env(&manager, "dev", &[]);

    assert!(
        names.iter().any(|name| name == "SERPAPI_API_KEY"),
        "the edited dev route runs SerpAPI, so its key must reach the child: {names:?}"
    );
    assert!(
        !names.iter().any(|name| name == "GITHUB_TOKEN"),
        "the compiled dev route's GitHub source no longer runs, so its token must stay out: {names:?}"
    );
}

#[test]
fn model_rerank_enabled_passes_systemone_key_to_child() {
    let mut profile = common::Profile::new();
    write_settings_db(
        &mut profile,
        "rerank-enabled.sqlite",
        serde_json::json!({
            "type": "fast",
            "ranking": {
                "mode": "rrf_model",
                "base_url": "http://127.0.0.1:3425/v1",
                "model": "synthetic-model",
                "candidate_limit": 50,
                "batch_size": 20,
                "rerank_timeout": 10
            }
        }),
    );
    set_variables(&mut profile, &[("SYSTEMONE_API_KEY", "synthetic-systemone")]);
    let manager = DesktopManager::new(profile.environment.clone());

    let names = child_env(&manager, "fast", &[]);

    assert!(
        names.iter().any(|name| name == "SYSTEMONE_API_KEY"),
        "model reranking is enabled and the CLI needs its key: {names:?}"
    );
}

#[test]
fn model_rerank_disabled_does_not_pass_systemone_key_to_child() {
    let mut profile = common::Profile::new();
    write_settings_db(
        &mut profile,
        "rerank-disabled.sqlite",
        serde_json::json!({"type": "fast"}),
    );
    set_variables(&mut profile, &[("SYSTEMONE_API_KEY", "synthetic-systemone")]);
    let manager = DesktopManager::new(profile.environment.clone());

    let names = child_env(&manager, "fast", &[]);

    assert!(
        !names.iter().any(|name| name == "SYSTEMONE_API_KEY"),
        "model reranking is off, so its key must not reach the child: {names:?}"
    );
}

#[test]
fn other_secret_marked_variables_still_never_reach_the_child() {
    let mut profile = common::Profile::new();
    write_settings_db(
        &mut profile,
        "custom-route-secrets.sqlite",
        serde_json::json!({
            "type": "custom",
            "routes": {
                "custom": {"label": "Custom", "sources": ["serpapi"]}
            }
        }),
    );
    set_variables(
        &mut profile,
        &[
            ("SERPAPI_API_KEY", "synthetic-serpapi"),
            ("UNRELATED_API_KEY", "synthetic-unrelated"),
            ("AWS_SECRET_ACCESS_KEY", "synthetic-aws"),
            ("DB_PASSWORD", "synthetic-password"),
            ("SOME_TOKEN", "synthetic-token"),
        ],
    );
    let manager = DesktopManager::new(profile.environment.clone());

    let names = child_env(&manager, "custom", &[]);

    assert!(
        names.iter().any(|name| name == "SERPAPI_API_KEY"),
        "the route source's own key is still passed: {names:?}"
    );
    for absent in [
        "UNRELATED_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "DB_PASSWORD",
        "SOME_TOKEN",
    ] {
        assert!(
            !names.iter().any(|name| name == absent),
            "{absent} must not reach the child: {names:?}"
        );
    }
}
