//! Status, safe update, and safe removal of the CLI-only Skill this tool installed.
//! Only files listed in our marker are ever touched; unknown files and other skills are never deleted.
use crate::skill::{record_target, STAGING_ID};
use crate::skill_common::{self, skill_version, FILES, MARKER};
use crate::windows_util::is_link;
use crate::skill::SkillManager;
use serde::Serialize;
use std::{
    fs,
    path::{Path, PathBuf},
};

/// What is currently at the skill target.
#[derive(Clone, Serialize, PartialEq, Debug)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[serde(rename_all = "snake_case")]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
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
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
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
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UpdatePlan {
    /// absent | current | unknown | ready | needs_confirmation, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub reason: String,
    pub state: InstallState,
    pub backup_required: bool,
    pub modified_files: Vec<String>,
    pub unknown_entries: Vec<String>,
    pub can_update: bool,
}

#[derive(Clone, Serialize, Debug)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct RemovePlan {
    /// ready | nothing_to_remove, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub reason: String,
    /// Exactly what would be deleted: our marker plus managed files, nothing else.
    pub will_delete: Vec<String>,
    /// Entries kept because we did not create them.
    pub will_keep: Vec<String>,
    pub can_remove: bool,
}

#[derive(Clone, Serialize, Debug)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct UpdateOutcome {
    /// updated | blocked | failed, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub verified: bool,
    pub backup: Option<String>,
    pub reason: String,
}

#[derive(Clone, Serialize, Debug)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct RemoveOutcome {
    /// removed | blocked | failed, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub deleted: Vec<String>,
    pub kept: Vec<String>,
    pub reason: String,
}

/// Entries directly inside the target that we did not place there.
fn unknown_entries(directory: &Path) -> Result<Vec<String>, String> {
    let managed: Vec<String> = FILES.iter().map(|(name, _)| top_level(name)).collect();
    let list = |path: &Path| -> Result<Vec<fs::DirEntry>, String> {
        fs::read_dir(path)
            .and_then(|entries| entries.collect())
            .map_err(|e| format!("Cannot inventory user content: {e}"))
    };
    let mut found = Vec::new();
    for entry in list(directory)? {
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "Cannot safely represent user filename")?;
        if name != MARKER && !managed.contains(&name) {
            found.push(name);
        }
    }
    // A missing managed folder can be repaired; any other inventory failure blocks mutation.
    let references = directory.join("references");
    if references.exists() {
        for entry in list(&references)? {
            let name = format!(
                "references/{}",
                entry
                    .file_name()
                    .into_string()
                    .map_err(|_| "Cannot safely represent user filename")?
            );
            if !FILES.iter().any(|(managed_name, _)| *managed_name == name) {
                found.push(name);
            }
        }
    }
    found.sort();
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
            "Nothing is installed here.".into(),
        );
    }
    if !skill_common::safe_managed_paths(directory) {
        return (
            InstallState::Unknown,
            None,
            vec![],
            vec![],
            "Unsafe linked or non-file managed path; left unchanged.".into(),
        );
    }
    let unknown = match unknown_entries(directory) {
        Ok(entries) => entries,
        Err(reason) => return (InstallState::Unknown, None, vec![], vec![], reason),
    };
    let Some(marker) = skill_common::read_marker(directory) else {
        return (
            InstallState::Unknown,
            None,
            vec![],
            unknown,
            "This folder exists but was not installed by this tool. It will not be changed.".into(),
        );
    };
    let mut modified = Vec::new();
    let mut marker_unverified = false;
    for (name, _shipped) in FILES {
        // Verified baseline only: the hash recorded at install time. A marker
        // without hashes (pre-schema releases) cannot prove the on-disk bytes
        // are unmodified, so such an install is classified Outdated rather
        // than treating the shipped content as if it had been verified.
        let baseline = marker.hashes.as_ref().and_then(|hashes| hashes.get(name));
        let on_disk = fs::read_to_string(directory.join(name))
            .ok()
            .map(|content| skill_common::sha256_hex(&content));
        match baseline {
            Some(hash) if on_disk.as_deref() == Some(hash.as_str()) => {}
            Some(_) => modified.push(name.to_string()),
            None => marker_unverified = true,
        }
    }
    let state = if !modified.is_empty() {
        InstallState::Modified
    } else if marker_unverified
        || marker.marker_schema != Some(skill_common::MARKER_SCHEMA)
        || marker.skill_version != skill_version()
    {
        InstallState::Outdated
    } else {
        InstallState::Current
    };
    let reason = match state {
        InstallState::Current => "Installed and matches this release.".into(),
        InstallState::Outdated if marker_unverified => format!(
            "Installed marker records no file hashes (schema {:?}); the install cannot be verified, so it is treated as outdated.",
            marker.marker_schema
        ),
        InstallState::Outdated => format!(
            "Installed version {} differs from release {}.",
            marker.skill_version,
            skill_version()
        ),
        InstallState::Modified => format!(
            "Managed files were edited locally: {}.",
            modified.join(", ")
        ),
        _ => String::new(),
    };
    (state, Some(marker.skill_version), modified, unknown, reason)
}

