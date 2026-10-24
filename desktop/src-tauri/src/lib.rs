//! Native management boundary; the CLI remains the search implementation.
pub(crate) mod credential;
pub(crate) mod credential_commands;
mod diagnostics;
mod environment;
pub(crate) mod settings;
pub mod source_catalog;
mod execution;
mod install;
mod process;
mod redaction;
mod secure_temp;
mod skill;
mod skill_manage;
pub mod user_path;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, DesktopManager, Discovery, RuntimeEnvironment};
pub use execution::{ExecutionStatus, SearchOptions};
pub use skill::{SkillInstall, SkillPlan};
pub use skill_manage::{InstallState, RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome, UpdatePlan};

/// Test seam for the settings writer. Not a supported public API.
#[doc(hidden)]
pub mod settings_fixture {
    pub use crate::settings::{
        config_path, save, save_with_dev, save_with_dev_mode, validate, view, view_with_doctor, view_with_dev,
        view_with_dev_mode, SettingsInput, SettingsView, Validated,
    };
    /// Whether the execution allowlist accepts a `--source` name.
    pub fn is_allowed_source(name: &str) -> bool {
        crate::execution::is_allowed_source(name)
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

    fn tavily() -> &'static credential_commands::SourceEntry {
        credential_commands::resolve_source("tavily").expect("tavily is allowlisted")
    }
    pub fn save<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        key: &str,
        now: f64,
    ) -> Result<CredentialOverview, String> {
        credential_commands::save(&Adapter(backend), variables, tavily(), key, now)
    }
    pub fn delete<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
    ) -> Result<CredentialOverview, String> {
        credential_commands::delete(&Adapter(backend), variables, tavily())
    }
    pub fn overview<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
    ) -> CredentialOverview {
        credential_commands::overview(&Adapter(backend), variables, tavily())
    }
    /// Source-aware overview for any allowlisted UI name. Unknown names return an error.
    pub fn overview_for<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        source: &str,
    ) -> Result<CredentialOverview, String> {
        let entry = credential_commands::resolve_source(source)?;
        Ok(credential_commands::overview(&Adapter(backend), variables, entry))
    }
    pub fn resolve(source: &str) -> Result<(&'static str, &'static str), String> {
        let entry = credential_commands::resolve_source(source)?;
        Ok((entry.name.as_str(), entry.key_provider.as_str()))
    }
    pub fn interpret(payload: &Value) -> TestOutcome {
        credential_commands::interpret_source(payload, tavily())
    }
    pub fn test_args(query: &str) -> Vec<String> {
        credential_commands::test_args(query, tavily())
    }
    pub fn source_test(source: &str, payload: &Value) -> Result<(Vec<String>, TestOutcome), String> {
        let entry = credential_commands::resolve_test_source(source)?;
        Ok((credential_commands::test_args("synthetic connectivity", entry), credential_commands::interpret_source(payload, entry)))
    }
}
/// Test seam for the shared source catalog. Not a supported public API.
#[doc(hidden)]
pub mod source_catalog_fixture {
    pub use crate::source_catalog::catalog;

    /// Settings canonicalization for a catalog name or CLI alias.
    pub fn settings_source(name: &str) -> Option<&'static str> {
        crate::settings::source_name(name).ok()
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

    /// Credential UI resolution: (canonical source, key provider, env aliases, label).
    pub fn credential_source(
        name: &str,
    ) -> Result<(&'static str, &'static str, &'static [String], &'static str), String> {
        let entry = crate::credential_commands::resolve_source(name)?;
        Ok((
            entry.name.as_str(),
            entry.key_provider.as_str(),
            entry.env.as_slice(),
            entry.label.as_str(),
        ))
    }

    /// Sources with an explicit native credential test path (keyed + keyless search).
    pub fn credential_test_source(name: &str) -> Result<&'static str, String> {
        crate::credential_commands::resolve_test_source(name).map(|entry| entry.name.as_str())
    }
}

#[cfg(feature = "native-window")]
pub use window::run;
