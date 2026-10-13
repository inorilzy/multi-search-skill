use crate::{CliStatus, DesktopManager, ExecutionStatus, RuntimeEnvironment, SearchOptions, SkillInstall, SkillPlan};
use std::{path::PathBuf, sync::Arc};
use tauri::Manager;

#[tauri::command]
async fn detect_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    path: Option<String>,
) -> Result<CliStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut status = manager.detect_cli(path.map(PathBuf::from));
        let secrets = crate::redaction::secrets(&manager.environment);
        for row in [&mut status.app, &mut status.user] {
            row.path = row
                .path
                .take()
                .map(|value| crate::redaction::scrub(&value, &secrets));
            row.reason = crate::redaction::scrub(&row.reason, &secrets);
        }
        status
    })
    .await
    .map_err(|_| "CLI detection worker failed".into())
}
#[tauri::command]
async fn start_test_search(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    path: Option<String>,
    options: SearchOptions,
) -> Result<u64, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        manager.start_search(path.map(PathBuf::from), options)
    })
    .await
    .map_err(|_| "Search worker failed")?
}
#[tauri::command]
fn poll_execution(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    id: u64,
) -> Result<ExecutionStatus, String> {
    manager.execution(id)
}
#[tauri::command]
fn cancel_test_search(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    id: u64,
) -> Result<ExecutionStatus, String> {
    manager.cancel_search(id)
}

#[tauri::command]
async fn skill_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<SkillPlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.skill_plan(&scope, project.map(PathBuf::from)))
        .await
        .map_err(|_| "Skill planning worker failed".into())
}
#[tauri::command]
async fn skill_install(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<SkillInstall, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.skill_install(&scope, project.map(PathBuf::from)))
        .await
        .map_err(|_| "Skill install worker failed".into())
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
    tauri::async_runtime::spawn_blocking(move || manager.install_plan_from(bundled.as_deref()))
        .await
        .map_err(|_| "Install planning failed".into())
}
#[tauri::command]
async fn install_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    bundled: tauri::State<'_, BundledCli>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    let bundled = bundled.0.clone();
    tauri::async_runtime::spawn_blocking(move || manager.install_from(bundled.as_deref()))
        .await
        .map_err(|_| "Install worker failed".into())
}
// Every credential command takes a UI source name. `resolve_source` is the only way a
// provider reaches the store target, so an unknown or crafted name fails before any access.
#[tauri::command]
async fn update_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    bundled: tauri::State<'_, BundledCli>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    let bundled = bundled.0.clone();
    tauri::async_runtime::spawn_blocking(move || manager.update_from(bundled.as_deref()))
        .await
        .map_err(|_| "Update worker failed".into())
}
#[tauri::command]
async fn uninstall_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.uninstall())
        .await
        .map_err(|_| "Uninstall worker failed".into())
}
#[tauri::command]
async fn credential_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::credential_commands::with_native(|backend| {
            crate::credential_commands::overview(backend, &variables, entry)
        })
    })
    .await
    .map_err(|_| "Credential status worker failed".into())
}
#[tauri::command]
async fn credential_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    key: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        crate::credential_commands::with_native(|backend| {
            crate::credential_commands::save(backend, &variables, entry, &key, now)
        })
    })
    .await
    .map_err(|_| "Credential save worker failed".to_string())?
}
#[tauri::command]
async fn credential_delete(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::credential_commands::with_native(|backend| {
            crate::credential_commands::delete(backend, &variables, entry)
        })
    })
    .await
    .map_err(|_| "Credential delete worker failed".to_string())?
}
#[tauri::command]
async fn credential_test(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    path: Option<String>,
) -> Result<crate::credential_commands::TestOutcome, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let detection = manager.detect_cli(path.map(PathBuf::from));
        if detection.app.status != "ready" {
            return Err(detection.app.reason);
        }
        let cli = PathBuf::from(detection.app.path.unwrap_or_default());
        manager.test_source(cli, entry, &format!("{} connectivity check", entry.source))
    })
    .await
    .map_err(|_| "Credential test worker failed".to_string())?
}

#[tauri::command]
async fn migration_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    path: Option<String>,
) -> Result<crate::credential_commands::MigrationPlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let keys_file = crate::credential_commands::keys_file_path(&manager.environment.variables)
            .ok_or_else(|| "无法定位旧 key 文件".to_string())?;
        let detection = manager.detect_cli(path.map(PathBuf::from));
        if detection.app.status != "ready" {
            return Err(detection.app.reason);
        }
        let cli = PathBuf::from(detection.app.path.unwrap_or_default());
        manager.migration_plan(cli, &keys_file)
    })
    .await
    .map_err(|_| "Migration plan worker failed".to_string())?
}
#[tauri::command]
async fn migration_apply(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    plan_token: String,
    approved: Vec<String>,
    choices: std::collections::BTreeMap<String, String>,
    path: Option<String>,
) -> Result<crate::credential_commands::MigrationResult, String> {
    let request = crate::credential_commands::migration_request(&plan_token, &approved, &choices)?;
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let keys_file = crate::credential_commands::keys_file_path(&manager.environment.variables)
            .ok_or_else(|| "无法定位旧 key 文件".to_string())?;
        let detection = manager.detect_cli(path.map(PathBuf::from));
        if detection.app.status != "ready" {
            return Err(detection.app.reason);
        }
        let cli = PathBuf::from(detection.app.path.unwrap_or_default());
        manager.migration_apply(cli, &keys_file, &request)
    })
    .await
    .map_err(|_| "Migration apply worker failed".to_string())?
}

#[tauri::command]
fn settings_view(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::settings::SettingsView, String> {
    Ok(crate::settings::view(&manager.inner().environment))
}
#[tauri::command]
fn settings_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    input: crate::settings::SettingsInput,
) -> Result<crate::settings::SettingsView, String> {
    crate::settings::save(&manager.inner().environment, &input)
}

#[tauri::command]
async fn skill_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<crate::SkillStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.skill_status(&scope, project.map(PathBuf::from)))
        .await
        .map_err(|_| "Skill status worker failed".to_string())?
}
#[tauri::command]
async fn skill_update(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
    confirm_overwrite: bool,
) -> Result<crate::UpdateOutcome, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        manager.skill_update(&scope, project.map(PathBuf::from), confirm_overwrite)
    })
    .await
    .map_err(|_| "Skill update worker failed".into())
}
#[tauri::command]
async fn skill_remove_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<crate::RemovePlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.skill_remove_plan(&scope, project.map(PathBuf::from)))
        .await
        .map_err(|_| "Skill removal planning worker failed".to_string())?
}
#[tauri::command]
async fn skill_remove(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
    confirmed: bool,
) -> Result<crate::RemoveOutcome, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.skill_remove(&scope, project.map(PathBuf::from), confirmed))
        .await
        .map_err(|_| "Skill removal worker failed".into())
}

/// Successor tickets add their own modules and typed commands here; no generic execution bridge.
pub fn run() {
    tauri::Builder::default()
        .manage(Arc::new(DesktopManager::new(RuntimeEnvironment::system())))
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
