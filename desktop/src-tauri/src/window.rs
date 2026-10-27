use crate::errors::{backend, finish};
use crate::{
    CliStatus, DesktopManager, ExecutionStatus, RuntimeEnvironment, SearchOptions, SkillInstall,
    SkillPlan,
};
use std::{path::PathBuf, sync::Arc};
use tauri::Manager;

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
async fn cookie_status(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::cookie::CookieStatus, String> {
    let manager = manager.inner().clone();
    offload(move || crate::cookie::status(&manager.environment), "cookie_status_failed").await
}
#[tauri::command]
async fn cookie_import(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    path: String,
    confirmed: bool,
) -> Result<crate::cookie::CookieStatus, String> {
    let manager = manager.inner().clone();
    offload(
        move || crate::cookie::import(&manager.environment, std::path::Path::new(&path), confirmed),
        "cookie_import_failed",
    )
    .await
}
#[tauri::command]
async fn cookie_delete(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    confirmed: bool,
) -> Result<crate::cookie::CookieStatus, String> {
    let manager = manager.inner().clone();
    offload(move || crate::cookie::delete(&manager.environment, confirmed), "cookie_delete_failed")
        .await
}

#[tauri::command]
async fn detect_cli(manager: tauri::State<'_, Arc<DesktopManager>>) -> Result<CliStatus, String> {
    let manager = manager.inner().clone();
    offload_value(
        move || {
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
        },
        "cli_detect_failed",
    )
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
    offload_value(
        move || manager.skill_plan(&scope, project.map(PathBuf::from)),
        "skill_plan_failed",
    )
    .await
}
#[tauri::command]
async fn skill_install(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<SkillInstall, String> {
    let manager = manager.inner().clone();
    offload_value(
        move || manager.skill_install(&scope, project.map(PathBuf::from)),
        "skill_install_failed",
    )
    .await
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
async fn user_path_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::user_path::PathPlan, String> {
    let manager = manager.inner().clone();
    offload(move || manager.user_path_plan(), "user_path_check_failed").await
}
#[tauri::command]
async fn user_path_change(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    remove: bool,
    confirmed: bool,
) -> Result<crate::user_path::PathPlan, String> {
    let manager = manager.inner().clone();
    offload(
        move || manager.user_path_change(remove, confirmed),
        "user_path_change_failed",
    )
    .await
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
    offload_value(
        move || {
            // Core decides the effective source; the desktop only displays it.
            let key_sources = manager.key_sources();
            let mut overview = crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::overview(backend, &variables, &entry)
            });
            crate::credential_commands::apply_core_source(
                &mut overview,
                key_sources.get(entry.provider),
            );
            overview
        },
        "credential_status_failed",
    )
    .await
}
#[tauri::command]
async fn credential_read(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialValue, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    offload(
        move || {
            crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::read(backend, &variables, &entry)
            })
        },
        "credential_read_failed",
    )
    .await
}
#[tauri::command]
async fn credential_reveal(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::CredentialValue, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    offload(
        move || {
            crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::reveal(backend, &variables, &entry)
            })
        },
        "credential_read_failed",
    )
    .await
}
#[tauri::command]
async fn credential_application_open(source: String) -> Result<(), String> {
    offload(
        move || crate::credential_commands::open_application(&source),
        "credential_application_failed",
    )
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
    offload(
        move || {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);
            let mut overview = crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::save(backend, &variables, &entry, &key, now)
            })?;
            // Read Core after the write so the returned overview reflects the new state.
            let key_sources = manager.key_sources();
            crate::credential_commands::apply_core_source(
                &mut overview,
                key_sources.get(entry.provider),
            );
            Ok::<_, String>(overview)
        },
        "credential_save_failed",
    )
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
    offload(
        move || {
            let mut overview = crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::delete(backend, &variables, &entry)
            })?;
            // Read Core after the delete so the returned overview reflects the new state.
            let key_sources = manager.key_sources();
            crate::credential_commands::apply_core_source(
                &mut overview,
                key_sources.get(entry.provider),
            );
            Ok::<_, String>(overview)
        },
        "credential_delete_failed",
    )
    .await
}
#[tauri::command]
async fn credential_append(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    keys: Vec<String>,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    offload(
        move || {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);
            crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::append(backend, &variables, &entry, &keys, now)
            })
        },
        "credential_append_failed",
    )
    .await
}
#[tauri::command]
async fn credential_remove(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
    index: usize,
    expected: String,
) -> Result<crate::credential_commands::CredentialOverview, String> {
    let entry = finish(crate::credential_commands::resolve_source(&source))?;
    let variables = manager.inner().environment.variables.clone();
    offload(
        move || {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);
            crate::credential_commands::with_native(&variables, |backend| {
                crate::credential_commands::remove_row(
                    backend, &variables, &entry, index, &expected, now,
                )
            })
        },
        "credential_remove_failed",
    )
    .await
}
#[tauri::command]
async fn credential_test(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    source: String,
) -> Result<crate::credential_commands::TestOutcome, String> {
    let entry = finish(crate::credential_commands::resolve_test_source(&source))?;
    let manager = manager.inner().clone();
    offload(
        move || {
            let cli = manager.execution_cli()?;
            manager.test_source(cli, &entry, &format!("{} connectivity check", entry.source))
        },
        "credential_test_failed",
    )
    .await
}

