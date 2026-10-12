//! Desktop settings writer against real temp files. The user config and home are never touched:
//! each test gets a unique temp directory and an explicit environment map.
use multi_search_desktop::settings_fixture as fixture;
use multi_search_desktop::{RuntimeEnvironment, settings_fixture::SettingsInput};
use std::{collections::BTreeMap, path::PathBuf};

struct Sandbox(PathBuf);
impl Sandbox {
    fn new(tag: &str) -> Self {
        let path = std::env::temp_dir().join(format!("ms-settings-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn env(&self, extra: &[(&str, String)]) -> RuntimeEnvironment {
        let mut variables = BTreeMap::from([
            ("USERPROFILE".to_string(), self.0.to_string_lossy().into_owned()),
        ]);
        for (k, v) in extra {
            variables.insert((*k).to_string(), v.clone());
        }
        RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables,
            cwd: self.0.clone(),
        }
    }
    fn user_config(&self) -> PathBuf {
        self.0.join(".multi-search").join("multi-search-config.json")
    }
    fn leftovers(&self) -> Vec<String> {
        let dir = self.user_config().parent().unwrap().to_path_buf();
        std::fs::read_dir(dir)
            .map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect())
            .unwrap_or_default()
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
fn save_writes_known_keys_with_sorted_canonical_sources_and_a_trailing_newline() {
    let sandbox = Sandbox::new("canonical");
    let env = sandbox.env(&[]);
    let view = fixture::save(&env, &input("fast", 30, &["v2ex", "brave", "github", "brave"])).unwrap();
    let text = std::fs::read_to_string(sandbox.user_config()).unwrap();
    assert!(text.ends_with('\n'));
    let json: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(json["type"], "fast");
    assert_eq!(json["timeout"], 30);
    assert_eq!(json["disabled_sources"], serde_json::json!(["brave", "github_repos", "sov2ex"]));
    assert_eq!(view.disabled_sources, vec!["brave", "github_repos", "sov2ex"]);
    assert_eq!(view.route, "fast");
    assert_eq!(view.path_source, "user");
    assert_eq!(sandbox.leftovers(), vec!["multi-search-config.json"], "no temp file may remain");
}

#[test]
fn save_preserves_unknown_fields_and_other_keys() {
    let sandbox = Sandbox::new("unknown");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(
        sandbox.user_config(),
        r#"{"count": 7, "no_scrape": true, "counts": {"brave": 3}, "future_field": {"nested": [1, 2]}}"#,
    )
    .unwrap();
    fixture::save(&env, &input("default", 45, &["tavily"])).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["count"], 7);
    assert_eq!(json["no_scrape"], true);
    assert_eq!(json["counts"]["brave"], 3);
    assert_eq!(json["future_field"]["nested"], serde_json::json!([1, 2]));
    assert_eq!(json["timeout"], 45);
    assert_eq!(json["disabled_sources"], serde_json::json!(["tavily"]));
}

#[test]
fn invalid_input_is_rejected_before_any_write_and_keeps_the_old_file_byte_for_byte() {
    let sandbox = Sandbox::new("invalid");
    let env = sandbox.env(&[]);
    fixture::save(&env, &input("dev", 20, &["hackernews"])).unwrap();
    let before = std::fs::read(sandbox.user_config()).unwrap();
    let bad_inputs = [
        input("nope", 20, &[]),
        input("dev", 0, &[]),
        input("dev", 61, &[]),
        input("dev", 20, &["jina"]),
        input("dev", 20, &["../../etc"]),
        input("dev", 20, &["tavily/../brave"]),
        SettingsInput { twitter_cookies_path: Some("bad\0path".into()), ..input("dev", 20, &[]) },
        SettingsInput { twitter_cookies_path: Some("x".repeat(2000)), ..input("dev", 20, &[]) },
    ];
    for bad in bad_inputs {
        assert!(fixture::save(&env, &bad).is_err(), "{:?} must be rejected", bad.route);
        assert_eq!(std::fs::read(sandbox.user_config()).unwrap(), before, "old config must survive");
    }
    assert_eq!(sandbox.leftovers(), vec!["multi-search-config.json"]);
}

#[test]
fn unparsable_existing_file_blocks_save_and_is_not_overwritten() {
    let sandbox = Sandbox::new("corrupt");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), "{ not json").unwrap();
    let error = fixture::save(&env, &input("default", 60, &[])).unwrap_err();
    assert!(error.contains("未保存"));
    assert_eq!(std::fs::read_to_string(sandbox.user_config()).unwrap(), "{ not json");
}

