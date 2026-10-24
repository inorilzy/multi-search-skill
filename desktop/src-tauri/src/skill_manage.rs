//! Status, safe update, and safe removal of the CLI-only Skill this tool installed.
//! Only files listed in our marker are ever touched; unknown files and other skills are never deleted.
use crate::skill::{self, skill_version, FILES, MARKER, SKILL_NAME};
use crate::DesktopManager;
use serde::Serialize;
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

/// What is currently at the skill target.
#[derive(Clone, Serialize, PartialEq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum InstallState {
    /// Nothing at the target.
    Absent,
    /// Our marker is present and every managed file matches the shipped content.
    Current,
    /// Our marker is present but it was written by an older release of this tool.
    Outdated,
    /// Our marker is present, but one or more managed files were edited by the user.
    Modified,
    /// A folder exists at the target but it has no valid marker from this tool.
    Unknown,
}

#[derive(Clone, Serialize, Debug)]
pub struct SkillStatus {
    pub host: String,
    pub scope: String,
    pub target: Option<String>,
    pub state: InstallState,
    pub installed_version: Option<String>,
    pub release_version: String,
    pub cli_requirements: String,
    pub cli_compatible: bool,
    pub compatibility_reason: String,
    pub can_update: bool,
    /// Shipped files this tool manages (paths relative to the target).
    pub managed_files: Vec<String>,
    /// Managed files whose content differs from the shipped release or the recorded hash.
    pub modified_files: Vec<String>,
    /// Entries in the target that are not managed by this tool; never deleted.
    pub unknown_entries: Vec<String>,
    pub reason: String,
}

#[derive(Clone, Serialize, Debug)]
pub struct UpdatePlan {
    pub status: String,
    pub reason: String,
    pub state: InstallState,
    pub backup_required: bool,
    pub modified_files: Vec<String>,
    pub unknown_entries: Vec<String>,
    pub can_update: bool,
}

#[derive(Clone, Serialize, Debug)]
pub struct RemovePlan {
    pub status: String,
    pub reason: String,
    /// Exactly what would be deleted: our marker plus managed files, nothing else.
    pub will_delete: Vec<String>,
    /// Entries kept because we did not create them.
    pub will_keep: Vec<String>,
    pub can_remove: bool,
}

#[derive(Clone, Serialize, Debug)]
pub struct UpdateOutcome {
    /// updated | blocked | failed
    pub status: String,
    pub verified: bool,
    pub backup: Option<String>,
    pub reason: String,
}

#[derive(Clone, Serialize, Debug)]
pub struct RemoveOutcome {
    /// removed | blocked | failed
    pub status: String,
    pub deleted: Vec<String>,
    pub kept: Vec<String>,
    pub reason: String,
}

/// Parsed view of our marker. `None` means the folder is not ours.
#[derive(Debug)]
struct Marker {
    version: String,
    hashes: BTreeMap<String, String>,
}