// Legacy migration: the CLI (`migrate-legacy`) owns every rule and store access; the desktop
// only maps UI names, writes a name-only request file, and returns the masked result.
#[tauri::command]
async fn migration_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::credential_commands::MigrationPlan, String> {
    let manager = manager.inner().clone();
    offload(
        move || {
            let keys_file =
                crate::credential_commands::keys_file_path(&manager.environment.variables)
                    .ok_or_else(|| "无法定位旧 key 文件".to_string())?;
            let cli = manager.execution_cli()?;
            manager.migration_plan(cli, &keys_file)
        },
        "migration_plan_failed",
    )
    .await
}
#[tauri::command]
async fn migration_apply(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    plan_token: String,
    approved: Vec<String>,
    choices: std::collections::BTreeMap<String, String>,
) -> Result<crate::credential_commands::MigrationResult, String> {
    let request = finish(crate::credential_commands::migration_request(
        &plan_token,
        &approved,
        &choices,
    ))?;
    let manager = manager.inner().clone();
    offload(
        move || {
            let keys_file =
                crate::credential_commands::keys_file_path(&manager.environment.variables)
                    .ok_or_else(|| "无法定位旧 key 文件".to_string())?;
            let cli = manager.execution_cli()?;
            manager.migration_apply(cli, &keys_file, &request)
        },
        "migration_apply_failed",
    )
    .await
}

#[tauri::command]
async fn settings_view(
    manager: tauri::State<'_, Arc<DesktopManager>>,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    offload_value(move || crate::settings::view(&manager.environment), "settings_view_failed").await
}
#[tauri::command]
async fn settings_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    input: crate::settings::SettingsInput,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    offload(
        move || crate::settings::save(&manager.environment, &input),
        "settings_save_failed",
    )
    .await
}
#[tauri::command]
async fn scrape_settings_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    backends: Vec<String>,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    offload(
        move || crate::settings::save_scrape_backends(&manager.environment, &backends),
        "scrape_settings_save_failed",
    )
    .await
}

/// 写入或清空 `~/.search-keys.json` 的 System One 密钥；值从不进入设置数据库或返回值。
#[tauri::command]
async fn rerank_key_save(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    key: String,
) -> Result<crate::settings::SettingsView, String> {
    let manager = manager.inner().clone();
    offload(
        move || crate::settings::save_systemone_key(&manager.environment, &key),
        "rerank_key_save_failed",
    )
    .await
}

