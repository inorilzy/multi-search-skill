//! Desktop settings writer against real temp files. The user config and home are never touched:
//! each test gets a unique temp directory and an explicit environment map.
use multi_search_desktop::settings_fixture as fixture;
use multi_search_desktop::{
    settings_fixture::{RouteConfig, RouteMap, SettingsInput},
    RuntimeEnvironment,
};
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
        let mut variables = BTreeMap::from([(
            "USERPROFILE".to_string(),
            self.0.to_string_lossy().into_owned(),
        )]);
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
        self.0
            .join(".multi-search")
            .join("multi-search-config.json")
    }
    fn leftovers(&self) -> Vec<String> {
        let dir = self.user_config().parent().unwrap().to_path_buf();
        std::fs::read_dir(dir)
            .map(|rd| {
                rd.filter_map(|e| e.ok())
                    .map(|e| e.file_name().to_string_lossy().into_owned())
                    .collect()
            })
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
fn save_h(
    sandbox: &Sandbox,
    env: &RuntimeEnvironment,
    request: &SettingsInput,
) -> Result<fixture::SettingsView, String> {
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
        timeout,
        disabled_sources: disabled.iter().map(|s| s.to_string()).collect(),
        routes: None,
        twitter_cookies_path: None,
    }
}

#[test]
fn save_writes_known_keys_with_sorted_canonical_sources_and_a_trailing_newline() {
    let sandbox = Sandbox::new("canonical");
    let env = sandbox.env(&[]);
    let view = save_h(
        &sandbox,
        &env,
        &input("fast", 30, &["v2ex", "brave", "github", "brave"]),
    )
    .unwrap();
    let text = std::fs::read_to_string(sandbox.user_config()).unwrap();
    assert!(text.ends_with('\n'));
    let json: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(json["type"], "fast");
    assert_eq!(json["timeout"], 30);
    assert_eq!(
        json["disabled_sources"],
        serde_json::json!(["brave", "github_repos", "sov2ex"])
    );
    assert_eq!(
        view.disabled_sources,
        vec!["brave", "github_repos", "sov2ex"]
    );
    assert_eq!(view.route, "fast");
    assert_eq!(view.path_source, "user");
    assert_eq!(
        sandbox.leftovers(),
        vec!["multi-search-config.json"],
        "no temp file may remain"
    );
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
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
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
        input("dev", 61, &[]),
        input("dev", 20, &["jina"]),
        input("dev", 20, &["../../etc"]),
        input("dev", 20, &["tavily/../brave"]),
        SettingsInput {
            twitter_cookies_path: Some("bad\0path".into()),
            ..input("dev", 20, &[])
        },
        SettingsInput {
            twitter_cookies_path: Some("x".repeat(2000)),
            ..input("dev", 20, &[])
        },
    ];
    for bad in bad_inputs {
        assert!(
            save_h(&sandbox, &env, &bad).is_err(),
            "{:?} must be rejected",
            bad.route
        );
        assert_eq!(
            std::fs::read(sandbox.user_config()).unwrap(),
            before,
            "old config must survive"
        );
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
    assert_eq!(
        std::fs::read_to_string(sandbox.user_config()).unwrap(),
        "{ not json"
    );
}

#[test]
fn env_config_path_is_the_only_target_when_set() {
    let sandbox = Sandbox::new("env");
    let custom = sandbox.0.join("custom").join("cfg.json");
    let env = sandbox.env(&[("MULTI_SEARCH_CONFIG", custom.to_string_lossy().into_owned())]);
    assert_eq!(fixture::config_path(&env).unwrap(), custom);
    let view = save_h(&sandbox, &env, &input("social", 10, &["twitter"])).unwrap();
    assert!(custom.exists());
    assert!(
        !sandbox.user_config().exists(),
        "the user config must not be written when env selects another path"
    );
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
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["twitter_cookies_path"], "C:/cookies/twitter.json");
    assert_eq!(
        view.twitter_cookies_path.as_deref(),
        Some("C:/cookies/twitter.json")
    );
    assert!(view.twitter_env_overrides);
    assert_eq!(view.active_sources, vec!["twitter"]);
    assert_eq!(view.status, "ok");

    let mut cleared = input("social", 60, &[]);
    cleared.twitter_cookies_path = Some("".into());
    save_h(&sandbox, &env, &cleared).unwrap();
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert!(json.get("twitter_cookies_path").is_none());
}