fn is_link(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

/// Ancestors of a Skill target that this tool creates and owns: `<target>`, `skills/`, `.claude/`.
/// Anything above `.claude/` (the user/project root and its parents) is machine layout.
const MANAGED_ANCESTOR_DEPTH: usize = 3;

pub(crate) fn safe_managed_paths(directory: &Path) -> bool {
    // Every ancestor the tool owns matters: references/ or the target itself may be a junction that
    // redirects writes. Ancestors above `.claude/` are not ours: macOS ships `/var -> /private/var`
    // and `/tmp -> private/tmp`, and home or project folders may legitimately sit behind a link.
    for ancestor in directory.ancestors().take(MANAGED_ANCESTOR_DEPTH) {
        if let Ok(metadata) = fs::symlink_metadata(ancestor) {
            if is_link(&metadata) || !metadata.is_dir() {
                return false;
            }
        }
    }
    for (name, _) in FILES.iter().copied().chain(std::iter::once((MARKER, ""))) {
        let path = directory.join(name);
        if let Some(parent) = path.parent() {
            if let Ok(metadata) = fs::symlink_metadata(parent) {
                if is_link(&metadata) || !metadata.is_dir() {
                    return false;
                }
            }
        }
        match fs::symlink_metadata(path) {
            Ok(metadata) if is_link(&metadata) || !metadata.is_file() => return false,
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => return false,
            _ => {}
        }
    }
    true
}

fn read_marker(directory: &Path) -> Option<Marker> {
    if !safe_managed_paths(directory) {
        return None;
    }
    let text = fs::read_to_string(directory.join(MARKER)).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    if value["managed_by"] != "multi-search-desktop" || value["skill"] != SKILL_NAME {
        return None;
    }
    let files = value["files"].as_array()?;
    if files.len() != FILES.len()
        || !FILES
            .iter()
            .all(|(name, _)| files.iter().any(|v| v.as_str() == Some(name)))
    {
        return None; // Ownership must match the known release manifest, never caller paths.
    }
    let version = value["skill_version"].as_str()?.to_string();
    let hashes = match value.get("hashes") {
        None => BTreeMap::new(), // The verified 06 release did not record hashes.
        Some(hashes) => hashes
            .as_object()?
            .iter()
            .map(|(k, v)| Some((k.clone(), v.as_str()?.to_string())))
            .collect::<Option<BTreeMap<_, _>>>()?,
    };
    Some(Marker { version, hashes })
}

/// Entries directly inside the target that we did not place there.
fn unknown_entries(directory: &Path) -> Result<Vec<String>, String> {
    let managed: Vec<String> = FILES.iter().map(|(name, _)| top_level(name)).collect();
    let list = |path: &Path| -> Result<Vec<fs::DirEntry>, String> {
        fs::read_dir(path)
            .and_then(|entries| entries.collect())
            .map_err(|e| format!("无法清点用户内容：{e}"))
    };
    let mut found = Vec::new();
    for entry in list(directory)? {
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "无法安全表示用户文件名")?;
        if name != MARKER && !managed.contains(&name) {
            found.push(name);
        }
    }
    // A missing managed folder can be repaired; any other inventory failure blocks mutation.
    let managed_dirs: Vec<&str> = FILES
        .iter()
        .filter_map(|(name, _)| name.rsplit_once('/').map(|(dir, _)| dir))
        .collect();
    for dir in managed_dirs {
        let path = directory.join(dir);
        if !path.exists() {
            continue;
        }
        for entry in list(&path)? {
            let name = format!(
                "{dir}/{}",
                entry
                    .file_name()
                    .into_string()
                    .map_err(|_| "无法安全表示用户文件名")?
            );
            if !FILES.iter().any(|(managed_name, _)| *managed_name == name) {
                found.push(name);
            }
        }
    }
    found.sort();
    found.dedup();
    Ok(found)
}

fn top_level(relative: &str) -> String {
    relative.split('/').next().unwrap_or(relative).to_string()
}

/// Classifies the folder. A file is `modified` when its bytes differ from the hash recorded at install time.
pub(crate) fn classify(
    directory: &Path,
) -> (
    InstallState,
    Option<String>,
    Vec<String>,
    Vec<String>,
    String,
) {
    if fs::symlink_metadata(directory).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound) {
        return (
            InstallState::Absent,
            None,
            vec![],
            vec![],
            "这里没有安装任何内容。".into(),
        );
    }
    if !safe_managed_paths(directory) {
        return (
            InstallState::Unknown,
            None,
            vec![],
            vec![],
            "受管路径是链接或非文件，已保持原样。".into(),
        );
    }
    let unknown = match unknown_entries(directory) {
        Ok(entries) => entries,
        Err(reason) => return (InstallState::Unknown, None, vec![], vec![], reason),
    };
    let Some(marker) = read_marker(directory) else {
        return (
            InstallState::Unknown,
            None,
            vec![],
            unknown,
            "该目录已存在，但不是本工具安装的，不会修改。".into(),
        );
    };
    let mut modified = Vec::new();
    for (name, shipped) in FILES {
        // Baseline: the hash recorded when we wrote the file. Markers from the 06 release carry no hashes,
        // so for a same-version marker the shipped content is the only baseline we can prove.
        let baseline = match marker.hashes.get(name) {
            Some(hash) => Some(hash.clone()),
            None if marker.version == skill_version() => Some(skill::sha256_hex(shipped)),
            None => None,
        };
        let on_disk = fs::read_to_string(directory.join(name))
            .ok()
            .map(|content| skill::sha256_hex(&content));
        if on_disk != baseline {
            modified.push(name.to_string());
        }
    }
    let state = if !modified.is_empty() {
        InstallState::Modified
    } else if marker.version != skill_version() {
        InstallState::Outdated
    } else {
        InstallState::Current
    };
    let reason = match state {
        InstallState::Current => "已安装，且与本版本一致。".into(),
        InstallState::Outdated => format!(
            "已安装版本 {} 与发布版本 {} 不一致。",
            marker.version,
            skill_version()
        ),
        InstallState::Modified => format!(
            "以下受管文件被本地修改：{}。",
            modified.join(", ")
        ),
        _ => String::new(),
    };
    (state, Some(marker.version), modified, unknown, reason)
}

