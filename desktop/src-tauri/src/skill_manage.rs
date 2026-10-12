//! Status, safe update, and safe removal of the CLI-only Skill this tool installed.
//! Only files listed in our marker are ever touched; unknown files and other skills are never deleted.
use crate::skill::{self, FILES, MARKER, SKILL_NAME, SKILL_VERSION};
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

fn read_marker(directory: &Path) -> Option<Marker> {
    let text = fs::read_to_string(directory.join(MARKER)).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    if value["managed_by"] != "multi-search-desktop" || value["skill"] != SKILL_NAME {
        return None;
    }
    let version = value["skill_version"].as_str()?.to_string();
    let hashes = value["hashes"]
        .as_object()?
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_string()))
        .collect();
    Some(Marker { version, hashes })
}

/// Entries directly inside the target that we did not place there.
fn unknown_entries(directory: &Path) -> Vec<String> {
    let managed: Vec<String> = FILES.iter().map(|(name, _)| top_level(name)).collect();
    let mut found: Vec<String> = fs::read_dir(directory)
        .map(|entries| {
            entries
                .flatten()
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .filter(|name| name != MARKER && !managed.contains(name))
                .collect()
        })
        .unwrap_or_default();
    // Unknown files under references/ are reported too, since that folder is ours but may hold extras.
    if let Ok(entries) = fs::read_dir(directory.join("references")) {
        for entry in entries.flatten() {
            let name = format!("references/{}", entry.file_name().to_string_lossy());
            if !FILES.iter().any(|(managed_name, _)| *managed_name == name) {
                found.push(name);
            }
        }
    }
    found.sort();
    found
}

fn top_level(relative: &str) -> String {
    relative.split('/').next().unwrap_or(relative).to_string()
}

/// Classifies the folder. A file is `modified` when its bytes differ from the hash recorded at install time.
pub(crate) fn classify(directory: &Path) -> (InstallState, Option<String>, Vec<String>, Vec<String>, String) {
    let unknown = unknown_entries(directory);
    if fs::symlink_metadata(directory).is_err() {
        return (InstallState::Absent, None, vec![], vec![], "Nothing is installed here.".into());
    }
    let Some(marker) = read_marker(directory) else {
        return (
            InstallState::Unknown,
            None,
            vec![],
            unknown,
            "This folder exists but was not installed by this tool. It will not be changed.".into(),
        );
    };
    let mut modified = Vec::new();
    for (name, shipped) in FILES {
        // Baseline: the hash recorded when we wrote the file. Markers from the 06 release carry no hashes,
        // so for a same-version marker the shipped content is the only baseline we can prove.
        let baseline = match marker.hashes.get(name) {
            Some(hash) => Some(hash.clone()),
            None if marker.version == SKILL_VERSION => Some(skill::sha256_hex(shipped)),
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
    } else if marker.version != SKILL_VERSION {
        InstallState::Outdated
    } else {
        InstallState::Current
    };
    let reason = match state {
        InstallState::Current => "Installed and matches this release.".into(),
        InstallState::Outdated => format!("Installed version {} differs from release {SKILL_VERSION}.", marker.version),
        InstallState::Modified => format!("Managed files were edited locally: {}.", modified.join(", ")),
        _ => String::new(),
    };
    (state, Some(marker.version), modified, unknown, reason)
}

fn join_target(manager: &DesktopManager, scope: &str, project: Option<PathBuf>) -> Result<PathBuf, String> {
    skill::target_directory(&manager.environment, scope, project.as_deref())
}

/// Copies every modified managed file into a timestamped backup folder beside the skill, before overwrite.
fn backup_modified(directory: &Path, modified: &[String]) -> Result<Option<PathBuf>, String> {
    if modified.is_empty() {
        return Ok(None);
    }
    let base = directory.parent().ok_or("Invalid target directory")?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default();
    let backup = base.join(format!(".multi-search-backup-{stamp}-{}", std::process::id()));
    for name in modified {
        let source = directory.join(name);
        let destination = backup.join(name);
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("Cannot create backup folder: {e}"))?;
        }
        fs::copy(&source, &destination).map_err(|e| format!("Cannot back up {name}: {e}"))?;
    }
    Ok(Some(backup))
}

