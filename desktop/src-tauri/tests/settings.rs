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
impl Sandbox {
    /// A dev-fallback path inside the sandbox that does not exist, so tests never read the repo file.
    fn absent_dev(&self) -> PathBuf {
        self.0.join("no-dev").join("multi-search-config.json")
    }
}
/// Save through the seam with the sandbox's absent dev path (hermetic: never reads the repo file).
fn save_h(sandbox: &Sandbox, env: &RuntimeEnvironment, request: &SettingsInput) -> Result<fixture::SettingsView, String> {
    fixture::save_with_dev(env, request, &sandbox.absent_dev())
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
        twitter_cookies_path: None,
    }
}

#[test]
fn save_writes_known_keys_with_sorted_canonical_sources_and_a_trailing_newline() {
    let sandbox = Sandbox::new("canonical");
    let env = sandbox.env(&[]);
    let view = save_h(&sandbox, &env, &input("fast", 30, &["v2ex", "brave", "github", "brave"])).unwrap();
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
    save_h(&sandbox, &env, &input("default", 45, &["tavily"])).unwrap();
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
    save_h(&sandbox, &env, &input("dev", 20, &["hackernews"])).unwrap();
    let before = std::fs::read(sandbox.user_config()).unwrap();
    let bad_inputs = [
        input("nope", 20, &[]),
        input("dev", 0, &[]),
        input("dev", 91, &[]),
        input("all", 1000, &[]),
        input("dev", 20, &["jina"]),
        input("dev", 20, &["../../etc"]),
        input("dev", 20, &["tavily/../brave"]),
        SettingsInput { twitter_cookies_path: Some("bad\0path".into()), ..input("dev", 20, &[]) },
        SettingsInput { twitter_cookies_path: Some("x".repeat(2000)), ..input("dev", 20, &[]) },
    ];
    for bad in bad_inputs {
        assert!(save_h(&sandbox, &env, &bad).is_err(), "{:?} must be rejected", bad.route);
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
    let error = save_h(&sandbox, &env, &input("default", 60, &[])).unwrap_err();
    assert!(error.contains("未保存"));
    assert_eq!(std::fs::read_to_string(sandbox.user_config()).unwrap(), "{ not json");
}

#[test]
fn env_config_path_is_the_only_target_when_set() {
    let sandbox = Sandbox::new("env");
    let custom = sandbox.0.join("custom").join("cfg.json");
    let env = sandbox.env(&[("MULTI_SEARCH_CONFIG", custom.to_string_lossy().into_owned())]);
    assert_eq!(fixture::config_path(&env).unwrap(), custom);
    let view = save_h(&sandbox, &env, &input("social", 10, &["twitter"])).unwrap();
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
    let view = save_h(&sandbox, &env, &request).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["twitter_cookies_path"], "C:/cookies/twitter.json");
    assert_eq!(view.twitter_cookies_path.as_deref(), Some("C:/cookies/twitter.json"));
    assert!(view.twitter_env_overrides);
    assert_eq!(view.active_sources, vec!["twitter"]);
    assert_eq!(view.status, "ok");

    let mut cleared = input("social", 60, &[]);
    cleared.twitter_cookies_path = Some("".into());
    save_h(&sandbox, &env, &cleared).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert!(json.get("twitter_cookies_path").is_none());
}

#[test]
fn all_sources_disabled_for_the_route_reports_no_active_source_without_reenabling() {
    let sandbox = Sandbox::new("alldisabled");
    let env = sandbox.env(&[]);
    let view = save_h(&sandbox, &env, &input("default", 60, &["baidu", "brave", "exa", "firecrawl", "parallel", "serpapi", "tavily"])).unwrap();
    assert!(view.active_sources.is_empty());
    assert_eq!(view.status, "no_active_source");
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["disabled_sources"].as_array().unwrap().len(), 7, "disabled list must not be silently reset");
}

