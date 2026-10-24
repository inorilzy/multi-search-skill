use crate::{
    CliStatus, DesktopManager, ExecutionStatus, RuntimeEnvironment, SearchOptions, SkillInstall,
    SkillPlan,
};
use std::{path::PathBuf, sync::Arc};
use tauri::Manager;

#[tauri::command]
async fn cookie_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::cookie::CookieStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::cookie::status(&manager.environment)).await.map_err(|_| "Cookie worker failed")?
}
#[tauri::command]
async fn cookie_import(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    path: String,
    confirmed: bool,
) -> Result<crate::cookie::CookieStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::cookie::import(&manager.environment, std::path::Path::new(&path), confirmed)).await.map_err(|_| "Cookie worker failed")?
}
#[tauri::command]
async fn cookie_delete(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    confirmed: bool,
) -> Result<crate::cookie::CookieStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::cookie::delete(&manager.environment, confirmed)).await.map_err(|_| "Cookie worker failed")?
}

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
async fn poll_execution(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    id: u64,
) -> Result<ExecutionStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.execution(id)).await.map_err(|_| "Command worker failed")?
}
#[tauri::command]
async fn cancel_test_search(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    id: u64,
) -> Result<ExecutionStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.cancel_search(id)).await.map_err(|_| "Command worker failed")?
}

#[tauri::command]
async fn skill_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<SkillPlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        manager.skill_plan(&scope, project.map(PathBuf::from))
    })
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
    tauri::async_runtime::spawn_blocking(move || {
        manager.skill_install(&scope, project.map(PathBuf::from))
    })
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
async fn user_path_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::user_path::PathPlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.user_path_plan())
        .await
        .map_err(|_| "PATH 检查失败")?
}
#[tauri::command]
async fn user_path_change(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    remove: bool,
    confirmed: bool,
) -> Result<crate::user_path::PathPlan, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.user_path_change(remove, confirmed))
        .await
        .map_err(|_| "PATH 修改失败")?
}
// Every credential command takes a UI source name. `resolve_source` is the only way a
// provider reaches the store target, so an unknown or crafted name fails before any access.
#[tauri::command]
async fn credential_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::overview(backend, &variables, &entry)
        })
    })
    .await
    .map_err(|_| "Credential status worker failed".into())
}
#[tauri::command]
async fn credential_read(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialValue, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::read(backend, &variables, &entry)
        })
    })
    .await
    .map_err(|_| "Credential read worker failed".to_string())?
}
#[tauri::command]
async fn credential_reveal(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialValue, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::reveal(backend, &variables, &entry)
        })
    })
    .await
    .map_err(|_| "Credential read worker failed".to_string())?
}
#[tauri::command]
async fn credential_application_open(source: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || crate::credential_commands::open_application(&source)).await.map_err(|_| "Browser worker failed")?
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
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::save(backend, &variables, &entry, &key, now)
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
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::delete(backend, &variables, &entry)
        })
    })
    .await
    .map_err(|_| "Credential delete worker failed".to_string())?
}
#[tauri::command]
async fn credential_append(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    keys: Vec<String>,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::append(backend, &variables, &entry, &keys, now)
        })
    })
    .await
    .map_err(|_| "Credential append worker failed".to_string())?
}
#[tauri::command]
async fn credential_remove(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    index: usize,
    expected: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = crate::credential_commands::resolve_source(&source)?;
    let variables = manager.inner().environment.variables.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        crate::credential_commands::with_native(&variables, |backend| {
            crate::credential_commands::remove_row(backend, &variables, &entry, index, &expected, now)
        })
    })
    .await
    .map_err(|_| "Credential remove worker failed".to_string())?
}
#[tauri::command]
async fn credential_test(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    path: Option<String>,
) -> Result<crate::credential_commands::TestOutcome, String> {
    let entry = crate::credential_commands::resolve_test_source(&source)?;
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let cli = manager.execution_cli(path.map(PathBuf::from))?;
        manager.test_source(cli, &entry, &format!("{} connectivity check", entry.source))
    })
    .await
    .map_err(|_| "Credential test worker failed".to_string())?
}

