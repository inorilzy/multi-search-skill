//! Filesystem journal primitives for atomic install/update/uninstall.
//!
//! Every mutation is a sequence of journaled moves: callers record each name
//! after it is moved, so a failure can restore exactly what was moved and
//! nothing else. `install.rs` and its update path share these primitives —
//! there is no second staging/rollback implementation.
use crate::manifest::Failure;
use crate::windows_util;
use std::{
    fs,
    path::{Path, PathBuf},
};

pub(crate) const ACTIVE: &str = "active.json";

/// Lock and permission errors are reported as-is; no process is ever terminated to make progress.
pub(crate) fn replace_error(error: &std::io::Error) -> String {
    // Windows reports a file held by another program as sharing violation (32) or access denied (5),
    // which Rust does not always map to PermissionDenied.
    let locked = matches!(error.raw_os_error(), Some(5) | Some(32));
    if locked || error.kind() == std::io::ErrorKind::PermissionDenied {
        return "文件被占用或权限不足，未强制终止进程，请关闭使用该 CLI 的程序后重试".into();
    }
    format!("无法替换残留文件：{error}")
}

/// `name` is the manifest-relative path; the managed root and every path component
/// below it must be real directories. Ancestors above the root are machine layout:
/// macOS mounts `/var` and `/tmp` through symlinks, and a user's home may legitimately
/// be one too. Refusing those would make every managed install impossible there;
/// Windows keeps its stricter whole-path check because reparse points there are the
/// redirect threat this boundary exists for.
pub(crate) fn destination(root: &Path, name: &str) -> Result<PathBuf, Failure> {
    #[cfg(not(windows))]
    if let Ok(meta) = fs::symlink_metadata(root) {
        if windows_util::is_link(&meta) || !meta.is_dir() {
            return Err(("unknown_existing", "安装路径含链接或非目录，未修改".into()));
        }
    }
    #[cfg(windows)]
    for ancestor in root.ancestors() {
        if let Ok(meta) = fs::symlink_metadata(ancestor) {
            if windows_util::is_link(&meta) || !meta.is_dir() {
                return Err(("unknown_existing", "安装路径含链接或非目录，未修改".into()));
            }
        }
    }
    let mut path = root.to_path_buf();
    let parts: Vec<_> = name.split('/').collect();
    for (index, part) in parts.iter().enumerate() {
        path.push(part);
        match fs::symlink_metadata(&path) {
            Ok(meta)
                if windows_util::is_link(&meta)
                    || (index + 1 < parts.len() && !meta.is_dir()) =>
            {
                return Err((
                    "unknown_existing",
                    format!("目标路径含链接或非目录，未修改：{name}"),
                ))
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(("failed", replace_error(&error))),
        }
    }
    Ok(path)
}

pub(crate) fn move_file(from: &Path, to: &Path, name: &str) -> Result<(), Failure> {
    let source = crate::manifest::resolve(from, name)?;
    let target = destination(to, name)?;
    if fs::symlink_metadata(&target).is_ok() {
        return Err(("unknown_existing", format!("目标已有内容，未覆盖：{name}")));
    }
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent).map_err(|e| ("failed", replace_error(&e)))?;
    }
    if let Err(error) = fs::rename(source, target) {
        prune_empty_parents(to, &[name.to_string()]);
        return Err(("failed", replace_error(&error)));
    }
    Ok(())
}

pub(crate) fn prune_empty_parents(root: &Path, names: &[String]) {
    for name in names {
        let mut parent = root.join(name).parent().map(Path::to_path_buf);
        while let Some(path) = parent {
            if path == root {
                break;
            }
            if destination(
                root,
                &path.strip_prefix(root).unwrap().to_string_lossy().replace('\\', "/"),
            )
            .is_err()
            {
                break;
            }
            if fs::remove_dir(&path).is_err() {
                break;
            }
            parent = path.parent().map(Path::to_path_buf);
        }
    }
}

pub(crate) fn check_destinations(
    root: &Path,
    names: &[String],
    previous: &[String],
) -> Result<(), Failure> {
    for name in names {
        let target = destination(root, name)?;
        if fs::symlink_metadata(&target).is_ok()
            && !previous.iter().any(|p| p.eq_ignore_ascii_case(name))
        {
            return Err((
                "unknown_existing",
                format!("新版本路径与未知内容冲突，未修改：{name}"),
            ));
        }
    }
    Ok(())
}