#[test]
fn toggling_a_source_back_on_removes_it_from_disabled_sources() {
    let sandbox = Sandbox::new("toggle");
    let env = sandbox.env(&[]);
    save_h(&sandbox, &env, &input("fast", 60, &["baidu", "exa"])).unwrap();
    let view = save_h(&sandbox, &env, &input("fast", 60, &["exa"])).unwrap();
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
    save_h(&sandbox, &env, &request).unwrap();
    std::fs::copy(sandbox.user_config(), PathBuf::from(target)).unwrap();
}

#[test]
fn view_without_a_file_reports_defaults_and_path_source() {
    let sandbox = Sandbox::new("view");
    let view = fixture::view_with_dev(&sandbox.env(&[]), &sandbox.absent_dev());
    assert!(!view.file_present);
    assert_eq!(view.route, "default");
    assert_eq!(view.timeout, 60);
    assert!(view.disabled_sources.is_empty());
    assert_eq!(view.status, "ok");
}

/// Dev fallback fixture: a file shaped like the repo-root config the CLI reads when no user file exists.
fn write_dev_fallback(sandbox: &Sandbox) -> PathBuf {
    let dev = sandbox.0.join("dev").join("multi-search-config.json");
    std::fs::create_dir_all(dev.parent().unwrap()).unwrap();
    std::fs::write(
        &dev,
        r#"{"type": "dev", "timeout": 40, "count": 9, "no_scrape": true, "counts": {"brave": 3}, "disabled_sources": ["exa"]}"#,
    )
    .unwrap();
    dev
}

#[test]
fn save_with_no_user_file_seeds_from_the_dev_fallback_the_cli_reads_and_writes_only_the_user_file() {
    let sandbox = Sandbox::new("fallback-seed");
    let dev = write_dev_fallback(&sandbox);
    let dev_before = std::fs::read(&dev).unwrap();
    let env = sandbox.env(&[]);
    let before = fixture::view_with_dev(&env, &dev);
    assert_eq!(before.read_source, "dev_fallback");
    assert!(before.save_creates_override, "saving will create a user file that overrides the fallback");
    assert_eq!(before.route, "dev", "displayed values are the ones the CLI reads today");
    assert_eq!(before.timeout, 40);

    let view = fixture::save_with_dev(&env, &input("fast", 30, &[]), &dev).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["count"], 9, "fields the CLI already honours are kept");
    assert_eq!(json["no_scrape"], true);
    assert_eq!(json["counts"]["brave"], 3);
    assert_eq!(json["type"], "fast");
    assert_eq!(json["timeout"], 30);
    assert_eq!(std::fs::read(&dev).unwrap(), dev_before, "the repo-root dev file must never be written");
    assert_eq!(view.read_source, "user");
    assert!(!view.save_creates_override, "after the save the user file is the one read");
}

#[test]
fn an_existing_user_file_is_read_and_written_and_is_not_overridden_by_the_dev_fallback() {
    let sandbox = Sandbox::new("user-wins");
    let dev = write_dev_fallback(&sandbox);
    let env = sandbox.env(&[]);
    fixture::save_with_dev(&env, &input("default", 45, &["tavily"]), &dev).unwrap();
    let view = fixture::view_with_dev(&env, &dev);
    assert_eq!(view.read_source, "user");
    assert!(!view.save_creates_override);
    assert_eq!(view.route, "default");
    assert_eq!(view.timeout, 45);
}

#[test]
fn env_target_is_saved_explicitly_and_never_redirected_to_user_or_dev_files() {
    let sandbox = Sandbox::new("env-explicit");
    let dev = write_dev_fallback(&sandbox);
    let custom = sandbox.0.join("custom").join("cfg.json");
    let env = sandbox.env(&[("MULTI_SEARCH_CONFIG", custom.to_string_lossy().into_owned())]);
    let view = fixture::save_with_dev(&env, &input("social", 10, &["twitter"]), &dev).unwrap();
    assert!(custom.exists());
    assert!(!sandbox.user_config().exists(), "no user file is created when env selects another target");
    assert_eq!(view.read_source, "env");
    assert!(!view.save_creates_override);
}

#[test]
fn defaults_without_any_file_report_defaults_and_no_override() {
    let sandbox = Sandbox::new("defaults-only");
    let missing_dev = sandbox.0.join("none").join("multi-search-config.json");
    let env = sandbox.env(&[]);
    let view = fixture::view_with_dev(&env, &missing_dev);
    assert_eq!(view.read_source, "defaults");
    assert!(!view.save_creates_override);
}

