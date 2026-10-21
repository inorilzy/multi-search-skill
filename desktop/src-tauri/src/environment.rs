use crate::windows_util;
use crate::RuntimeEnvironment;
use std::collections::BTreeMap;
use std::path::PathBuf;

/// `%VAR%` expansion now lives in `windows_util`; kept as a forwarding alias
/// for callers that already import it from here.
pub(crate) fn expand(value: &str, variables: &BTreeMap<String, String>) -> String {
    windows_util::expand(value, variables)
}

impl RuntimeEnvironment {
    /// Base search path for a manager with a live user registry store.
    #[cfg(all(windows, feature = "native-window"))]
    pub(crate) fn machine_paths(&self) -> Vec<PathBuf> {
        use windows_sys::Win32::System::Registry::HKEY_LOCAL_MACHINE;
        let value = windows_util::registry_string(
            HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
            "Path",
        )
        .unwrap_or_default();
        std::env::split_paths(&windows_util::expand(
            &value,
            &self.variables,
        ))
        .collect()
    }
    pub fn system() -> Self {
        let mut variables: BTreeMap<String, String> = std::env::vars().collect();
        let app_path = if let Some(path) = variables.get("PATH") {
            std::env::split_paths(path).collect()
        } else {
            std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).collect()
        };
        #[cfg(windows)]
        #[allow(unused_mut)]
        let mut user_path = {
            use windows_sys::Win32::System::Registry::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
            let machine = windows_util::registry_string(
                HKEY_LOCAL_MACHINE,
                "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
                "Path",
            )
            .unwrap_or_default();
            let user =
                windows_util::registry_string(HKEY_CURRENT_USER, "Environment", "Path")
                    .unwrap_or_default();
            std::env::split_paths(&windows_util::expand(
                &format!("{machine};{user}"),
                &variables,
            ))
            .collect()
        };
        #[cfg(not(windows))]
        let mut user_path = Vec::new();
        // An isolated acceptance launcher can set a separate disposable user PATH; no registry changes.
        #[cfg(feature = "install-test-boundary")]
        if variables
            .get("MULTI_SEARCH_TEST_ISOLATION")
            .map(String::as_str)
            == Some("1")
        {
            if let Some(value) = variables.get("MULTI_SEARCH_DESKTOP_TEST_USER_PATH") {
                user_path = std::env::split_paths(value).collect();
            }
        }
        variables.insert("PYTHONIOENCODING".into(), "utf-8".into());
        let cwd = variables
            .get("USERPROFILE")
            .map(PathBuf::from)
            .or_else(|| variables.get("HOME").map(PathBuf::from))
            .unwrap_or_else(std::env::temp_dir);
        Self {
            app_path,
            user_path,
            variables,
            cwd,
        }
    }
}
