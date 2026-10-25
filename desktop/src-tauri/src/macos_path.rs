//! macOS persistent user PATH registration.
//!
//! There is no registry on macOS: a durable user PATH lives in the user's
//! login-shell profile. This module implements [`PathStore`] over one clearly
//! marked block appended to `.zprofile` (zsh, the default login shell) or
//! `.bash_profile` (bash). POSIX semantics apply throughout: `:` delimiters,
//! case-sensitive absolute paths, no `%VAR%` expansion.
//!
//! Safety contract:
//! * The managed block is the only text this tool owns. Add appends it;
//!   remove deletes exactly the recorded block, and only when the full
//!   expected profile bytes and the ownership receipt still match.
//! * The receipt lives in `~/.multi-search/path-ownership.json`, outside the
//!   managed CLI root, so it survives uninstallation of the CLI itself.
//! * The profile and the receipt must be regular files. Existing symlinks —
//!   and any symlinked component below the home directory — fail closed. The
//!   standard macOS ancestors above the home directory (`/var -> /private/var`)
//!   are allowed; a profile that does not exist yet is created only on a
//!   confirmed add.
//! * Re-read immediately before writing (CAS): a changed file is refused,
//!   never blindly overwritten. Writes are atomic same-directory renames after
//!   `fsync`, under an exclusive `flock` so a concurrent desktop process
//!   cannot interleave.
//! * The PATH line is emitted single-quoted with the `'\''` idiom, so spaces,
//!   `$`, backticks and quotes cannot inject shell code.

use crate::user_path::{PathReceipt, PathStore, PathValue};
use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::OpenOptionsExt,
    path::{Path, PathBuf},
    sync::Mutex,
};

const BLOCK_BEGIN: &str = "# >>> MultiSearch CLI PATH >>>";
const BLOCK_END: &str = "# <<< MultiSearch CLI PATH <<<";
const RECEIPT_NAME: &str = "path-ownership.json";
const LOCK_NAME: &str = "path-ownership.lock";

/// One managed block inside a profile: its exact bytes and where it starts.
#[derive(Clone, PartialEq, serde::Serialize, serde::Deserialize)]
struct ManagedBlock {
    bytes: String,
    begin_offset: u64,
}

/// macOS receipt envelope: which profile the block lives in, the block itself,
/// and the platform-neutral receipt (`before`/`after` are the *PATH value*
/// states, `entry` the managed bin directory).
#[derive(Clone, PartialEq, serde::Serialize, serde::Deserialize)]
struct MacReceipt {
    profile: PathBuf,
    block: ManagedBlock,
    receipt: PathReceipt,
}

/// Persistent store over one login-shell profile. `home` and `profile` are
/// resolved at construction so an instance is bound to a single target file.
pub struct MacOsPathStore {
    home: PathBuf,
    profile: PathBuf,
    lock: Mutex<()>,
}

impl MacOsPathStore {
    /// Production constructor bound to the real environment.
    pub fn current_user() -> Result<Self, String> {
        let variables: BTreeMap<String, String> = std::env::vars().collect();
        Self::for_environment(&variables)
    }

    /// Constructor from an explicit environment (tests supply a disposable
    /// HOME). Profile selection:
    ///   1. `MULTI_SEARCH_SHELL_PROFILE` = `zsh` | `bash` (explicit override),
    ///   2. otherwise the basename of `SHELL` must be `zsh` or `bash`,
    ///   3. anything else (fish, tcsh, missing SHELL, unsupported override)
    ///      is an error rather than a silently wrong profile.
    /// `ZDOTDIR` is honoured only when it is an absolute path inside the home
    /// directory; anything else is rejected instead of writing to an arbitrary
    /// or wrong location.
    pub fn for_environment(variables: &BTreeMap<String, String>) -> Result<Self, String> {
        let home = variables
            .get("HOME")
            .filter(|value| !value.is_empty() && Path::new(value).is_absolute())
            .map(PathBuf::from)
            .ok_or("无法确定用户主目录（HOME 缺失或不是绝对路径）")?;
        let shell = variables
            .get("MULTI_SEARCH_SHELL_PROFILE")
            .cloned()
            .or_else(|| {
                variables
                    .get("SHELL")
                    .and_then(|value| value.rsplit('/').next().map(str::to_string))
            })
            .ok_or("无法确定登录 Shell（SHELL 未设置）")?;
        let profile = match shell.as_str() {
            "zsh" => match variables.get("ZDOTDIR") {
                Some(dir) => {
                    let dir = PathBuf::from(dir);
                    if !dir.is_absolute() {
                        return Err("ZDOTDIR 不是绝对路径，不支持，未修改".into());
                    }
                    // Only a ZDOTDIR inside the user's own home is honoured;
                    // anything else could point at another account's config.
                    if !dir.starts_with(&home) {
                        return Err("ZDOTDIR 位于主目录之外，不支持，未修改".into());
                    }
                    dir.join(".zprofile")
                }
                None => home.join(".zprofile"),
            },
            "bash" => home.join(".bash_profile"),
            other => {
                return Err(format!(
                    "暂不支持 {other} 的 PATH 注册（目前支持 zsh 与 bash），未修改"
                ))
            }
        };
        Ok(Self {
            home,
            profile,
            lock: Mutex::new(()),
        })
    }