#[tauri::command]
async fn settings_view(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || Ok(crate::settings::view(&manager.environment))).await.map_err(|_| "Command worker failed")?
}
#[tauri::command]
async fn scrape_settings_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    backends: Vec<String>,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::settings::save_scrape_backends(&manager.environment, &backends)).await.map_err(|_| "Command worker failed")?
}
#[tauri::command]
async fn settings_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    input: crate::settings::SettingsInput,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::settings::save(&manager.environment, &input)).await.map_err(|_| "Command worker failed")?
}

/// 只读站点抓取记忆；state.sqlite 缺失或损坏时返回 available=false 的视图。
#[tauri::command]
async fn scrape_memory_view(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    site: Option<String>,
) -> Result<crate::scrape_memory::ScrapeMemoryView, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || Ok(crate::scrape_memory::view(
        &manager.environment,
        site.as_deref(),
    ))).await.map_err(|_| "Command worker failed")?
}
#[tauri::command]
async fn scrape_memory_pin(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    site: String,
    scraper: String,
) -> Result<crate::scrape_memory::ScrapeMemoryView, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::scrape_memory::pin(&manager.environment, &site, &scraper)).await.map_err(|_| "Command worker failed")?
}
#[tauri::command]
async fn scrape_memory_reset(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    site: String,
) -> Result<crate::scrape_memory::ScrapeMemoryView, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || crate::scrape_memory::reset(&manager.environment, Some(&site))).await.map_err(|_| "Command worker failed")?
}

/// Provider manifest for the sources/settings pages. Returns the same rows the
/// desktop uses internally; the UI keeps no copy of this table.
#[tauri::command]
fn provider_list() -> Vec<crate::provider::ProviderInfo> {
    crate::provider::list()
}

#[tauri::command]
async fn skill_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<crate::SkillStatus, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        manager.skill_status(&scope, project.map(PathBuf::from))
    })
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
    tauri::async_runtime::spawn_blocking(move || {
        manager.skill_remove_plan(&scope, project.map(PathBuf::from))
    })
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
    tauri::async_runtime::spawn_blocking(move || {
        manager.skill_remove(&scope, project.map(PathBuf::from), confirmed)
    })
    .await
    .map_err(|_| "Skill removal worker failed".into())
}

/// Successor tickets add their own modules and typed commands here; no generic execution bridge.
pub fn run() {
    let mut environment = RuntimeEnvironment::system();
    environment.user_path = environment.machine_paths();
    let path_store: Arc<dyn crate::user_path::PathStore> =
        Arc::new(crate::user_path::NativePathStore::current_user());
    #[cfg(feature = "install-test-boundary")]
    let path_store = if environment
        .variables
        .get("MULTI_SEARCH_TEST_ISOLATION")
        .map(String::as_str)
        == Some("1")
    {
        // Compile-time-only acceptance boundary. Never present in the distributed build.
        let key = environment
            .variables
            .get("MULTI_SEARCH_ACCEPTANCE_PATH_KEY")
            .expect("isolated PATH key required");
        environment.user_path.clear();
        Arc::new(
            crate::user_path::NativePathStore::isolated_key(key)
                .expect("invalid isolated PATH key"),
        ) as Arc<dyn crate::user_path::PathStore>
    } else {
        path_store
    };
    let manager = DesktopManager::with_user_path_store(environment, path_store);
    tauri::Builder::default()
        .manage(Arc::new(manager))
        .setup(|app| {
            let bundled = app
                .path()
                .resource_dir()
                .ok()
                .map(|dir| dir.join("cli-bundle"));
            app.manage(BundledCli(bundled));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            cookie_status,
            cookie_import,
            cookie_delete,
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
            credential_read,
            credential_reveal,
            credential_application_open,
            credential_save,
            credential_delete,
            credential_test,
            credential_append,
            credential_remove,
            settings_view,
            settings_save,
            scrape_settings_save,
            provider_list,
            scrape_memory_view,
            scrape_memory_pin,
            scrape_memory_reset
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
