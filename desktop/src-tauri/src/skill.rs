//! Installs the CLI-only Skill for Claude Code. The CLI stays the only search implementation.
use crate::skill_common::{
    self, home_directory, skill_version, target_directory, Requirements, FILES, MARKER, SKILL_NAME,
};
use crate::diagnostics::CliDiscovery;
use crate::{process, RuntimeEnvironment};
use serde::Serialize;
use std::{
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

pub(crate) static STAGING_ID: AtomicU64 = AtomicU64::new(0);

// Re-exported so `skill_manage` can import everything Skill-related from one
// module without importing `skill` itself (which would create a cycle).
pub(crate) use crate::skill_common::{file_names, verify_directory, write_directory};

fn registry_path(environment: &RuntimeEnvironment) -> Result<PathBuf, String> {
    Ok(home_directory(environment).ok_or("Missing user profile")?.join(".multi-search/managed-skills.json"))
}

fn managed_targets(environment: &RuntimeEnvironment) -> Result<Vec<PathBuf>, String> {
    let path = registry_path(environment)?;
    let targets: Vec<PathBuf> = match fs::read(&path) {
        Ok(raw) => serde_json::from_slice(&raw).map_err(|_| "unverified: invalid managed Skill registry")?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(_) => return Err("unverified: unreadable managed Skill registry".into()),
    };
    if targets.iter().any(|p| !p.is_absolute() || !p.ends_with(".claude/skills/multi-search")) {
        return Err("unverified: invalid managed Skill target".into());
    }
    Ok(targets)
}

pub(crate) fn record_target(environment: &RuntimeEnvironment, target: &Path, present: bool) -> Result<(), String> {
    let mut targets = managed_targets(environment)?;
    targets.retain(|p| p != target);
    if present { targets.push(target.to_path_buf()); }
    let path = registry_path(environment)?;
    fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("Cannot record managed Skill: {e}"))?;
    let temp = path.with_extension(format!("{}-{}.tmp", std::process::id(), STAGING_ID.fetch_add(1, Ordering::Relaxed)));
    fs::write(&temp, serde_json::to_vec(&targets).unwrap()).map_err(|e| format!("Cannot record managed Skill: {e}"))?;
    fs::rename(temp, path).map_err(|e| format!("Cannot commit managed Skill registry: {e}"))
}

fn installed_requirements(environment: &RuntimeEnvironment) -> Result<Requirements, String> {
    let mut targets = managed_targets(environment)?;
    // Legacy global installs predate the registry; inspect this one known location, never scan projects.
    let global = target_directory(environment, "global", None)?;
    if fs::symlink_metadata(global.join(MARKER)).is_ok() && !targets.contains(&global) { targets.push(global); }
    let mut required = skill_common::requirements();
    for target in targets {
        if !skill_common::safe_managed_paths(&target) {
            return Err(format!("unverified: unsafe managed Skill path {}", target.display()));
        }
        let raw = fs::read(target.join(MARKER)).map_err(|_| format!("unverified: missing managed Skill record {}", target.display()))?;
        let value: serde_json::Value = serde_json::from_slice(&raw).map_err(|_| "unverified: corrupt managed Skill record")?;
        if value["managed_by"] != "multi-search-desktop" || value["skill"] != SKILL_NAME || value["skill_version"] != skill_version() {
            return Err("unverified: unknown managed Skill record or version".into());
        }
        let files = value["files"].as_array().ok_or("unverified: missing Skill file inventory")?;
        if files.len() != FILES.len() || !FILES.iter().all(|(name, _)| files.iter().any(|v| v.as_str() == Some(name))) {
            return Err("unverified: unknown Skill file inventory".into());
        }
        let parsed = match value.get("requirements") {
            None => skill_common::requirements(), // Legacy v1 maps to the full documented capability set.
            Some(value) => serde_json::from_value::<Requirements>(value.clone()).map_err(|_| "unverified: invalid Skill requirements")?,
        };
        if parsed.is_empty() || parsed.iter().any(|(c, flags)| c.is_empty() || c.starts_with('-') || c.contains(char::is_whitespace) || flags.is_empty() || flags.iter().any(|f| !f.starts_with("--") || f.contains(char::is_whitespace))) {
            return Err("unverified: invalid Skill capability contract".into());
        }
        for (command, flags) in parsed {
            let entry = required.entry(command).or_default();
            for flag in flags { if !entry.contains(&flag) { entry.push(flag); } }
        }
    }
    Ok(required)
}