fn join_target(
    manager: &DesktopManager,
    scope: &str,
    project: Option<PathBuf>,
) -> Result<PathBuf, String> {
    skill::target_directory(&manager.environment, scope, project.as_deref())
}

/// Copies every modified managed file into a timestamped backup folder beside the skill, before overwrite.
fn backup_modified(directory: &Path, modified: &[String]) -> Result<Option<PathBuf>, String> {
    if modified.is_empty() {
        return Ok(None);
    }
    let base = directory
        .parent()
        .and_then(Path::parent)
        .ok_or("目标无效 directory")?;
    let backup = crate::secure_temp::create_dir(base, ".multi-search-backup-")
        .map_err(|e| format!("无法保留备份目录：{e}"))?;
    for name in modified {
        let source = directory.join(name);
        if fs::symlink_metadata(&source).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound) {
            continue; // A locally deleted file has no bytes to back up.
        }
        let destination = backup.join(name);
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("无法创建备份目录：{e}"))?;
        }
        fs::copy(&source, &destination).map_err(|e| format!("无法备份 {name}：{e}"))?;
    }
    Ok(Some(backup))
}

fn copy_user_entry(source: &Path, destination: &Path) -> Result<(), String> {
    let metadata =
        fs::symlink_metadata(source).map_err(|e| format!("无法检查用户内容：{e}"))?;
    if is_link(&metadata) {
        return Err(
            "链接的用户内容无法安全复制；原文件未改变。".into(),
        );
    }
    if metadata.is_dir() {
        fs::create_dir_all(destination).map_err(|e| format!("无法保留用户目录：{e}"))?;
        for entry in fs::read_dir(source).map_err(|e| format!("无法读取用户目录：{e}"))? {
            let entry = entry.map_err(|e| format!("无法读取用户条目：{e}"))?;
            copy_user_entry(&entry.path(), &destination.join(entry.file_name()))?;
        }
    } else if metadata.is_file() {
        fs::copy(source, destination).map_err(|e| format!("无法保留用户文件：{e}"))?;
    } else {
        return Err("不支持的用户内容；原文件未改变。".into());
    }
    Ok(())
}

