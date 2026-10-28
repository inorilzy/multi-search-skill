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
        CredentialOverview, CredentialValue, MigrationItem, MigrationPlan, MigrationResult,
        TestOutcome,
    };
    pub use crate::diagnostics::{CliStatus, Discovery};
    pub use crate::execution::{ExecutionStatus, SearchOptions};
    pub use crate::install::{InstallOutcome, InstallPlan, InstallStep};
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
        view_with_dev, keys_file_path, rerank_key_status, save_systemone_key, RankingInput, RouteConfig, RouteMap, SettingsInput, SettingsView, Validated,
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

/// Test seam for the Tavily credential store. Not a supported public API.
#[cfg(feature = "test-fixtures")]
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
        // Fixture-only in-memory adapter; native production uses an IMMEDIATE transaction.
        fn save_jina(&self, value: Value, saved_at: f64) -> Result<(), CredentialError> {
            let previous = crate::credential::load(self, "", "jina")?.map(|(v, _)| v);
            let merged = crate::credential::merge_jina_metadata(value, previous.as_ref());
            self.write("jina", &crate::credential::encode_blob(&merged, saved_at))
        }
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
        Ok(credential_commands::reveal(&Adapter(backend), variables, &entry)?.value)
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
        if !credential::is_store_provider(provider) {
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
        if !credential::is_store_provider(provider) {
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
        if !credential::is_store_provider(provider) {
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
        if !credential::is_store_provider(provider) {
            return Err("unsupported provider".into());
        }
        credential::SqliteCredentialBackend {
            path: path.to_path_buf(),
        }
        .delete(provider)
        .map_err(|e| e.to_string())
    }
    /// Same platform guard the `credential_save`/`credential_append`/
    /// `credential_remove`/`migration_apply` commands run before any backend
    /// access; lets boundary tests assert the stable unsupported code.
    pub fn require_supported() -> Result<(), String> {
        credential_commands::require_supported().map_err(String::from)
    }
    /// Whether this build can encrypt on the current platform (DPAPI fact).
    pub fn storage_supported() -> bool {
        crate::credential::storage_supported()
    }
    /// Serialized `{code,message}` the unsupported-path writes must produce,
    /// so tests compare the exact wire result, not a reconstructed string.
    pub fn unsupported_rejection() -> String {
        String::from(credential_commands::unsupported_error())
    }
    /// Full `migration_apply` command body: platform guard first, then the
    /// same request build + CLI path the Tauri handler runs. A rejection must
    /// arrive before the CLI runs and before any file/request file is touched.
    /// The legacy `keys_file` is read-only input, never modified here.
    pub fn guarded_migration_apply(
        environment: &crate::RuntimeEnvironment,
        cli: &std::path::Path,
        keys_file: &std::path::Path,
        plan_token: &str,
        approved: &[String],
        choices: &std::collections::BTreeMap<String, String>,
    ) -> Result<credential_commands::MigrationResult, String> {
        // Same guard the Tauri `migration_apply` runs before anything else.
        credential_commands::require_supported().map_err(String::from)?;
        let request = crate::errors::finish(
            credential_commands::migration_request(plan_token, approved, choices),
        )?;
        credential_commands::migration_apply(environment, cli, keys_file, &request)
    }
    /// Command-body write seam: runs the same platform guard as the
    /// `credential_save` / `credential_append` / `credential_remove` commands,
    /// then the production SQLite path, against a caller-supplied database.
    /// Returns the serialized `{code,message}` rejection on unsupported platforms.
    pub fn guarded_native_save(path: &std::path::Path, provider: &str, key: &str, now: f64) -> Result<(), String> {
        credential_commands::require_supported().map_err(String::from)?;
        crate::credential::save(&crate::credential::SqliteCredentialBackend { path: path.to_path_buf() }, "", provider, key, now)
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
    pub fn guarded_native_append(path: &std::path::Path, provider: &str, keys: &[String], now: f64) -> Result<(), String> {
        credential_commands::require_supported().map_err(String::from)?;
        native_append(path, provider, keys, now)
    }
    pub fn guarded_native_remove_row(path: &std::path::Path, provider: &str, index: usize, expected: &str, now: f64) -> Result<(), String> {
        credential_commands::require_supported().map_err(String::from)?;
        native_remove_row(path, provider, index, expected, now)
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
        if !credential::is_store_provider(provider) {
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
        if !credential::is_store_provider(provider) {
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
        if !credential::is_store_provider(provider) {
            return Err("unsupported provider".into());
        }
        credential::SqliteCredentialBackend {
            path: path.to_path_buf(),
        }
        .remove_row(provider, index, &credential::snapshot(expected), now)
        .map_err(|e| e.to_string())
    }
    /// Overview exactly as the production command returns it: local store state plus
    /// the effective source decided by Core's `doctor --format json` payload.
    pub fn overview_with_core<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        source: &str,
        doctor: &Value,
    ) -> Result<CredentialOverview, String> {
        let entry = credential_commands::resolve_source(source)?;
        let key_sources = credential_commands::core_key_sources(doctor);
        let mut overview = credential_commands::overview(&Adapter(backend), variables, &entry);
        credential_commands::apply_core_source(&mut overview, key_sources.get(entry.provider));
        Ok(overview)
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
