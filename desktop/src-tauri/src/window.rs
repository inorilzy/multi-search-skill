use crate::{CliStatus, DesktopManager, ExecutionStatus, RuntimeEnvironment, SearchOptions};
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

/// Successor tickets add their own modules and typed commands here; no generic execution bridge.
pub fn run() {
    tauri::Builder::default()
        .manage(Arc::new(DesktopManager::new(RuntimeEnvironment::system())))
        .invoke_handler(tauri::generate_handler![
            detect_cli,
            start_test_search,
            poll_execution,
            cancel_test_search
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
