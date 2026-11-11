//! Balance command boundary: plugin-id allowlist, CLI JSON parsing and Chinese error mapping.
//! The fixture CLI stands in for the managed CLI; no network is involved.
mod common;

use multi_search_desktop::balance_fixture as balance;
use multi_search_desktop::credential_fixture as credential;
use std::time::{Duration, Instant};

const BALANCE_JSON: &str = r#"{
  "schema_version": 1,
  "providers": [{
    "id": "tavily",
    "label": "Tavily",
    "auth_methods": [{
      "type": "api",
      "label": "API Key",
      "credential": "tavily",
      "purpose": "search_key"
    }],
    "balance_supported": true,
    "balance_note": "",
    "reports": [{
      "provider": "tavily",
      "status": "ok",
      "scope": "key",
      "unit": "credits",
      "remaining": null,
      "limit": 1000.5,
      "used": 0,
      "resets_at": null,
      "period": "month",
      "key_fingerprint": null,
      "error_kind": null,
      "message": "",
      "fetched_at": "2026-11-01T00:00:00+00:00"
    }]
  }]
}"#;

#[test]
fn provider_ids_are_checked_against_the_plugin_whitelist() {
    assert_eq!(balance::validate(None).unwrap(), None);
    assert_eq!(balance::validate(Some(" tavily ")).unwrap().as_deref(), Some("tavily"));
    assert_eq!(balance::validate(Some("exa")).unwrap().as_deref(), Some("exa"));
    for bad in ["", "  ", "../tavily", "tavily/../exa", "github_repos", "unknown"] {
        assert_eq!(balance::validate(Some(bad)).unwrap_err(), "不支持的余额服务商");
    }
    // A rejected id must fail before a missing executable could ever be spawned.
    let profile = common::Profile::new();
    let missing = profile.root.join("missing-cli");
    let error = balance::view_with_timeout(
        &profile.environment,
        &missing,
        Some("evil"),
        false,
        Duration::from_millis(100),
    )
    .unwrap_err();
    assert_eq!(error, "不支持的余额服务商");
}

#[test]
fn balance_cli_json_is_parsed_and_nulls_stay_none() {
    let view = balance::parse(BALANCE_JSON).unwrap();
    assert_eq!(view.schema_version, 1);
    assert_eq!(view.providers.len(), 1);
    let provider = &view.providers[0];
    assert_eq!(provider.id, "tavily");
    assert_eq!(provider.auth_methods[0].method_type, "api");
    assert_eq!(provider.auth_methods[0].purpose, "search_key");
    let report = &provider.reports[0];
    assert_eq!(report.remaining, None, "unknown must not become zero");
    assert_eq!(report.limit, Some(1000.5));
    assert_eq!(report.used, Some(0.0));
    assert_eq!(report.resets_at, None);

    assert_eq!(balance::parse("").unwrap_err(), "CLI 未返回有效的余额结果。");
    assert_eq!(balance::parse("not-json").unwrap_err(), "CLI 未返回有效的余额结果。");
    assert_eq!(
        balance::parse(r#"{"schema_version":2,"providers":[]}"#).unwrap_err(),
        "CLI 返回了不支持的余额结果版本。"
    );
}

#[test]
fn timeout_and_invalid_output_map_to_chinese_errors() {
    assert_eq!(
        balance::interpret(true, None, false, "").unwrap_err(),
        "查询余额超时，请稍后重试。"
    );
    assert_eq!(
        balance::interpret(false, Some(0), true, "{}").unwrap_err(),
        "CLI 返回的余额结果过大，无法读取。"
    );
    assert_eq!(
        balance::interpret(false, Some(1), false, "").unwrap_err(),
        "读取余额失败，请检查 CLI 后重试。"
    );
    assert_eq!(
        balance::interpret(false, Some(0), false, "not-json").unwrap_err(),
        "CLI 未返回有效的余额结果。"
    );
}

#[test]
fn view_calls_the_cli_with_provider_and_refresh_flags() {
    let profile = common::Profile::new();
    let cli = profile.root.join(multi_search_desktop::CLI_FILE_NAME);
    let args_path = profile.root.join("balance-args.json");
    let mut environment = profile.environment.clone();
    environment.variables.insert("FIXTURE_BALANCE".into(), "ok".into());
    environment
        .variables
        .insert("FIXTURE_ARGS_PATH".into(), args_path.to_string_lossy().into_owned());

    let view = balance::view(&environment, &cli, Some("tavily"), true).unwrap();
    assert_eq!(view.providers[0].reports[0].status, "ok");

    let args: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(args_path).unwrap()).unwrap();
    assert_eq!(
        args,
        serde_json::json!(["balance", "--format", "json", "--provider", "tavily", "--refresh"])
    );
}

#[test]
fn a_hanging_cli_hits_the_process_timeout() {
    let profile = common::Profile::new();
    let cli = profile.root.join(multi_search_desktop::CLI_FILE_NAME);
    let mut environment = profile.environment.clone();
    environment.variables.insert("FIXTURE_BALANCE".into(), "hang".into());
    let started = Instant::now();
    let error = balance::view_with_timeout(
        &environment,
        &cli,
        Some("tavily"),
        false,
        Duration::from_millis(300),
    )
    .unwrap_err();
    assert_eq!(error, "查询余额超时，请稍后重试。");
    assert!(started.elapsed() < Duration::from_secs(5));
}

#[test]
fn exa_admin_is_a_writable_balance_only_credential_entry() {
    let profile = common::Profile::new();
    assert_eq!(
        credential::resolve("exa_admin").unwrap(),
        ("exa_admin", "exa_admin")
    );
    let row = credential::save_for(
        &profile.environment.variables,
        "exa_admin",
        "synthetic-exa-service-key",
    )
    .unwrap();
    assert_eq!(row.source, "exa_admin");
    assert_eq!(row.store.state, "present");
    assert_eq!(
        credential::read_for(&profile.environment.variables, "exa_admin").unwrap(),
        "synthetic-exa-service-key"
    );
    let keys_path = credential::keys_file_path(&profile.environment.variables).unwrap();
    let keys: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(keys_path).unwrap()).unwrap();
    assert_eq!(keys["exa_admin"], "synthetic-exa-service-key");
    // Balance-only credentials never pretend to be search-test sources.
    assert!(credential::source_test("exa_admin", &serde_json::json!({})).is_err());
}
