//! T04 account command and grouped usage contracts through a disposable managed CLI.
mod common;

use multi_search_desktop::{accounts_fixture, DesktopManager, CLI_FILE_NAME};
use serde_json::{json, Value};
use std::time::{Duration, Instant};

fn account() -> Value {
    json!({"id":"acc_A1", "name":"公司", "source":"oauth", "login_identity":"owner@example.com",
        "keys":["sha256:1234abcd"], "balance_credentials":{"exa_admin":"sha256:abcd1234"}})
}

fn profile_with_payload(payload: Value) -> common::Profile {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_ACCOUNTS_JSON".into(), payload.to_string());
    profile
}

fn mode(mode: &str) -> common::Profile {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_ACCOUNTS".into(), mode.into());
    profile
}

fn recorded_args(invoke: impl FnOnce(&DesktopManager)) -> Value {
    let mut profile =
        profile_with_payload(json!({"provider":"exa", "account":account(), "accounts":{}}));
    let path = profile.root.join("args.json");
    profile.environment.variables.insert(
        "FIXTURE_ARGS_PATH".into(),
        path.to_string_lossy().into_owned(),
    );
    invoke(&DesktopManager::new(profile.environment.clone()));
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn invalid_providers_never_start_cli_discovery() {
    let mut profile = common::Profile::new();
    let marker = profile.root.join("started");
    profile.environment.variables.insert(
        "FIXTURE_LAUNCH_PATH".into(),
        marker.to_string_lossy().into_owned(),
    );
    let manager = DesktopManager::new(profile.environment.clone());
    for provider in [
        "",
        " ",
        "../exa",
        "exa/../tavily",
        "github_repos",
        "unknown",
    ] {
        assert_eq!(
            manager.accounts_view(Some(provider)).unwrap_err(),
            "不支持的账号服务商"
        );
        assert_eq!(
            manager.accounts_add(provider, "公司").unwrap_err(),
            "不支持的账号服务商"
        );
        assert_eq!(
            manager
                .accounts_rename(provider, "acc_A1", "公司")
                .unwrap_err(),
            "不支持的账号服务商"
        );
        assert_eq!(
            manager
                .accounts_remove(provider, "acc_A1", false)
                .unwrap_err(),
            "不支持的账号服务商"
        );
        assert_eq!(
            manager
                .accounts_move_key(provider, "sha256:1234abcd", "default")
                .unwrap_err(),
            "不支持的账号服务商"
        );
    }
    assert!(!marker.exists());
}

#[test]
fn invalid_account_ids_are_rejected_before_any_cli_process() {
    let mut profile = common::Profile::new();
    let marker = profile.root.join("started");
    profile.environment.variables.insert(
        "FIXTURE_LAUNCH_PATH".into(),
        marker.to_string_lossy().into_owned(),
    );
    let manager = DesktopManager::new(profile.environment.clone());
    for id in [
        "",
        "acc_",
        "acc_a/b",
        "acc_a-b",
        "acc_中文",
        " acc_A1",
        "acc_a\n",
        "../default",
        "--help",
    ] {
        assert_eq!(
            manager.accounts_rename("exa", id, "公司").unwrap_err(),
            "无效的账号 ID。"
        );
        assert_eq!(
            manager.accounts_remove("exa", id, false).unwrap_err(),
            "无效的账号 ID。"
        );
        assert_eq!(
            manager
                .accounts_move_key("exa", "sha256:1234abcd", id)
                .unwrap_err(),
            "无效的账号 ID。"
        );
    }
    assert!(!marker.exists());
}

#[test]
fn default_account_cannot_be_renamed_or_removed() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    assert_eq!(
        manager
            .accounts_rename("exa", "default", "公司")
            .unwrap_err(),
        "默认账号不能重命名或删除。"
    );
    assert_eq!(
        manager.accounts_remove("exa", "default", true).unwrap_err(),
        "默认账号不能重命名或删除。"
    );
}