    /// The profile path this store is bound to.
    #[allow(dead_code)]
    pub fn profile_path(&self) -> &Path {
        &self.profile
    }

    fn receipt_path(&self) -> PathBuf {
        self.home.join(".multi-search").join(RECEIPT_NAME)
    }

    fn lock_path(&self) -> PathBuf {
        self.home.join(".multi-search").join(LOCK_NAME)
    }

    /// Fail closed when `path` itself or any component below `base` is a
    /// symlink. Components at or above `base` are allowed: the standard macOS
    /// `/var -> /private/var` system links are not tool-owned.
    fn no_links_below(&self, base: &Path, path: &Path) -> Result<(), String> {
        let relative = path
            .strip_prefix(base)
            .map_err(|_| "PATH 注册路径不在主目录内，未修改".to_string())?;
        let mut cursor = base.to_path_buf();
        for component in relative.components() {
            cursor.push(component.as_os_str());
            match fs::symlink_metadata(&cursor) {
                Ok(meta) if meta.file_type().is_symlink() => {
                    return Err(format!(
                        "PATH 注册路径包含符号链接（{}），已拒绝",
                        cursor.display()
                    ));
                }
                Ok(_) => {}
                // Missing components are allowed: a confirmed add may create
                // them; every later access re-checks what actually exists.
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(_) => {
                    return Err(format!("无法检查 {} 的文件类型，已拒绝", cursor.display()));
                }
            }
        }
        Ok(())
    }

