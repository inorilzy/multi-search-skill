use crate::{CliStatus, DesktopManager, ExecutionStatus, RuntimeEnvironment, SearchOptions, SkillInstall, SkillPlan};
use std::{path::PathBuf, sync::Arc};
use tauri::Manager;
use crate::errors::{backend, finish};

/// Join a blocking worker and normalize both failure layers into the `{ code, message }` contract:
/// a worker panic gets a stable code, an inner operation error keeps its localized message.
async fn offload<T, F>(work: F, worker_code: &'static str) -> Result<T, String>
where
    F: FnOnce() -> Result<T, String> + Send + 'static,
    T: Send + 'static,
{
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|_| backend(worker_code).into())
        .and_then(finish)
}

/// Offload work that cannot fail on its own (it reports outcomes in its payload).
async fn offload_value<T, F>(work: F, worker_code: &'static str) -> Result<T, String>
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|_| backend(worker_code).into())
}

// No command accepts an executable path from the frontend: every CLI run resolves the managed
// install (then PATH) in the backend, so script running in the webview cannot pick a program.
#[tauri::command]
async fn detect_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<CliStatus, String> {
    let manager = manager.inner().clone();
    offload_value(move || {
        let mut status = manager.detect_cli();
        let secrets = crate::redaction::secrets(&manager.environment);
        for row in [&mut status.app, &mut status.user, &mut status.execution] {
            row.path = row
                .path
                .take()
                .map(|value| crate::redaction::scrub(&value, &secrets));
            row.reason = crate::redaction::scrub(&row.reason, &secrets);
        }
        status
    }, "cli_detect_failed")
    .await
}
#[tauri::command]
async fn start_test_search(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    options: SearchOptions,
) -> Result<u64, String> {
    let manager = manager.inner().clone();
    offload(move || manager.start_search(options), "search_start_failed").await
}
#[tauri::command]
async fn poll_execution(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    id: u64,
) -> Result<ExecutionStatus, String> {
    let manager = manager.inner().clone();
    offload(move || manager.execution(id), "execution_poll_failed").await
}
#[tauri::command]
async fn cancel_test_search(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    id: u64,
) -> Result<ExecutionStatus, String> {
    let manager = manager.inner().clone();
    offload(move || manager.cancel_search(id), "execution_cancel_failed").await
}

#[tauri::command]
async fn skill_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<SkillPlan, String> {
    let manager = manager.inner().clone();
    offload_value(move || manager.skill_plan(&scope, project.map(PathBuf::from)), "skill_plan_failed").await
}
#[tauri::command]
async fn skill_install(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<SkillInstall, String> {
    let manager = manager.inner().clone();
    offload_value(move || manager.skill_install(&scope, project.map(PathBuf::from)), "skill_install_failed").await
}
/// The app's own `cli-bundle` resource directory, resolved once at startup. Never a frontend parameter.
struct BundledCli(Option<PathBuf>);

#[tauri::command]
async fn install_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    bundled: tauri::State<'_, BundledCli>,
) -> Result<crate::install::InstallPlan, String> {
    let manager = manager.inner().clone();
    let bundled = bundled.0.clone();
    offload_value(move || manager.install_plan_from(bundled.as_deref()), "install_plan_failed").await
}
#[tauri::command]
async fn install_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    bundled: tauri::State<'_, BundledCli>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    let bundled = bundled.0.clone();
    offload_value(move || manager.install_from(bundled.as_deref()), "install_failed").await
}
#[tauri::command]
async fn update_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    bundled: tauri::State<'_, BundledCli>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    let bundled = bundled.0.clone();
    offload_value(move || manager.update_from(bundled.as_deref()), "update_failed").await
}
#[tauri::command]
async fn uninstall_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    offload_value(move || manager.uninstall(), "uninstall_failed").await
}
#[tauri::command]
async fn user_path_plan(manager: tauri::State<'_, Arc<DesktopManager>>) -> Result<crate::user_path::PathPlan, String> {
    let manager = manager.inner().clone();
    offload(move || manager.user_path_plan(), "user_path_check_failed").await
}
#[tauri::command]
async fn user_path_change(manager: tauri::State<'_, Arc<DesktopManager>>, remove: bool, confirmed: bool) -> Result<crate::user_path::PathPlan, String> {
    let manager = manager.inner().clone();
    offload(move || manager.user_path_change(remove, confirmed), "user_path_change_failed").await
}
// Every credential command takes a UI source name. `resolve_source` is the only way a
// provider reaches the store target, so an unknown or crafted name fails before any access.
#[tauri::command]
async fn credential_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    let manager = manager.inner().clone();
    offload_value(move || {
        // Core decides the effective source; the desktop only displays it.
        let key_sources = manager.key_sources();
        let mut overview = crate::credential_commands::with_native(|backend| {
            crate::credential_commands::overview(backend, &variables, entry)
        });
        crate::credential_commands::apply_core_source(
            &mut overview,
            key_sources.get(&entry.key_provider),
        );
        overview
    }, "credential_status_failed")
    .await
}
#[tauri::command]
async fn credential_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    key: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    let manager = manager.inner().clone();
    offload(move || {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let mut overview = crate::credential_commands::with_native(|backend| {
            crate::credential_commands::save(backend, &variables, entry, &key, now)
        })?;
        // Read Core after the write so the returned overview reflects the new state.
        let key_sources = manager.key_sources();
        crate::credential_commands::apply_core_source(
            &mut overview,
            key_sources.get(&entry.key_provider),
        );
        Ok::<_, String>(overview)
    }, "credential_save_failed")
    .await
}
#[tauri::command]
async fn credential_delete(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    let manager = manager.inner().clone();
    offload(move || {
        let mut overview = crate::credential_commands::with_native(|backend| {
            crate::credential_commands::delete(backend, &variables, entry)
        })?;
        // Read Core after the delete so the returned overview reflects the new state.
        let key_sources = manager.key_sources();
        crate::credential_commands::apply_core_source(
            &mut overview,
            key_sources.get(&entry.key_provider),
        );
        Ok::<_, String>(overview)
    }, "credential_delete_failed")
    .await
}
#[tauri::command]
async fn credential_test(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::TestOutcome, String> {
    let entry = finish(crate::credential_commands::resolve_test_source(&source))?;
    let manager = manager.inner().clone();
    offload(move || {
        let cli = manager.execution_cli()?;
        manager.test_source(cli, entry, &format!("{} connectivity check", entry.name))
    }, "credential_test_failed")
    .await
}

#[tauri::command]
async fn migration_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::credential_commands::MigrationPlan, String> {
    let manager = manager.inner().clone();
    offload(move || {
        let keys_file = crate::credential_commands::keys_file_path(&manager.environment.variables)
            .ok_or_else(|| "无法定位旧 key 文件".to_string())?;
        let cli = manager.execution_cli()?;
        manager.migration_plan(cli, &keys_file)
    }, "migration_plan_failed")
    .await
}
#[tauri::command]
async fn migration_apply(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    plan_token: String,
    approved: Vec<String>,
    choices: std::collections::BTreeMap<String, String>,
) -> Result<crate::credential_commands::MigrationResult, String> {
    let request = finish(crate::credential_commands::migration_request(&plan_token, &approved, &choices))?;
    let manager = manager.inner().clone();
    offload(move || {
        let keys_file = crate::credential_commands::keys_file_path(&manager.environment.variables)
            .ok_or_else(|| "无法定位旧 key 文件".to_string())?;
        let cli = manager.execution_cli()?;
        manager.migration_apply(cli, &keys_file, &request)
    }, "migration_apply_failed")
    .await
}

#[tauri::command]
async fn settings_view(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    offload_value(move || {
        // The CLI's doctor payload is the single source of truth for the displayed config path.
        let doctor = manager.doctor_config();
        crate::settings::view_with_doctor(&manager.environment, doctor.as_ref())
    }, "settings_view_failed")
    .await
}
#[tauri::command]
async fn settings_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    input: crate::settings::SettingsInput,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    offload(move || crate::settings::save(&manager.environment, &input), "settings_save_failed").await
}

