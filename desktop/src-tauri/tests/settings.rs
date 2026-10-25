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
        timeout: Some(timeout),
        disabled_sources: disabled.iter().map(|s| s.to_string()).collect(),
        routes: None,
        twitter_cookies_path: None,
        scrape_backends: None,
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
        input("dev", 91, &[]),
        input("all", 1000, &[]),
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
fn scrape_backends_save_trims_dedupes_and_keeps_order() {
    let s = Sandbox::new("scrape-save");
    let e = s.env(&[]);
    let mut request = input("default", 60, &[]);
    request.scrape_backends = Some(vec![
        " firecrawl ".into(),
        "jina".into(),
        "firecrawl".into(),
        " exa ".into(),
    ]);
    let view = fixture::save(&e, &request).unwrap();
    assert_eq!(
        s.object()["scrape_backends"],
        serde_json::json!(["firecrawl", "jina", "exa"])
    );
    assert_eq!(view.scrape_backends, ["firecrawl", "jina", "exa"]);
}

#[test]
fn scrape_backends_reject_unknown_and_empty_lists_without_writing() {
    let s = Sandbox::new("scrape-invalid");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    let before = std::fs::read(s.db()).unwrap();
    for bad in [
        vec!["jina".to_string(), "bing".to_string()],
        vec!["".to_string()],
        vec![],
    ] {
        let mut request = input("default", 60, &[]);
        request.scrape_backends = Some(bad);
        assert!(fixture::save(&e, &request).is_err());
        assert_eq!(std::fs::read(s.db()).unwrap(), before);
    }
    let mut unknown = input("default", 60, &[]);
    unknown.scrape_backends = Some(vec!["bing".into()]);
    assert!(fixture::save(&e, &unknown)
        .unwrap_err()
        .contains("不支持的抓取后端：bing"));
    let mut empty = input("default", 60, &[]);
    empty.scrape_backends = Some(vec![]);
    assert!(fixture::save(&e, &empty)
        .unwrap_err()
        .contains("至少要保留一个后端"));
}

#[test]
fn omitted_scrape_backends_preserve_existing_key() {
    let s = Sandbox::new("scrape-preserve");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(
        r#"{"type":"default","scrape_backends":["tavily","jina"],"future_field":1}"#,
    );
    // None（旧调用方）不改动，也不删除该键。
    fixture::save(&e, &input("default", 30, &[])).unwrap();
    assert_eq!(
        s.object()["scrape_backends"],
        serde_json::json!(["tavily", "jina"])
    );
    assert_eq!(s.object()["future_field"], 1);
}

#[test]
fn missing_scrape_backends_view_uses_factory_chain_and_options() {
    let s = Sandbox::new("scrape-defaults");
    let view = fixture::view(&s.env(&[]));
    assert_eq!(view.scrape_backends, ["jina", "exa", "tavily", "firecrawl"]);
    assert_eq!(view.builtin_scrape_backends, view.scrape_backends);
    assert_eq!(
        view.scrape_backend_options
            .iter()
            .map(|option| (option.name.as_str(), option.label.as_str()))
            .collect::<Vec<_>>(),
        [
            ("jina", "Jina Reader"),
            ("exa", "Exa"),
            ("tavily", "Tavily"),
            ("firecrawl", "Firecrawl"),
        ]
    );
}

