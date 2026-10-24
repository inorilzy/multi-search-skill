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
    mutation: Mutex<()>,
}

impl DesktopManager {
    pub fn new(environment: RuntimeEnvironment) -> Self {
        Self {
            environment,
            user_path_store: None,
            execution_slot: Mutex::new(None),
            next_id: AtomicU64::new(1),
            closed: AtomicBool::new(false),
            mutation: Mutex::new(()),
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

    // ponytail: one per-manager mutation lock; split by domain only if concurrency is needed.
    fn mutation_guard(&self) -> Result<std::sync::MutexGuard<'_, ()>, String> {
        self.mutation.try_lock().map_err(|error| match error {
            std::sync::TryLockError::WouldBlock => "Another management operation is in progress".into(),
            std::sync::TryLockError::Poisoned(_) => "Previous management operation failed; restart and verify installation".into(),
        })
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

    #[allow(dead_code)]
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
        self.install_from(None)
    }

    pub fn update(&self) -> InstallOutcome {
        self.update_from(None)
    }

    pub fn uninstall(&self) -> InstallOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return InstallOutcome {
            status: "blocked".into(), steps: vec![], version: None, bin: None, path_hint: String::new(), reason,
        }};
        self.install_view().uninstall()
    }

    #[cfg_attr(not(feature = "native-window"), allow(dead_code))]
    pub(crate) fn install_plan_from(&self, bundled: Option<&std::path::Path>) -> InstallPlan {
        self.install_view().install_plan_from(bundled)
    }

    pub(crate) fn install_from(&self, bundled: Option<&std::path::Path>) -> InstallOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return InstallOutcome {
            status: "blocked".into(), steps: vec![], version: None, bin: None, path_hint: String::new(), reason,
        }};
        self.install_view().install_from(bundled)
    }

    pub(crate) fn update_from(&self, bundled: Option<&std::path::Path>) -> InstallOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return InstallOutcome {
            status: "blocked".into(), steps: vec![], version: None, bin: None, path_hint: String::new(), reason,
        }};
        self.install_view().update_from(bundled)
    }

    // ---- skill --------------------------------------------------------

    pub fn skill_plan(&self, scope: &str, project: Option<PathBuf>) -> SkillPlan {
        self.skills_view().skill_plan(scope, project)
    }

    pub fn skill_install(&self, scope: &str, project: Option<PathBuf>) -> SkillInstall {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return SkillInstall {
            status: "blocked".into(), target: None, verified: false, files: vec![], reason,
        }};
        self.skills_view().skill_install(scope, project)
    }

    pub fn skill_update(
        &self,
        scope: &str,
        project: Option<PathBuf>,
        confirm_overwrite: bool,
    ) -> UpdateOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return UpdateOutcome {
            status: "blocked".into(), verified: false, backup: None, reason,
        }};
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
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return RemoveOutcome {
            status: "blocked".into(), deleted: vec![], kept: vec![], reason,
        }};
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

    #[allow(dead_code)]
    pub(crate) fn require_storage_cli(&self, cli: &std::path::Path) -> Result<(), String> {
        self.credential_manager().require_storage_cli(cli)
    }

    #[cfg_attr(not(feature = "native-window"), allow(dead_code))]
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
        let _guard = self.mutation_guard()?;
        self.user_path_view().change(remove, confirmed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn execution_slot_recovers_after_poison() {
        let manager = Arc::new(DesktopManager::new(RuntimeEnvironment {
            app_path: vec![], user_path: vec![], variables: Default::default(), cwd: std::env::temp_dir(),
        }));
        let other = manager.clone();
        let _ = std::thread::spawn(move || { let _guard = other.execution_slot.lock().unwrap(); panic!("synthetic poison"); }).join();
        assert!(manager.execution(1).is_err());
        manager.shutdown();
    }
    #[test]
    fn management_mutations_fail_fast_while_busy() {
        let manager = DesktopManager::new(RuntimeEnvironment {
            app_path: vec![], user_path: vec![], variables: Default::default(), cwd: std::env::temp_dir(),
        });
        let _guard = manager.mutation_guard().unwrap();
        assert_eq!(manager.install().status, "blocked");
        assert_eq!(manager.update().status, "blocked");
        assert_eq!(manager.uninstall().status, "blocked");
        assert_eq!(manager.skill_install("global", None).status, "blocked");
        assert_eq!(manager.skill_update("global", None, true).status, "blocked");
        assert_eq!(manager.skill_remove("global", None, true).status, "blocked");
        assert!(match manager.user_path_change(true, true) {
            Err(reason) => reason.contains("Another management operation"),
            Ok(_) => false,
        });
    }
}