#[derive(Clone, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct SkillPlan {
    pub host: String,
    pub scope: String,
    pub target: Option<String>,
    /// ready | exists | invalid_scope | cli_missing | cli_incompatible, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub reason: String,
    pub files: Vec<String>,
    pub can_install: bool,
}

#[derive(Clone, Serialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(feature = "ts", ts(export_to = "types.d.ts"))]
pub struct SkillInstall {
    /// installed | blocked | failed, or a new value added later; UI must fall back to a raw string.
    pub status: String,
    pub target: Option<String>,
    pub verified: bool,
    pub reason: String,
    pub files: Vec<String>,
}

fn blocked_plan(scope: &str, status: &str, reason: String, target: Option<String>) -> SkillPlan {
    SkillPlan {
        host: "claude-code".into(),
        scope: scope.into(),
        target,
        status: status.into(),
        reason,
        files: file_names(),
        can_install: false,
    }
}

/// Skill install/capability domain. `discovery` supplies the user-CLI lookup
/// the plan needs; nothing else is shared with the manager.
pub(crate) struct SkillManager<'a> {
    pub(crate) environment: &'a RuntimeEnvironment,
    pub(crate) discovery: CliDiscovery<'a>,
}

impl SkillManager<'_> {
    pub fn skill_plan(&self, scope: &str, project: Option<PathBuf>) -> SkillPlan {
        let target = match target_directory(&self.environment, scope, project.as_deref()) {
            Ok(target) => target,
            Err(reason) => return blocked_plan(scope, "invalid_scope", reason, None),
        };
        let target_text = target.to_string_lossy().into_owned();
        if !skill_common::safe_managed_paths(&target) {
            return blocked_plan(scope, "invalid_scope", "Unsafe linked managed path".into(), Some(target_text));
        }
        // symlink_metadata also sees dangling links, which a rename would not replace either.
        if fs::symlink_metadata(&target).is_ok() {
            return blocked_plan(
                scope,
                "exists",
                "A multi-search skill already exists here; this release does not overwrite it.".into(),
                Some(target_text),
            );
        }
        let cli = self.discovery.detect().user;
        if cli.status != "ready" {
            let reason = format!(
                "The CLI is not discoverable from the user environment ({}). Install the CLI first.",
                cli.status
            );
            return blocked_plan(scope, "cli_missing", reason, Some(target_text));
        }
        if let Err(reason) = check_compatibility(self.environment, cli.path.as_deref().unwrap_or_default()) {
            return blocked_plan(scope, "cli_incompatible", reason, Some(target_text));
        }
        SkillPlan {
            host: "claude-code".into(),
            scope: scope.into(),
            target: Some(target_text),
            status: "ready".into(),
            reason: "Ready to install into the target directory shown above.".into(),
            files: file_names(),
            can_install: true,
        }
    }

    pub fn skill_install(&self, scope: &str, project: Option<PathBuf>) -> SkillInstall {
        let plan = self.skill_plan(scope, project);
        let blocked = |reason: String| SkillInstall {
            status: "blocked".into(),
            target: plan.target.clone(),
            verified: false,
            reason,
            files: file_names(),
        };
        if !plan.can_install {
            return blocked(plan.reason.clone());
        }
        let target = PathBuf::from(plan.target.clone().unwrap_or_default());
        let failed = |reason: String| SkillInstall {
            status: "failed".into(),
            target: plan.target.clone(),
            verified: false,
            reason,
            files: file_names(),
        };
        if !skill_common::safe_managed_paths(&target) {
            return blocked("Unsafe linked managed path".into());
        }
        // Staging sits beside skills/, not inside it, so a half-written folder never appears as a skill.
        let Some(base) = target.parent().and_then(Path::parent) else {
            return failed("Invalid target directory".into());
        };
        let staging = base.join(format!(
            ".multi-search-staging-{}-{}",
            std::process::id(),
            STAGING_ID.fetch_add(1, Ordering::Relaxed)
        ));
        if let Err(error) = fs::create_dir_all(&staging) {
            return failed(format!("Cannot prepare the install folder: {error}"));
        }
        if let Err(reason) = write_directory(&staging) {
            let _ = fs::remove_dir_all(&staging);
            return failed(reason);
        }
        let Some(skills_dir) = target.parent() else {
            let _ = fs::remove_dir_all(&staging);
            return failed("Invalid target directory".into());
        };
        if let Err(error) = fs::create_dir_all(skills_dir) {
            let _ = fs::remove_dir_all(&staging);
            return failed(format!("Cannot create the skills folder: {error}"));
        }
        if fs::symlink_metadata(&target).is_ok() {
            let _ = fs::remove_dir_all(&staging);
            return blocked("A multi-search skill appeared at the target; nothing was changed.".into());
        }
        if let Err(error) = fs::rename(&staging, &target) {
            let _ = fs::remove_dir_all(&staging);
            return failed(format!("Cannot place the skill at the target: {error}"));
        }
        match verify_directory(&target).and_then(|()| record_target(&self.environment, &target, true)) {
            Ok(()) => SkillInstall {
                status: "installed".into(),
                target: plan.target.clone(),
                verified: true,
                reason: "Installed and verified. Start a new Claude Code session to load it.".into(),
                files: file_names(),
            },
            Err(reason) => {
                // We created this folder with the rename above, so removing it leaves no user content behind.
                let _ = fs::remove_dir_all(&target);
                failed(format!("Installed files failed verification and were removed: {reason}"))
            }
        }
    }

}