/// Removes a residue inside an owned root. Links are removed as files, never followed.
pub(crate) fn remove_entry(path: &Path) -> Result<(), Failure> {
    let result = match fs::symlink_metadata(path) {
        Err(_) => Ok(()),
        Ok(meta) if meta.is_dir() && !windows_util::is_link(&meta) => fs::remove_dir_all(path),
        Ok(_) => fs::remove_file(path),
    };
    result.map_err(|e| ("failed", replace_error(&e)))
}

pub(crate) fn remove_owned_file(root: &Path, name: &str) -> Result<(), Failure> {
    let path = destination(root, name)?;
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(("failed", replace_error(&error))),
    }
}

/// Removes the manifest-owned entries all-or-nothing: each is first renamed into a holding
/// directory, and if any rename is refused (for example a file in use) the moved entries are
/// restored, so a locked file never leaves a half-removed install behind.
pub(crate) fn remove_owned_entries(root: &Path, names: &[String]) -> Result<(), Failure> {
    // Random, exclusively created name: another process's holding directory is never reused.
    let Ok(holding) = crate::secure_temp::create_dir(root, "removing-") else {
        return Err(("failed", "无法创建卸载暂存目录，未做任何修改".into()));
    };
    let mut moved = Vec::new();
    for name in names {
        if let Err(failure) = move_file(root, &holding, name) {
            return Err(restore_backup(root, &holding, &moved, &[], failure));
        }
        moved.push(name.clone());
    }
    // Past this point the names are detached. If the final delete fails, the pointer stays and the
    // install reads as unverified (its files are gone), so later actions are blocked, not silently wrong.
    remove_entry(&holding)?;
    prune_empty_parents(root, names);
    Ok(())
}

/// Swaps the verified staging tree into the root and commits the pointer last.
pub(crate) fn activate(
    root: &Path,
    staging: &Path,
    names: &[String],
    pointer: &impl serde::Serialize,
    moved: &mut Vec<String>,
) -> Result<(), Failure> {
    for name in names {
        move_file(staging, root, name)?;
        moved.push(name.clone());
    }
    write_json(&root.join(ACTIVE), pointer)?;
    moved.push(ACTIVE.into());
    Ok(())
}

/// Leaves no active pointer and no bundle files behind after a failed activation.
pub(crate) fn rollback(root: &Path, names: &[String]) {
    for name in names.iter().rev() {
        let _ = remove_owned_file(root, name);
    }
    prune_empty_parents(root, names);
}

/// Restore only journaled moves; a failed restore leaves all remaining recovery data in place.
pub(crate) fn restore_backup(
    root: &Path,
    backup: &Path,
    moved: &[String],
    activated: &[String],
    failure: Failure,
) -> Failure {
    let mut errors = Vec::new();
    for name in activated.iter().rev() {
        if let Err((_, reason)) = remove_owned_file(root, name) {
            errors.push(reason);
        }
    }
    for name in moved.iter().rev() {
        if let Err((_, reason)) = move_file(backup, root, name) {
            errors.push(reason);
        }
    }
    if errors.is_empty() {
        prune_empty_parents(backup, moved);
        let _ = fs::remove_dir(backup);
        (failure.0, format!("{}；已恢复旧版本", failure.1))
    } else {
        (
            "failed",
            format!(
                "{}；回滚未完成：{}；恢复文件保留于 {}",
                failure.1,
                errors.join("；"),
                backup.display()
            ),
        )
    }
}

pub(crate) fn write_json(path: &Path, value: &impl serde::Serialize) -> Result<(), Failure> {
    let text = serde_json::to_string_pretty(value)
        .map_err(|_| ("failed", "无法序列化安装状态".into()))?;
    // Random temp name + exclusive create + rename: a pre-placed file (or a concurrent writer)
    // can never be adopted or partially read.
    crate::secure_temp::replace_file(path, text.as_bytes())
        .map_err(|e| ("failed", format!("无法写入安装状态：{e}")))
}

/// Cleanup is tied to a directory exclusively created by this call, never a filename-prefix scan.
pub(crate) struct StagingCleanup(pub(crate) PathBuf);
impl Drop for StagingCleanup {
    fn drop(&mut self) {
        let _ = remove_entry(&self.0);
    }
}