#[test]
fn blank_account_names_are_rejected() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    assert_eq!(
        manager.accounts_add("exa", " \n ").unwrap_err(),
        "账号名称不能为空。"
    );
    assert_eq!(
        manager.accounts_rename("exa", "acc_A1", " ").unwrap_err(),
        "账号名称不能为空。"
    );
}

#[test]
fn move_key_accepts_only_the_cli_fingerprint_format() {
    let profile = common::Profile::new();
    let manager = DesktopManager::new(profile.environment.clone());
    for fingerprint in [
        "raw-key",
        "--help",
        "sha256:123",
        "sha256:ABCDEF12",
        "sha256:1234abcd\n",
    ] {
        assert_eq!(
            manager
                .accounts_move_key("exa", fingerprint, "default")
                .unwrap_err(),
            "无效的 Key 指纹。"
        );
    }
}

#[test]
fn accounts_list_preserves_identity_and_balance_only_fingerprints() {
    let payload = json!({"accounts":{"exa":[account()]}});
    let profile = profile_with_payload(payload.clone());
    let view = DesktopManager::new(profile.environment.clone())
        .accounts_view(Some("exa"))
        .unwrap();
    assert_eq!(view.status, "ready");
    assert_eq!(view.message, "");
    assert_eq!(
        serde_json::to_value(view).unwrap()["accounts"],
        payload["accounts"]
    );
    assert!(!profile.root.join(".multi-search/keys.json").exists());
}

#[test]
fn account_identity_can_be_absent() {
    let mut row = account();
    row.as_object_mut().unwrap().remove("login_identity");
    let profile = profile_with_payload(json!({"accounts":{"exa":[row.clone()]}}));
    let view = DesktopManager::new(profile.environment.clone())
        .accounts_view(None)
        .unwrap();
    assert_eq!(
        serde_json::to_value(view).unwrap()["accounts"]["exa"][0],
        row
    );
}

#[test]
fn list_uses_fixed_json_flags_and_a_trimmed_plugin_id() {
    assert_eq!(
        recorded_args(|manager| {
            manager.accounts_view(Some(" exa ")).unwrap();
        }),
        json!(["accounts", "list", "--format", "json", "--provider", "exa"])
    );
}

#[test]
fn list_without_filter_passes_no_provider_flag() {
    assert_eq!(
        recorded_args(|manager| {
            manager.accounts_view(None).unwrap();
        }),
        json!(["accounts", "list", "--format", "json"])
    );
}

#[test]
fn add_passes_a_name_as_one_option_value_and_parses_the_created_account() {
    assert_eq!(
        recorded_args(|manager| {
            let result = manager.accounts_add(" exa ", " --refresh 公司 ").unwrap();
            assert_eq!(result.status, "ready");
            assert_eq!(serde_json::to_value(result.account).unwrap(), account());
            assert!(!result.removed);
        }),
        json!([
            "accounts",
            "add",
            "exa",
            "--name=--refresh 公司",
            "--format",
            "json"
        ])
    );
}

#[test]
fn rename_passes_the_account_id_and_new_name() {
    assert_eq!(
        recorded_args(|manager| {
            manager.accounts_rename("exa", "acc_A1", "个人").unwrap();
        }),
        json!([
            "accounts",
            "rename",
            "exa",
            "acc_A1",
            "--name=个人",
            "--format",
            "json"
        ])
    );
}

#[test]
fn remove_keeps_keys_without_the_delete_flag() {
    assert_eq!(
        recorded_args(|manager| {
            manager.accounts_remove("exa", "acc_A1", false).unwrap();
        }),
        json!(["accounts", "remove", "exa", "acc_A1", "--format", "json"])
    );
}

#[test]
fn remove_deletes_keys_only_when_explicitly_requested() {
    assert_eq!(
        recorded_args(|manager| {
            manager.accounts_remove("exa", "acc_A1", true).unwrap();
        }),
        json!([
            "accounts",
            "remove",
            "exa",
            "acc_A1",
            "--delete-keys",
            "--format",
            "json"
        ])
    );
}

