//! Usage command boundary; the fixture CLI replaces the managed executable without network.
mod common;

use multi_search_desktop::{usage_fixture as usage, DesktopManager};
use std::time::{Duration, Instant};

// Mirrors T04's CLI schema, including unknown amounts, totals and nullable pace fields.
const USAGE_JSON: &str = r#"{
  "schema_version": 1,
  "retention_days": 30,
  "providers": [{
    "id": "tavily", "label": "Tavily", "balance_supported": true, "balance_note": "",
    "accounts": [],
    "total": {"remaining": null, "limit": null, "percent": null, "unit": null, "relative": false},
    "alert": null,
    "current": [{
      "provider": "tavily", "status": "ok", "scope": "key", "unit": "credits",
      "remaining": null, "limit": 1000.5, "used": 0,
      "resets_at": null, "period": "month", "key_fingerprint": null,
      "error_kind": null, "message": "", "fetched_at": "2026-11-01T00:00:00+00:00"
    }],
    "totals": [{"scope": "key", "unit": "credits", "key_count": 2,
                "message": "部分 Key 未知", "remaining": null, "limit": 1000.5}],
    "history": [{"key_fingerprint": null, "scope": "key", "unit": "credits",
                 "remaining": null, "limit": 1000.5, "fetched_at": "2026-11-01T00:00:00+00:00"}],
    "pace": [{"key_fingerprint": null, "scope": "key", "unit": "credits",
              "rate_per_day": null, "projected_empty_at": null,
              "lasts_until_reset": null, "reason": "insufficient_data"}],
    "calls": {"today": {"search": 0, "scrape": 2, "failures": 1},
              "last_7_days": {"search": 4, "scrape": 3, "failures": 1},
              "daily": [{"day": "2026-11-01", "search": 0, "scrape": 2, "failures": 1}]}
  }]
}"#;

fn profile_with_payload(payload: &str) -> common::Profile {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_USAGE_JSON".into(), payload.into());
    profile
}

#[test]
fn unknown_provider_is_rejected_before_cli_discovery() {
    let profile = common::Profile::new();
    let mut environment = profile.environment.clone();
    environment.app_path.clear();
    environment.user_path.clear();
    let manager = DesktopManager::new(environment);
    for provider in [
        "",
        "  ",
        "../tavily",
        "tavily/../exa",
        "github_repos",
        "unknown",
    ] {
        assert_eq!(
            manager.usage_view(Some(provider), false).unwrap_err(),
            "不支持的用量服务商"
        );
    }
}

#[test]
fn an_old_cli_returns_an_update_state_instead_of_an_error() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_USAGE".into(), "legacy".into());
    let manager = DesktopManager::new(profile.environment.clone());
    let view = manager.usage_view(None, false).unwrap();
    assert_eq!(view.status, "cli_update_required");
    assert_eq!(view.message, "当前 CLI 不支持用量查询，请更新 CLI 后重试。");
    assert!(view.providers.is_empty());
}

#[test]
fn rejected_provider_never_starts_an_available_cli() {
    let mut profile = common::Profile::new();
    let marker = profile.root.join("cli-started");
    profile.environment.variables.insert(
        "FIXTURE_LAUNCH_PATH".into(),
        marker.to_string_lossy().into_owned(),
    );
    let manager = DesktopManager::new(profile.environment.clone());
    assert_eq!(
        manager.usage_view(Some("unknown"), true).unwrap_err(),
        "不支持的用量服务商"
    );
    assert!(
        !marker.exists(),
        "even a version probe must not start for a rejected provider"
    );
}

#[test]
fn cli_usage_data_preserves_totals_history_pace_and_unknown_amounts() {
    let profile = profile_with_payload(USAGE_JSON);
    let manager = DesktopManager::new(profile.environment.clone());
    let view = manager.usage_view(Some("tavily"), false).unwrap();
    assert_eq!(view.status, "ready");
    assert_eq!(view.message, "");
    let mut wire = serde_json::to_value(&view).unwrap();
    wire.as_object_mut().unwrap().remove("status");
    wire.as_object_mut().unwrap().remove("message");
    let mut expected: serde_json::Value = serde_json::from_str(USAGE_JSON).unwrap();
    // BalanceReport uses f64: JSON's integer zero and floating zero carry the same amount.
    expected["providers"][0]["current"][0]["used"] = serde_json::json!(0.0);
    assert_eq!(wire, expected);
}

