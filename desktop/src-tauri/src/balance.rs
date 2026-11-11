//! Provider balances through the managed CLI only. The desktop never contacts a provider:
//! `multi-search balance --format json` is the single implementation (cache, redaction and
//! per-provider timeouts live in Core), and this module validates its input and output.
use crate::RuntimeEnvironment;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::time::Duration;

/// The CLI enforces its own total deadline below this process timeout; the extra room covers
/// interpreter startup and JSON serialization.
const BALANCE_TIMEOUT: Duration = Duration::from_secs(30);

/// One balance auth method as declared by the plugin catalog. Only `type` is rename-sensitive:
/// the CLI emits `type`, while Rust keeps `method_type` for readability.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct BalanceAuthMethod {
    #[serde(rename = "type")]
    #[cfg_attr(feature = "ts", ts(rename = "type"))]
    pub method_type: String,
    pub label: String,
    pub credential: String,
    pub purpose: String,
}

/// One provider row from the balance CLI. Unknown future status/scope/unit values stay strings,
/// so the UI can fall back to the raw wire value instead of rejecting the whole payload.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct BalanceReport {
    pub provider: String,
    pub status: String,
    pub scope: String,
    pub unit: String,
    pub remaining: Option<f64>,
    pub limit: Option<f64>,
    pub used: Option<f64>,
    pub resets_at: Option<String>,
    pub period: Option<String>,
    pub key_fingerprint: Option<String>,
    pub error_kind: Option<String>,
    pub message: String,
    pub fetched_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct BalanceProvider {
    pub id: String,
    pub label: String,
    pub auth_methods: Vec<BalanceAuthMethod>,
    pub balance_supported: bool,
    pub balance_note: String,
    pub reports: Vec<BalanceReport>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct BalanceView {
    pub schema_version: u32,
    pub providers: Vec<BalanceProvider>,
}

/// Validate the optional `--provider` value against the plugin ids the shared catalog declares.
/// This must run before any child process is started, so the frontend cannot reach an arbitrary
/// provider spelling through the CLI.
pub(crate) fn validate_provider(provider: Option<&str>) -> Result<Option<String>, String> {
    let Some(provider) = provider else {
        return Ok(None);
    };
    let trimmed = provider.trim();
    if trimmed.is_empty() || crate::source_catalog::catalog().plugin(trimmed).is_none() {
        return Err("不支持的余额服务商".into());
    }
    Ok(Some(trimmed.to_string()))
}

/// The exact argv the balance command receives. Options are fixed here; the frontend supplies
/// only a validated provider id and the refresh flag.
pub(crate) fn balance_args(provider: Option<&str>, refresh: bool) -> Vec<String> {
    let mut args = vec!["balance".into(), "--format".into(), "json".into()];
    if let Some(provider) = provider {
        args.push("--provider".into());
        args.push(provider.into());
    }
    if refresh {
        args.push("--refresh".into());
    }
    args
}

/// Parse and version-check the CLI's JSON balance payload. Both failures are Chinese messages
/// because they are displayed verbatim by the credential page.
pub(crate) fn parse_balance_view(stdout: &str) -> Result<BalanceView, String> {
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        return Err("CLI 未返回有效的余额结果。".into());
    }
    let view: BalanceView =
        serde_json::from_str(trimmed).map_err(|_| "CLI 未返回有效的余额结果。".to_string())?;
    if view.schema_version != 1 {
        return Err("CLI 返回了不支持的余额结果版本。".into());
    }
    Ok(view)
}

/// Turn a finished CLI run into a view. Kept separate from process spawning so the timeout,
/// truncation and invalid-output branches are testable without a real CLI.
pub(crate) fn interpret_parts(
    timed_out: bool,
    code: Option<i32>,
    truncated: bool,
    stdout: &str,
) -> Result<BalanceView, String> {
    if timed_out {
        return Err("查询余额超时，请稍后重试。".into());
    }
    if truncated {
        return Err("CLI 返回的余额结果过大，无法读取。".into());
    }
    if code != Some(0) {
        return Err("读取余额失败，请检查 CLI 后重试。".into());
    }
    parse_balance_view(stdout)
}

fn interpret(output: &crate::process::Output) -> Result<BalanceView, String> {
    interpret_parts(output.timed_out, output.code, output.truncated, &output.stdout)
}

/// Run the managed CLI with the same credential-variable allowlist other sensitive commands use,
/// so a provider key supplied through the environment still reaches Core without entering argv.
pub(crate) fn view(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: Option<&str>,
    refresh: bool,
) -> Result<BalanceView, String> {
    view_with_timeout(environment, cli, provider, refresh, BALANCE_TIMEOUT)
}

pub(crate) fn view_with_timeout(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: Option<&str>,
    refresh: bool,
    timeout: Duration,
) -> Result<BalanceView, String> {
    // The whitelist check comes first: an invalid name must never become a CLI argument.
    let provider = validate_provider(provider)?;
    let names: Vec<String> = crate::source_catalog::catalog()
        .env
        .providers
        .values()
        .flatten()
        .cloned()
        .collect();
    let credentials: Vec<&str> = names.iter().map(String::as_str).collect();
    let output = crate::process::bounded_with(
        cli,
        &balance_args(provider.as_deref(), refresh),
        environment,
        &credentials,
        timeout,
    )
    .map_err(|_| "无法启动 CLI".to_string())?;
    interpret(&output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_must_be_a_known_plugin_id() {
        assert_eq!(validate_provider(None).unwrap(), None);
        assert_eq!(validate_provider(Some(" tavily ")).unwrap().as_deref(), Some("tavily"));
        assert_eq!(validate_provider(Some("exa")).unwrap().as_deref(), Some("exa"));
        for bad in ["", "  ", "../tavily", "tavily/../exa", "github_repos", "unknown"] {
            assert_eq!(validate_provider(Some(bad)).unwrap_err(), "不支持的余额服务商");
        }
    }

    #[test]
    fn args_are_fixed_and_refresh_is_explicit() {
        assert_eq!(
            balance_args(Some("tavily"), true),
            vec!["balance", "--format", "json", "--provider", "tavily", "--refresh"]
        );
        assert_eq!(balance_args(None, false), vec!["balance", "--format", "json"]);
    }

    #[test]
    fn invalid_or_versioned_output_is_a_chinese_error() {
        assert_eq!(parse_balance_view("").unwrap_err(), "CLI 未返回有效的余额结果。");
        assert_eq!(parse_balance_view("not-json").unwrap_err(), "CLI 未返回有效的余额结果。");
        assert_eq!(
            parse_balance_view(r#"{"schema_version":2,"providers":[]}"#).unwrap_err(),
            "CLI 返回了不支持的余额结果版本。"
        );
        assert_eq!(
            interpret_parts(true, None, false, "").unwrap_err(),
            "查询余额超时，请稍后重试。"
        );
        assert_eq!(
            interpret_parts(false, Some(0), true, "{}").unwrap_err(),
            "CLI 返回的余额结果过大，无法读取。"
        );
        assert_eq!(
            interpret_parts(false, Some(1), false, "{}").unwrap_err(),
            "读取余额失败，请检查 CLI 后重试。"
        );
    }
}