#[test]
fn remove_preserves_the_cli_removal_receipt() {
    let profile =
        profile_with_payload(json!({"provider":"exa", "account":account(), "removed":true}));
    let result = DesktopManager::new(profile.environment.clone())
        .accounts_remove("exa", "acc_A1", false)
        .unwrap();
    assert!(result.removed);
    assert_eq!(result.account.unwrap().id, "acc_A1");
}

#[test]
fn move_key_accepts_default_as_the_destination() {
    assert_eq!(
        recorded_args(|manager| {
            manager
                .accounts_move_key("exa", "sha256:1234abcd", "default")
                .unwrap();
        }),
        json!([
            "accounts",
            "move-key",
            "exa",
            "sha256:1234abcd",
            "--to",
            "default",
            "--format",
            "json"
        ])
    );
}

#[test]
fn move_key_accepts_a_saved_account_as_the_destination() {
    assert_eq!(
        recorded_args(|manager| {
            manager
                .accounts_move_key("exa", "sha256:1234abcd", "acc_A1")
                .unwrap();
        }),
        json!([
            "accounts",
            "move-key",
            "exa",
            "sha256:1234abcd",
            "--to",
            "acc_A1",
            "--format",
            "json"
        ])
    );
}

#[test]
fn invalid_account_json_returns_a_chinese_error() {
    let mut profile = common::Profile::new();
    profile
        .environment
        .variables
        .insert("FIXTURE_ACCOUNTS_JSON".into(), "not-json".into());
    let manager = DesktopManager::new(profile.environment.clone());
    assert_eq!(
        manager.accounts_view(None).unwrap_err(),
        "CLI 未返回有效的账号结果。"
    );
    assert_eq!(
        manager.accounts_add("exa", "公司").unwrap_err(),
        "CLI 未返回有效的账号结果。"
    );
}

#[test]
fn malformed_nested_account_metadata_returns_a_chinese_error() {
    let mut row = account();
    row["balance_credentials"]["exa_admin"] = json!(false);
    let profile = profile_with_payload(json!({"accounts":{"exa":[row]}}));
    assert_eq!(
        DesktopManager::new(profile.environment.clone())
            .accounts_view(None)
            .unwrap_err(),
        "CLI 未返回有效的账号结果。"
    );
}

#[test]
fn a_missing_mutation_account_is_not_reported_as_success() {
    let profile = profile_with_payload(json!({"provider":"exa"}));
    assert_eq!(
        DesktopManager::new(profile.environment.clone())
            .accounts_add("exa", "公司")
            .unwrap_err(),
        "CLI 未返回有效的账号结果。"
    );
}

#[test]
fn a_hanging_accounts_cli_returns_a_chinese_timeout() {
    let profile = mode("hang");
    let started = Instant::now();
    let error = accounts_fixture::view_with_timeout(
        &profile.environment,
        &profile.root.join(CLI_FILE_NAME),
        None,
        Duration::from_millis(300),
    )
    .unwrap_err();
    assert_eq!(error, "账号操作超时，请稍后重试。");
    assert!(started.elapsed() < Duration::from_secs(5));
}

#[test]
fn old_cli_list_returns_an_identifiable_update_state() {
    let profile = mode("legacy");
    let view = DesktopManager::new(profile.environment.clone())
        .accounts_view(None)
        .unwrap();
    assert_eq!(view.status, "cli_update_required");
    assert_eq!(view.message, "当前 CLI 不支持账号管理，请更新 CLI 后重试。");
    assert!(view.accounts.is_empty());
}