#[test]
fn unreadable_store_keeps_empty_counts_unknown_and_preserves_usage_error() {
    let mut payload: serde_json::Value = serde_json::from_str(USAGE_JSON).unwrap();
    payload["usage_error"] = serde_json::json!("unreadable");
    payload["providers"][0]["calls"] =
        serde_json::json!({"today": {}, "last_7_days": {}, "daily": []});
    let profile = profile_with_payload(&payload.to_string());
    let view = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap();
    assert_eq!(view.usage_error.as_deref(), Some("unreadable"));
    assert_eq!(view.providers[0].calls.today.search, None);
    assert_eq!(
        serde_json::to_value(view).unwrap()["providers"][0]["calls"],
        payload["providers"][0]["calls"]
    );
}

#[test]
fn boolean_pace_outcomes_and_a_null_reason_are_preserved() {
    for outcome in [true, false] {
        let mut payload: serde_json::Value = serde_json::from_str(USAGE_JSON).unwrap();
        payload["providers"][0]["pace"][0]["lasts_until_reset"] = serde_json::json!(outcome);
        payload["providers"][0]["pace"][0]["reason"] = serde_json::Value::Null;
        let profile = profile_with_payload(&payload.to_string());
        let view = DesktopManager::new(profile.environment.clone())
            .usage_view(None, false)
            .unwrap();
        assert_eq!(view.providers[0].pace[0].lasts_until_reset, Some(outcome));
        assert_eq!(view.providers[0].pace[0].reason, None);
    }
}

#[test]
fn refresh_uses_fixed_cli_arguments_and_a_trimmed_plugin_id() {
    let mut profile = common::Profile::new();
    let args_path = profile.root.join("usage-args.json");
    profile.environment.variables.insert(
        "FIXTURE_ARGS_PATH".into(),
        args_path.to_string_lossy().into_owned(),
    );
    DesktopManager::new(profile.environment.clone())
        .usage_view(Some(" exa "), true)
        .unwrap();
    let args: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(args_path).unwrap()).unwrap();
    assert_eq!(
        args,
        serde_json::json!([
            "usage",
            "--format",
            "json",
            "--provider",
            "exa",
            "--refresh"
        ])
    );
}

#[test]
fn offline_all_provider_read_does_not_pass_refresh_or_provider_flags() {
    let mut profile = common::Profile::new();
    let args_path = profile.root.join("usage-args.json");
    profile.environment.variables.insert(
        "FIXTURE_ARGS_PATH".into(),
        args_path.to_string_lossy().into_owned(),
    );
    DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap();
    let args: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(args_path).unwrap()).unwrap();
    assert_eq!(args, serde_json::json!(["usage", "--format", "json"]));
}

#[test]
fn invalid_json_is_a_chinese_error() {
    let profile = profile_with_payload("not-json");
    let error = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap_err();
    assert_eq!(error, "CLI 未返回有效的用量结果。");
}

#[test]
fn unsupported_schema_is_a_chinese_error() {
    let profile =
        profile_with_payload(r#"{"schema_version":2,"retention_days":30,"providers":[]}"#);
    let error = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap_err();
    assert_eq!(error, "CLI 返回了不支持的用量结果版本。");
}

#[test]
fn a_hanging_cli_times_out_with_a_chinese_error() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_USAGE".into(), "hang".into());
    let started = Instant::now();
    let error = usage::view_with_timeout(
        &profile.environment,
        &profile.root.join(multi_search_desktop::CLI_FILE_NAME),
        None,
        false,
        Duration::from_millis(300),
    )
    .unwrap_err();
    assert_eq!(error, "查询用量超时，请稍后重试。");
    assert!(started.elapsed() < Duration::from_secs(5));
}

#[test]
fn configuration_failure_is_not_mistaken_for_an_old_cli() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_USAGE".into(), "failure".into());
    let error = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap_err();
    assert_eq!(error, "读取用量失败，请检查 CLI 后重试。");
}

#[test]
fn unrecognized_option_is_not_mistaken_for_a_missing_usage_command() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_USAGE".into(), "invalid-option".into());
    let error = DesktopManager::new(profile.environment.clone())
        .usage_view(None, true)
        .unwrap_err();
    assert_eq!(error, "读取用量失败，请检查 CLI 后重试。");
}

#[test]
fn truncated_output_is_a_chinese_error() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_USAGE".into(), "truncated".into());
    let error = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap_err();
    assert_eq!(error, "CLI 返回的用量结果过大，无法读取。");
}
