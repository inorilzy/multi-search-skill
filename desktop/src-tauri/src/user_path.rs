//! Explicit, current-user-only PATH registration. No mutation occurs during installation.
use crate::DesktopManager;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, Mutex},
};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PathValue {
    pub text: String,
    pub kind: u32,
    pub exists: bool,
}
impl PathValue {
    pub fn expandable(text: &str) -> Self {
        Self {
            text: text.into(),
            kind: 2,
            exists: true,
        }
    }
}
#[derive(Clone, PartialEq, Serialize, Deserialize)]
pub struct PathReceipt {
    before: PathValue,
    after: PathValue,
    entry: String,
}
/// OS boundary: values retain their registry type and original spelling. Implementations must
/// re-read immediately before writing, and reject a changed value instead of clobbering it.
pub trait PathStore: Send + Sync {
    fn read(&self) -> Result<PathValue, String>;
    fn receipt(&self) -> Result<Option<PathReceipt>, String>;
    fn compare_write(
        &self,
        expected: &PathValue,
        desired: &PathValue,
        receipt: Option<&PathReceipt>,
    ) -> Result<(), String>;
}
pub struct MemoryPathStore {
    state: Mutex<(PathValue, Option<PathReceipt>)>,
}
impl MemoryPathStore {
    pub fn new(value: PathValue) -> Self {
        Self {
            state: Mutex::new((value, None)),
        }
    }
    pub fn value(&self) -> PathValue {
        self.read().unwrap()
    }
}
impl PathStore for MemoryPathStore {
    fn read(&self) -> Result<PathValue, String> {
        Ok(self.state.lock().unwrap().0.clone())
    }
    fn receipt(&self) -> Result<Option<PathReceipt>, String> {
        Ok(self.state.lock().unwrap().1.clone())
    }
    fn compare_write(
        &self,
        expected: &PathValue,
        desired: &PathValue,
        receipt: Option<&PathReceipt>,
    ) -> Result<(), String> {
        let mut state = self.state.lock().unwrap();
        if &state.0 != expected {
            return Err("用户 PATH 已改变，请重新检查后重试".into());
        }
        *state = (desired.clone(), receipt.cloned());
        Ok(())
    }
}
#[derive(Serialize)]
pub struct PathPlan {
    pub status: String,
    pub directory: String,
    pub reason: String,
    pub can_add: bool,
    pub can_remove: bool,
}
fn normalized(value: &str, variables: &BTreeMap<String, String>) -> String {
    crate::environment::expand(value.trim().trim_matches('"'), variables)
        .replace('/', "\\")
        .trim_end_matches('\\')
        .to_lowercase()
}
impl DesktopManager {
    /// Explicit dependency injection for isolated acceptance. Production uses the native registry.
    pub fn with_user_path_store(
        environment: crate::RuntimeEnvironment,
        store: Arc<dyn PathStore>,
    ) -> Self {
        let mut manager = Self::new(environment);
        manager.user_path_store = Some(store);
        manager
    }
    pub fn user_path_plan(&self) -> Result<PathPlan, String> {
        let store = self
            .user_path_store
            .as_ref()
            .ok_or("当前环境未连接用户 PATH 存储")?;
        let current = store.read()?;
        let receipt = store.receipt()?;
        let install = self.install_plan();
        let directory = PathBuf::from(&install.bin)
            .parent()
            .ok_or("安装目录不可用")?
            .to_string_lossy()
            .into_owned();
        let found = current.text.split(';').any(|p| {
            normalized(p, &self.environment.variables)
                == normalized(&directory, &self.environment.variables)
        });
        let owned = receipt
            .as_ref()
            .is_some_and(|r| r.after == current && r.entry == directory);
        Ok(PathPlan {
            status: if owned { "owned" } else if found { "existing" } else { "absent" }.into(),
            directory,
            reason: "仅修改当前用户 PATH；系统 PATH 不变。完成后重新检查，并重启终端或 Agent 宿主。原有或已修改的项目不会被认领或移除。".into(),
            can_add: !found && matches!(install.status.as_str(), "installed" | "update_available"),
            can_remove: owned,
        })
    }
    pub fn user_path_change(&self, remove: bool, confirmed: bool) -> Result<PathPlan, String> {
        let mut plan = self.user_path_plan()?;
        if !confirmed {
            plan.status = "confirmation_required".into();
            return Ok(plan);
        }
        let store = self.user_path_store.as_ref().ok_or("用户 PATH 不可用")?;
        let current = store.read()?;
        if remove {
            let receipt = store
                .receipt()?
                .ok_or("没有本工具添加 PATH 的记录，未修改")?;
            if receipt.after != current || receipt.entry != plan.directory {
                return Err("用户 PATH 或所有权记录已改变，保留现状".into());
            }
            store.compare_write(&current, &receipt.before, None)?;
            plan.status = "removed".into();
        } else {
            if current.text.split(';').any(|p| {
                normalized(p, &self.environment.variables)
                    == normalized(&plan.directory, &self.environment.variables)
            }) {
                plan.status = "existing".into();
                return Ok(plan);
            }
            if !plan.can_add {
                return Err("请先安装并验证受管 CLI".into());
            }
            // Prepend: the managed directory must come first in the user PATH so a same-named
            // `multi-search.exe` in a later user entry cannot shadow the verified install.
            let mut desired = current.clone();
            desired.text = if current.text.is_empty() {
                plan.directory.clone()
            } else {
                format!("{};{}", plan.directory, current.text)
            };
            desired.exists = true;
            let receipt = PathReceipt {
                before: current.clone(),
                after: desired.clone(),
                entry: plan.directory.clone(),
            };
            store.compare_write(&current, &desired, Some(&receipt))?;
            plan.status = "added".into();
        }
        Ok(plan)
    }
    pub(crate) fn current_user_paths(&self) -> Vec<PathBuf> {
        let Some(store) = self.user_path_store.as_ref() else {
            return self.environment.user_path.clone();
        };
        let Ok(value) = store.read() else {
            return Vec::new();
        };
        let mut paths = self.environment.user_path.clone();
        // The production base is the machine PATH, not a stale snapshot of the user's PATH.
        paths.extend(std::env::split_paths(&crate::environment::expand(
            &value.text,
            &self.environment.variables,
        )));
        paths
    }
}