#[test]
fn source_names_the_settings_page_sends_are_accepted_by_the_execution_allowlist() {
    use multi_search_desktop::settings_fixture::is_allowed_source;
    // Every canonical name the settings page sends, plus the CLI aliases it may read back.
    for name in ["baidu", "brave", "exa", "firecrawl", "github_repos", "hackernews", "parallel",
                 "serpapi", "sov2ex", "stackoverflow", "tavily", "twitter", "v2ex", "github-repos"] {
        assert!(is_allowed_source(name), "{name} must be accepted");
    }
    assert!(!is_allowed_source("jina"));
    assert!(!is_allowed_source("../etc"));
}

#[test]
fn unreadable_target_blocks_save_and_leaves_the_old_file_and_no_temp_file() {
    let sandbox = Sandbox::new("blocked");
    let env = sandbox.env(&[]);
    save_h(&sandbox, &env, &input("dev", 20, &["hackernews"])).unwrap();
    let before = std::fs::read(sandbox.user_config()).unwrap();
    // A directory at the target path cannot be read as a config, so save stops before any write.
    let blocker = sandbox.0.join("blocked.json");
    std::fs::create_dir_all(&blocker).unwrap();
    let env_blocked = sandbox.env(&[("MULTI_SEARCH_CONFIG", blocker.to_string_lossy().into_owned())]);
    assert!(save_h(&sandbox, &env_blocked, &input("dev", 20, &[])).is_err());
    assert_eq!(std::fs::read(sandbox.user_config()).unwrap(), before);
    assert!(sandbox.leftovers().iter().all(|n| !n.contains(".tmp-")));
}

#[test]
fn release_build_never_reads_or_displays_the_dev_fallback() {
    let sandbox = Sandbox::new("release-no-dev");
    let dev = write_dev_fallback(&sandbox);
    let env = sandbox.env(&[]);
    let view = fixture::view_with_dev_mode(&env, &dev, false, None);
    assert_eq!(view.read_source, "defaults", "release must not fall back to the build machine's source tree");
    assert_eq!(view.path_source, "defaults");
    assert_eq!(view.route, "default", "release must not display dev values");
    assert_eq!(view.timeout, 60);
    assert!(!view.save_creates_override);
    let user = sandbox.user_config().to_string_lossy().into_owned();
    assert_eq!(view.config_path.as_deref(), Some(user.as_str()), "the user path is shown, not the dev file");

    let saved = fixture::save_with_dev_mode(&env, &input("fast", 30, &[]), &dev, false).unwrap();
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["type"], "fast");
    assert!(json.get("count").is_none(), "release save must not merge dev-only fields");
    assert!(json.get("no_scrape").is_none(), "release save must not merge dev-only fields");
    assert_eq!(saved.read_source, "user");
}

#[test]
fn doctor_payload_supplies_the_displayed_config_path_and_source() {
    let sandbox = Sandbox::new("doctor-path");
    let env = sandbox.env(&[]);
    let cli_config = sandbox.0.join("cli-home").join("multi-search-config.json");
    let cli_text = cli_config.to_string_lossy().into_owned();
    let doctor = serde_json::json!({
        "config_path": cli_text.clone(),
        "config_path_source": "user",
    });
    let view = fixture::view_with_dev_mode(&env, &sandbox.absent_dev(), false, Some(&doctor));
    assert_eq!(
        view.config_path.as_deref(),
        Some(cli_text.as_str()),
        "the desktop must display the path reported by doctor --format json"
    );
    assert_eq!(view.path_source, "user");
    assert_eq!(view.read_source, "user");
    assert!(!view.file_present);
}

