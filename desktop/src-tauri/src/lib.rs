//! Native management boundary; the CLI remains the search implementation.
pub(crate) mod config_db;
pub mod credential;
pub mod credential_commands;
pub mod diagnostics;
mod environment;
pub mod execution;
pub mod install;
mod journal;
mod manager;
mod manifest;
mod process;
pub mod provider;
mod redaction;
pub mod scrape_memory;
pub mod settings;
pub mod skill;
mod skill_common;
pub mod skill_manage;
pub mod user_path;
mod windows_util;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, Discovery, RuntimeEnvironment};

pub use manager::DesktopManager;
pub use execution::{ExecutionStatus, SearchOptions};
pub use skill::{SkillInstall, SkillPlan};
pub use skill_manage::{
    InstallState, RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome, UpdatePlan,
};

/// Re-exports used by the UI contract test (`tests/ui_contract.rs`) so every
/// command payload is reachable from a single, stable namespace. These are
/// the same Rust types each `#[tauri::command]` already returns or accepts;
/// no new public surface is added beyond what the IPC layer exposes.
pub mod contract {
    pub use crate::credential::CredentialStatus;
    pub use crate::credential_commands::{CredentialOverview, CredentialValue, TestOutcome};
    pub use crate::diagnostics::{CliStatus, Discovery};
    pub use crate::execution::{ExecutionStatus, SearchOptions};
    pub use crate::install::{InstallOutcome, InstallPlan, InstallStep};
    pub use crate::provider::ProviderInfo;
    pub use crate::scrape_memory::{ScrapeMemoryRow, ScrapeMemoryView};
    pub use crate::settings::{
        RouteConfig, ScrapeBackendOption, SettingsInput, SettingsView,
    };
    pub use crate::skill::{SkillInstall, SkillPlan};
    pub use crate::skill_manage::{
        InstallState, RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome, UpdatePlan,
    };
    pub use crate::user_path::{PathPlan, PathReceipt, PathValue};
}

/// Test seam for the settings writer. Not a supported public API.
#[doc(hidden)]
pub mod settings_fixture {
    pub use crate::settings::{
        builtin_routes, config_path, save, save_with_dev, validate, view, view_with_dev,
        RouteConfig, RouteMap, SettingsInput, SettingsView, Validated,
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

/// Test seam for the CLI child-process environment boundary. Not a supported public API.
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

/// Test seam for the Tavily credential store. Not a supported public API.
#[doc(hidden)]
pub mod credential_fixture {
    use crate::credential::{CredentialBackend, CredentialError};
    use crate::credential_commands::{self, CredentialOverview, TestOutcome};
    use serde_json::Value;
    use std::collections::BTreeMap;

    /// Test backend contract with string errors, mapped onto the internal trait.
    pub trait Backend {
        fn read(&self, target: &str) -> Result<Option<Vec<u8>>, String>;
        fn write(&self, target: &str, blob: &[u8]) -> Result<(), String>;
        fn delete(&self, target: &str) -> Result<bool, String>;
    }
    struct Adapter<'a, B: Backend + Sync + ?Sized>(&'a B);
    impl<B: Backend + Sync + ?Sized> CredentialBackend for Adapter<'_, B> {
        fn read(&self, t: &str) -> Result<Option<Vec<u8>>, CredentialError> {
            self.0.read(t).map_err(CredentialError::Unavailable)
        }
        fn write(&self, t: &str, b: &[u8]) -> Result<(), CredentialError> {
            self.0.write(t, b).map_err(CredentialError::Unavailable)
        }
        fn delete(&self, t: &str) -> Result<bool, CredentialError> {
            self.0.delete(t).map_err(CredentialError::Unavailable)
        }
    }

