//! Installs the CLI-only Skill for Claude Code. The CLI stays the only search implementation.
use crate::{process, DesktopManager, RuntimeEnvironment};
use serde::Serialize;
use std::{
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

const SKILL_NAME: &str = "multi-search";
const SKILL_VERSION: &str = "1";
const MARKER: &str = ".multi-search-install.json";
static STAGING_ID: AtomicU64 = AtomicU64::new(0);

/// Files shipped with this product release, embedded so the desktop app never reads a loose copy.
const FILES: [(&str, &str); 3] = [
    (
        "SKILL.md",
        include_str!("../../skill/multi-search/SKILL.md"),
    ),
    (
        "references/cli.md",
        include_str!("../../skill/multi-search/references/cli.md"),
    ),
    (
        "references/verification.md",
        include_str!("../../skill/multi-search/references/verification.md"),
    ),
];

/// Flags the Skill relies on, per subcommand, as printed by the CLI's own `--help`.
const REQUIRED_FLAGS: [(&str, &[&str]); 3] = [
    ("search", &["--route", "--expand", "--format"]),
    ("fetch", &["--full-content", "--format"]),
    ("read", &["--keyword", "--offset", "--format"]),
];

#[derive(Clone, Serialize)]
pub struct SkillPlan {
    pub host: String,
    pub scope: String,
    pub target: Option<String>,
    /// ready | exists | invalid_scope | cli_missing | cli_incompatible
    pub status: String,
    pub reason: String,
    pub files: Vec<String>,
    pub can_install: bool,
}

#[derive(Clone, Serialize)]
pub struct SkillInstall {
    /// installed | blocked | failed
    pub status: String,
    pub target: Option<String>,
    pub verified: bool,
    pub reason: String,
    pub files: Vec<String>,
}

fn file_names() -> Vec<String> {
    FILES.iter().map(|(name, _)| (*name).to_string()).collect()
}

fn home_directory(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    environment
        .variables
        .get("USERPROFILE")
        .or_else(|| environment.variables.get("HOME"))
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
}

/// Resolves the skill directory; the parent `.claude` directory is the only one this module creates.
fn target_directory(
    environment: &RuntimeEnvironment,
    scope: &str,
    project: Option<&Path>,
) -> Result<PathBuf, String> {
    let base = match scope {
        "global" => home_directory(environment)
            .ok_or_else(|| "The user profile directory is not available".to_string())?,
        "project" => {
            let project = project.ok_or_else(|| "Select the project directory".to_string())?;
            if !project.is_absolute() || !project.is_dir() {
                return Err("Select an existing absolute project directory".into());
            }
            project.to_path_buf()
        }
        _ => return Err("Scope must be global or project".into()),
    };
    Ok(base.join(".claude").join("skills").join(SKILL_NAME))
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

fn verify_directory(directory: &Path) -> Result<(), String> {
    for (name, expected) in FILES {
        let actual = fs::read_to_string(directory.join(name))
            .map_err(|_| format!("{name} is missing after writing"))?;
        if actual != expected {
            return Err(format!("{name} does not match the released content"));
        }
    }
    let marker = fs::read_to_string(directory.join(MARKER))
        .map_err(|_| "The install marker is missing".to_string())?;
    let marker: serde_json::Value =
        serde_json::from_str(&marker).map_err(|_| "The install marker is invalid".to_string())?;
    if marker["managed_by"] != "multi-search-desktop" || marker["skill_version"] != SKILL_VERSION {
        return Err("The install marker does not match this release".into());
    }
    Ok(())
}

fn write_directory(directory: &Path) -> Result<(), String> {
    for (name, content) in FILES {
        let path = directory.join(name);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("Cannot create {name}: {e}"))?;
        }
        fs::write(&path, content).map_err(|e| format!("Cannot write {name}: {e}"))?;
    }
    let marker = serde_json::json!({
        "managed_by": "multi-search-desktop",
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "files": file_names(),
    });
    fs::write(directory.join(MARKER), format!("{marker}\n"))
        .map_err(|e| format!("Cannot write {MARKER}: {e}"))?;
    verify_directory(directory)
}

impl DesktopManager {
    pub fn skill_plan(&self, scope: &str, project: Option<PathBuf>) -> SkillPlan {
        let target = match target_directory(&self.environment, scope, project.as_deref()) {
            Ok(target) => target,
            Err(reason) => return blocked_plan(scope, "invalid_scope", reason, None),
        };
        let target_text = target.to_string_lossy().into_owned();
        // symlink_metadata also sees dangling links, which a rename would not replace either.
        if fs::symlink_metadata(&target).is_ok() {
            return blocked_plan(
                scope,
                "exists",
                "A multi-search skill already exists here; this release does not overwrite it.".into(),
                Some(target_text),
            );
        }
        let cli = self.detect_cli(None).user;
        if cli.status != "ready" {
            let reason = format!(
                "The CLI is not discoverable from the user environment ({}). Install the CLI first.",
                cli.status
            );
            return blocked_plan(scope, "cli_missing", reason, Some(target_text));
        }
        if let Err(reason) = self.check_compatibility(cli.path.as_deref().unwrap_or_default()) {
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
        match verify_directory(&target) {
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

    fn check_compatibility(&self, cli_path: &str) -> Result<(), String> {
        let cli = PathBuf::from(cli_path);
        for (subcommand, flags) in REQUIRED_FLAGS {
            let output = process::bounded(
                &cli,
                &[subcommand.into(), "--help".into()],
                &self.environment,
                Duration::from_secs(5),
            )
            .map_err(|_| "The CLI help could not be read".to_string())?;
            if output.timed_out || output.code != Some(0) {
                return Err(format!("The CLI `{subcommand} --help` failed; update the CLI."));
            }
            if let Some(flag) = flags.iter().find(|flag| !output.stdout.contains(*flag)) {
                return Err(format!(
                    "The installed CLI does not support `{subcommand} {flag}`; update the CLI to match this Skill."
                ));
            }
        }
        Ok(())
    }
}