/// 只读站点抓取记忆；state.sqlite 缺失或损坏时返回 available=false 的视图。
#[tauri::command]
async fn scrape_memory_view(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    site: Option<String>,
) -> Result<crate::scrape_memory::ScrapeMemoryView, String> {
    let manager = manager.inner().clone();
    offload_value(
        move || crate::scrape_memory::view(&manager.environment, site.as_deref()),
        "scrape_memory_view_failed",
    )
    .await
}
#[tauri::command]
async fn scrape_memory_pin(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    site: String,
    scraper: String,
) -> Result<crate::scrape_memory::ScrapeMemoryView, String> {
    let manager = manager.inner().clone();
    offload(
        move || crate::scrape_memory::pin(&manager.environment, &site, &scraper),
        "scrape_memory_pin_failed",
    )
    .await
}
#[tauri::command]
async fn scrape_memory_reset(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    site: String,
) -> Result<crate::scrape_memory::ScrapeMemoryView, String> {
    let manager = manager.inner().clone();
    offload(
        move || crate::scrape_memory::reset(&manager.environment, Some(&site)),
        "scrape_memory_reset_failed",
    )
    .await
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
    offload(
        move || manager.skill_status(&scope, project.map(PathBuf::from)),
        "skill_status_failed",
    )
    .await
}
#[tauri::command]
async fn skill_update(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
    confirm_overwrite: bool,
) -> Result<crate::UpdateOutcome, String> {
    let manager = manager.inner().clone();
    offload_value(
        move || manager.skill_update(&scope, project.map(PathBuf::from), confirm_overwrite),
        "skill_update_failed",
    )
    .await
}
#[tauri::command]
async fn skill_remove_plan(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
) -> Result<crate::RemovePlan, String> {
    let manager = manager.inner().clone();
    offload(
        move || manager.skill_remove_plan(&scope, project.map(PathBuf::from)),
        "skill_remove_plan_failed",
    )
    .await
}
#[tauri::command]
async fn skill_remove(
    manager: tauri::State<'_, Arc<DesktopManager>>,
    scope: String,
    project: Option<String>,
    confirmed: bool,
) -> Result<crate::RemoveOutcome, String> {
    let manager = manager.inner().clone();
    offload_value(
        move || manager.skill_remove(&scope, project.map(PathBuf::from), confirmed),
        "skill_remove_failed",
    )
    .await
}

/// Successor tickets add their own modules and typed commands here; no generic execution bridge.
pub fn run() {
    let mut environment = RuntimeEnvironment::system();
    // Windows: the registry-backed machine PATH is the base and the user PATH lives in HKCU.
    #[cfg(windows)]
    let path_store: Arc<dyn crate::user_path::PathStore> = {
        environment.user_path = environment.machine_paths();
        Arc::new(crate::user_path::NativePathStore::current_user())
    };
    // macOS has no registry user PATH: registration is a marked block in the
    // user's login-shell profile (.zprofile/.bash_profile), bound to a
    // receipt under ~/.multi-search. The process PATH is the search base; the
    // store contributes only the managed directory once registered.
    #[cfg(target_os = "macos")]
    let path_store: Arc<dyn crate::user_path::PathStore> = {
        environment.user_path =
            std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).collect();
        match crate::macos_path::MacOsPathStore::current_user() {
            Ok(store) => Arc::new(store),
            Err(reason) => {
                eprintln!("user PATH store unavailable: {reason}");
                // A profile we cannot safely identify reports `unavailable`
                // instead of pretending a change is possible.
                Arc::new(crate::user_path::UnsupportedPathStore(reason))
            }
        }
    };
    // Other Unix platforms have no supported registration backend yet; report
    // unavailability truthfully rather than an in-memory fake.
    #[cfg(not(any(windows, target_os = "macos")))]
    let path_store: Arc<dyn crate::user_path::PathStore> = {
        environment.user_path =
            std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).collect();
        Arc::new(crate::user_path::UnsupportedPathStore(
            "当前平台不支持用户 PATH 注册".into(),
        ))
    };
    #[cfg(all(windows, feature = "install-test-boundary"))]
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
            migration_plan,
            migration_apply,
            settings_view,
            settings_save,
            scrape_settings_save,
            rerank_key_save,
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