#[test]
fn a_doctor_reported_dev_fallback_is_displayed_with_its_values_even_in_a_release_build() {
    let sandbox = Sandbox::new("doctor-dev");
    let dev = write_dev_fallback(&sandbox);
    let dev_text = dev.to_string_lossy().into_owned();
    let env = sandbox.env(&[]);
    let doctor = serde_json::json!({
        "config_path": dev_text.clone(),
        "config_path_source": "dev_fallback",
    });
    let view = fixture::view_with_dev_mode(&env, &sandbox.absent_dev(), false, Some(&doctor));
    assert_eq!(view.path_source, "dev_fallback");
    assert_eq!(view.read_source, "dev_fallback");
    assert_eq!(view.config_path.as_deref(), Some(dev_text.as_str()));
    assert_eq!(view.route, "dev", "values come from the exact path the CLI reported");
    assert!(view.save_creates_override, "saving creates the user file that overrides the CLI's fallback");
}

#[test]
fn an_unusable_doctor_payload_leaves_the_local_path_rules_in_place() {
    let sandbox = Sandbox::new("doctor-invalid");
    let env = sandbox.env(&[]);
    let doctor = serde_json::json!({"config_path": 7, "config_path_source": "elsewhere"});
    let view = fixture::view_with_dev_mode(&env, &sandbox.absent_dev(), false, Some(&doctor));
    assert_eq!(view.read_source, "defaults");
    assert_eq!(view.path_source, "defaults");
    let user_text = sandbox.user_config().to_string_lossy().into_owned();
    assert_eq!(
        view.config_path.as_deref(),
        Some(user_text.as_str()),
        "an unrecognised doctor payload must not override the save target"
    );
}

fn timeout_range_covers_every_cli_route_default() {
    // ROUTE_META in search_runner.py: default/social/dev 60, fast 45, all 90.
    for (route, expected) in [("default", 60), ("fast", 45), ("all", 90), ("social", 60), ("dev", 60)] {
        assert_eq!(fixture::route_default_timeout(route), expected, "{route}");
        assert!((fixture::TIMEOUT_MIN..=fixture::TIMEOUT_MAX).contains(&expected), "{route} default must be savable");
    }
    assert_eq!(fixture::TIMEOUT_MIN, 1);
    assert_eq!(fixture::TIMEOUT_MAX, 90);
    let sandbox = Sandbox::new("timeout-90");
    let env = sandbox.env(&[]);
    let view = save_h(&sandbox, &env, &input("all", 90, &[])).unwrap();
    assert_eq!(view.timeout, 90);
    assert!(view.timeout_configured);
    assert!(!view.timeout_out_of_range);
    assert!(save_h(&sandbox, &env, &input("all", 91, &[])).is_err());
}

#[test]
fn an_absent_timeout_reports_the_route_default_and_is_never_written_when_not_edited() {
    let sandbox = Sandbox::new("timeout-absent");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), r#"{"type": "all"}"#).unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.timeout, 90, "the all route default, not a desktop invention");
    assert!(!view.timeout_configured);
    let request = SettingsInput { timeout: None, ..input("all", 1, &["brave"]) };
    save_h(&sandbox, &env, &request).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert!(json.get("timeout").is_none(), "an unedited timeout must not be materialised");
}

#[test]
fn an_out_of_range_stored_timeout_is_shown_as_is_and_preserved_when_not_edited() {
    let sandbox = Sandbox::new("timeout-wide");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), r#"{"type": "default", "timeout": 120}"#).unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.timeout, 120, "no silent rewrite to 60");
    assert!(view.timeout_configured);
    assert!(view.timeout_out_of_range);
    let request = SettingsInput { timeout: None, ..input("dev", 1, &[]) };
    save_h(&sandbox, &env, &request).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["timeout"], 120);
    assert_eq!(json["type"], "dev");
}

#[test]
fn unknown_disabled_entries_are_reported_and_kept_through_a_save() {
    let sandbox = Sandbox::new("unknown-disabled");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), r#"{"disabled_sources": ["future_source", "exa", 7]}"#).unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.disabled_sources, vec!["exa"]);
    assert_eq!(view.unknown_disabled_sources, vec!["future_source", "7"]);
    save_h(&sandbox, &env, &input("default", 30, &["brave"])).unwrap();
    let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["disabled_sources"], serde_json::json!(["brave", "future_source", 7]), "known edits apply; unknown entries survive");
}
