//! `DesktopManager` is the shared state boundary. It owns only fields that
//! genuinely cross domains — the environment, the execution slot/counters,
//! the closed flag and the injected PATH store — and exposes each domain as a
//! stateless view (`CliDiscovery`, `InstallManager`, `SkillManager`,
//! `CredentialManager`, `UserPathManager`). Every `impl DesktopManager` lives
//! here; domain modules define their own types instead of adding impl blocks.
use crate::credential_commands::{CredentialManager, SourceEntry, TestOutcome};
use crate::diagnostics::{CliDiscovery, CliStatus};
use crate::execution::{Execution, ExecutionManager, ExecutionStatus, SearchOptions};
use crate::install::{AppInfo, InstallManager, InstallOutcome, InstallPlan};
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
    log_viewer: crate::log_viewer::LogViewerSlot,
    /// Core's `doctor` key-source report, shared briefly: a page asks for several
    /// providers at once and each answer comes from the same doctor run.
    key_sources_cache: ShortCache<KeySources>,
    /// The verified managed CLI path. Verifying re-hashes every installed file (~90 MB),
    /// and every CLI-running command asks for it; install/update/uninstall clear it.
    managed_cli_cache: ShortCache<Option<PathBuf>>,
}

type KeySources = std::collections::BTreeMap<String, crate::credential_commands::CoreKeySource>;
/// Long enough to cover one page's parallel status reads, short enough that a key
/// edited in a terminal shows up on the next refresh.
const KEY_SOURCES_TTL: std::time::Duration = std::time::Duration::from_secs(5);
/// Covers one page load (several commands each resolve the CLI); a tampered or removed
/// install is still caught within seconds, and install changes clear it at once.
const MANAGED_CLI_TTL: std::time::Duration = std::time::Duration::from_secs(10);

/// A value shared for a short time. Callers serialize on one lock, so concurrent
/// readers that arrive while the value is being produced reuse that one result.
pub(crate) struct ShortCache<T> {
    ttl: std::time::Duration,
    slot: Mutex<Option<(std::time::Instant, T)>>,
}

impl<T: Clone> ShortCache<T> {
    pub(crate) fn new(ttl: std::time::Duration) -> Self {
        Self { ttl, slot: Mutex::new(None) }
    }

    /// Return the fresh value, or produce one. `keep` decides whether a produced value
    /// may be cached (a failed answer must not be).
    pub(crate) fn get_or(&self, produce: impl FnOnce() -> T, keep: impl FnOnce(&T) -> bool) -> T {
        let mut slot = self.slot.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some((at, value)) = slot.as_ref() {
            if at.elapsed() < self.ttl {
                return value.clone();
            }
        }
        let value = produce();
        *slot = keep(&value).then(|| (std::time::Instant::now(), value.clone()));
        value
    }

    pub(crate) fn clear(&self) {
        *self.slot.lock().unwrap_or_else(std::sync::PoisonError::into_inner) = None;
    }
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
            log_viewer: Default::default(),
            key_sources_cache: ShortCache::new(KEY_SOURCES_TTL),
            managed_cli_cache: ShortCache::new(MANAGED_CLI_TTL),
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
        // Discovery prefers the verified managed install so a same-named file on PATH cannot
        // stand in for it. `managed_cli` never consults PATH itself.
        let managed = self.managed_cli_cache.get_or(|| self.install_view().managed_cli(), |_| true);
        CliDiscovery::new(&self.environment, self.user_path_store.as_ref(), managed)
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

    /// Discovery never takes a caller-supplied executable: the UI can only observe the managed
    /// install and what the app and user PATH resolve to.
    pub fn detect_cli(&self) -> CliStatus {
        self.discovery_view().detect()
    }

    /// Core's own per-provider credential-source report (`doctor --format json`).
    #[cfg_attr(not(feature = "native-window"), allow(dead_code))]
    ///
    /// Concurrent callers wait on one lock, so N parallel status reads run doctor once.
    /// Writes that change keys call `invalidate_key_sources` first.
    pub(crate) fn key_sources(&self) -> KeySources {
        // An empty answer means doctor failed or timed out; never cache a failure.
        self.key_sources_cache
            .get_or(|| self.discovery_view().key_sources(), |sources| !sources.is_empty())
    }

    /// Drop the shared doctor report so the next read reflects a key change.
    pub(crate) fn invalidate_key_sources(&self) {
        self.key_sources_cache.clear();
    }

    /// Keep diagnostics truthful about the old app PATH, while UI commands can use the
    /// newly verified user PATH immediately. An explicitly selected bad executable never falls back.
    pub fn execution_cli(&self) -> Result<PathBuf, String> {
        self.discovery_view().execution_path()
    }

    #[allow(dead_code)]
    pub(crate) fn current_user_paths(&self) -> Vec<PathBuf> {
        self.discovery_view().current_user_paths()
    }

    // ---- execution ----------------------------------------------------

    pub fn start_search(&self, options: SearchOptions) -> Result<u64, String> {
        self.execution_view().start_search(options)
    }

    pub fn cancel_search(&self, id: u64) -> Result<ExecutionStatus, String> {
        self.execution_view().cancel_search(id)
    }

    pub fn execution(&self, id: u64) -> Result<ExecutionStatus, String> {
        self.execution_view().execution(id)
    }

    pub fn shutdown(&self) {
        self.execution_view().shutdown();
        self.log_viewer.stop();
    }

    // ---- log viewer ---------------------------------------------------

    /// Start (or reuse) `multi-search logs serve` with the same CLI the test search uses.
    pub fn log_viewer(&self) -> Result<crate::log_viewer::LogViewerInfo, String> {
        let cli = self.execution_cli()?;
        self.log_viewer.ensure(&cli, &self.environment)
    }