#[test]
fn env_config_path_is_the_only_target_when_set() {
    let sandbox = Sandbox::new("env");
    let custom = sandbox.0.join("custom").join("cfg.json");
    let env = sandbox.env(&[("MULTI_SEARCH_CONFIG", custom.to_string_lossy().into_owned())]);
    assert_eq!(fixture::config_path(&env).unwrap(), custom);
    let view = fixture::save(&env, &input("social", 10, &["twitter"])).unwrap();
    assert!(custom.exists());
    assert!(!sandbox.user_config().exists(), "the user config must not be written when env selects another path");
    assert_eq!(view.path_source, "env");
    assert_eq!(view.status, "no_active_source");
    assert!(view.message.contains("social") && view.message.contains("不会运行"));
}

#[test]
fn twitter_reference_is_saved_as_a_path_and_env_is_reported_as_overriding() {
    let sandbox = Sandbox::new("twitter");
    let env = sandbox.env(&[("TWITTER_COOKIES_PATH", "C:/secret/env-cookies.json".into())]);
    let mut request = input("social", 60, &[]);
    request.twitter_cookies_path = Some("  C:/cookies/twitter.json  ".into());
    let view = fixture::save(&env, &request).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["twitter_cookies_path"], "C:/cookies/twitter.json");
    assert_eq!(view.twitter_cookies_path.as_deref(), Some("C:/cookies/twitter.json"));
    assert!(view.twitter_env_overrides);
    assert_eq!(view.active_sources, vec!["twitter"]);
    assert_eq!(view.status, "ok");

    let mut cleared = input("social", 60, &[]);
    cleared.twitter_cookies_path = Some("".into());
    fixture::save(&env, &cleared).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert!(json.get("twitter_cookies_path").is_none());
}

#[test]
fn all_sources_disabled_for_the_route_reports_no_active_source_without_reenabling() {
    let sandbox = Sandbox::new("alldisabled");
    let env = sandbox.env(&[]);
    let view = fixture::save(&env, &input("default", 60, &["baidu", "brave", "exa", "firecrawl", "parallel", "serpapi", "tavily"])).unwrap();
    assert!(view.active_sources.is_empty());
    assert_eq!(view.status, "no_active_source");
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["disabled_sources"].as_array().unwrap().len(), 7, "disabled list must not be silently reset");
}

#[test]
fn toggling_a_source_back_on_removes_it_from_disabled_sources() {
    let sandbox = Sandbox::new("toggle");
    let env = sandbox.env(&[]);
    fixture::save(&env, &input("fast", 60, &["baidu", "exa"])).unwrap();
    let view = fixture::save(&env, &input("fast", 60, &["exa"])).unwrap();
    assert_eq!(view.disabled_sources, vec!["exa"]);
    // Route "fast" runs baidu, tavily, firecrawl, exa; only exa stays disabled.
    assert_eq!(view.active_sources, vec!["baidu", "tavily", "firecrawl"]);
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["disabled_sources"], serde_json::json!(["exa"]));
}

/// Handoff to the independent CLI check: when MS_SETTINGS_HANDOFF names a path, the exact file
/// the desktop save path produced is copied there so the Python CLI test reads it unchanged.
#[test]
fn handoff_file_for_the_independent_cli_check() {
    let Some(target) = std::env::var_os("MS_SETTINGS_HANDOFF") else { return };
    let sandbox = Sandbox::new("handoff");
    let env = sandbox.env(&[]);
    let mut request = input("default", 25, &["brave"]);
    // Synthetic path reference only; the CLI test checks it is passed through, never read.
    request.twitter_cookies_path = Some("C:/synthetic/handoff-twitter-cookies.json".into());
    fixture::save(&env, &request).unwrap();
    std::fs::copy(sandbox.user_config(), PathBuf::from(target)).unwrap();
}

#[test]
fn view_without_a_file_reports_defaults_and_path_source() {
    let sandbox = Sandbox::new("view");
    let view = fixture::view(&sandbox.env(&[]));
    assert!(!view.file_present);
    assert_eq!(view.route, "default");
    assert_eq!(view.timeout, 60);
    assert!(view.disabled_sources.is_empty());
    assert_eq!(view.status, "ok");
}

#[test]
fn unreadable_target_blocks_save_and_leaves_the_old_file_and_no_temp_file() {
    let sandbox = Sandbox::new("blocked");
    let env = sandbox.env(&[]);
    fixture::save(&env, &input("dev", 20, &["hackernews"])).unwrap();
    let before = std::fs::read(sandbox.user_config()).unwrap();
    // A directory at the target path cannot be read as a config, so save stops before any write.
    let blocker = sandbox.0.join("blocked.json");
    std::fs::create_dir_all(&blocker).unwrap();
    let env_blocked = sandbox.env(&[("MULTI_SEARCH_CONFIG", blocker.to_string_lossy().into_owned())]);
    assert!(fixture::save(&env_blocked, &input("dev", 20, &[])).is_err());
    assert_eq!(std::fs::read(sandbox.user_config()).unwrap(), before);
    assert!(sandbox.leftovers().iter().all(|n| !n.contains(".tmp-")));
}
