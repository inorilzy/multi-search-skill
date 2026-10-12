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
#[tauri::command]
async fn install_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::install::InstallPlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.install_plan())
        .await
        .map_err(|_| "Install planning failed".into())
}
#[tauri::command]
async fn install_cli(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::install::InstallOutcome, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.install())
        .await
        .map_err(|_| "Install worker failed".into())
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
            skill_remove
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