    // ---- install ------------------------------------------------------

    /// The installed CLI changed: the cached path and doctor report may be stale.
    fn forget_install_state(&self) {
        self.managed_cli_cache.clear();
        self.key_sources_cache.clear();
    }

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
        let outcome = self.install_view().uninstall();
        self.forget_install_state();
        outcome
    }

    /// App and bundled-CLI versions for the sidebar footer. Read-only; takes no mutation guard.
    #[cfg_attr(not(feature = "native-window"), allow(dead_code))]
    pub(crate) fn app_info_from(&self, bundled: Option<&std::path::Path>) -> AppInfo {
        crate::install::app_info(&self.environment, bundled)
    }

    #[cfg_attr(not(feature = "native-window"), allow(dead_code))]
    pub(crate) fn install_plan_from(&self, bundled: Option<&std::path::Path>) -> InstallPlan {
        self.install_view().install_plan_from(bundled)
    }

    pub(crate) fn install_from(&self, bundled: Option<&std::path::Path>) -> InstallOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return InstallOutcome {
            status: "blocked".into(), steps: vec![], version: None, bin: None, path_hint: String::new(), reason,
        }};
        let outcome = self.install_view().install_from(bundled);
        self.forget_install_state();
        outcome
    }

    pub(crate) fn update_from(&self, bundled: Option<&std::path::Path>) -> InstallOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return InstallOutcome {
            status: "blocked".into(), steps: vec![], version: None, bin: None, path_hint: String::new(), reason,
        }};
        let outcome = self.install_view().update_from(bundled);
        self.forget_install_state();
        outcome
    }

    // ---- skill --------------------------------------------------------

    pub fn skill_plan(&self, host: &str, scope: &str, project: Option<PathBuf>) -> SkillPlan {
        self.skills_view().skill_plan(host, scope, project)
    }

    pub fn skill_install(&self, host: &str, scope: &str, project: Option<PathBuf>) -> SkillInstall {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return SkillInstall {
            status: "blocked".into(), target: None, verified: false, files: vec![], reason,
        }};
        self.skills_view().skill_install(host, scope, project)
    }

    pub fn skill_update(
        &self,
        host: &str,
        scope: &str,
        project: Option<PathBuf>,
        confirm_overwrite: bool,
    ) -> UpdateOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return UpdateOutcome {
            status: "blocked".into(), verified: false, backup: None, reason,
        }};
        self.skills_view().skill_update(host, scope, project, confirm_overwrite)
    }

    pub fn skill_remove_plan(
        &self,
        host: &str,
        scope: &str,
        project: Option<PathBuf>,
    ) -> Result<RemovePlan, String> {
        self.skills_view().skill_remove_plan(host, scope, project)
    }

    pub fn skill_remove(
        &self,
        host: &str,
        scope: &str,
        project: Option<PathBuf>,
        confirmed: bool,
    ) -> RemoveOutcome {
        let _guard = match self.mutation_guard() { Ok(guard) => guard, Err(reason) => return RemoveOutcome {
            status: "blocked".into(), deleted: vec![], kept: vec![], reason,
        }};
        self.skills_view().skill_remove(host, scope, project, confirmed)
    }

    pub fn skill_status(
        &self,
        host: &str,
        scope: &str,
        project: Option<PathBuf>,
    ) -> Result<SkillStatus, String> {
        self.skills_view().skill_status(host, scope, project)
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
        assert_eq!(manager.skill_install("claude-code", "global", None).status, "blocked");
        assert_eq!(manager.skill_update("claude-code", "global", None, true).status, "blocked");
        assert_eq!(manager.skill_remove("claude-code", "global", None, true).status, "blocked");
        assert!(match manager.user_path_change(true, true) {
            Err(reason) => reason.contains("Another management operation"),
            Ok(_) => false,
        });
    }
}

#[cfg(test)]
mod short_cache_tests {
    use super::ShortCache;
    use std::sync::{atomic::{AtomicUsize, Ordering}, Arc};
    use std::time::Duration;

    #[test]
    fn concurrent_readers_share_one_production() {
        let cache = Arc::new(ShortCache::new(Duration::from_secs(5)));
        let runs = Arc::new(AtomicUsize::new(0));
        let handles: Vec<_> = (0..4)
            .map(|_| {
                let (cache, runs) = (cache.clone(), runs.clone());
                std::thread::spawn(move || {
                    cache.get_or(
                        || {
                            runs.fetch_add(1, Ordering::SeqCst);
                            std::thread::sleep(Duration::from_millis(50));
                            7
                        },
                        |_| true,
                    )
                })
            })
            .collect();
        for handle in handles {
            assert_eq!(handle.join().unwrap(), 7);
        }
        assert_eq!(runs.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn failures_are_not_cached_and_clear_forces_a_new_read() {
        let cache = ShortCache::new(Duration::from_secs(5));
        let runs = AtomicUsize::new(0);
        let read = |value: i32| cache.get_or(|| { runs.fetch_add(1, Ordering::SeqCst); value }, |v| *v != 0);
        assert_eq!(read(0), 0);
        assert_eq!(read(1), 1, "a failed answer is not reused");
        assert_eq!(read(2), 1, "a good answer is reused within the ttl");
        cache.clear();
        assert_eq!(read(3), 3);
        assert_eq!(runs.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn expired_values_are_produced_again() {
        let cache = ShortCache::new(Duration::from_millis(0));
        assert_eq!(cache.get_or(|| 1, |_| true), 1);
        assert_eq!(cache.get_or(|| 2, |_| true), 2);
    }
}
