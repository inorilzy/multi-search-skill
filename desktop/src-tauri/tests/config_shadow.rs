//! Ticket 08: the desktop imports a parseable user JSON config once, on the first
//! settings write, and never reads it again. All paths are disposable.
use multi_search_desktop::{
    settings_fixture::{self as fixture, SettingsInput},
    RuntimeEnvironment,
};
use std::{collections::BTreeMap, path::PathBuf};

struct Sandbox(PathBuf);

impl Sandbox {
    fn new(tag: &str) -> Self {
        let p = std::env::temp_dir().join(format!("ms-config-shadow-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&p);
        std::fs::create_dir_all(&p).unwrap();
        Self(p)
    }
    fn db(&self) -> PathBuf {
        self.0.join(".multi-search/config.sqlite")
    }
    fn user_json(&self) -> PathBuf {
        self.0.join(".multi-search/multi-search-config.json")
    }
    fn seed_user_json(&self, body: &str) {
        std::fs::create_dir_all(self.user_json().parent().unwrap()).unwrap();
        std::fs::write(self.user_json(), body).unwrap();
    }
    fn env(&self, extra: &[(&str, String)]) -> RuntimeEnvironment {
        let mut variables =
            BTreeMap::from([("USERPROFILE".into(), self.0.to_string_lossy().into_owned())]);
        for (key, value) in extra {
            variables.insert((*key).into(), value.clone());
        }
        RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables,
            cwd: self.0.clone(),
        }
    }
    fn object(&self) -> serde_json::Value {
        let connection = rusqlite::Connection::open(self.db()).unwrap();
        let text: String = connection
            .query_row("SELECT data FROM settings WHERE id=1", [], |row| row.get(0))
            .unwrap();
        serde_json::from_str(&text).unwrap()
    }
    fn replace(&self, body: &str) {
        let connection = rusqlite::Connection::open(self.db()).unwrap();
        connection
            .execute("UPDATE settings SET data=?1 WHERE id=1", [body])
            .unwrap();
    }
}

impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn input(route: &str, timeout: u32) -> SettingsInput {
    SettingsInput {
        route: route.into(),
        timeout: Some(timeout),
        disabled_sources: vec![],
        routes: None,
        twitter_cookies_path: None,
        scrape_backends: None,
        ranking: None,
    }
}

const ADVANCED_JSON: &str = r#"{
    "count": 7,
    "counts": {"brave": 3, "tavily": 2},
    "query_fusion": {"mode": "weighted", "primary_weight": 2, "variant_budget": 4},
    "expand": ["比较", "对比"],
    "expand_queries": ["版本差异"],
    "serpapi_engines": ["google", "bing"],
    "no_scrape": true,
    "future_field": {"nested": [1, 2]}
}"#;

#[test]
fn first_save_imports_user_json_advanced_settings_and_applies_the_edit() {
    let s = Sandbox::new("first-save");
    s.seed_user_json(ADVANCED_JSON);
    let view = fixture::save(&s.env(&[]), &input("dev", 45)).unwrap();

    let object = s.object();
    assert_eq!(object["type"], "dev", "the edit wins over the JSON base");
    assert_eq!(object["timeout"], 45);
    assert_eq!(object["count"], 7);
    assert_eq!(object["counts"]["brave"], 3);
    assert_eq!(object["counts"]["tavily"], 2);
    assert_eq!(object["query_fusion"]["mode"], "weighted");
    assert_eq!(object["query_fusion"]["primary_weight"], 2);
    assert_eq!(object["query_fusion"]["variant_budget"], 4);
    assert_eq!(object["expand"], serde_json::json!(["比较", "对比"]));
    assert_eq!(object["expand_queries"], serde_json::json!(["版本差异"]));
    assert_eq!(
        object["serpapi_engines"],
        serde_json::json!(["google", "bing"])
    );
    assert_eq!(object["no_scrape"], true);
    assert_eq!(object["future_field"]["nested"], serde_json::json!([1, 2]));
    assert_eq!(view.route, "dev");
    assert_eq!(view.read_source, "sqlite");
}

#[test]
fn first_debug_log_switch_imports_user_json_advanced_settings() {
    let s = Sandbox::new("first-switch");
    s.seed_user_json(
        r#"{"counts":{"brave":4},"query_fusion":{"mode":"weighted"},"expand":["同义词"]}"#,
    );
    let view = fixture::save_debug_log(&s.env(&[]), true).unwrap();

    assert!(view.debug_log);
    let object = s.object();
    assert_eq!(object["debug_log"], true);
    assert_eq!(object["counts"]["brave"], 4);
    assert_eq!(object["query_fusion"]["mode"], "weighted");
    assert_eq!(object["expand"], serde_json::json!(["同义词"]));
}

#[test]
fn later_saves_never_read_the_user_json_again() {
    let s = Sandbox::new("later-save");
    s.seed_user_json(r#"{"count":7,"query_fusion":{"mode":"weighted"}}"#);
    let env = s.env(&[]);
    fixture::save(&env, &input("default", 60)).unwrap();

    s.seed_user_json(r#"{"count":99,"query_fusion":{"mode":"rrf"},"new_field":true}"#);
    fixture::save(&env, &input("fast", 30)).unwrap();

    let object = s.object();
    assert_eq!(object["count"], 7, "the imported value is authoritative");
    assert_eq!(object["query_fusion"]["mode"], "weighted");
    assert!(
        object.get("new_field").is_none(),
        "later JSON edits are ignored"
    );
    assert_eq!(object["type"], "fast");
    assert_eq!(object["timeout"], 30);
}

#[test]
fn an_empty_settings_row_still_blocks_a_second_import() {
    let s = Sandbox::new("empty-row");
    s.seed_user_json(r#"{"count":7}"#);
    let env = s.env(&[]);
    fixture::save(&env, &input("default", 60)).unwrap();
    s.replace("{}");

    s.seed_user_json(r#"{"count":99}"#);
    fixture::save(&env, &input("default", 60)).unwrap();

    assert!(s.object().get("count").is_none());
}

#[test]
fn unparseable_or_non_object_user_json_is_ignored() {
    for (index, body) in ["{ not json", "[]", "null", "7"].into_iter().enumerate() {
        let s = Sandbox::new(&format!("invalid-{index}"));
        s.seed_user_json(body);
        let view = fixture::save(&s.env(&[]), &input("default", 60)).unwrap();

        assert_eq!(view.status, "ok");
        let object = s.object();
        assert_eq!(object["type"], "default");
        assert_eq!(object["timeout"], 60);
        assert!(object.get("count").is_none());
    }
}

#[test]
fn settings_view_reports_cli_env_as_the_read_source() {
    let s = Sandbox::new("cli-env");
    let explicit = s.0.join("explicit.json");
    std::fs::write(&explicit, r#"{"type":"social","counts":{"brave":1}}"#).unwrap();
    let environment = s.env(&[(
        "MULTI_SEARCH_CONFIG",
        explicit.to_string_lossy().into_owned(),
    )]);

    let before_save = fixture::view(&environment);
    assert_eq!(before_save.read_source, "cli_env");
    assert_eq!(before_save.path_source, "user");
    assert_eq!(
        before_save.route, "default",
        "the desktop page still shows SQLite/defaults, not the CLI-only file"
    );

    fixture::save(&environment, &input("default", 60)).unwrap();
    assert_eq!(fixture::view(&environment).read_source, "cli_env");
    assert_eq!(fixture::view(&s.env(&[])).read_source, "sqlite");
}
