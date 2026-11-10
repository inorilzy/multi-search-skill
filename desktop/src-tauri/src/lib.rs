//! Native management boundary; the CLI remains the search implementation.
pub(crate) mod config_db;
pub mod cookie;
pub mod credential;
pub mod credential_commands;
pub mod diagnostics;
mod environment;
mod errors;
pub mod execution;
pub mod install;
mod journal;
mod keys_file;
pub mod log_viewer;
#[cfg(target_os = "macos")]
pub mod macos_path;
mod manager;
mod manifest;
mod process;
pub mod provider;
mod redaction;
pub mod scrape_memory;
mod secure_temp;
pub mod settings;
pub mod skill;
mod skill_common;
pub mod skill_manage;
pub mod source_catalog;
pub mod user_path;
mod windows_util;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, Discovery, RuntimeEnvironment, CLI_FILE_NAME};

pub use execution::{ExecutionStatus, SearchOptions};
pub use manager::DesktopManager;
pub use skill::{SkillInstall, SkillPlan};
pub use skill_common::skill_version;
pub use skill_manage::{
    InstallState, RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome, UpdatePlan,
};

/// Re-exports used by the UI contract test (`tests/ui_contract.rs`) so every
/// command payload is reachable from a single, stable namespace. These are
/// the same Rust types each `#[tauri::command]` already returns or accepts;
/// no new public surface is added beyond what the IPC layer exposes.
pub mod contract {
    pub use crate::cookie::CookieStatus;
    pub use crate::credential::CredentialStatus;
    pub use crate::credential_commands::{
        CredentialOverview, CredentialValue, TestOutcome,
    };
    pub use crate::diagnostics::{CliStatus, Discovery};
    pub use crate::execution::{ExecutionStatus, SearchOptions};
    pub use crate::install::{AppInfo, InstallOutcome, InstallPlan, InstallStep};
    pub use crate::log_viewer::LogViewerInfo;
    pub use crate::provider::ProviderInfo;
    pub use crate::scrape_memory::{ScrapeMemoryRow, ScrapeMemoryView};
    pub use crate::settings::{
        RankingInput, RankingState, RerankKeyStatus, RouteConfig, ScrapeBackendOption,
        SettingsInput, SettingsView,
    };
    pub use crate::skill::{SkillInstall, SkillPlan};
    pub use crate::skill_manage::{
        InstallState, RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome, UpdatePlan,
    };
    pub use crate::user_path::{PathPlan, PathReceipt, PathValue};
}

/// Test seam for the settings writer. Not a supported public API.
/// Compiled only with the test-only `test-fixtures` feature, never in a product build.
#[cfg(feature = "test-fixtures")]
#[doc(hidden)]
pub mod settings_fixture {
    pub use crate::settings::{
        builtin_routes, config_path, route_default_timeout, save, save_with_dev, validate, view,
        view_with_dev, keys_file_path, rerank_key_status, save_systemone_key, save_debug_log, RankingInput, RouteConfig, RouteMap, SettingsInput, SettingsView, Validated,
        TIMEOUT_MAX, TIMEOUT_MIN,
    };
    /// Dev fallback location for the real app: the repo-root file the CLI reads when no user file exists.
    pub fn default_dev_config() -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("multi-search-config.json")
    }
    /// Whether the execution allowlist accepts a `--source` name.
    pub fn is_allowed_source(name: &str) -> bool {
        crate::execution::is_allowed_source(name)
    }
}

/// Test seam for PATH registration. Not a supported public API.
#[cfg(feature = "test-fixtures")]
#[doc(hidden)]
pub mod user_path_fixture {
    use crate::user_path::{PathReceipt, PathValue};

    /// Build the receipt exactly as `UserPathManager::change` does for an add.
    pub fn receipt(before: &PathValue, after: &PathValue, entry: &str) -> PathReceipt {
        PathReceipt::new(before, after, entry)
    }
}