#[cfg(windows)]
pub struct NativePathStore {
    subkey: String,
    lock: Mutex<()>,
}
#[cfg(windows)]
impl NativePathStore {
    pub fn current_user() -> Self {
        Self {
            subkey: "Environment".into(),
            lock: Mutex::new(()),
        }
    }
    /// A dedicated test key, never the developer's Environment key.
    #[cfg(feature = "install-test-boundary")]
    pub fn isolated_key(subkey: &str) -> Result<Self, String> {
        if !subkey.starts_with("Software\\MultiSearchAcceptance\\") || subkey.contains("..") {
            return Err("隔离注册表键无效".into());
        }
        Ok(Self {
            subkey: subkey.into(),
            lock: Mutex::new(()),
        })
    }
    fn get(&self, name: &str) -> Result<Option<(u32, Vec<u8>)>, String> {
        use windows_sys::Win32::System::Registry::*;
        let key: Vec<u16> = self.subkey.encode_utf16().chain(Some(0)).collect();
        let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
        let (mut kind, mut length) = (0, 0);
        unsafe {
            let result = RegGetValueW(
                HKEY_CURRENT_USER,
                key.as_ptr(),
                name.as_ptr(),
                RRF_RT_ANY | RRF_NOEXPAND,
                &mut kind,
                std::ptr::null_mut(),
                &mut length,
            );
            if result == 2 {
                return Ok(None);
            }
            if result != 0 {
                return Err(format!("读取用户 PATH 失败（{result}）"));
            }
            let mut bytes = vec![0u8; length as usize];
            let result = RegGetValueW(
                HKEY_CURRENT_USER,
                key.as_ptr(),
                name.as_ptr(),
                RRF_RT_ANY | RRF_NOEXPAND,
                &mut kind,
                bytes.as_mut_ptr().cast(),
                &mut length,
            );
            if result != 0 {
                return Err(format!("读取用户 PATH 失败（{result}）"));
            }
            bytes.truncate(length as usize);
            Ok(Some((kind, bytes)))
        }
    }
    fn set(&self, name: &str, value: Option<(u32, &str)>) -> Result<(), String> {
        use windows_sys::Win32::System::Registry::*;
        let key: Vec<u16> = self.subkey.encode_utf16().chain(Some(0)).collect();
        let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
        unsafe {
            let mut handle = std::ptr::null_mut();
            let result = RegCreateKeyExW(
                HKEY_CURRENT_USER,
                key.as_ptr(),
                0,
                std::ptr::null(),
                0,
                KEY_SET_VALUE,
                std::ptr::null(),
                &mut handle,
                std::ptr::null_mut(),
            );
            if result != 0 {
                return Err(format!("打开用户 PATH 失败（{result}）"));
            }
            let result = if let Some((kind, text)) = value {
                let data: Vec<u16> = text.encode_utf16().chain(Some(0)).collect();
                RegSetValueExW(
                    handle,
                    name.as_ptr(),
                    0,
                    kind,
                    data.as_ptr().cast(),
                    (data.len() * 2) as u32,
                )
            } else {
                RegDeleteValueW(handle, name.as_ptr())
            };
            RegCloseKey(handle);
            if result != 0 && !(value.is_none() && result == 2) {
                return Err(format!("保存用户 PATH 失败（{result}）；请重新检查"));
            }
            Ok(())
        }
    }
}
#[cfg(windows)]
fn decode(bytes: &[u8]) -> Result<String, String> {
    if !bytes.len().is_multiple_of(2) {
        return Err("注册表 PATH 格式不支持".into());
    }
    let mut words: Vec<u16> = bytes
        .chunks_exact(2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .collect();
    if words.last() == Some(&0) {
        words.pop();
    }
    let text = String::from_utf16(&words).map_err(|_| "注册表 PATH 不是有效文本")?;
    if text.contains('\0') {
        return Err("注册表 PATH 包含无效字符".into());
    }
    Ok(text)
}
#[cfg(windows)]
impl PathStore for NativePathStore {
    fn read(&self) -> Result<PathValue, String> {
        match self.get("Path")? {
            None => Ok(PathValue {
                text: String::new(),
                kind: 2,
                exists: false,
            }),
            Some((kind, bytes)) if kind == 1 || kind == 2 => Ok(PathValue {
                text: decode(&bytes)?,
                kind,
                exists: true,
            }),
            _ => Err("用户 PATH 注册表类型不支持，未修改".into()),
        }
    }
    fn receipt(&self) -> Result<Option<PathReceipt>, String> {
        self.get("MultiSearchPathOwnership")?
            .map(|(_, bytes)| {
                serde_json::from_str(&decode(&bytes)?)
                    .map_err(|_| "PATH 所有权记录不可验证，未修改".into())
            })
            .transpose()
    }
    fn compare_write(
        &self,
        expected: &PathValue,
        desired: &PathValue,
        receipt: Option<&PathReceipt>,
    ) -> Result<(), String> {
        let _guard = self.lock.lock().map_err(|_| "PATH 操作锁不可用")?;
        let previous_receipt = self.receipt()?;
        if &self.read()? != expected {
            return Err("用户 PATH 已改变，请重新检查后重试".into());
        }
        // Write ownership first. If the PATH write fails, the record alone cannot authorize removal:
        // its complete expected after-value must also match the current value.
        let encoded = receipt
            .map(serde_json::to_string)
            .transpose()
            .map_err(|_| "PATH 记录编码失败")?;
        self.set(
            "MultiSearchPathOwnership",
            encoded.as_deref().map(|s| (1, s)),
        )?;
        let result = if &self.read()? != expected {
            Err("用户 PATH 已改变，请重新检查后重试".into())
        } else {
            self.set(
                "Path",
                desired
                    .exists
                    .then_some((desired.kind, desired.text.as_str())),
            )
        };
        if result.is_err() {
            let old = previous_receipt
                .as_ref()
                .and_then(|r| serde_json::to_string(r).ok());
            let _ = self.set("MultiSearchPathOwnership", old.as_deref().map(|s| (1, s)));
        } else if self.subkey == "Environment" {
            // Notify Explorer so subsequently launched terminals inherit the updated user PATH.
            // Isolated acceptance keys never broadcast a global environment change.
            use windows_sys::Win32::UI::WindowsAndMessaging::{SendMessageTimeoutW, HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG};
            let name: Vec<u16> = "Environment".encode_utf16().chain(Some(0)).collect();
            let sent = unsafe { SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, name.as_ptr() as isize, SMTO_ABORTIFHUNG, 1000, std::ptr::null_mut()) };
            if sent == 0 { return Err("用户 PATH 已保存，但通知新进程失败；请重新登录或重启宿主后检查".into()); }
        }
        result
    }
}