fn join_target(
    manager: &SkillManager<'_>,
    scope: &str,
    project: Option<PathBuf>,
) -> Result<PathBuf, String> {
    skill_common::target_directory(&manager.environment, scope, project.as_deref())
}

/// Copies every modified managed file into a timestamped backup folder beside the skill, before overwrite.
fn backup_modified(directory: &Path, modified: &[String]) -> Result<Option<PathBuf>, String> {
    if modified.is_empty() {
        return Ok(None);
    }
    let base = directory
        .parent()
        .and_then(Path::parent)
        .ok_or("Invalid target directory")?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default();
    let backup = base.join(format!(
        ".multi-search-backup-{stamp}-{}-{}",
        std::process::id(),
        STAGING_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    fs::create_dir(&backup).map_err(|e| format!("Cannot reserve backup folder: {e}"))?;
    for name in modified {
        let source = directory.join(name);
        if fs::symlink_metadata(&source).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound) {
            continue; // A locally deleted file has no bytes to back up.
        }
        let destination = backup.join(name);
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("Cannot create backup folder: {e}"))?;
        }
        fs::copy(&source, &destination).map_err(|e| format!("Cannot back up {name}: {e}"))?;
    }
    Ok(Some(backup))
}

fn copy_user_entry(source: &Path, destination: &Path) -> Result<(), String> {
    let metadata =
        fs::symlink_metadata(source).map_err(|e| format!("Cannot inspect user content: {e}"))?;
    if is_link(&metadata) {
        return Err(
            "Linked user content cannot be copied safely; the original is unchanged.".into(),
        );
    }
    if metadata.is_dir() {
        fs::create_dir_all(destination).map_err(|e| format!("Cannot preserve user folder: {e}"))?;
        for entry in fs::read_dir(source).map_err(|e| format!("Cannot read user folder: {e}"))? {
            let entry = entry.map_err(|e| format!("Cannot read user entry: {e}"))?;
            copy_user_entry(&entry.path(), &destination.join(entry.file_name()))?;
        }
    } else if metadata.is_file() {
        fs::copy(source, destination).map_err(|e| format!("Cannot preserve user file: {e}"))?;
    } else {
        return Err("Unsupported user entry; the original is unchanged.".into());
    }
    Ok(())
}

