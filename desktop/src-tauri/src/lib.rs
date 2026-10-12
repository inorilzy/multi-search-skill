//! Native management boundary; the CLI remains the search implementation.
mod diagnostics;
mod environment;
mod execution;
mod process;
mod redaction;
mod skill;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, DesktopManager, Discovery, RuntimeEnvironment};
pub use execution::{ExecutionStatus, SearchOptions};
pub use skill::{SkillInstall, SkillPlan};
#[cfg(feature = "native-window")]
pub use window::run;
