use crate::RuntimeEnvironment;
use std::{collections::BTreeMap, path::PathBuf};
#[cfg(windows)]
fn registry_string(
    root: windows_sys::Win32::System::Registry::HKEY,
    subkey: &str,
    name: &str,
) -> Option<String> {
    use windows_sys::Win32::System::Registry::{RegGetValueW, RRF_RT_REG_EXPAND_SZ, RRF_RT_REG_SZ};
    let sub: Vec<u16> = subkey.encode_utf16().chain(Some(0)).collect();
    let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    let mut bytes = 0;
    unsafe {
        if RegGetValueW(
            root,
            sub.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut bytes,
        ) != 0
        {
            return None;
        }
        let mut value = vec![0u16; bytes as usize / 2];
        if RegGetValueW(
            root,
            sub.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ,
            std::ptr::null_mut(),
            value.as_mut_ptr() as _,
            &mut bytes,
        ) != 0
        {
            return None;
        }
        while value.last() == Some(&0) {
            value.pop();
        }
        Some(String::from_utf16_lossy(&value))
    }
}
fn expand(value: &str, variables: &BTreeMap<String, String>) -> String {
    let mut output = value.to_string();
    for _ in 0..4 {
        let prior = output.clone();
        for (key, value) in variables {
            output = output
                .replace(&format!("%{key}%"), value)
                .replace(&format!("%{}%", key.to_uppercase()), value);
        }
        if output == prior {
            break;
        }
    }
    output
}
impl RuntimeEnvironment {
    pub fn system() -> Self {
        let mut variables: BTreeMap<String, String> = std::env::vars().collect();
        let app_path =
            std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).collect();
        #[cfg(windows)]
        #[allow(unused_mut)]
        let mut user_path = {
            use windows_sys::Win32::System::Registry::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
            let machine = registry_string(
                HKEY_LOCAL_MACHINE,
                "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
                "Path",
            )
            .unwrap_or_default();
            let user =
                registry_string(HKEY_CURRENT_USER, "Environment", "Path").unwrap_or_default();
            std::env::split_paths(&expand(&format!("{machine};{user}"), &variables)).collect()
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
