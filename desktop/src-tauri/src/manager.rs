//! `DesktopManager` is the shared state boundary. It owns only fields that
//! genuinely cross domains — the environment, the execution slot/counters,
//! the closed flag and the injected PATH store — and exposes each domain as a
//! stateless view (`CliDiscovery`, `InstallManager`, `SkillManager`,
//! `CredentialManager`, `UserPathManager`). Every `impl DesktopManager` lives
//! here; domain modules define their own types instead of adding impl blocks.
use crate::credential_commands::{CredentialManager, SourceEntry, TestOutcome};
use crate::diagnostics::{CliDiscovery, CliStatus};
use crate::execution::{Execution, ExecutionManager, ExecutionStatus, SearchOptions};
use crate::install::{InstallManager, InstallOutcome, InstallPlan};
use crate::skill::{SkillInstall, SkillManager, SkillPlan};
use crate::skill_manage::{
    RemoveOutcome, RemovePlan, SkillStatus, UpdateOutcome,
};
use crate::user_path::{PathPlan, PathStore, UserPathManager};
use crate::RuntimeEnvironment;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicU64},
        Arc, Mutex,
    },
};

pub struct DesktopManager {
    pub(crate) environment: RuntimeEnvironment,
    pub(crate) user_path_store: Option<Arc<dyn PathStore>>,
    pub(crate) execution_slot: Mutex<Option<Arc<Mutex<Execution>>>>,
    pub(crate) next_id: AtomicU64,
    pub(crate) closed: AtomicBool,
}

impl DesktopManager {
    pub fn new(environment: RuntimeEnvironment) -> Self {
        Self {
            environment,
            user_path_store: None,
            execution_slot: Mutex::new(None),
            next_id: AtomicU64::new(1),
            closed: AtomicBool::new(false),
        }
    }

    /// Explicit dependency injection for isolated acceptance. Production uses the native registry.
    pub fn with_user_path_store(
        environment: RuntimeEnvironment,
        store: Arc<dyn PathStore>,
    ) -> Self {
        let mut manager = Self::new(environment);
        manager.user_path_store = Some(store);
        manager
    }

    // ---- domain views -------------------------------------------------

    fn discovery_view(&self) -> CliDiscovery<'_> {
        CliDiscovery::new(&self.environment, self.user_path_store.as_ref())
    }

    fn install_view(&self) -> InstallManager<'_> {
        InstallManager {
            environment: &self.environment,
        }
    }

    fn skills_view(&self) -> SkillManager<'_> {
        SkillManager {
            environment: &self.environment,
            discovery: self.discovery_view(),
        }
    }

    fn user_path_view(&self) -> UserPathManager<'_> {
        UserPathManager {
            environment: &self.environment,
            store: self.user_path_store.as_ref(),
            install: self.install_view(),
        }
    }

    fn execution_view(&self) -> ExecutionManager<'_> {
        ExecutionManager {
            environment: &self.environment,
            execution_slot: &self.execution_slot,
            next_id: &self.next_id,
            closed: &self.closed,
            discovery: self.discovery_view(),
            install: self.install_view(),
        }
    }

    // ---- CLI discovery ------------------------------------------------

    pub fn detect_cli(&self, explicit_path: Option<PathBuf>) -> CliStatus {
        self.discovery_view().detect(explicit_path)
    }

    /// Keep diagnostics truthful about the old app PATH, while UI commands can use the
    /// newly verified user PATH immediately. An explicitly selected bad executable never falls back.
    pub fn execution_cli(&self, explicit_path: Option<PathBuf>) -> Result<PathBuf, String> {
        self.discovery_view().execution_path(explicit_path)
    }

    pub(crate) fn current_user_paths(&self) -> Vec<PathBuf> {
        self.discovery_view().current_user_paths()
    }

    // ---- execution ----------------------------------------------------

    pub fn start_search(
        &self,
        path: Option<PathBuf>,
        options: SearchOptions,
    ) -> Result<u64, String> {
        self.execution_view().start_search(path, options)
    }

    pub fn cancel_search(&self, id: u64) -> Result<ExecutionStatus, String> {
        self.execution_view().cancel_search(id)
    }

    pub fn execution(&self, id: u64) -> Result<ExecutionStatus, String> {
        self.execution_view().execution(id)
    }

    pub fn shutdown(&self) {
        self.execution_view().shutdown()
    }

    // ---- install ------------------------------------------------------

    pub fn install_plan(&self) -> InstallPlan {
        self.install_view().install_plan()
    }

    pub fn install(&self) -> InstallOutcome {
        self.install_view().install()
    }

    pub fn update(&self) -> InstallOutcome {
        self.install_view().update()
    }

    pub fn uninstall(&self) -> InstallOutcome {
        self.install_view().uninstall()
    }

    pub(crate) fn install_plan_from(&self, bundled: Option<&std::path::Path>) -> InstallPlan {
        self.install_view().install_plan_from(bundled)
    }

    pub(crate) fn install_from(&self, bundled: Option<&std::path::Path>) -> InstallOutcome {
        self.install_view().install_from(bundled)
    }

    pub(crate) fn update_from(&self, bundled: Option<&std::path::Path>) -> InstallOutcome {
        self.install_view().update_from(bundled)
    }

    // ---- skill --------------------------------------------------------

    pub fn skill_plan(&self, scope: &str, project: Option<PathBuf>) -> SkillPlan {
        self.skills_view().skill_plan(scope, project)
    }

    pub fn skill_install(&self, scope: &str, project: Option<PathBuf>) -> SkillInstall {
        self.skills_view().skill_install(scope, project)
    }

    pub fn skill_update(
        &self,
        scope: &str,
        project: Option<PathBuf>,
        confirm_overwrite: bool,
    ) -> UpdateOutcome {
        self.skills_view().skill_update(scope, project, confirm_overwrite)
    }

    pub fn skill_remove_plan(
        &self,
        scope: &str,
        project: Option<PathBuf>,
    ) -> Result<RemovePlan, String> {
        self.skills_view().skill_remove_plan(scope, project)
    }

    pub fn skill_remove(
        &self,
        scope: &str,
        project: Option<PathBuf>,
        confirmed: bool,
    ) -> RemoveOutcome {
        self.skills_view().skill_remove(scope, project, confirmed)
    }

    pub fn skill_status(
        &self,
        scope: &str,
        project: Option<PathBuf>,
    ) -> Result<SkillStatus, String> {
        self.skills_view().skill_status(scope, project)
    }

    // ---- credentials --------------------------------------------------

    pub(crate) fn credential_manager(&self) -> CredentialManager<'_> {
        CredentialManager {
            environment: &self.environment,
        }
    }

    pub(crate) fn require_storage_cli(&self, cli: &std::path::Path) -> Result<(), String> {
        self.credential_manager().require_storage_cli(cli)
    }

    pub(crate) fn test_source(
        &self,
        cli: PathBuf,
        entry: &SourceEntry,
        query: &str,
    ) -> Result<TestOutcome, String> {
        self.credential_manager().test_source(cli, entry, query)
    }

    // ---- user PATH ----------------------------------------------------

    pub fn user_path_plan(&self) -> Result<PathPlan, String> {
        self.user_path_view().plan()
    }

    pub fn user_path_change(&self, remove: bool, confirmed: bool) -> Result<PathPlan, String> {
        self.user_path_view().change(remove, confirmed)
    }
}