#[tauri::command]
async fn skill_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<crate::SkillStatus, String> {
    let manager = manager.inner().clone();
    offload(move || manager.skill_status(&scope, project.map(PathBuf::from)), "skill_status_failed").await
}
#[tauri::command]
async fn skill_update(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
    confirm_overwrite: bool,
) -> Result<crate::UpdateOutcome, String> {
    let manager = manager.inner().clone();
    offload_value(move || {
        manager.skill_update(&scope, project.map(PathBuf::from), confirm_overwrite)
    }, "skill_update_failed")
    .await
}
#[tauri::command]
async fn skill_remove_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<crate::RemovePlan, String> {
    let manager = manager.inner().clone();
    offload(move || manager.skill_remove_plan(&scope, project.map(PathBuf::from)), "skill_remove_plan_failed").await
}
#[tauri::command]
async fn skill_remove(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
    confirmed: bool,
) -> Result<crate::RemoveOutcome, String> {
    let manager = manager.inner().clone();
    offload_value(move || manager.skill_remove(&scope, project.map(PathBuf::from), confirmed), "skill_remove_failed").await
}

/// Successor tickets add their own modules and typed commands here; no generic execution bridge.
pub fn run() {
    let mut environment = RuntimeEnvironment::system();
    environment.user_path = environment.machine_paths();
    let path_store: Arc<dyn crate::user_path::PathStore> = Arc::new(crate::user_path::NativePathStore::current_user());
    #[cfg(feature = "install-test-boundary")]
    let path_store = if environment.variables.get("MULTI_SEARCH_TEST_ISOLATION").map(String::as_str) == Some("1") {
        // Compile-time-only acceptance boundary. Never present in the distributed build.
        let key = environment.variables.get("MULTI_SEARCH_ACCEPTANCE_PATH_KEY").expect("isolated PATH key required");
        environment.user_path.clear();
        Arc::new(crate::user_path::NativePathStore::isolated_key(key).expect("invalid isolated PATH key")) as Arc<dyn crate::user_path::PathStore>
    } else { path_store };
    let manager = DesktopManager::with_user_path_store(environment, path_store);
    tauri::Builder::default()
        .manage(Arc::new(manager))
        .setup(|app| {
            let bundled = app.path().resource_dir().ok().map(|dir| dir.join("cli-bundle"));
            app.manage(BundledCli(bundled));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            detect_cli,
            start_test_search,
            poll_execution,
            cancel_test_search,
            skill_plan,
            skill_install,
            install_plan,
            install_cli,
            skill_status,
            skill_update,
            skill_remove_plan,
            skill_remove,
            update_cli,
            uninstall_cli,
            user_path_plan,
            user_path_change,
            credential_status,
            credential_save,
            credential_delete,
            credential_test,
            migration_plan,
            migration_apply,
            settings_view,
            settings_save
        ])
        .on_window_event(|window, event| {
            if matches!(
                event,
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed
            ) {
                window.state::<Arc<DesktopManager>>().shutdown();
            }
        })
        .run(tauri::generate_context!())
        .expect("desktop runtime failed");
}