impl SkillManager<'_> {
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
                    "Confirmation required: local edits in {}.",
                    modified.join(", ")
                ),
            };
        }
        // Compatibility is checked by the same path as install; an incompatible CLI blocks the update.
        let cli = self.discovery.detect().user;
        if cli.status != "ready" {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason: format!(
                    "The CLI is not discoverable ({}). Install the CLI first.",
                    cli.status
                ),
            };
        }
        if let Err(reason) = crate::skill::check_compatibility(self.environment, cli.path.as_deref().unwrap_or_default()) {
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
                reason: "Invalid target".into(),
            };
        };
        let staging = base.join(format!(
            ".multi-search-update-{}-{}",
            std::process::id(),
            STAGING_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        if let Err(error) = fs::create_dir(&staging) {
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!(
                    "Cannot reserve staging folder; installed skill unchanged: {error}"
                ),
            };
        }
        if let Err(reason) = skill_common::write_directory(&staging) {
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!("Update failed; the installed skill was kept. {reason}"),
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
        let old = base.join(format!(
            ".multi-search-old-{}-{}",
            std::process::id(),
            STAGING_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        if let Err(error) = fs::rename(&target, &old) {
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!("Update failed; the installed skill was kept. {error}"),
            };
        }
        if let Err(error) = fs::rename(&staging, &target) {
            // Restore the old folder so the user keeps a usable skill.
            let restored = fs::rename(&old, &target);
            let _ = fs::remove_dir_all(&staging);
            let recovery = match restored {
                Ok(()) => "The installed skill was restored.".into(),
                Err(restore_error) => format!(
                    "Automatic restore failed ({restore_error}); original files remain at {}.",
                    old.display()
                ),
            };
            return UpdateOutcome {
                status: "failed".into(),
                verified: false,
                backup: backup_text,
                reason: format!("Update failed. {recovery} {error}"),
            };
        }
        match skill_common::verify_directory(&target).and_then(|()| record_target(&self.environment, &target, true)) {
            Ok(()) => {
                let _ = fs::remove_dir_all(&old);
                UpdateOutcome {
                    status: "updated".into(),
                    verified: true,
                    backup: backup_text,
                    reason: "Updated and verified. Start a new Claude Code session to load it."
                        .into(),
                }
            }
            Err(reason) => {
                // Verification failed: remove the new folder and restore the old one.
                let restored = fs::remove_dir_all(&target).and_then(|()| fs::rename(&old, &target));
                let recovery = match restored {
                    Ok(()) => "The installed skill was restored.".into(),
                    Err(error) => format!(
                        "Automatic restore failed ({error}); original files remain at {}.",
                        old.display()
                    ),
                };
                UpdateOutcome {
                    status: "failed".into(),
                    verified: false,
                    backup: backup_text,
                    reason: format!("Update failed verification. {recovery} {reason}"),
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
                reason: "Confirmation required before removing the listed files.".into(),
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
        // Remove the now-empty references folder and the skill folder only if nothing else is left.
        let _ = fs::remove_dir(target.join("references"));
        let _ = fs::remove_dir(&target);
        let kept = plan.will_keep.clone();
        // Success means every managed file is gone; kept user content never counts against it.
        let managed_left = plan
            .will_delete
            .iter()
            .any(|name| target.join(name).exists());
        if !managed_left {
            if let Err(reason) = record_target(&self.environment, &target, false) {
                return RemoveOutcome { status: "failed".into(), deleted, kept, reason };
            }
            RemoveOutcome {
                status: "removed".into(),
                deleted,
                kept,
                reason: "Removed. Other files and skills were kept.".into(),
            }
        } else {
            RemoveOutcome {
                status: "failed".into(),
                deleted,
                kept,
                reason: "Removal could not be confirmed; re-check the folder.".into(),
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
        let cli = self.discovery.detect().user;
        let compatibility = if cli.status == "ready" {
            crate::skill::check_compatibility(self.environment, cli.path.as_deref().unwrap_or_default())
        } else {
            Err(format!(
                "CLI is not discoverable ({}). Install a compatible CLI first.",
                cli.status
            ))
        };
        let cli_compatible = compatibility.is_ok();
        let compatibility_reason = compatibility
            .err()
            .unwrap_or_else(|| "CLI satisfies this release's required commands and flags.".into());
        let can_update =
            cli_compatible && matches!(state, InstallState::Outdated | InstallState::Modified);
        Ok(SkillStatus {
            host: "claude-code".into(),
            scope: scope.into(),
            target: Some(target.to_string_lossy().into_owned()),
            state,
            installed_version,
            release_version: skill_version(),
            cli_requirements: skill_common::REQUIRED_FLAGS
                .iter()
                .map(|(command, flags)| format!("{command}: {}", flags.join(" ")))
                .collect::<Vec<_>>()
                .join("; "),
            cli_compatible,
            compatibility_reason,
            can_update,
            managed_files: skill_common::file_names(),
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
            "Nothing to update. Install the Skill first.",
        ),
        InstallState::Current => ("current", false, false, "Already up to date."),
        InstallState::Unknown => (
            "unknown",
            false,
            false,
            "Not managed by this tool; update is refused.",
        ),
        InstallState::Outdated => (
            "ready",
            true,
            false,
            "Update to this release. Unmodified files only.",
        ),
        InstallState::Modified => (
            "needs_confirmation",
            true,
            true,
            "Local edits detected. Confirm to back them up and overwrite with this release.",
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
            reason: "No content from this tool is installed here.".into(),
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
                    "Removes only the files this tool installed. Your other files and skills stay."
                        .into(),
                will_delete,
                will_keep: unknown.to_vec(),
                can_remove: true,
            }
        }
    }
}