/// Test seam for the bundled-resource install entrypoints the window calls.
///
/// `install_plan_from` / `install_from` / `update_from` take the app's own
/// `cli-bundle` resource directory and are crate-private. An acceptance test
/// needs exactly that path — the compiled anchor plus the real platform root —
/// without going through the env-override boundary, so this forwards them.
/// Not a supported public API; compiled only with `test-fixtures`.
#[cfg(feature = "test-fixtures")]
#[doc(hidden)]
pub mod install_fixture {
    use crate::install::{InstallOutcome, InstallPlan};
    use crate::DesktopManager;
    use std::path::Path;

    pub fn plan(manager: &DesktopManager, bundled: Option<&Path>) -> InstallPlan {
        manager.install_plan_from(bundled)
    }

    pub fn install(manager: &DesktopManager, bundled: Option<&Path>) -> InstallOutcome {
        manager.install_from(bundled)
    }

    pub fn update(manager: &DesktopManager, bundled: Option<&Path>) -> InstallOutcome {
        manager.update_from(bundled)
    }
}

/// Test seam for the CLI child-process environment boundary. Not a supported public API.
#[cfg(feature = "test-fixtures")]
#[doc(hidden)]
pub mod process_fixture {
    use std::collections::BTreeMap;

    /// Filter a desktop environment the same way `OwnedProcess::spawn` does.
    pub fn child_environment(variables: &BTreeMap<String, String>) -> BTreeMap<String, String> {
        crate::process::child_environment(variables)
    }

    /// Run a program through the real `OwnedProcess` boundary with a synthetic
    /// desktop environment, and return its stdout. Used to prove that the
    /// allowlist applies to an actual child process, not just the pure filter.
    pub fn run(
        program: &std::path::Path,
        args: &[String],
        variables: BTreeMap<String, String>,
        cwd: std::path::PathBuf,
    ) -> Result<String, String> {
        let environment = crate::RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables,
            cwd,
        };
        crate::process::bounded(
            program,
            args,
            &environment,
            std::time::Duration::from_secs(10),
        )
        .map(|output| output.stdout)
        .map_err(|error| error.to_string())
    }
}

/// Test seam for the keys-file credential editor. Not a supported public API.
/// Every function takes the environment variables that locate `~/.multi-search/keys.json`, so tests
/// point `HOME`/`USERPROFILE` at a disposable directory.
#[cfg(feature = "test-fixtures")]
#[doc(hidden)]
pub mod credential_fixture {
    use crate::credential_commands::{self, CredentialOverview, CredentialValue, TestOutcome};
    use serde_json::Value;
    use std::collections::BTreeMap;