#[test]
fn dirty_scrape_backends_read_tolerantly_and_fall_back_when_useless() {
    let s = Sandbox::new("scrape-tolerant");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(r#"{"type":"default","scrape_backends":["bing"," tavily ","tavily",7,"exa"]}"#);
    let view = fixture::view(&e);
    assert_eq!(view.status, "ok");
    assert_eq!(view.scrape_backends, ["tavily", "exa"]);
    assert!(view.scrape_backends_invalid, "unknown/non-string entries are invalid saved data");

    for (index, body) in [
        r#"{"type":"default","scrape_backends":["bing"]}"#,
        r#"{"type":"default","scrape_backends":[]}"#,
        r#"{"type":"default","scrape_backends":"jina"}"#,
        r#"{"type":"default","scrape_backends":null}"#,
    ]
    .into_iter()
    .enumerate()
    {
        let s = Sandbox::new(&format!("scrape-fallback-{index}"));
        let e = s.env(&[]);
        fixture::save(&e, &input("default", 60, &[])).unwrap();
        s.replace(body);
        let view = fixture::view(&e);
        assert_eq!(view.status, "ok");
        assert_eq!(view.scrape_backends, ["jina", "exa", "tavily", "firecrawl"]);
        // null 与缺失等价（历史默认）；其余三种是用户明确写入的非法值。
        assert_eq!(
            view.scrape_backends_invalid,
            !body.contains(":null"),
            "{body} must be reported as invalid saved data"
        );
    }
}

#[test]
fn missing_or_absent_scrape_backends_is_not_reported_invalid() {
    let s = Sandbox::new("scrape-absent");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(r#"{"type":"default"}"#);
    let view = fixture::view(&e);
    assert!(!view.scrape_backends_invalid);
    assert_eq!(view.scrape_backends, ["jina", "exa", "tavily", "firecrawl"]);
}

#[test]
fn invalid_saved_scrape_backends_can_be_overwritten_by_save() {
    let s = Sandbox::new("scrape-overwrite");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace(r#"{"type":"default","scrape_backends":[]}"#);
    let before = fixture::view(&e);
    assert!(before.scrape_backends_invalid);
    assert_eq!(before.status, "ok");

    let mut request = input("default", 60, &[]);
    request.scrape_backends = Some(vec!["jina".into(), "tavily".into()]);
    let saved = fixture::save(&e, &request).unwrap();
    assert!(!saved.scrape_backends_invalid);
    assert_eq!(saved.scrape_backends, ["jina", "tavily"]);
    assert_eq!(
        s.object()["scrape_backends"],
        serde_json::json!(["jina", "tavily"])
    );
}

#[test]
fn unreadable_view_still_exposes_default_scrape_chain() {
    let s = Sandbox::new("scrape-unreadable");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 60, &[])).unwrap();
    s.replace("{ not json");
    let view = fixture::view(&e);
    assert_eq!(view.status, "config_unreadable");
    assert_eq!(view.scrape_backends, ["jina", "exa", "tavily", "firecrawl"]);
    assert!(!view.scrape_backends_invalid);
    assert_eq!(view.scrape_backend_options.len(), 4);
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
    let mut request = input("fast", 30, &["exa"]);
    request.scrape_backends = Some(vec!["firecrawl".into(), "jina".into()]);
    let view = fixture::save(&e, &request).unwrap();
    assert_eq!(view.route, "fast");

    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let read_script = r#"
import json, sys
from multi_search_mcp.src.support.credential_store import ConfigDatabase
from multi_search_mcp.src.search.resolve import resolve_scrape_backends
data = ConfigDatabase(sys.argv[1]).read_settings()
assert resolve_scrape_backends(data) == ['firecrawl', 'jina']
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
                timeout: Some(91),
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

#[test]
fn scrape_patch_and_other_settings_writes_preserve_each_other() {
    let sandbox = Sandbox::new("scrape-patch-race");
    let env = sandbox.env(&[]);
    fixture::save(&env, &input("default", 20, &[])).unwrap();
    sandbox.replace(r#"{"type":"default","timeout":20,"future":{"keep":true}}"#);
    for _ in 0..20 {
        let a = env.clone();
        let b = env.clone();
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let peer = barrier.clone();
        let scrape = std::thread::spawn(move || {
            peer.wait();
            multi_search_desktop::settings::save_scrape_backends(&a, &["firecrawl".into(), "exa".into()]).unwrap();
        });
        barrier.wait();
        // Other pages omit scrape_backends rather than replaying its snapshot.
        fixture::save(&b, &input("dev", 37, &["brave"])).unwrap();
        scrape.join().unwrap();
        let object = sandbox.object();
        assert_eq!(object["type"], "dev");
        assert_eq!(object["timeout"], 37);
        assert_eq!(object["disabled_sources"], serde_json::json!(["brave"]));
        assert_eq!(object["scrape_backends"], serde_json::json!(["firecrawl", "exa"]));
        assert_eq!(object["future"], serde_json::json!({"keep":true}));
    }
    for invalid in [vec![], vec!["unknown".into()]] {
        let before = sandbox.object();
        assert!(multi_search_desktop::settings::save_scrape_backends(&env, &invalid).is_err());
        assert_eq!(sandbox.object(), before);
    }
}


#[test]
fn timeout_range_covers_every_cli_route_default() {
    // ROUTE_META in search_runner.py: default/social/dev 60, fast 45, all 90.
    for (route, expected) in [("default", 60), ("fast", 45), ("all", 90), ("social", 60), ("dev", 60)] {
        assert_eq!(fixture::route_default_timeout(route), expected, "{route}");
        assert!((fixture::TIMEOUT_MIN..=fixture::TIMEOUT_MAX).contains(&expected), "{route} default must be savable");
    }
    assert_eq!(fixture::TIMEOUT_MIN, 1);
    assert_eq!(fixture::TIMEOUT_MAX, 90);
    let s = Sandbox::new("timeout-90");
    let e = s.env(&[]);
    let view = fixture::save(&e, &input("all", 90, &[])).unwrap();
    assert_eq!(view.timeout, 90);
    assert!(view.timeout_configured);
    assert!(!view.timeout_out_of_range);
    assert_eq!((view.timeout_min, view.timeout_max), (1, 90));
    assert!(fixture::save(&e, &input("all", 91, &[])).is_err());
}

#[test]
fn an_absent_timeout_reports_the_route_default_and_is_never_written_when_not_edited() {
    let s = Sandbox::new("timeout-absent");
    let e = s.env(&[]);
    fixture::save(&e, &input("all", 30, &[])).unwrap();
    s.replace(r#"{"type": "all"}"#);
    let view = fixture::view(&e);
    assert_eq!(view.timeout, 90, "the all route default, not a desktop invention");
    assert!(!view.timeout_configured);
    let request = SettingsInput { timeout: None, ..input("all", 1, &["brave"]) };
    fixture::save(&e, &request).unwrap();
    assert!(s.object().get("timeout").is_none(), "an unedited timeout must not be materialised");
}

#[test]
fn an_out_of_range_stored_timeout_is_shown_as_is_and_preserved_when_not_edited() {
    let s = Sandbox::new("timeout-wide");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 30, &[])).unwrap();
    s.replace(r#"{"type": "default", "timeout": 120}"#);
    let view = fixture::view(&e);
    assert_eq!(view.timeout, 120, "no silent rewrite to 60");
    assert!(view.timeout_configured);
    assert!(view.timeout_out_of_range);
    let request = SettingsInput { timeout: None, ..input("dev", 1, &[]) };
    fixture::save(&e, &request).unwrap();
    let object = s.object();
    assert_eq!(object["timeout"], 120);
    assert_eq!(object["type"], "dev");
}

#[test]
fn unknown_disabled_entries_are_reported_and_kept_through_a_save() {
    let s = Sandbox::new("unknown-disabled");
    let e = s.env(&[]);
    fixture::save(&e, &input("default", 30, &[])).unwrap();
    s.replace(r#"{"disabled_sources": ["future_source", "exa", 7]}"#);
    let view = fixture::view(&e);
    assert_eq!(view.disabled_sources, vec!["exa"]);
    assert_eq!(view.unknown_disabled_sources, vec!["future_source", "7"]);
    fixture::save(&e, &input("default", 30, &["brave"])).unwrap();
    assert_eq!(
        s.object()["disabled_sources"],
        serde_json::json!(["brave", "future_source", 7]),
        "known edits apply; unknown entries survive"
    );
}