    fn tavily() -> credential_commands::SourceEntry {
        credential_commands::resolve_source("tavily").expect("tavily is allowlisted")
    }
    pub fn save<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        key: &str,
        now: f64,
    ) -> Result<CredentialOverview, String> {
        credential_commands::save(&Adapter(backend), variables, &tavily(), key, now)
    }
    pub fn delete<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
    ) -> Result<CredentialOverview, String> {
        credential_commands::delete(&Adapter(backend), variables, &tavily())
    }
    pub fn overview<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
    ) -> CredentialOverview {
        credential_commands::overview(&Adapter(backend), variables, &tavily())
    }
    /// Source-aware overview for any allowlisted UI name. Unknown names return an error.
    pub fn overview_for<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        source: &str,
    ) -> Result<CredentialOverview, String> {
        let entry = credential_commands::resolve_source(source)?;
        Ok(credential_commands::overview(
            &Adapter(backend),
            variables,
            &entry,
        ))
    }
    pub fn read_for<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        source: &str,
    ) -> Result<String, String> {
        let entry = credential_commands::resolve_source(source)?;
        Ok(credential_commands::read(&Adapter(backend), variables, &entry)?.value)
    }
    pub fn save_for<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        source: &str,
        key: &str,
        now: f64,
    ) -> Result<CredentialOverview, String> {
        credential_commands::save(
            &Adapter(backend),
            variables,
            &credential_commands::resolve_source(source)?,
            key,
            now,
        )
    }
    /// Isolated native store test seam: caller supplies an explicit disposable database path.
    pub fn native_write(
        path: &std::path::Path,
        provider: &str,
        key: &Value,
        now: f64,
    ) -> Result<(), String> {
        use crate::credential::{self, CredentialBackend};
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        credential::SqliteCredentialBackend {
            path: path.to_path_buf(),
        }
        .write(provider, &credential::encode_blob(key, now))
        .map_err(|e| e.to_string())
    }
    /// Isolated native editor-save seam: same merge semantics as the desktop editor.
    pub fn native_editor_save(
        path: &std::path::Path,
        provider: &str,
        text: &str,
        now: f64,
    ) -> Result<(), String> {
        use crate::credential;
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        credential::save(
            &credential::SqliteCredentialBackend { path: path.to_path_buf() },
            "",
            provider,
            text,
            now,
        )
        .map(|_| ())
        .map_err(|e| e.to_string())
    }
    pub fn native_read(path: &std::path::Path, provider: &str) -> Result<Option<Value>, String> {
        use crate::credential;
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        credential::load(
            &credential::SqliteCredentialBackend {
                path: path.to_path_buf(),
            },
            "",
            provider,
        )
        .map(|v| v.map(|(key, _)| key))
        .map_err(|e| e.to_string())
    }
    pub fn native_delete(path: &std::path::Path, provider: &str) -> Result<bool, String> {
        use crate::credential::{self, CredentialBackend};
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        credential::SqliteCredentialBackend {
            path: path.to_path_buf(),
        }
        .delete(provider)
        .map_err(|e| e.to_string())
    }
    /// Isolated native row-mutation seams: same production path the
    /// `credential_append` / `credential_remove` commands use, on a
    /// caller-supplied disposable database.
    pub fn native_append(
        path: &std::path::Path,
        provider: &str,
        keys: &[String],
        now: f64,
    ) -> Result<(), String> {
        use crate::credential::{self, CredentialBackend};
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        credential::SqliteCredentialBackend {
            path: path.to_path_buf(),
        }
        .append(provider, keys, now)
        .map_err(|e| e.to_string())
    }
    /// Writes an arbitrary `key` shape straight into the encrypted store,
    /// bypassing `validate_value` — the only way to seed shapes the editor
    /// cannot render, to prove row ops reject rather than silently drop them.
    pub fn native_write_raw(
        path: &std::path::Path,
        provider: &str,
        key: &Value,
        now: f64,
    ) -> Result<(), String> {
        use crate::credential;
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        let blob = serde_json::json!({"v":1,"key":key,"saved_at":now}).to_string().into_bytes();
        let encrypted = credential::crypt(&blob, true).map_err(|e| e.to_string())?;
        let conn = crate::config_db::open(path)?;
        conn.execute("INSERT INTO credentials(provider,encrypted_value,saved_at) VALUES(?1,?2,?3) ON CONFLICT(provider) DO UPDATE SET encrypted_value=excluded.encrypted_value,saved_at=excluded.saved_at",
            rusqlite::params![provider, encrypted, now])
            .map_err(|e| e.to_string())?;
        Ok(())
    }
    pub fn native_remove_row(
        path: &std::path::Path,
        provider: &str,
        index: usize,
        expected: &str,
        now: f64,
    ) -> Result<(), String> {
        use crate::credential::{self, CredentialBackend};
        if !credential::STORE_PROVIDERS.contains(&provider) {
            return Err("unsupported provider".into());
        }
        credential::SqliteCredentialBackend {
            path: path.to_path_buf(),
        }
        .remove_row(provider, index, expected, now)
        .map_err(|e| e.to_string())
    }
    pub fn resolve(source: &str) -> Result<(&'static str, &'static str), String> {
        let entry = credential_commands::resolve_source(source)?;
        Ok((entry.source, entry.provider))
    }
    pub fn interpret(payload: &Value) -> TestOutcome {
        credential_commands::interpret_source(payload, &tavily())
    }
    pub fn test_args(query: &str) -> Vec<String> {
        credential_commands::test_args(query, &tavily())
    }
    pub fn source_test(
        source: &str,
        payload: &Value,
    ) -> Result<(Vec<String>, TestOutcome), String> {
        let entry = credential_commands::resolve_test_source(source)?;
        Ok((
            credential_commands::test_args("synthetic connectivity", &entry),
            credential_commands::interpret_source(payload, &entry),
        ))
    }
}
#[cfg(feature = "native-window")]
pub use window::run;
