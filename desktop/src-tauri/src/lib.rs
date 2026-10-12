//! Native management boundary; the CLI remains the search implementation.
mod diagnostics;
mod environment;
mod execution;
mod install;
mod process;
mod redaction;
mod skill;
mod skill_manage;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, DesktopManager, Discovery, RuntimeEnvironment};
pub use execution::{ExecutionStatus, SearchOptions};
pub use skill::{SkillInstall, SkillPlan};
pub use skill_manage::{InstallState, RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome, UpdatePlan};
#[cfg(feature = "native-window")]
pub use window::run;