#[test]
fn all_sources_disabled_for_the_route_reports_no_active_source_without_reenabling() {
    let sandbox = Sandbox::new("alldisabled");
    let env = sandbox.env(&[]);
    let view = save_h(
        &sandbox,
        &env,
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
    assert!(view.active_sources.is_empty());
    assert_eq!(view.status, "no_active_source");
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(
        json["disabled_sources"].as_array().unwrap().len(),
        7,
        "disabled list must not be silently reset"
    );
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
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["disabled_sources"], serde_json::json!(["exa"]));
}

/// Handoff to the independent CLI check: when MS_SETTINGS_HANDOFF names a path, the exact file
/// the desktop save path produced is copied there so the Python CLI test reads it unchanged.
#[test]
fn handoff_file_for_the_independent_cli_check() {
    let Some(target) = std::env::var_os("MS_SETTINGS_HANDOFF") else {
        return;
    };
    let sandbox = Sandbox::new("handoff");
    let env = sandbox.env(&[]);
    let mut request = input("default", 25, &["brave"]);
    // Synthetic path reference only; the CLI test checks it is passed through, never read.
    request.twitter_cookies_path = Some("C:/synthetic/handoff-twitter-cookies.json".into());
    // 模拟新 UI 保存完整路由映射，供 Python 测试逐字段核对两端工厂。
    request.routes = Some(fixture::builtin_routes());
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
fn save_with_no_user_file_seeds_from_the_dev_fallback_the_cli_reads_and_writes_only_the_user_file()
{
    let sandbox = Sandbox::new("fallback-seed");
    let dev = write_dev_fallback(&sandbox);
    let dev_before = std::fs::read(&dev).unwrap();
    let env = sandbox.env(&[]);
    let before = fixture::view_with_dev(&env, &dev);
    assert_eq!(before.read_source, "dev_fallback");
    assert!(
        before.save_creates_override,
        "saving will create a user file that overrides the fallback"
    );
    assert_eq!(
        before.route, "dev",
        "displayed values are the ones the CLI reads today"
    );
    assert_eq!(before.timeout, 40);

    let view = fixture::save_with_dev(&env, &input("fast", 30, &[]), &dev).unwrap();
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(json["count"], 9, "fields the CLI already honours are kept");
    assert_eq!(json["no_scrape"], true);
    assert_eq!(json["counts"]["brave"], 3);
    assert_eq!(json["type"], "fast");
    assert_eq!(json["timeout"], 30);
    assert_eq!(
        std::fs::read(&dev).unwrap(),
        dev_before,
        "the repo-root dev file must never be written"
    );
    assert_eq!(view.read_source, "user");
    assert!(
        !view.save_creates_override,
        "after the save the user file is the one read"
    );
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
    assert!(
        !sandbox.user_config().exists(),
        "no user file is created when env selects another target"
    );
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
    let env_blocked = sandbox.env(&[(
        "MULTI_SEARCH_CONFIG",
        blocker.to_string_lossy().into_owned(),
    )]);
    assert!(save_h(&sandbox, &env_blocked, &input("dev", 20, &[])).is_err());
    assert_eq!(std::fs::read(sandbox.user_config()).unwrap(), before);
    assert!(sandbox.leftovers().iter().all(|n| !n.contains(".tmp-")));
}

#[test]
fn builtin_factory_has_the_cross_layer_contract_and_is_used_only_when_routes_is_missing() {
    let routes = fixture::builtin_routes();
    assert_eq!(routes.len(), 5);
    assert_eq!(routes["default"].label, "默认（网页综合）");
    assert_eq!(
        routes["default"].sources,
        [
            "brave",
            "parallel",
            "tavily",
            "exa",
            "serpapi",
            "firecrawl",
            "baidu"
        ]
    );
    assert_eq!(
        routes["fast"].sources,
        ["baidu", "tavily", "firecrawl", "exa"]
    );
    assert_eq!(
        routes["all"].sources,
        [
            "brave",
            "parallel",
            "tavily",
            "exa",
            "serpapi",
            "baidu",
            "firecrawl",
            "twitter",
            "stackoverflow",
            "github_repos",
            "hackernews",
            "sov2ex"
        ]
    );
    assert_eq!(routes["social"].sources, ["twitter"]);
    assert_eq!(
        routes["dev"].sources,
        ["stackoverflow", "github_repos", "hackernews"]
    );
    assert!(routes.values().all(|route| route.timeout.is_none()));

    let sandbox = Sandbox::new("explicit-no-backfill");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(
        sandbox.user_config(),
        r#"{"type":"only","routes":{"only":{"label":"仅保留自定义","sources":["tavily"],"timeout":null}}}"#,
    )
    .unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.routes.len(), 1);
    assert!(view.routes.contains_key("only"));
    assert!(
        !view.routes.contains_key("default"),
        "explicit routes must not restore deleted built-ins"
    );
    assert_eq!(view.builtin_routes, routes);
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
fn complete_route_map_can_create_edit_and_delete_custom_or_builtin_groups() {
    let sandbox = Sandbox::new("route-crud");
    let env = sandbox.env(&[]);
    let mut create = input("research_1", 41, &[]);
    create.routes = Some(custom_routes());
    let created = save_h(&sandbox, &env, &create).unwrap();
    assert_eq!(created.route, "research_1");
    assert_eq!(created.routes["research_1"].label, "研究组合");
    assert_eq!(
        created.routes["research_1"].sources,
        ["github_repos", "sov2ex"]
    );
    assert_eq!(created.effective_timeout, 7);

    let mut edited_routes = created.routes.clone();
    edited_routes.remove("all"); // Built-ins are ordinary editable/deletable groups after initialization.
    edited_routes.get_mut("research_1").unwrap().label = "研究与社区".into();
    edited_routes.get_mut("research_1").unwrap().timeout = None;
    let mut edit = input("research_1", 33, &["sov2ex"]);
    edit.routes = Some(edited_routes);
    let edited = save_h(&sandbox, &env, &edit).unwrap();
    assert!(!edited.routes.contains_key("all"));
    assert_eq!(edited.routes["research_1"].label, "研究与社区");
    assert_eq!(
        edited.effective_timeout, 33,
        "null route timeout inherits the global timeout"
    );
    assert_eq!(edited.active_sources, ["github_repos"]);
    assert_eq!(
        edited.routes["research_1"].sources,
        ["github_repos", "sov2ex"],
        "global disabling must not remove route membership"
    );

    let mut deleted_routes = edited.routes.clone();
    deleted_routes.remove("research_1");
    let mut delete = input("default", 33, &["sov2ex"]);
    delete.routes = Some(deleted_routes);
    let deleted = save_h(&sandbox, &env, &delete).unwrap();
    assert!(!deleted.routes.contains_key("research_1"));
    assert!(
        !deleted.routes.contains_key("all"),
        "saving must not backfill a deleted built-in"
    );
}

#[test]
fn current_or_last_route_cannot_be_deleted_and_invalid_route_fields_are_rejected() {
    let routes = custom_routes();
    let mut without_current = routes.clone();
    without_current.remove("research_1");
    let mut deleting_current = input("research_1", 30, &[]);
    deleting_current.routes = Some(without_current);
    assert!(fixture::validate(&deleting_current)
        .unwrap_err()
        .contains("先切换"));

    let mut only = RouteMap::new();
    only.insert(
        "one".into(),
        RouteConfig {
            label: "One".into(),
            sources: vec!["tavily".into()],
            timeout: None,
        },
    );
    only.clear();
    let mut deleting_last = input("one", 30, &[]);
    deleting_last.routes = Some(only);
    assert!(fixture::validate(&deleting_last).is_err());

    for bad in [
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
        let mut map = RouteMap::new();
        map.insert(bad.0.into(), bad.1);
        let mut request = input(bad.0, 30, &[]);
        request.routes = Some(map);
        assert!(
            fixture::validate(&request).is_err(),
            "{} must be rejected",
            bad.0
        );
    }
    let mut too_long = RouteMap::new();
    too_long.insert(
        "long".into(),
        RouteConfig {
            label: "界".repeat(81),
            sources: vec!["tavily".into()],
            timeout: None,
        },
    );
    let mut request = input("long", 30, &[]);
    request.routes = Some(too_long);
    assert!(fixture::validate(&request).is_err());
}

#[test]
fn save_without_routes_preserves_the_exact_existing_custom_map_and_unrelated_fields() {
    let sandbox = Sandbox::new("preserve-routes");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    let routes = serde_json::json!({
        "custom": {"label": "Custom", "sources": ["hackernews", "brave"], "timeout": 9}
    });
    std::fs::write(
        sandbox.user_config(),
        serde_json::to_vec(&serde_json::json!({
            "type": "custom", "timeout": 60, "routes": routes, "future": {"keep": true}
        }))
        .unwrap(),
    )
    .unwrap();
    let saved = save_h(&sandbox, &env, &input("custom", 44, &["brave"])).unwrap();
    assert_eq!(saved.routes["custom"].timeout, Some(9));
    assert_eq!(saved.effective_timeout, 9);
    let object: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(sandbox.user_config()).unwrap()).unwrap();
    assert_eq!(object["routes"], routes);
    assert_eq!(object["future"]["keep"], true);
}