impl DesktopManager {
    /// Updates an installed skill that this tool manages. Modified files need `confirm_overwrite`
    /// and are backed up first. The old skill stays in place until the new one is verified.
    pub fn skill_update(&self, scope: &str, project: Option<PathBuf>, confirm_overwrite: bool) -> UpdateOutcome {
        let target = match join_target(self, scope, project.clone()) {
            Ok(target) => target,
            Err(reason) => return UpdateOutcome { status: "blocked".into(), verified: false, backup: None, reason },
        };
        let (state, _, modified, unknown, _) = classify(&target);
        let plan = plan_update(&state, &modified, &unknown);
        if !plan.can_update {
            return UpdateOutcome { status: "blocked".into(), verified: false, backup: None, reason: plan.reason };
        }
        if plan.backup_required && !confirm_overwrite {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason: format!("Confirmation required: local edits in {}.", modified.join(", ")),
            };
        }
        // Compatibility is checked by the same path as install; an incompatible CLI blocks the update.
        let cli = self.detect_cli(None).user;
        if cli.status != "ready" {
            return UpdateOutcome {
                status: "blocked".into(),
                verified: false,
                backup: None,
                reason: format!("The CLI is not discoverable ({}). Install the CLI first.", cli.status),
            };
        }
        if let Err(reason) = self.check_compatibility(cli.path.as_deref().unwrap_or_default()) {
            return UpdateOutcome { status: "blocked".into(), verified: false, backup: None, reason };
        }
        let backup = match backup_modified(&target, &modified) {
            Ok(backup) => backup,
            Err(reason) => return UpdateOutcome { status: "failed".into(), verified: false, backup: None, reason },
        };
        let backup_text = backup.as_ref().map(|p| p.to_string_lossy().into_owned());
        // Stage the new release beside the target so a failed write never leaves a half-updated skill.
        let Some(base) = target.parent() else {
            return UpdateOutcome { status: "failed".into(), verified: false, backup: backup_text, reason: "Invalid target".into() };
        };
        let staging = base.join(format!(
            ".multi-search-update-{}-{}",
            std::process::id(),
            skill::STAGING_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        if let Err(reason) = skill::write_directory(&staging) {
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome { status: "failed".into(), verified: false, backup: backup_text, reason: format!("Update failed; the installed skill was kept. {reason}") };
        }
        // Swap: move the old folder aside, put the verified new folder in place, then drop the old one.
        let old = base.join(format!(".multi-search-old-{}-{}", std::process::id(), skill::STAGING_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
        if let Err(error) = fs::rename(&target, &old) {
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome { status: "failed".into(), verified: false, backup: backup_text, reason: format!("Update failed; the installed skill was kept. {error}") };
        }
        if let Err(error) = fs::rename(&staging, &target) {
            // Restore the old folder so the user keeps a usable skill.
            let _ = fs::rename(&old, &target);
            let _ = fs::remove_dir_all(&staging);
            return UpdateOutcome { status: "failed".into(), verified: false, backup: backup_text, reason: format!("Update failed; the installed skill was kept. {error}") };
        }
        match skill::verify_directory(&target) {
            Ok(()) => {
                let _ = fs::remove_dir_all(&old);
                UpdateOutcome { status: "updated".into(), verified: true, backup: backup_text, reason: "Updated and verified. Start a new Claude Code session to load it.".into() }
            }
            Err(reason) => {
                // Verification failed: remove the new folder and restore the old one.
                let _ = fs::remove_dir_all(&target);
                let _ = fs::rename(&old, &target);
                UpdateOutcome { status: "failed".into(), verified: false, backup: backup_text, reason: format!("Update failed verification; the installed skill was kept. {reason}") }
            }
        }
    }

    /// Plans removal: shows exactly which files would be deleted and which are kept.
    pub fn skill_remove_plan(&self, scope: &str, project: Option<PathBuf>) -> Result<RemovePlan, String> {
        let target = join_target(self, scope, project)?;
        let (state, _, _, unknown, _) = classify(&target);
        Ok(plan_remove(&state, &unknown))
    }

    /// Removes only the files this tool installed, after confirmation. Never deletes the skills folder.
    pub fn skill_remove(&self, scope: &str, project: Option<PathBuf>, confirmed: bool) -> RemoveOutcome {
        let target = match join_target(self, scope, project) {
            Ok(target) => target,
            Err(reason) => return RemoveOutcome { status: "blocked".into(), deleted: vec![], kept: vec![], reason },
        };
        let (state, _, _, unknown, _) = classify(&target);
        let plan = plan_remove(&state, &unknown);
        if !plan.can_remove {
            return RemoveOutcome { status: "blocked".into(), deleted: vec![], kept: plan.will_keep, reason: plan.reason };
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
        for name in &plan.will_delete {
            let path = target.join(name);
            if path.is_file() && fs::remove_file(&path).is_ok() {
                deleted.push(name.clone());
            }
        }
        // Remove the now-empty references folder and the skill folder only if nothing else is left.
        let _ = fs::remove_dir(target.join("references"));
        let _ = fs::remove_dir(&target);
        let kept = plan.will_keep.clone();
        // Success means every managed file is gone; kept user content never counts against it.
        let managed_left = plan.will_delete.iter().any(|name| target.join(name).exists());
        if !managed_left {
            RemoveOutcome { status: "removed".into(), deleted, kept, reason: "Removed. Other files and skills were kept.".into() }
        } else {
            RemoveOutcome { status: "failed".into(), deleted, kept, reason: "Removal could not be confirmed; re-check the folder.".into() }
        }
    }

    /// Read-only: reports what is installed without writing anything.
    pub fn skill_status(&self, scope: &str, project: Option<PathBuf>) -> Result<SkillStatus, String> {
        let target = join_target(self, scope, project)?;
        let (state, installed_version, modified_files, unknown_entries, reason) = classify(&target);
        Ok(SkillStatus {
            host: "claude-code".into(),
            scope: scope.into(),
            target: Some(target.to_string_lossy().into_owned()),
            state,
            installed_version,
            release_version: SKILL_VERSION.into(),
            managed_files: skill::file_names(),
            modified_files,
            unknown_entries,
            reason,
        })
    }
}

/// Pure planning: decides update eligibility from the classified state.
pub(crate) fn plan_update(state: &InstallState, modified: &[String], unknown: &[String]) -> UpdatePlan {
    let (status, can_update, backup_required, reason) = match state {
        InstallState::Absent => ("absent", false, false, "Nothing to update. Install the Skill first."),
        InstallState::Current => ("current", false, false, "Already up to date."),
        InstallState::Unknown => ("unknown", false, false, "Not managed by this tool; update is refused."),
        InstallState::Outdated => ("ready", true, false, "Update to this release. Unmodified files only."),
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
            let mut will_delete: Vec<String> = FILES.iter().map(|(n, _)| (*n).to_string()).collect();
            will_delete.push(MARKER.into());
            RemovePlan {
                status: "ready".into(),
                reason: "Removes only the files this tool installed. Your other files and skills stay.".into(),
                will_delete,
                will_keep: unknown.to_vec(),
                can_remove: true,
            }
        }
    }
}
