//! Native management boundary; the CLI remains the search implementation.
mod diagnostics;
mod environment;
mod execution;
mod install;
mod process;
mod redaction;
#[cfg(feature = "native-window")]
mod window;
pub use diagnostics::{CliStatus, DesktopManager, Discovery, RuntimeEnvironment};
pub use execution::{ExecutionStatus, SearchOptions};
#[cfg(feature = "native-window")]
pub use window::run;
