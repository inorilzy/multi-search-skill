//! SQLite settings against disposable paths only. Legacy JSON/env are not configuration sources.
use fixture::SettingsInput;
use multi_search_desktop::{settings_fixture as fixture, RuntimeEnvironment};
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
    assert!(!serde_json::to_value(&v).unwrap().as_object().unwrap().contains_key("twitter_env_overrides"));
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
    assert!(!serde_json::to_value(&v).unwrap().as_object().unwrap().contains_key("save_creates_override"));
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
    for (tag, sql) in [("nonempty", "CREATE TABLE unrelated(value TEXT);"), ("incomplete", "CREATE TABLE credentials(provider TEXT PRIMARY KEY); PRAGMA user_version=1;")] {
        let s=Sandbox::new(tag); std::fs::create_dir_all(s.db().parent().unwrap()).unwrap();
        let c=rusqlite::Connection::open(s.db()).unwrap(); c.execute_batch(sql).unwrap(); drop(c);
        let before=std::fs::read(s.db()).unwrap(); assert!(fixture::save(&s.env(&[]), &input("default",60,&[])).is_err());
        assert_eq!(std::fs::read(s.db()).unwrap(),before);
    }
}
#[test]
fn empty_userprofile_falls_back_to_home() {
    let s=Sandbox::new("home-fallback"); let e=s.env(&[("USERPROFILE", "".into()),("HOME",s.0.to_string_lossy().into_owned())]);
    assert_eq!(fixture::config_path(&e).unwrap(),s.db());
}

#[test]
fn independent_cli_handoff_database() {
    let Some(target) = std::env::var_os("MS_SETTINGS_HANDOFF") else {
        return;
    };
    let s = Sandbox::new("handoff");
    let mut request = input("default", 25, &["brave"]);
    request.twitter_cookies_path = Some("C:/synthetic/handoff-twitter-cookies.json".into());
    fixture::save(&s.env(&[]), &request).unwrap();
    std::fs::copy(s.db(), PathBuf::from(target)).unwrap();
}