#[test]
fn old_cli_mutations_return_an_identifiable_update_state() {
    let profile = mode("legacy");
    let manager = DesktopManager::new(profile.environment.clone());
    for result in [
        manager.accounts_add("exa", "公司"),
        manager.accounts_rename("exa", "acc_A1", "个人"),
        manager.accounts_remove("exa", "acc_A1", true),
        manager.accounts_move_key("exa", "sha256:1234abcd", "default"),
    ] {
        let result = result.unwrap();
        assert_eq!(result.status, "cli_update_required");
        assert!(result.account.is_none());
        assert!(!result.removed);
    }
}

#[test]
fn configuration_failure_is_not_an_old_cli_update_state() {
    let profile = mode("failure");
    assert_eq!(
        DesktopManager::new(profile.environment.clone())
            .accounts_view(None)
            .unwrap_err(),
        "账号操作失败，请检查 CLI 后重试。"
    );
}

#[test]
fn unsupported_flags_are_not_an_old_cli_update_state() {
    let profile = mode("invalid-option");
    assert_eq!(
        DesktopManager::new(profile.environment.clone())
            .accounts_view(None)
            .unwrap_err(),
        "账号操作失败，请检查 CLI 后重试。"
    );
}

#[test]
fn excessive_account_output_returns_a_chinese_error() {
    let profile = mode("truncated");
    assert_eq!(
        DesktopManager::new(profile.environment.clone())
            .accounts_view(None)
            .unwrap_err(),
        "CLI 返回的账号结果过大，无法读取。"
    );
}

fn usage_provider() -> Value {
    let total = json!({"remaining":10.0,"limit":null,"percent":50.0,"unit":"usd","relative":true});
    let report = json!({"provider":"exa","status":"ok","scope":"account","unit":"usd", "remaining":10.0,
        "limit":null,"used":null,"resets_at":null,"period":null,"key_fingerprint":"sha256:abcd1234",
        "error_kind":null,"message":"","fetched_at":"2026-11-01T00:00:00+00:00"});
    json!({"id":"exa","label":"Exa","balance_supported":true,"balance_note":"", "current":[report.clone()],
        "totals":[],"history":[],"pace":[],"calls":{"today":{},"last_7_days":{},"daily":[]},
        "accounts":[{"id":"acc_A1","name":"公司","source":"oauth", "total":total.clone(),
            "keys":[{"key_fingerprint":"sha256:1234abcd","report":null},{"key_fingerprint":"sha256:abcd1234","report":report}]}],
        "total":total,"alert":"wont_last"})
}

fn usage_profile(row: Value) -> common::Profile {
    let mut profile = common::Profile::new();
    profile.environment.variables.insert(
        "FIXTURE_USAGE_JSON".into(),
        json!({"schema_version":1,"retention_days":30,"providers":[row]}).to_string(),
    );
    profile
}

#[test]
fn usage_preserves_account_groups_nullable_reports_relative_totals_and_alerts() {
    let row = usage_provider();
    let profile = usage_profile(row.clone());
    let view = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap();
    assert_eq!(view.status, "ready");
    assert_eq!(serde_json::to_value(view).unwrap()["providers"][0], row);
}

#[test]
fn usage_without_account_fields_returns_a_cli_update_state() {
    let mut row = usage_provider();
    for field in ["accounts", "total", "alert"] {
        row.as_object_mut().unwrap().remove(field);
    }
    let profile = usage_profile(row);
    let view = DesktopManager::new(profile.environment.clone())
        .usage_view(None, false)
        .unwrap();
    assert_eq!(view.status, "cli_update_required");
    assert_eq!(view.message, "当前 CLI 不支持账号用量，请更新 CLI 后重试。");
}

#[test]
fn usage_rejects_a_malformed_account_total() {
    let mut row = usage_provider();
    row["accounts"][0]["total"]["relative"] = json!("yes");
    let profile = usage_profile(row);
    assert_eq!(
        DesktopManager::new(profile.environment.clone())
            .usage_view(None, false)
            .unwrap_err(),
        "CLI 未返回有效的用量结果。"
    );
}