impl DesktopManager {
    /// Updates an installed skill that this tool manages. Modified files need `confirm_overwrite`
    /// and are backed up first. The old skill stays in place until the new one is verified.
    pub fn skill_update(
        &self,
        scope: &str,
        project: Option<PathBuf>,
        confirm_overwrite: bool,
    ) -> UpdateOutcome {
        let target = match join_target(self, scope, project.clone()) {
            Ok(target) => target,
            Err(reason) => {
                return UpdateOutcome {
                    status: "blocked".into(),
                    verified: false,
                    backup: None,
                    reason,
                }
            }
        };
        let (state, _, modified, unknown, _) = classify(&target);
        let plan = plan_update(&state, &modified, &unknown);
        if !plan.can_update {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason: plan.reason,
            };
        }
        if plan.backup_required && !confirm_overwrite {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason: format!(
                    "需要确认：以下文件有本地修改 {}。",
                    modified.join(", ")
                ),
            };
        }
        // Compatibility is checked by the same path as install; an incompatible CLI blocks the update.
        let cli = self.detect_cli().user;
        if cli.status != "ready" {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason: format!(
                    "无法发现 CLI（{}）。请先安装 CLI。",
                    cli.status
                ),
            };
        }
        if let Err(reason) = self.check_compatibility(cli.path.as_deref().unwrap_or_default()) {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason,
            };
        }
        let backup = match backup_modified(&target, &modified) {
            Ok(backup) => backup,
            Err(reason) => {
                return UpdateOutcome {
                    status: "failed".into(),
                    verified: false,
                    backup: None,
                    reason,
                }
            }
        };
        let backup_text = backup.as_ref().map(|p| p.to_string_lossy().into_owned());
        // Stage the new release beside the target so a failed write never leaves a half-updated skill.
        let Some(base) = target.parent().and_then(Path::parent) else {
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: "目标无效".into(),
            };
        };
        let staging = match crate::secure_temp::create_dir(base, ".multi-search-update-") {
            Ok(staging) => staging,
            Err(error) => {
                return UpdateOutcome {
                    status: "failed".into(),
                    verified: false,
                    backup: backup_text,
                    reason: format!(
                        "无法保留暂存目录；已安装 Skill 未改变：{error}"
                    ),
                };
            }
        };
        if let Err(reason) = skill::write_directory(&staging) {
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!("更新失败；已安装 Skill 已保留。{reason}"),
            };
        }
        for name in &unknown {
            if let Err(reason) = copy_user_entry(&target.join(name), &staging.join(name)) {
                let _ = fs::remove_dir_all(&staging);
                return UpdateOutcome {
                    status: "failed".into(),
                    verified: false,
                    backup: backup_text,
                    reason,
                };
            }
        }
        // Swap: move the old folder aside, put the verified new folder in place, then drop the old one.
        // A fresh random name that does not exist yet; rename never targets a planted entry.
        let old = base.join(format!(".multi-search-old-{}", crate::secure_temp::token()));
        if let Err(error) = fs::rename(&target, &old) {
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!("更新失败；已安装 Skill 已保留。{error}"),
            };
        }
        if let Err(error) = fs::rename(&staging, &target) {
            // Restore the old folder so the user keeps a usable skill.
            let restored = fs::rename(&old, &target);
            let _ = fs::remove_dir_all(&staging);
            let recovery = match restored {
                Ok(()) => "已恢复原 Skill。".into(),
                Err(restore_error) => format!(
                    "自动恢复失败（{restore_error}）；原始文件仍在 {}。",
                    old.display()
                ),
            };
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!("更新失败。{recovery} {error}"),
            };
        }
        match skill::verify_directory(&target).and_then(|()| skill::record_target(&self.environment, &target, true)) {
            Ok(()) => {
                let _ = fs::remove_dir_all(&old);
                UpdateOutcome {
                    status: "updated".into(),
                    verified: true,
                    backup: backup_text,
                    reason: "已更新并校验；请新开 Claude Code 会话以加载。"
                        .into(),
                }
            }
            Err(reason) => {
                // Verification failed: remove the new folder and restore the old one.
                let restored = fs::remove_dir_all(&target).and_then(|()| fs::rename(&old, &target));
                let recovery = match restored {
                    Ok(()) => "已恢复原 Skill。".into(),
                    Err(error) => format!(
                        "自动恢复失败（{error}）；原始文件仍在 {}。",
                        old.display()
                    ),
                };
                UpdateOutcome {
                    status: "failed".into(),
                    verified: false,
                    backup: backup_text,
                    reason: format!("更新未通过校验。{recovery} {reason}"),
                }
            }
        }
    }

    /// Plans removal: shows exactly which files would be deleted and which are kept.
    pub fn skill_remove_plan(
        &self,
        scope: &str,
        project: Option<PathBuf>,
    ) -> Result<RemovePlan, String> {
        let target = join_target(self, scope, project)?;
        let (state, _, _, unknown, _) = classify(&target);
        Ok(plan_remove(&state, &unknown))
    }

    /// Removes only the files this tool installed, after confirmation. Never deletes the skills folder.
    pub fn skill_remove(
        &self,
        scope: &str,
        project: Option<PathBuf>,
        confirmed: bool,
    ) -> RemoveOutcome {
        let target = match join_target(self, scope, project) {
            Ok(target) => target,
            Err(reason) => {
                return RemoveOutcome {
                    status: "blocked".into(),
                    deleted: vec![],
                    kept: vec![],
                    reason,
                }
            }
        };
        let (state, _, _, unknown, _) = classify(&target);
        let plan = plan_remove(&state, &unknown);
        if !plan.can_remove {
            return RemoveOutcome {
                status: "blocked".into(),
                deleted: vec![],
                kept: plan.will_keep,
                reason: plan.reason,
            };
        }
        if !confirmed {
            return RemoveOutcome {
                status: "blocked".into(),
                deleted: vec![],
                kept: plan.will_keep,
                reason: "移除列出的文件前需要确认。".into(),
            };
        }
        let mut deleted = Vec::new();
        for name in plan
            .will_delete
            .iter()
            .filter(|name| name.as_str() != MARKER)
        {
            let path = target.join(name);
            if path.is_file() && fs::remove_file(&path).is_ok() {
                deleted.push(name.clone());
            }
        }
        // Keep proof of ownership when a managed file could not be removed, so retry stays safe.
        let content_left = FILES
            .iter()
            .any(|(name, _)| fs::symlink_metadata(target.join(name)).is_ok());
        if !content_left && fs::remove_file(target.join(MARKER)).is_ok() {
            deleted.push(MARKER.into());
        }
        // Remove now-empty managed folders (references/, agents/) and the skill
        // folder only when nothing else is left.
        for dir in FILES
            .iter()
            .filter_map(|(name, _)| name.rsplit_once('/').map(|(dir, _)| dir))
        {
            let _ = fs::remove_dir(target.join(dir));
        }
        let _ = fs::remove_dir(&target);
        let kept = plan.will_keep.clone();
        // Success means every managed file is gone; kept user content never counts against it.
        let managed_left = plan
            .will_delete
            .iter()
            .any(|name| target.join(name).exists());
        if !managed_left {
            if let Err(reason) = skill::record_target(&self.environment, &target, false) {
                return RemoveOutcome { status: "failed".into(), deleted, kept, reason };
            }
            RemoveOutcome {
                status: "removed".into(),
                deleted,
                kept,
                reason: "已移除；其他文件和 Skill 已保留。".into(),
            }
        } else {
            RemoveOutcome {
                status: "failed".into(),
                deleted,
                kept,
                reason: "移除结果无法确认；请重新检查目标目录。".into(),
            }
        }
    }

    /// Read-only: reports what is installed without writing anything.
    pub fn skill_status(
        &self,
        scope: &str,
        project: Option<PathBuf>,
    ) -> Result<SkillStatus, String> {
        let target = join_target(self, scope, project)?;
        let (state, installed_version, modified_files, unknown_entries, reason) = classify(&target);
        let cli = self.detect_cli().user;
        let compatibility = if cli.status == "ready" {
            self.check_compatibility(cli.path.as_deref().unwrap_or_default())
        } else {
            Err(format!(
                "CLI is not discoverable ({}). Install a compatible CLI first.",
                cli.status
            ))
        };
        let cli_compatible = compatibility.is_ok();
        let compatibility_reason = compatibility
            .err()
            .unwrap_or_else(|| "CLI 满足本版本要求的命令与参数。".into());
        let can_update =
            cli_compatible && matches!(state, InstallState::Outdated | InstallState::Modified);
        Ok(SkillStatus {
            host: "claude-code".into(),
            scope: scope.into(),
            target: Some(target.to_string_lossy().into_owned()),
            state,
            installed_version,
            release_version: skill_version(),
            cli_requirements: skill::REQUIRED_FLAGS
                .iter()
                .map(|(command, flags)| format!("{command}: {}", flags.join(" ")))
                .collect::<Vec<_>>()
                .join("; "),
            cli_compatible,
            compatibility_reason,
            can_update,
            managed_files: skill::file_names(),
            modified_files,
            unknown_entries,
            reason,
        })
    }
}

