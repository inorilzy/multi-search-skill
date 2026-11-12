//! Local usage through the managed CLI. Core owns history, call counts, pace and refresh caching.
use crate::{balance::BalanceReport, RuntimeEnvironment};
use serde::{Deserialize, Serialize};
use std::{path::Path, time::Duration};

const USAGE_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageHistoryPoint {
    pub key_fingerprint: Option<String>,
    pub scope: String,
    pub unit: String,
    pub remaining: Option<f64>,
    pub limit: Option<f64>,
    pub fetched_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsagePace {
    pub key_fingerprint: Option<String>,
    pub scope: String,
    pub unit: String,
    pub rate_per_day: Option<f64>,
    pub projected_empty_at: Option<String>,
    pub lasts_until_reset: Option<bool>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageTotal {
    pub scope: String,
    pub unit: String,
    pub key_count: u32,
    pub message: String,
    pub remaining: Option<f64>,
    pub limit: Option<f64>,
}

/// Core emits an empty object when the usage store cannot be read. Missing counts stay unknown.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageCallCounts {
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub search: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub scrape: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub failures: Option<u32>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageDailyCalls {
    pub day: String,
    pub search: u32,
    pub scrape: u32,
    pub failures: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageCalls {
    pub today: UsageCallCounts,
    pub last_7_days: UsageCallCounts,
    pub daily: Vec<UsageDailyCalls>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageProvider {
    pub id: String,
    pub label: String,
    pub balance_supported: bool,
    pub balance_note: String,
    pub current: Vec<BalanceReport>,
    pub totals: Vec<UsageTotal>,
    pub history: Vec<UsageHistoryPoint>,
    pub pace: Vec<UsagePace>,
    pub calls: UsageCalls,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UsageView {
    // Desktop status: `ready` or `cli_update_required`; not supplied by Core.
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
    pub schema_version: u32,
    pub retention_days: u32,
    pub providers: Vec<UsageProvider>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub usage_error: Option<String>,
}

pub(crate) fn validate_provider(provider: Option<&str>) -> Result<Option<String>, String> {
    crate::balance::validate_provider(provider).map_err(|_| "不支持的用量服务商".into())
}

fn usage_args(provider: Option<&str>, refresh: bool) -> Vec<String> {
    let mut args = vec!["usage".into(), "--format".into(), "json".into()];
    if let Some(provider) = provider {
        args.push("--provider".into());
        args.push(provider.into());
    }
    if refresh {
        args.push("--refresh".into());
    }
    args
}

fn parse_usage_view(stdout: &str) -> Result<UsageView, String> {
    let mut view: UsageView = serde_json::from_str(stdout.trim())
        .map_err(|_| "CLI 未返回有效的用量结果。".to_string())?;
    if view.schema_version != 1 {
        return Err("CLI 返回了不支持的用量结果版本。".into());
    }
    view.status = "ready".into();
    view.message.clear();
    Ok(view)
}

pub(crate) fn view(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: Option<&str>,
    refresh: bool,
) -> Result<UsageView, String> {
    view_with_timeout(environment, cli, provider, refresh, USAGE_TIMEOUT)
}

pub(crate) fn view_with_timeout(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: Option<&str>,
    refresh: bool,
    timeout: Duration,
) -> Result<UsageView, String> {
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
        &usage_args(provider.as_deref(), refresh),
        environment,
        &credentials,
        timeout,
    )
    .map_err(|_| "无法启动 CLI".to_string())?;
    if output.timed_out {
        return Err("查询用量超时，请稍后重试。".into());
    }
    if output.truncated {
        return Err("CLI 返回的用量结果过大，无法读取。".into());
    }
    // Only argparse's rejection of this subcommand means an old CLI. Config/provider failures
    // and unsupported flags still surface as errors, never as a misleading update prompt.
    if output.code == Some(2)
        && output.stderr.lines().any(|line| {
            line.contains("argument command: invalid choice: 'usage'")
                || line.contains("argument command: invalid choice: \"usage\"")
        })
    {
        return Ok(UsageView {
            status: "cli_update_required".into(),
            message: "当前 CLI 不支持用量查询，请更新 CLI 后重试。".into(),
            schema_version: 1,
            retention_days: 30,
            providers: vec![],
            usage_error: None,
        });
    }
    if output.code != Some(0) {
        return Err("读取用量失败，请检查 CLI 后重试。".into());
    }
    parse_usage_view(&output.stdout)
}
