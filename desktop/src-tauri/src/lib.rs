//! Native management boundary; the CLI remains the search implementation.
pub(crate) mod credential;
pub(crate) mod credential_commands;
mod diagnostics;
mod environment;
mod execution;
mod install;
mod process;
mod redaction;
mod skill;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, DesktopManager, Discovery, RuntimeEnvironment};
pub use execution::{ExecutionStatus, SearchOptions};
pub use skill::{SkillInstall, SkillPlan};

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

    pub fn save<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
        key: &str,
        now: f64,
    ) -> Result<CredentialOverview, String> {
        credential_commands::save(&Adapter(backend), variables, key, now)
    }
    pub fn delete<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
    ) -> Result<CredentialOverview, String> {
        credential_commands::delete(&Adapter(backend), variables)
    }
    pub fn overview<B: Backend + Sync + ?Sized>(
        backend: &B,
        variables: &BTreeMap<String, String>,
    ) -> CredentialOverview {
        credential_commands::overview(&Adapter(backend), variables)
    }
    pub fn interpret(payload: &Value) -> TestOutcome {
        credential_commands::interpret_payload(payload)
    }
    pub fn test_args(query: &str) -> Vec<String> {
        credential_commands::test_args(query)
    }
}
#[cfg(feature = "native-window")]
pub use window::run;
