//! Account metadata and mutations belong to Core; desktop only validates the CLI boundary.
use crate::RuntimeEnvironment;
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::Path, time::Duration};

const ACCOUNTS_TIMEOUT: Duration = Duration::from_secs(30);
const UPDATE_MESSAGE: &str = "当前 CLI 不支持账号管理，请更新 CLI 后重试。";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct ProviderAccount {
    pub id: String,
    pub name: String,
    pub source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "ts", ts(optional))]
    pub login_identity: Option<String>,
    pub keys: Vec<String>,
    pub balance_credentials: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct AccountsView {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
    pub accounts: BTreeMap<String, Vec<ProviderAccount>>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct AccountMutation {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
    pub provider: String,
    pub account: Option<ProviderAccount>,
    #[serde(default)]
    pub removed: bool,
}

pub(crate) enum Action<'a> {
    Add {
        name: &'a str,
    },
    Rename {
        account_id: &'a str,
        name: &'a str,
    },
    Remove {
        account_id: &'a str,
        delete_keys: bool,
    },
    MoveKey {
        fingerprint: &'a str,
        account_id: &'a str,
    },
}

pub(crate) fn validate_provider(provider: Option<&str>) -> Result<Option<String>, String> {
    crate::balance::validate_provider(provider).map_err(|_| "不支持的账号服务商".into())
}

fn validate_account(account_id: &str, allow_default: bool) -> Result<(), String> {
    if account_id == "default" {
        return if allow_default {
            Ok(())
        } else {
            Err("默认账号不能重命名或删除。".into())
        };
    }
    if !account_id.strip_prefix("acc_").is_some_and(|suffix| {
        !suffix.is_empty() && suffix.bytes().all(|c| c.is_ascii_alphanumeric())
    }) {
        return Err("无效的账号 ID。".into());
    }
    Ok(())
}

pub(crate) fn mutation_args(provider: &str, action: Action<'_>) -> Result<Vec<String>, String> {
    let provider = validate_provider(Some(provider))?.unwrap();
    let mut args = vec!["accounts".into()];
    let name = match action {
        Action::Add { name } => {
            args.extend(["add".into(), provider]);
            Some(name)
        }
        Action::Rename { account_id, name } => {
            validate_account(account_id, false)?;
            args.extend(["rename".into(), provider, account_id.into()]);
            Some(name)
        }
        Action::Remove {
            account_id,
            delete_keys,
        } => {
            validate_account(account_id, false)?;
            args.extend(["remove".into(), provider, account_id.into()]);
            if delete_keys {
                args.push("--delete-keys".into());
            }
            None
        }
        Action::MoveKey {
            fingerprint,
            account_id,
        } => {
            validate_account(account_id, true)?;
            if !fingerprint.strip_prefix("sha256:").is_some_and(|suffix| {
                suffix.len() == 8
                    && suffix
                        .bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            }) {
                return Err("无效的 Key 指纹。".into());
            }
            args.extend([
                "move-key".into(),
                provider,
                fingerprint.into(),
                "--to".into(),
                account_id.into(),
            ]);
            None
        }
    };
    if let Some(name) = name {
        if name.trim().is_empty() {
            return Err("账号名称不能为空。".into());
        }
        // Keep a name beginning with '-' an option value, never another CLI flag.
        args.push(format!("--name={}", name.trim()));
    }
    args.extend(["--format".into(), "json".into()]);
    Ok(args)
}

// None denotes argparse rejecting the accounts command, rather than a configuration failure.
fn run(
    environment: &RuntimeEnvironment,
    cli: &Path,
    args: &[String],
    timeout: Duration,
) -> Result<Option<String>, String> {
    let output = crate::process::bounded(cli, args, environment, timeout)
        .map_err(|_| "无法启动 CLI".to_string())?;
    if output.timed_out {
        return Err("账号操作超时，请稍后重试。".into());
    }
    if output.truncated {
        return Err("CLI 返回的账号结果过大，无法读取。".into());
    }
    if output.code == Some(2)
        && output.stderr.lines().any(|line| {
            line.contains("argument command: invalid choice: 'accounts'")
                || line.contains("argument command: invalid choice: \"accounts\"")
        })
    {
        return Ok(None);
    }
    if output.code != Some(0) {
        return Err("账号操作失败，请检查 CLI 后重试。".into());
    }
    Ok(Some(output.stdout))
}

pub(crate) fn view(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: Option<&str>,
) -> Result<AccountsView, String> {
    view_with_timeout(environment, cli, provider, ACCOUNTS_TIMEOUT)
}

pub(crate) fn view_with_timeout(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: Option<&str>,
    timeout: Duration,
) -> Result<AccountsView, String> {
    let provider = validate_provider(provider)?;
    let mut args = vec![
        "accounts".into(),
        "list".into(),
        "--format".into(),
        "json".into(),
    ];
    if let Some(provider) = provider {
        args.extend(["--provider".into(), provider]);
    }
    let Some(stdout) = run(environment, cli, &args, timeout)? else {
        return Ok(AccountsView {
            status: "cli_update_required".into(),
            message: UPDATE_MESSAGE.into(),
            accounts: BTreeMap::new(),
        });
    };
    let mut view: AccountsView = serde_json::from_str(stdout.trim())
        .map_err(|_| "CLI 未返回有效的账号结果。".to_string())?;
    view.status = "ready".into();
    view.message.clear();
    Ok(view)
}

pub(crate) fn write(
    environment: &RuntimeEnvironment,
    cli: &Path,
    provider: &str,
    args: &[String],
) -> Result<AccountMutation, String> {
    let Some(stdout) = run(environment, cli, args, ACCOUNTS_TIMEOUT)? else {
        return Ok(AccountMutation {
            status: "cli_update_required".into(),
            message: UPDATE_MESSAGE.into(),
            provider: provider.trim().into(),
            account: None,
            removed: false,
        });
    };
    let mut result: AccountMutation = serde_json::from_str(stdout.trim())
        .map_err(|_| "CLI 未返回有效的账号结果。".to_string())?;
    if result.account.is_none() {
        return Err("CLI 未返回有效的账号结果。".into());
    }
    result.status = "ready".into();
    result.message.clear();
    Ok(result)
}
