//! SQLite settings against disposable paths only. Legacy JSON/env are not configuration sources.
use multi_search_desktop::{
    settings_fixture::{self as fixture, RouteConfig, RouteMap, SettingsInput},
    RuntimeEnvironment,
};
use std::{collections::BTreeMap, path::PathBuf};
struct Sandbox(PathBuf);
impl Sandbox {
    fn new(tag: &str) -> Self {
        let p =
            std::env::temp_dir().join(format!("ms-sqlite-settings-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&p);
        std::fs::create_dir_all(&p).unwrap();
        Self(p)
    }
    fn db(&self) -> PathBuf {
        self.0.join(".multi-search/config.sqlite")
    }
    fn env(&self, extra: &[(&str, String)]) -> RuntimeEnvironment {
        let mut variables =
            BTreeMap::from([("USERPROFILE".into(), self.0.to_string_lossy().into_owned())]);
        for (k, v) in extra {
            variables.insert((*k).into(), v.clone());
        }
        RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables,
            cwd: self.0.clone(),
        }
    }
    fn object(&self) -> serde_json::Value {
        let c = rusqlite::Connection::open(self.db()).unwrap();
        let s: String = c
            .query_row("SELECT data FROM settings WHERE id=1", [], |r| r.get(0))
            .unwrap();
        serde_json::from_str(&s).unwrap()
    }
    fn replace(&self, body: &str) {
        let c = rusqlite::Connection::open(self.db()).unwrap();
        c.execute("UPDATE settings SET data=?1 WHERE id=1", [body])
            .unwrap();
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn input(route: &str, timeout: u32, disabled: &[&str]) -> SettingsInput {
    SettingsInput {
        route: route.into(),
        timeout,
        disabled_sources: disabled.iter().map(|s| s.to_string()).collect(),
        routes: None,
        twitter_cookies_path: None,
    }
}
#[test]
fn save_canonical_sources_into_versioned_sqlite() {
    let s = Sandbox::new("canonical");
    let v = fixture::save(
        &s.env(&[]),
        &input("fast", 30, &["v2ex", "brave", "github", "brave"]),
    )
    .unwrap();
    assert_eq!(
        s.object()["disabled_sources"],
        serde_json::json!(["brave", "github_repos", "sov2ex"])
    );
    assert_eq!(v.route, "fast");
    assert_eq!(v.read_source, "sqlite");
    let c = rusqlite::Connection::open(s.db()).unwrap();
    assert_eq!(
        c.pragma_query_value::<i64, _>(None, "user_version", |r| r.get(0))
            .unwrap(),
        1
    );
    assert_eq!(
        c.query_row::<i64, _, _>("SELECT count(*) FROM settings", [], |r| r.get(0))
            .unwrap(),
        1
    );
}
#[test]
fn unknown_fields_preserved() {
    let s = Sandbox::new("unknown");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(
        r#"{"count":7,"no_scrape":true,"counts":{"brave":3},"future_field":{"nested":[1,2]}}"#,
    );
    fixture::save(&e, &input("dev", 45, &["tavily"])).unwrap();
    let o = s.object();
    assert_eq!(o["count"], 7);
    assert_eq!(o["counts"]["brave"], 3);
    assert_eq!(o["future_field"]["nested"], serde_json::json!([1, 2]));
    assert_eq!(o["no_scrape"], true);
}
#[test]
fn invalid_input_does_not_change_database() {
    let s = Sandbox::new("invalid");
    let e = s.env(&[]);
    fixture::save(&e, &input("dev", 20, &[])).unwrap();
    let before = std::fs::read(s.db()).unwrap();
    for bad in [
        input("nope", 20, &[]),
        input("dev", 0, &[]),
        input("dev", 61, &[]),
        input("dev", 20, &["jina"]),
        input("dev", 20, &["../../etc"]),
        SettingsInput {
            twitter_cookies_path: Some("bad\0path".into()),
            ..input("dev", 20, &[])
        },
        SettingsInput {
            twitter_cookies_path: Some("x".repeat(2000)),
            ..input("dev", 20, &[])
        },
    ] {
        assert!(fixture::save(&e, &bad).is_err());
        assert_eq!(std::fs::read(s.db()).unwrap(), before);
    }
}
#[test]
fn malformed_settings_block_save_and_roll_back() {
    let s = Sandbox::new("bad-json");
    let e = s.env(&[]);
    fixture::save(&e, &input("dev", 20, &[])).unwrap();
    s.replace("{ not json");
    let before = std::fs::read(s.db()).unwrap();
    assert!(fixture::save(&e, &input("default", 60, &[]))
        .unwrap_err()
        .contains("未保存"));
    assert_eq!(std::fs::read(s.db()).unwrap(), before);
    assert_eq!(fixture::view(&e).status, "config_unreadable");
}
#[test]
fn explicit_db_is_only_target() {
    let s = Sandbox::new("isolate");
    let custom = s.0.join("custom/config.sqlite");
    let e = s.env(&[(
        "MULTI_SEARCH_CONFIG_DB",
        custom.to_string_lossy().into_owned(),
    )]);
    assert_eq!(fixture::config_path(&e).unwrap(), custom);
    let v = fixture::save(&e, &input("social", 10, &["twitter"])).unwrap();
    assert!(custom.exists());
    assert!(!s.db().exists());
    assert_eq!(v.path_source, "env");
    assert_eq!(v.status, "no_active_source");
}
#[test]
fn twitter_is_path_only_and_env_never_overrides() {
    let s = Sandbox::new("twitter");
    let e = s.env(&[("TWITTER_COOKIES_PATH", "C:/secret/env.json".into())]);
    let mut i = input("social", 60, &[]);
    i.twitter_cookies_path = Some(" C:/cookies/saved.json ".into());
    let v = fixture::save(&e, &i).unwrap();
    assert_eq!(s.object()["twitter_cookies_path"], "C:/cookies/saved.json");
    assert!(!serde_json::to_value(&v)
        .unwrap()
        .as_object()
        .unwrap()
        .contains_key("twitter_env_overrides"));
    assert_eq!(v.active_sources, vec!["twitter"]);
    fixture::save(&e, &input("social", 60, &[])).unwrap();
    assert!(s.object().get("twitter_cookies_path").is_none());
}
#[test]
fn all_route_sources_disabled_is_truthful() {
    let s = Sandbox::new("all-disabled");
    let v = fixture::save(
        &s.env(&[]),
        &input(
            "default",
            60,
            &[
                "baidu",
                "brave",
                "exa",
                "firecrawl",
                "parallel",
                "serpapi",
                "tavily",
            ],
        ),
    )
    .unwrap();
    assert!(v.active_sources.is_empty());
    assert_eq!(v.status, "no_active_source");
    assert_eq!(s.object()["disabled_sources"].as_array().unwrap().len(), 7);
}
#[test]
fn toggle_source_preserves_other_settings() {
    let s = Sandbox::new("toggle");
    let e = s.env(&[]);
    fixture::save(&e, &input("fast", 25, &["baidu", "exa"])).unwrap();
    let v = fixture::save(&e, &input("fast", 25, &["exa"])).unwrap();
    assert_eq!(v.active_sources, vec!["baidu", "tavily", "firecrawl"]);
    assert_eq!(v.disabled_sources, vec!["exa"]);
    assert_eq!(s.object()["timeout"], 25);
}
#[test]
fn missing_database_shows_defaults_without_creating_it() {
    let s = Sandbox::new("missing");
    let v = fixture::view(&s.env(&[]));
    assert!(!v.file_present);
    assert_eq!(v.read_source, "defaults");
    assert_eq!(v.route, "default");
    assert_eq!(v.timeout, 60);
    assert!(!s.db().exists());
}
#[test]
fn old_user_dev_and_config_env_are_ignored_and_untouched() {
    let s = Sandbox::new("legacy");
    let dev = s.0.join("dev.json");
    std::fs::write(&dev, r#"{"type":"dev","timeout":7}"#).unwrap();
    let old = s.0.join(".multi-search/multi-search-config.json");
    std::fs::create_dir_all(old.parent().unwrap()).unwrap();
    std::fs::write(&old, r#"{"type":"social","timeout":5}"#).unwrap();
    let e = s.env(&[("MULTI_SEARCH_CONFIG", old.to_string_lossy().into_owned())]);
    let before = std::fs::read(&old).unwrap();
    let v = fixture::view_with_dev(&e, &dev);
    assert_eq!(v.route, "default");
    assert!(!serde_json::to_value(&v)
        .unwrap()
        .as_object()
        .unwrap()
        .contains_key("save_creates_override"));
    fixture::save_with_dev(&e, &input("fast", 30, &[]), &dev).unwrap();
    assert_eq!(std::fs::read(&old).unwrap(), before);
    assert_eq!(
        std::fs::read_to_string(&dev).unwrap(),
        r#"{"type":"dev","timeout":7}"#
    );
}
#[test]
fn restart_reads_sqlite_not_dev() {
    let s = Sandbox::new("restart");
    let e = s.env(&[]);
    fixture::save(&e, &input("dev", 33, &["exa"])).unwrap();
    let fresh = s.env(&[]);
    let v = fixture::view(&fresh);
    assert_eq!(v.route, "dev");
    assert_eq!(v.timeout, 33);
    assert_eq!(v.disabled_sources, vec!["exa"]);
}
#[test]
fn corrupt_db_blocks_save_without_overwriting() {
    let s = Sandbox::new("corrupt-db");
    std::fs::create_dir_all(s.db().parent().unwrap()).unwrap();
    std::fs::write(s.db(), b"not a sqlite database").unwrap();
    let before = std::fs::read(s.db()).unwrap();
    assert!(fixture::save(&s.env(&[]), &input("dev", 20, &[])).is_err());
    assert_eq!(std::fs::read(s.db()).unwrap(), before);
    assert_eq!(fixture::view(&s.env(&[])).status, "config_unreadable");
}
#[test]
fn unsupported_version_fails_closed() {
    let s = Sandbox::new("version");
    std::fs::create_dir_all(s.db().parent().unwrap()).unwrap();
    let c = rusqlite::Connection::open(s.db()).unwrap();
    c.pragma_update(None, "user_version", 2).unwrap();
    drop(c);
    assert!(fixture::save(&s.env(&[]), &input("dev", 20, &[])).is_err());
}
#[test]
fn trigger_failure_rolls_back_previous_settings() {
    let s = Sandbox::new("rollback");
    let e = s.env(&[]);
    fixture::save(&e, &input("dev", 20, &[])).unwrap();
    let before = s.object();
    let c = rusqlite::Connection::open(s.db()).unwrap();
    c.execute_batch("CREATE TRIGGER deny_settings BEFORE UPDATE ON settings BEGIN SELECT RAISE(ABORT,'denied'); END;").unwrap();
    assert!(fixture::save(&e, &input("fast", 30, &[])).is_err());
    assert_eq!(s.object(), before);
}
#[test]
fn source_names_accepted_by_execution_allowlist() {
    for name in [
        "baidu",
        "brave",
        "exa",
        "firecrawl",
        "github_repos",
        "hackernews",
        "parallel",
        "serpapi",
        "sov2ex",
        "stackoverflow",
        "tavily",
        "twitter",
        "v2ex",
        "github-repos",
    ] {
        assert!(fixture::is_allowed_source(name));
    }
    assert!(!fixture::is_allowed_source("jina"));
    assert!(!fixture::is_allowed_source("../etc"));
}
#[test]
fn version_zero_nonempty_and_incomplete_version_one_are_rejected() {
    for (tag, sql) in [
        ("nonempty", "CREATE TABLE unrelated(value TEXT);"),
        (
            "incomplete",
            "CREATE TABLE credentials(provider TEXT PRIMARY KEY); PRAGMA user_version=1;",
        ),
    ] {
        let s = Sandbox::new(tag);
        std::fs::create_dir_all(s.db().parent().unwrap()).unwrap();
        let c = rusqlite::Connection::open(s.db()).unwrap();
        c.execute_batch(sql).unwrap();
        drop(c);
        let before = std::fs::read(s.db()).unwrap();
        assert!(fixture::save(&s.env(&[]), &input("default", 60, &[])).is_err());
        assert_eq!(std::fs::read(s.db()).unwrap(), before);
    }
}
#[test]
fn empty_userprofile_falls_back_to_home() {
    let s = Sandbox::new("home-fallback");
    let e = s.env(&[
        ("USERPROFILE", "".into()),
        ("HOME", s.0.to_string_lossy().into_owned()),
    ]);
    assert_eq!(fixture::config_path(&e).unwrap(), s.db());
}

#[test]
fn independent_cli_handoff_database() {
    let Some(target) = std::env::var_os("MS_SETTINGS_HANDOFF") else {
        return;
    };
    let s = Sandbox::new("handoff");
    let mut routes = fixture::builtin_routes();
    routes.insert(
        "handoff_custom".into(),
        RouteConfig {
            label: "联调".into(),
            sources: vec!["hackernews".into(), "stackoverflow".into()],
            timeout: Some(11),
        },
    );
    let mut request = input("handoff_custom", 25, &["brave"]);
    request.routes = Some(routes);
    request.twitter_cookies_path = Some("C:/synthetic/handoff-twitter-cookies.json".into());
    fixture::save(&s.env(&[]), &request).unwrap();
    std::fs::copy(s.db(), PathBuf::from(target)).unwrap();
}

/// Ticket 05: a database written by the desktop (Rust) must be readable by the
/// Python CLI without re-creating or migrating schema. Also asserts the CLI
/// refuses a database whose `user_version` is newer than it understands.
#[test]
fn python_cli_reads_desktop_written_settings_and_rejects_future_versions() {
    let s = Sandbox::new("python-interop");
    let e = s.env(&[]);
    let view = fixture::save(&e, &input("fast", 30, &["exa"])).unwrap();
    assert_eq!(view.route, "fast");

    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let read_script = r#"
import json, sys
from multi_search_mcp.src.support.credential_store import ConfigDatabase
data = ConfigDatabase(sys.argv[1]).read_settings()
print(json.dumps({"type": data.get("type"), "timeout": data.get("timeout"), "disabled_sources": data.get("disabled_sources")}))
"#;
    let output = std::process::Command::new("python")
        .args(["-B", "-c", read_script])
        .arg(s.db())
        .env("PYTHONPATH", &root)
        .env("HOME", &s.0)
        .env("USERPROFILE", &s.0)
        .env("MULTI_SEARCH_CONFIG_DB", s.db())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "python read failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let payload: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(payload["type"], "fast");
    assert_eq!(payload["timeout"], 30);
    assert_eq!(payload["disabled_sources"], serde_json::json!(["exa"]));

    // A future schema version is rejected by the CLI rather than silently
    // treated as the current layout.
    let c = rusqlite::Connection::open(s.db()).unwrap();
    c.pragma_update(None, "user_version", 99).unwrap();
    drop(c);
    let future = std::process::Command::new("python")
        .args(["-B", "-c", read_script])
        .arg(s.db())
        .env("PYTHONPATH", &root)
        .env("HOME", &s.0)
        .env("USERPROFILE", &s.0)
        .env("MULTI_SEARCH_CONFIG_DB", s.db())
        .output()
        .unwrap();
    assert!(!future.status.success());
    let stderr = String::from_utf8_lossy(&future.stderr);
    assert!(
        stderr.contains("schema version") && stderr.contains("desktop"),
        "future version must point at the desktop owner: {stderr}"
    );
    // The desktop itself also refuses the future version instead of downgrading.
    assert!(fixture::save(&s.env(&[]), &input("fast", 30, &[])).is_err());
}

fn custom_routes() -> RouteMap {
    let mut routes = fixture::builtin_routes();
    routes.insert(
        "research_1".into(),
        RouteConfig {
            label: "  研究组合  ".into(),
            sources: vec!["github".into(), "github_repos".into(), "v2ex".into()],
            timeout: Some(7),
        },
    );
    routes
}

#[test]
fn builtin_factory_is_used_only_when_routes_is_missing() {
    let builtins = fixture::builtin_routes();
    assert_eq!(builtins.len(), 5);
    assert_eq!(builtins["default"].label, "默认（网页综合）");
    assert_eq!(
        builtins["fast"].sources,
        ["baidu", "tavily", "firecrawl", "exa"]
    );
    assert_eq!(builtins["all"].sources.len(), 12);
    assert!(builtins.values().all(|route| route.timeout.is_none()));

    let s = Sandbox::new("explicit-no-backfill");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(r#"{"type":"only","routes":{"only":{"label":"仅保留自定义","sources":["tavily"],"timeout":null}}}"#);
    let view = fixture::view(&e);
    assert_eq!(view.routes.len(), 1);
    assert!(view.routes.contains_key("only"));
    assert!(!view.routes.contains_key("default"));
    assert_eq!(view.builtin_routes, builtins);
}

#[test]
fn complete_route_map_supports_create_edit_delete_and_global_disable() {
    let s = Sandbox::new("route-crud");
    let e = s.env(&[]);
    let mut create = input("research_1", 41, &[]);
    create.routes = Some(custom_routes());
    let created = fixture::save(&e, &create).unwrap();
    assert_eq!(created.routes["research_1"].label, "研究组合");
    assert_eq!(
        created.routes["research_1"].sources,
        ["github_repos", "sov2ex"]
    );
    assert_eq!(created.effective_timeout, 7);

    let mut edited_routes = created.routes.clone();
    edited_routes.remove("all");
    edited_routes.get_mut("research_1").unwrap().label = "研究与社区".into();
    edited_routes.get_mut("research_1").unwrap().timeout = None;
    let mut edit = input("research_1", 33, &["sov2ex"]);
    edit.routes = Some(edited_routes);
    let edited = fixture::save(&e, &edit).unwrap();
    assert!(!edited.routes.contains_key("all"));
    assert_eq!(edited.effective_timeout, 33);
    assert_eq!(edited.active_sources, ["github_repos"]);
    assert_eq!(
        edited.routes["research_1"].sources,
        ["github_repos", "sov2ex"]
    );

    let mut deleted_routes = edited.routes.clone();
    deleted_routes.remove("research_1");
    let mut delete = input("default", 33, &["sov2ex"]);
    delete.routes = Some(deleted_routes);
    let deleted = fixture::save(&e, &delete).unwrap();
    assert!(!deleted.routes.contains_key("research_1"));
    assert!(!deleted.routes.contains_key("all"));
}

#[test]
fn current_last_and_invalid_routes_are_rejected_before_sqlite_changes() {
    let s = Sandbox::new("route-invalid");
    let e = s.env(&[]);
    let mut initial = input("research_1", 30, &[]);
    initial.routes = Some(custom_routes());
    fixture::save(&e, &initial).unwrap();
    let before = std::fs::read(s.db()).unwrap();

    let mut without_current = custom_routes();
    without_current.remove("research_1");
    let mut deleting_current = input("research_1", 30, &[]);
    deleting_current.routes = Some(without_current);
    assert!(fixture::save(&e, &deleting_current)
        .unwrap_err()
        .contains("先切换"));

    for (id, route) in [
        (
            "web",
            RouteConfig {
                label: "Web".into(),
                sources: vec!["tavily".into()],
                timeout: None,
            },
        ),
        (
            "UPPER",
            RouteConfig {
                label: "Upper".into(),
                sources: vec!["tavily".into()],
                timeout: None,
            },
        ),
        (
            "bad id",
            RouteConfig {
                label: "Space".into(),
                sources: vec!["tavily".into()],
                timeout: None,
            },
        ),
        (
            "empty-source",
            RouteConfig {
                label: "Empty".into(),
                sources: vec![],
                timeout: None,
            },
        ),
        (
            "bad-timeout",
            RouteConfig {
                label: "Timeout".into(),
                sources: vec!["tavily".into()],
                timeout: Some(61),
            },
        ),
        (
            "bad-source",
            RouteConfig {
                label: "Source".into(),
                sources: vec!["unknown".into()],
                timeout: None,
            },
        ),
    ] {
        let mut routes = RouteMap::new();
        routes.insert(id.into(), route);
        let mut request = input(id, 30, &[]);
        request.routes = Some(routes);
        assert!(
            fixture::save(&e, &request).is_err(),
            "{id} must be rejected"
        );
    }
    let mut empty = input("one", 30, &[]);
    empty.routes = Some(RouteMap::new());
    assert!(fixture::save(&e, &empty).is_err());
    assert_eq!(std::fs::read(s.db()).unwrap(), before);
}

#[test]
fn omitted_routes_preserve_existing_map_and_unknown_fields() {
    let s = Sandbox::new("preserve-routes");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    let routes = serde_json::json!({
        "custom": {"label":"Custom","sources":["hackernews","brave"],"timeout":9}
    });
    s.replace(
        &serde_json::json!({
            "type":"custom","timeout":60,"routes":routes,"future":{"keep":true}
        })
        .to_string(),
    );
    let saved = fixture::save(&e, &input("custom", 44, &["brave"])).unwrap();
    assert_eq!(saved.routes["custom"].timeout, Some(9));
    assert_eq!(saved.effective_timeout, 9);
    let object = s.object();
    assert_eq!(object["routes"], routes);
    assert_eq!(object["future"]["keep"], true);
}

#[test]
fn malformed_routes_or_type_are_unreadable_and_block_transactional_save() {
    let cases = [
        r#"{"type":"default","routes":{}}"#,
        r#"{"type":"missing","routes":{"only":{"label":"Only","sources":["tavily"],"timeout":null}}}"#,
        r#"{"type":7}"#,
        r#"{"type":"default","routes":{"default":{"label":"Default","sources":["unknown"],"timeout":null}}}"#,
        r#"{"type":"default","routes":{"default":{"label":"Default","sources":["tavily"],"timeout":null,"extra":true}}}"#,
        r#"{"type":"default","routes":[]}"#,
    ];
    for (index, body) in cases.into_iter().enumerate() {
        let s = Sandbox::new(&format!("bad-routes-{index}"));
        let e = s.env(&[]);
        fixture::save(&e, &input("default", 60, &[])).unwrap();
        s.replace(body);
        let view = fixture::view(&e);
        assert_eq!(view.status, "config_unreadable");
        assert!(view.route.is_empty());
        assert!(view.routes.is_empty());
        let before = std::fs::read(s.db()).unwrap();
        assert!(fixture::save(&e, &input("default", 30, &[])).is_err());
        assert_eq!(std::fs::read(s.db()).unwrap(), before);
    }
}

#[test]
fn aliases_null_type_and_legacy_timeout_previews_remain_compatible() {
    let s = Sandbox::new("compat-routes");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(r#"{"type":null}"#);
    assert_eq!(fixture::view(&e).route, "default");
    s.replace(r#"{"type":"web","timeout":12}"#);
    assert_eq!(fixture::view(&e).effective_timeout, 12);
    s.replace(r#"{"type":"fast"}"#);
    let fast = fixture::view(&e);
    assert!(!fast.timeout_configured);
    assert_eq!(fast.effective_timeouts["fast"], 45);
    assert_eq!(fast.effective_timeouts["all"], 90);

    s.replace(r#"{"type":"custom","routes":{"custom":{"label":"Custom","sources":[" github ","github-repos"," v2ex "],"timeout":null}}}"#);
    assert_eq!(
        fixture::view(&e).routes["custom"].sources,
        ["github_repos", "sov2ex"]
    );
}