/// Pure planning: decides update eligibility from the classified state.
pub(crate) fn plan_update(
    state: &InstallState,
    modified: &[String],
    unknown: &[String],
) -> UpdatePlan {
    let (status, can_update, backup_required, reason) = match state {
        InstallState::Absent => (
            "absent",
            false,
            false,
            "没有可更新的内容，请先安装 Skill。",
        ),
        InstallState::Current => ("current", false, false, "已是最新版本。"),
        InstallState::Unknown => (
            "unknown",
            false,
            false,
            "不是本工具管理的 Skill，已拒绝更新。",
        ),
        InstallState::Outdated => (
            "ready",
            true,
            false,
            "可更新到本版本；仅限未修改的文件。",
        ),
        InstallState::Modified => (
            "needs_confirmation",
            true,
            true,
            "检测到本地修改；确认备份后才会用本版本覆盖。",
        ),
    };
    UpdatePlan {
        status: status.into(),
        reason: reason.into(),
        state: state.clone(),
        backup_required,
        modified_files: modified.to_vec(),
        unknown_entries: unknown.to_vec(),
        can_update,
    }
}

/// Pure planning: lists exactly what removal deletes, never the folder itself.
pub(crate) fn plan_remove(state: &InstallState, unknown: &[String]) -> RemovePlan {
    match state {
        InstallState::Absent | InstallState::Unknown => RemovePlan {
            status: "nothing_to_remove".into(),
            reason: "这里没有本工具安装的内容。".into(),
            will_delete: vec![],
            will_keep: unknown.to_vec(),
            can_remove: false,
        },
        _ => {
            let mut will_delete: Vec<String> =
                FILES.iter().map(|(n, _)| (*n).to_string()).collect();
            will_delete.push(MARKER.into());
            RemovePlan {
                status: "ready".into(),
                reason:
                    "仅移除本工具安装的文件；其他文件和 Skill 会保留。"
                        .into(),
                will_delete,
                will_keep: unknown.to_vec(),
                can_remove: true,
            }
        }
    }
}