#[test]
fn explicit_bad_routes_or_type_make_view_unreadable_and_block_save_byte_for_byte() {
    let cases = [
        r#"{"type":"default","routes":{}}"#,
        r#"{"type":"missing","routes":{"only":{"label":"Only","sources":["tavily"],"timeout":null}}}"#,
        r#"{"type":7}"#,
        r#"{"type":"default","routes":{"default":{"label":"Default","sources":["unknown"],"timeout":null}}}"#,
        r#"{"type":"default","routes":{"default":{"label":"Default","sources":["tavily"],"timeout":null,"extra":true}}}"#,
        r#"{"type":"default","routes":[]}"#,
    ];
    for (index, body) in cases.into_iter().enumerate() {
        let sandbox = Sandbox::new(&format!("bad-routes-{index}"));
        let env = sandbox.env(&[]);
        std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
        std::fs::write(sandbox.user_config(), body).unwrap();
        let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
        assert_eq!(view.status, "config_unreadable");
        assert!(
            view.route.is_empty(),
            "bad config must not pretend default is selected"
        );
        assert!(
            view.routes.is_empty(),
            "bad config must not pretend built-ins are active"
        );
        let before = std::fs::read(sandbox.user_config()).unwrap();
        assert!(save_h(&sandbox, &env, &input("default", 30, &[])).is_err());
        assert_eq!(std::fs::read(sandbox.user_config()).unwrap(), before);
    }
}