    fn tavily() -> credential_commands::SourceEntry {
        credential_commands::resolve_source("tavily").expect("tavily is allowlisted")
    }
    fn entry(source: &str) -> Result<credential_commands::SourceEntry, String> {
        credential_commands::resolve_source(source)
    }
    /// The keys file the desktop and the CLI share, for these variables.
    pub fn keys_file_path(variables: &BTreeMap<String, String>) -> Option<std::path::PathBuf> {
        crate::keys_file::path(variables)
    }
    pub fn overview(variables: &BTreeMap<String, String>) -> CredentialOverview {
        credential_commands::overview(variables, &tavily())
    }
    pub fn overview_for(variables: &BTreeMap<String, String>, source: &str) -> Result<CredentialOverview, String> {
        Ok(credential_commands::overview(variables, &entry(source)?))
    }
    /// Plaintext editor value (`credential_reveal`).
    pub fn read_for(variables: &BTreeMap<String, String>, source: &str) -> Result<String, String> {
        Ok(credential_commands::reveal(variables, &entry(source)?)?.value)
    }
    /// Masked value plus snapshot (`credential_read`).
    pub fn masked_for(variables: &BTreeMap<String, String>, source: &str) -> Result<CredentialValue, String> {
        credential_commands::read(variables, &entry(source)?)
    }
    pub fn save_for(variables: &BTreeMap<String, String>, source: &str, key: &str) -> Result<CredentialOverview, String> {
        credential_commands::save(variables, &entry(source)?, key)
    }
    pub fn append_for(variables: &BTreeMap<String, String>, source: &str, keys: &[String]) -> Result<CredentialOverview, String> {
        credential_commands::append(variables, &entry(source)?, keys)
    }
    /// `expected` is the snapshot hash returned by `credential_read`.
    pub fn remove_row_for(variables: &BTreeMap<String, String>, source: &str, index: usize, expected: &str) -> Result<CredentialOverview, String> {
        credential_commands::remove_row(variables, &entry(source)?, index, expected)
    }
    pub fn delete_for(variables: &BTreeMap<String, String>, source: &str) -> Result<CredentialOverview, String> {
        credential_commands::delete(variables, &entry(source)?)
    }
    /// Snapshot hash of an editor text, as `credential_read` reports it.
    pub fn snapshot(text: &str) -> String {
        crate::credential::snapshot(text)
    }
    /// Overview exactly as the production command returns it: local keys-file state plus
    /// the effective source decided by Core's `doctor --format json` payload.
    pub fn overview_with_core(variables: &BTreeMap<String, String>, source: &str, doctor: &Value) -> Result<CredentialOverview, String> {
        let entry = entry(source)?;
        let key_sources = credential_commands::core_key_sources(doctor);
        let mut overview = credential_commands::overview(variables, &entry);
        credential_commands::apply_core_source(&mut overview, key_sources.get(entry.provider));
        Ok(overview)
    }
    pub fn resolve(source: &str) -> Result<(&'static str, &'static str), String> {
        let entry = entry(source)?;
        Ok((entry.source, entry.provider))
    }
    pub fn interpret(payload: &Value) -> TestOutcome {
        credential_commands::interpret_source(payload, &tavily())
    }
    pub fn test_args(query: &str) -> Vec<String> {
        credential_commands::test_args(query, &tavily())
    }
    pub fn source_test(source: &str, payload: &Value) -> Result<(Vec<String>, TestOutcome), String> {
        let entry = credential_commands::resolve_test_source(source)?;
        Ok((
            credential_commands::test_args("synthetic connectivity", &entry),
            credential_commands::interpret_source(payload, &entry),
        ))
    }
}

/// Test seam for the shared source catalog. Not a supported public API.
#[doc(hidden)]
pub mod source_catalog_fixture {
    pub use crate::source_catalog::catalog;

    /// Settings canonicalization for a catalog name or CLI alias.
    pub fn settings_source(name: &str) -> Option<&'static str> {
        crate::provider::resolve(name).ok().map(|entry| entry.source)
    }

    /// Canonical route name plus the ordered sources the desktop would run.
    pub fn route(name: &str) -> Option<(&'static str, &'static [String])> {
        let entry = catalog().route(name)?;
        Some((entry.name.as_str(), entry.sources.as_slice()))
    }

    /// The execution allowlist exactly as `start_search` enforces it.
    pub fn execution_allows(name: &str) -> bool {
        crate::execution::is_allowed_source(name)
    }

    /// Credential UI resolution: (UI source, key provider, env aliases, label).
    pub fn credential_source(
        name: &str,
    ) -> Result<(&'static str, &'static str, &'static [String], &'static str), String> {
        let entry = crate::credential_commands::resolve_source(name)?;
        let env = catalog()
            .source(entry.canonical)
            .map(|source| source.env.as_slice())
            .unwrap_or(&[]);
        Ok((entry.source, entry.provider, env, entry.label))
    }

    /// Sources with an explicit native credential test path (keyed + keyless search).
    pub fn credential_test_source(name: &str) -> Result<&'static str, String> {
        crate::credential_commands::resolve_test_source(name).map(|entry| entry.source)
    }
}

#[cfg(feature = "native-window")]
pub use window::run;