/// Pure function: checks the installed CLI against the shipped capability set.
pub(crate) fn check_compatibility(
    environment: &RuntimeEnvironment,
    cli_path: &str,
) -> Result<(), String> {
    check_requirements(environment, cli_path, skill_common::requirements())
}

/// Pure function: checks a candidate CLI against the requirements recorded by
/// managed Skill installs. Used by install/update previews.
pub(crate) fn check_managed_compatibility(
    environment: &RuntimeEnvironment,
    cli_path: &str,
) -> Result<(), String> {
    check_requirements(environment, cli_path, installed_requirements(environment)?)
}

fn check_requirements(
    environment: &RuntimeEnvironment,
    cli_path: &str,
    required: Requirements,
) -> Result<(), String> {
        let cli = PathBuf::from(cli_path);
        for (subcommand, flags) in required {
            let output = process::bounded(
                &cli,
                &[subcommand.clone(), "--help".into()],
                environment,
                Duration::from_secs(5),
            )
            .map_err(|_| "The CLI help could not be read".to_string())?;
            if output.timed_out || output.code != Some(0) {
                return Err(format!("The CLI `{subcommand} --help` failed; update the CLI."));
            }
            let help_tokens: Vec<_> = output.stdout.split(|c: char| !(c.is_ascii_alphanumeric() || c == '-' || c == '_')).collect();
            if let Some(flag) = flags.iter().find(|flag| !help_tokens.contains(&flag.as_str())) {
                return Err(format!(
                    "The installed CLI does not support `{subcommand} {flag}`; update the CLI to match this Skill."
                ));
            }
        }
        Ok(())
}