    /// Raw profile bytes as a `PathValue` (internal form used by CAS).
    /// A missing file is `exists: false` with empty text; a symlink or
    /// non-regular file fails closed.
    fn read_profile(&self) -> Result<PathValue, String> {
        self.no_links_below(&self.home, &self.profile)?;
        let meta = match fs::symlink_metadata(&self.profile) {
            Ok(meta) => meta,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(PathValue {
                    text: String::new(),
                    kind: 0,
                    exists: false,
                });
            }
            Err(_) => return Err("无法读取登录配置文件，未修改".into()),
        };
        if !meta.is_file() {
            return Err("登录配置文件不是普通文件（可能是符号链接或目录），已拒绝".into());
        }
        let bytes = fs::read(&self.profile).map_err(|_| "无法读取登录配置文件，未修改")?;
        let text = String::from_utf8(bytes).map_err(|_| "登录配置文件不是有效 UTF-8，已拒绝")?;
        Ok(PathValue {
            text,
            kind: 0,
            exists: true,
        })
    }

    fn read_receipt(&self) -> Result<Option<MacReceipt>, String> {
        let path = self.receipt_path();
        self.no_links_below(&self.home, &path)?;
        let meta = match fs::symlink_metadata(&path) {
            Ok(meta) => meta,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err("无法读取 PATH 所有权记录，未修改".into()),
        };
        if meta.file_type().is_symlink() || !meta.is_file() {
            return Err("PATH 所有权记录不是普通文件，已拒绝".into());
        }
        let bytes = fs::read(&path).map_err(|_| "无法读取 PATH 所有权记录，未修改")?;
        serde_json::from_slice(&bytes)
            .map(Some)
            .map_err(|_| "PATH 所有权记录不可验证，未修改".into())
    }

    /// The marked block as literal bytes: begin marker, quoted export line,
    /// end marker, trailing newline.
    fn block_bytes(directory: &str) -> String {
        format!(
            "{BLOCK_BEGIN}\nexport PATH={}:\"$PATH\"\n{BLOCK_END}\n",
            shell_quote(directory)
        )
    }

    /// Locate the owned block inside `text`. Returns `None` when the block is
    /// absent, appears more than once, or its end marker no longer ends a
    /// line (hand-edited).
    fn find_block(text: &str) -> Option<ManagedBlock> {
        let begin = text.find(BLOCK_BEGIN)?;
        // A second begin marker means ambiguous ownership; never edit.
        if text[begin + BLOCK_BEGIN.len()..].contains(BLOCK_BEGIN) {
            return None;
        }
        let end_rel = text[begin..].find(BLOCK_END)?;
        let end = begin + end_rel + BLOCK_END.len();
        if !(end == text.len() || text[end..].starts_with('\n')) {
            return None;
        }
        Some(ManagedBlock {
            bytes: format!("{}\n", &text[begin..end]),
            begin_offset: begin as u64,
        })
    }

    /// The managed bin directory recorded in an existing block, recovered by
    /// stripping the `export PATH=` wrapper and unquoting.
    fn block_directory(block: &ManagedBlock) -> Option<String> {
        block.bytes.lines().find_map(|line| {
            line.strip_prefix("export PATH=")
                .and_then(|rest| rest.strip_suffix(":\"$PATH\""))
                .map(unquote)
        })
    }

    /// Atomic same-directory write: temp file + fsync + rename. The target
    /// (when it exists) must remain a regular file — never a symlink swapped
    /// in after our earlier checks. Parent directories are created only when
    /// `create_parent` (the confirmed-add path) allows it.
    fn atomic_write(&self, path: &Path, bytes: &[u8], create_parent: bool) -> Result<(), String> {
        let parent = path.parent().ok_or("PATH 注册路径无父目录")?;
        if create_parent {
            fs::create_dir_all(parent).map_err(|_| "无法创建 PATH 注册目录")?;
        } else if !parent.is_dir() {
            return Err("PATH 注册目录不存在，未修改".into());
        }
        self.no_links_below(&self.home, path)?;
        let temp = parent.join(format!(".path-write.{}.tmp", std::process::id()));
        let result = (|| -> Result<(), String> {
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&temp)
                .map_err(|_| "无法创建 PATH 临时文件")?;
            use std::io::Write;
            file.write_all(bytes)
                .and_then(|()| file.sync_all())
                .map_err(|_| "无法写入 PATH 临时文件")?;
            if let Ok(meta) = fs::symlink_metadata(path) {
                if !meta.is_file() {
                    return Err("PATH 注册目标不是普通文件，已拒绝".into());
                }
            }
            fs::rename(&temp, path).map_err(|_| "无法保存 PATH 配置，未修改")?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temp);
        }
        result
    }

    fn write_receipt(&self, receipt: Option<&MacReceipt>) -> Result<(), String> {
        let path = self.receipt_path();
        match receipt {
            Some(receipt) => {
                let bytes =
                    serde_json::to_vec(receipt).map_err(|_| "PATH 所有权记录编码失败")?;
                self.atomic_write(&path, &bytes, true)
            }
            None => match fs::symlink_metadata(&path) {
                Ok(meta) if meta.is_file() => {
                    fs::remove_file(&path).map_err(|_| "无法清除 PATH 所有权记录".to_string())
                }
                Ok(_) => Err("PATH 所有权记录不是普通文件，已拒绝".into()),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Err(_) => Err("无法读取 PATH 所有权记录，未修改".into()),
            },
        }
    }
}

impl PathStore for MacOsPathStore {
    /// The user-PATH *value* this registration contributes: the managed bin
    /// directory when the owned block is present, empty otherwise. Discovery
    /// splits `text` on `:`. `exists` reports whether the profile file itself
    /// exists, so callers can distinguish "no registration" from "no file".
    fn read(&self) -> Result<PathValue, String> {
        let profile = self.read_profile()?;
        let directory = Self::find_block(&profile.text)
            .and_then(|block| Self::block_directory(&block))
            .unwrap_or_default();
        Ok(PathValue {
            text: directory,
            kind: 0,
            exists: profile.exists,
        })
    }

    fn receipt(&self) -> Result<Option<PathReceipt>, String> {
        Ok(self.read_receipt()?.map(|record| record.receipt))
    }