#[test]
fn route_sources_trim_aliases_and_deduplicate_in_first_seen_order() {
    let sandbox = Sandbox::new("trim-route-sources");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(
        sandbox.user_config(),
        r#"{"type":"custom","routes":{"custom":{"label":"Custom","sources":[" github ","github-repos"," v2ex "],"timeout":null}}}"#,
    )
    .unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.status, "ok");
    assert_eq!(view.routes["custom"].sources, ["github_repos", "sov2ex"]);
}

#[test]
fn legacy_web_type_reads_as_default_but_web_cannot_be_defined() {
    let sandbox = Sandbox::new("web-alias");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), r#"{"type":"web","timeout":12}"#).unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.route, "default");
    assert_eq!(view.effective_timeout, 12);

    let mut request = input("web", 20, &[]);
    request.routes = Some(fixture::builtin_routes());
    let validated = fixture::validate(&request).unwrap();
    assert_eq!(
        validated.route, "default",
        "web input remains a compatibility alias"
    );
}

#[test]
fn null_type_is_the_legacy_default_but_other_non_strings_are_unreadable() {
    let sandbox = Sandbox::new("null-type");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), r#"{"type":null}"#).unwrap();
    let view = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert_eq!(view.status, "ok");
    assert_eq!(view.route, "default");

    std::fs::write(sandbox.user_config(), r#"{"type":false}"#).unwrap();
    assert_eq!(
        fixture::view_with_dev(&env, &sandbox.absent_dev()).status,
        "config_unreadable"
    );
}

#[test]
fn effective_timeout_matches_legacy_cli_meta_when_global_timeout_is_missing() {
    let sandbox = Sandbox::new("meta-timeout");
    let env = sandbox.env(&[]);
    std::fs::create_dir_all(sandbox.user_config().parent().unwrap()).unwrap();
    std::fs::write(sandbox.user_config(), r#"{"type":"fast"}"#).unwrap();
    let fast = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert!(!fast.timeout_configured);
    assert_eq!(fast.timeout, 60, "the editable global default remains 60");
    assert_eq!(
        fast.effective_timeout, 45,
        "preview matches CLI fast metadata"
    );
    assert_eq!(fast.effective_timeouts["fast"], 45);
    assert_eq!(fast.effective_timeouts["all"], 90);
    assert_eq!(fast.effective_timeouts["default"], 60);

    std::fs::write(sandbox.user_config(), r#"{"type":"all"}"#).unwrap();
    assert_eq!(
        fixture::view_with_dev(&env, &sandbox.absent_dev()).effective_timeout,
        90
    );

    std::fs::write(sandbox.user_config(), r#"{"type":"fast","timeout":22}"#).unwrap();
    let explicit = fixture::view_with_dev(&env, &sandbox.absent_dev());
    assert!(explicit.timeout_configured);
    assert_eq!(explicit.effective_timeout, 22);
}