    fn compare_write(
        &self,
        expected: &PathValue,
        desired: &PathValue,
        receipt: Option<&PathReceipt>,
    ) -> Result<(), String> {
        let _in_process = self.lock.lock().map_err(|_| "PATH 操作锁不可用")?;
        // Exclusive cross-process advisory lock: another desktop instance
        // cannot interleave its own read-modify-write between our read and
        // rename. The ownership directory is created here (a state mutation
        // only on the confirmed-change path).
        let lock_path = self.lock_path();
        if let Some(parent) = lock_path.parent() {
            fs::create_dir_all(parent).map_err(|_| "无法创建 PATH 所有权目录")?;
        }
        let lock_file = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .open(&lock_path)
            .map_err(|_| "无法打开 PATH 操作锁文件")?;
        unsafe {
            if libc_flock(std::os::unix::io::AsRawFd::as_raw_fd(&lock_file), LOCK_EX) != 0 {
                return Err("无法锁定 PATH 操作".into());
            }
        }
        // `lock_file` closing on drop releases the flock.

        match receipt {
            // ---- add ----------------------------------------------------
            Some(receipt) => {
                // The domain always prepends `entry`; the recorded receipt
                // must describe exactly this request.
                let expected_head = format!("{}:", receipt.entry);
                if !(desired.text == receipt.entry || desired.text.starts_with(&expected_head))
                    || receipt.after.text != desired.text
                {
                    return Err("PATH 所有权记录与请求不一致，未修改".into());
                }
                let profile = self.read_profile()?;
                // The add base must be exactly what `expected` describes:
                // `expected.text` is the managed-entry view (empty unless a
                // block already exists), so recompute it from the profile.
                let current_entry = Self::find_block(&profile.text)
                    .and_then(|block| Self::block_directory(&block))
                    .unwrap_or_default();
                if current_entry != expected.text || profile.exists != expected.exists {
                    return Err("用户 PATH 配置文件已改变，请重新检查后重试".into());
                }
                if Self::find_block(&profile.text).is_some() {
                    return Err("PATH 配置块已存在，保留现状".into());
                }
                let mut text = profile.text.clone();
                if !text.is_empty() && !text.ends_with('\n') {
                    text.push('\n');
                }
                let begin = text.len() as u64;
                let block = ManagedBlock {
                    bytes: Self::block_bytes(&receipt.entry),
                    begin_offset: begin,
                };
                text.push_str(&block.bytes);
                let new_profile = PathValue {
                    text: text.clone(),
                    kind: 0,
                    exists: true,
                };
                let record = MacReceipt {
                    profile: self.profile.clone(),
                    block,
                    receipt: PathReceipt {
                        after: PathValue {
                            text: receipt.entry.clone(),
                            kind: 0,
                            exists: true,
                        },
                        ..receipt.clone()
                    },
                };
                self.atomic_write(&self.profile, new_profile.text.as_bytes(), true)?;
                if let Err(error) = self.write_receipt(Some(&record)) {
                    // Best-effort rollback of the block so a failed receipt
                    // write cannot leave an unverifiable registration behind.
                    let _ = self.atomic_write(&self.profile, profile.text.as_bytes(), false);
                    return Err(error);
                }
                Ok(())
            }
            // ---- remove ---------------------------------------------------
            None => {
                let record = self
                    .read_receipt()?
                    .ok_or("没有本工具添加 PATH 的记录，未修改")?;
                let profile = self.read_profile()?;
                // The recorded after-value must match the current view and the
                // block must still sit at its recorded offset byte-for-byte.
                let current_entry = Self::find_block(&profile.text)
                    .and_then(|block| Self::block_directory(&block))
                    .unwrap_or_default();
                if record.receipt.after.text != current_entry
                    || record.receipt.before.text != desired.text
                    || current_entry != expected.text
                {
                    return Err("用户 PATH 或所有权记录已改变，保留现状".into());
                }
                let start = record.block.begin_offset as usize;
                let end = start + record.block.bytes.len();
                if profile.text.len() < end
                    || profile.text[start..end] != record.block.bytes
                {
                    return Err("PATH 配置块已改变，保留现状".into());
                }
                let mut text = String::with_capacity(profile.text.len());
                text.push_str(&profile.text[..start]);
                text.push_str(&profile.text[end..]);
                self.atomic_write(&self.profile, text.as_bytes(), false)?;
                self.write_receipt(None)?;
                Ok(())
            }
        }
    }
}

const LOCK_EX: i32 = 2;
extern "C" {
    fn flock(fd: i32, operation: i32) -> i32;
}
unsafe fn libc_flock(fd: i32, operation: i32) -> i32 {
    unsafe { flock(fd, operation) }
}

/// Shell-safe single-quoted literal: `'` becomes `'\''` so spaces, `$`,
/// backticks, quotes and newlines cannot break out or inject commands.
fn shell_quote(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    out.push('\'');
    for ch in value.chars() {
        if ch == '\'' {
            out.push_str("'\\''");
        } else {
            out.push(ch);
        }
    }
    out.push('\'');
    out
}

/// Inverse of `shell_quote` for the single-quote idiom this module emits.
/// Malformed input (no surrounding quotes) yields an empty string rather
/// than a guessed path.
fn unquote(quoted: &str) -> String {
    let Some(inner) = quoted
        .strip_prefix('\'')
        .and_then(|s| s.strip_suffix('\''))
    else {
        return String::new();
    };
    inner.replace("'\\''", "'")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::user_path::{PathReceipt, PathValue};
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct Home(PathBuf);
    impl Home {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "macos-path-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir_all(&root).unwrap();
            Self(root)
        }
        fn env(&self, shell: &str) -> BTreeMap<String, String> {
            BTreeMap::from([
                ("HOME".into(), self.0.to_string_lossy().into_owned()),
                ("SHELL".into(), format!("/bin/{shell}")),
            ])
        }
        fn path(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }
    }
    impl Drop for Home {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn store(home: &Home, shell: &str) -> MacOsPathStore {
        MacOsPathStore::for_environment(&home.env(shell)).unwrap()
    }

    /// Drive one add through the store exactly as `UserPathManager::change`
    /// does: empty current value, desired = entry (+ prior text), receipt.
    fn add(store: &MacOsPathStore, dir: &str) {
        let current = store.read().unwrap();
        let desired = PathValue {
            text: dir.to_string(),
            kind: 0,
            exists: true,
        };
        let receipt = PathReceipt::new(&current, &desired, dir);
        store.compare_write(&current, &desired, Some(&receipt)).unwrap();
    }

    fn remove(store: &MacOsPathStore) {
        let current = store.read().unwrap();
        let before = store.receipt().unwrap().unwrap().before;
        store.compare_write(&current, &before, None).unwrap();
    }

    #[test]
    fn unsupported_shell_is_rejected_without_touching_any_profile() {
        let home = Home::new();
        let mut env = home.env("zsh");
        env.insert("SHELL".into(), "/opt/homebrew/bin/fish".into());
        assert!(MacOsPathStore::for_environment(&env).is_err());
        let mut env = home.env("zsh");
        env.insert("MULTI_SEARCH_SHELL_PROFILE".into(), "fish".into());
        assert!(MacOsPathStore::for_environment(&env).is_err());
        assert!(!home.path(".zprofile").exists());
        assert!(!home.path(".bash_profile").exists());
        assert!(!home.path(".multi-search").exists());
    }

    #[test]
    fn zdotdir_is_honoured_only_inside_home() {
        let home = Home::new();
        let outside = Home::new();
        let mut env = home.env("zsh");
        env.insert("ZDOTDIR".into(), outside.0.to_string_lossy().into_owned());
        assert!(MacOsPathStore::for_environment(&env).is_err());
        let mut env = home.env("zsh");
        env.insert("ZDOTDIR".into(), "relative/dir".into());
        assert!(MacOsPathStore::for_environment(&env).is_err());
        // Inside home: honoured.
        let zdotdir = home.path("zdot");
        let mut env = home.env("zsh");
        env.insert("ZDOTDIR".into(), zdotdir.to_string_lossy().into_owned());
        let store = MacOsPathStore::for_environment(&env).unwrap();
        assert_eq!(store.profile_path(), zdotdir.join(".zprofile"));
    }

    #[test]
    fn add_appends_marked_block_and_remove_restores_exact_bytes() {
        let home = Home::new();
        let store = store(&home, "zsh");
        let profile = home.path(".zprofile");
        std::fs::write(&profile, "export EDITOR=vim\nexport PATH=/opt/bin:$PATH\n").unwrap();
        let before_bytes = std::fs::read_to_string(&profile).unwrap();
        let dir = home
            .0
            .join("Library/Application Support/MultiSearch/cli/bin")
            .to_string_lossy()
            .into_owned();
        add(&store, &dir);
        let text = std::fs::read_to_string(&profile).unwrap();
        assert!(text.starts_with(&before_bytes));
        assert!(text.contains(BLOCK_BEGIN));
        assert!(text.contains(&format!("export PATH='{}':\"$PATH\"", dir)));
        assert!(store.receipt().unwrap().is_some());
        // A second add refuses rather than duplicating the block.
        let current = store.read().unwrap();
        let desired = PathValue { text: dir.clone(), kind: 0, exists: true };
        let receipt = PathReceipt::new(&current, &desired, &dir);
        assert!(store.compare_write(&current, &desired, Some(&receipt)).is_err());
        remove(&store);
        assert_eq!(std::fs::read_to_string(&profile).unwrap(), before_bytes);
        assert!(store.receipt().unwrap().is_none());
    }

    #[test]
    fn add_to_missing_profile_creates_it_only_on_write() {
        let home = Home::new();
        let store = store(&home, "bash");
        // Planning reads must not create anything.
        assert_eq!(store.read().unwrap().text, "");
        assert!(!home.path(".bash_profile").exists());
        assert!(!home.path(".multi-search").exists());
        add(&store, "/opt/managed/bin");
        let text = std::fs::read_to_string(home.path(".bash_profile")).unwrap();
        assert!(text.contains(BLOCK_BEGIN));
        remove(&store);
        assert_eq!(std::fs::read_to_string(home.path(".bash_profile")).unwrap(), "");
    }

    #[test]
    fn symlinked_profile_and_symlinked_components_fail_closed() {
        let home = Home::new();
        let outside = Home::new();
        let target = outside.path("elsewhere");
        std::fs::write(&target, "export EDITOR=vim\n").unwrap();
        std::os::unix::fs::symlink(&target, home.path(".zprofile")).unwrap();
        let store = store(&home, "zsh");
        assert!(store.read().is_err());
        let current = PathValue { text: String::new(), kind: 0, exists: false };
        let desired = PathValue { text: "/x/bin".into(), kind: 0, exists: true };
        let receipt = PathReceipt::new(&current, &desired, "/x/bin");
        assert!(store.compare_write(&current, &desired, Some(&receipt)).is_err());
        assert_eq!(std::fs::read_to_string(&target).unwrap(), "export EDITOR=vim\n");

        // Symlinked *component* below home also fails.
        let home2 = Home::new();
        std::os::unix::fs::symlink(&outside.0, home2.path("linked-dir")).unwrap();
        let mut env = home2.env("zsh");
        env.insert("ZDOTDIR".into(), home2.path("linked-dir").to_string_lossy().into_owned());
        let store = MacOsPathStore::for_environment(&env).unwrap();
        assert!(store.read().is_err());
    }

    #[test]
    fn changed_profile_or_receipt_is_refused_not_overwritten() {
        let home = Home::new();
        let store = store(&home, "zsh");
        let profile = home.path(".zprofile");
        add(&store, "/opt/managed/bin");
        // User edits the file afterwards: removal must refuse and preserve.
        std::fs::write(&profile, "export EDITOR=vim\n# user edit\n").unwrap();
        let current = store.read().unwrap();
        let before = PathValue { text: String::new(), kind: 0, exists: true };
        assert!(store.compare_write(&current, &before, None).is_err());
        assert_eq!(
            std::fs::read_to_string(&profile).unwrap(),
            "export EDITOR=vim\n# user edit\n"
        );
        // Tampered/unverifiable receipt fails closed too.
        std::fs::write(home.path(".multi-search/path-ownership.json"), "garbage").unwrap();
        assert!(store.receipt().is_err());
    }

    #[test]
    fn shell_quoting_blocks_injection() {
        assert_eq!(shell_quote("/Users/a b/cli bin"), "'/Users/a b/cli bin'");
        assert_eq!(shell_quote("/Users/$HOME/`id`/x"), "'/Users/$HOME/`id`/x'");
        assert_eq!(shell_quote("/Users/o'neil/bin"), "'/Users/o'\\''neil/bin'");
        assert_eq!(unquote(&shell_quote("/Users/o'neil/$x/`id`")), "/Users/o'neil/$x/`id`");
        assert_eq!(unquote("not-quoted"), "");
    }

    #[test]
    fn receipt_survives_a_fresh_store_instance() {
        let home = Home::new();
        add(&store(&home, "bash"), "/opt/managed/bin");
        // Simulate app restart: a brand-new store over the same home reads
        // the same registration and receipt.
        let reopened = store(&home, "bash");
        assert_eq!(reopened.read().unwrap().text, "/opt/managed/bin");
        let receipt = reopened.receipt().unwrap().unwrap();
        assert_eq!(receipt.entry, "/opt/managed/bin");
        remove(&reopened);
        assert_eq!(store(&home, "bash").read().unwrap().text, "");
    }

    #[test]
    fn non_utf8_profile_fails_closed() {
        let home = Home::new();
        std::fs::write(home.path(".zprofile"), b"\xff\xfe\x00").unwrap();
        let store = store(&home, "zsh");
        assert!(store.read().is_err());
    }
}
