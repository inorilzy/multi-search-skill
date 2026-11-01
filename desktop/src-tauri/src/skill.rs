//! Installs the CLI-only Skill for Claude Code or the cross-tool `.agents/skills` location. The CLI stays the only search implementation.
use crate::skill_common::{
    self, home_directory, reload_hint, target_directory, Requirements, FILES, HOSTS, MARKER, SKILL_NAME,
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
    let known = |p: &PathBuf| HOSTS.iter().any(|(_, folder)| p.ends_with(Path::new(folder).join("skills").join(SKILL_NAME)));
    if targets.iter().any(|p| !p.is_absolute() || !known(p)) {
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
    let global = target_directory(environment, "claude-code", "global", None)?;
    if fs::symlink_metadata(global.join(MARKER)).is_ok() && !targets.contains(&global) { targets.push(global); }
    let mut required = skill_common::requirements();
    for target in targets {
        if !skill_common::safe_managed_paths(&target) {
            return Err(format!("unverified: unsafe managed Skill path {}", target.display()));
        }
        let raw = fs::read(target.join(MARKER)).map_err(|_| format!("unverified: missing managed Skill record {}", target.display()))?;
        let value: serde_json::Value = serde_json::from_slice(&raw).map_err(|_| "unverified: corrupt managed Skill record")?;
        // Ownership is managed_by + skill name. An older release of our own Skill is
        // still a known record: its recorded `requirements` (or the legacy full set)
        // is exactly what a new CLI must keep supporting, so a version that merely
        // differs from this build must not block a CLI update.
        let version_ok = value["skill_version"].as_str().is_some_and(|v| !v.trim().is_empty());
        if value["managed_by"] != "multi-search-desktop" || value["skill"] != SKILL_NAME || !version_ok {
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

fn blocked_plan(host: &str, scope: &str, status: &str, reason: String, target: Option<String>) -> SkillPlan {
    SkillPlan {
        host: host.into(),
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
    pub fn skill_plan(&self, host: &str, scope: &str, project: Option<PathBuf>) -> SkillPlan {
        let target = match target_directory(&self.environment, host, scope, project.as_deref()) {
            Ok(target) => target,
            Err(reason) => return blocked_plan(host, scope, "invalid_scope", reason, None),
        };
        let target_text = target.to_string_lossy().into_owned();
        if !skill_common::safe_managed_paths(&target) {
            return blocked_plan(host, scope, "invalid_scope", "目标路径含符号链接或非目录项，已拒绝".into(), Some(target_text));
        }
        // symlink_metadata also sees dangling links, which a rename would not replace either.
        if fs::symlink_metadata(&target).is_ok() {
            return blocked_plan(
                host,
                scope,
                "exists",
                "这里已有 multi-search Skill；安装不会覆盖，请在下方“已安装 Skill”中检查或更新。".into(),
                Some(target_text),
            );
        }
        let cli = self.discovery.detect().user;
        if cli.status != "ready" {
            let reason = format!(
                "在用户 PATH 中找不到 multi-search CLI（{}）。请先在“安装 CLI”页安装并加入 PATH，然后重启本应用。",
                cli.status
            );
            return blocked_plan(host, scope, "cli_missing", reason, Some(target_text));
        }
        if let Err(reason) = check_compatibility(self.environment, cli.path.as_deref().unwrap_or_default()) {
            return blocked_plan(host, scope, "cli_incompatible", reason, Some(target_text));
        }
        SkillPlan {
            host: host.into(),
            scope: scope.into(),
            target: Some(target_text),
            status: "ready".into(),
            reason: "可以安装到上面的目标目录。".into(),
            files: file_names(),
            can_install: true,
        }
    }

    pub fn skill_install(&self, host: &str, scope: &str, project: Option<PathBuf>) -> SkillInstall {
        let plan = self.skill_plan(host, scope, project);
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
            return blocked("目标路径含符号链接或非目录项，已拒绝".into());
        }
        // Staging sits beside skills/, not inside it, so a half-written folder never appears as a skill.
        let Some(base) = target.parent().and_then(Path::parent) else {
            return failed("目标目录无效".into());
        };
        let staging = base.join(format!(
            ".multi-search-staging-{}-{}",
            std::process::id(),
            STAGING_ID.fetch_add(1, Ordering::Relaxed)
        ));
        if let Err(error) = fs::create_dir_all(&staging) {
            return failed(format!("无法准备安装目录：{error}"));
        }
        if let Err(reason) = write_directory(&staging) {
            let _ = fs::remove_dir_all(&staging);
            return failed(reason);
        }
        let Some(skills_dir) = target.parent() else {
            let _ = fs::remove_dir_all(&staging);
            return failed("目标目录无效".into());
        };
        if let Err(error) = fs::create_dir_all(skills_dir) {
            let _ = fs::remove_dir_all(&staging);
            return failed(format!("无法创建 skills 目录：{error}"));
        }
        if fs::symlink_metadata(&target).is_ok() {
            let _ = fs::remove_dir_all(&staging);
            return blocked("目标位置刚出现了 multi-search Skill，未做任何修改。".into());
        }
        if let Err(error) = fs::rename(&staging, &target) {
            let _ = fs::remove_dir_all(&staging);
            return failed(format!("无法把 Skill 放到目标位置：{error}"));
        }
        match verify_directory(&target).and_then(|()| record_target(&self.environment, &target, true)) {
            Ok(()) => SkillInstall {
                status: "installed".into(),
                target: plan.target.clone(),
                verified: true,
                reason: format!("已安装并校验。{}。", reload_hint(host)),
                files: file_names(),
            },
            Err(reason) => {
                // We created this folder with the rename above, so removing it leaves no user content behind.
                let _ = fs::remove_dir_all(&target);
                failed(format!("安装后的文件未通过校验，已删除：{reason}"))
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
            .map_err(|_| "无法读取 CLI 帮助".to_string())?;
            if output.timed_out || output.code != Some(0) {
                return Err(format!("CLI `{subcommand} --help` 运行失败，请更新 CLI。"));
            }
            let help_tokens: Vec<_> = output.stdout.split(|c: char| !(c.is_ascii_alphanumeric() || c == '-' || c == '_')).collect();
            if let Some(flag) = flags.iter().find(|flag| !help_tokens.contains(&flag.as_str())) {
                return Err(format!(
                    "已安装的 CLI 不支持 `{subcommand} {flag}`，请更新 CLI 以匹配本 Skill。"
                ));
            }
        }
        Ok(())
}

#[cfg(test)]
mod compatibility_tests {
    use super::*;

    #[test]
    fn older_managed_skill_preserves_requirements_and_rejects_invalid_records() {
        let root = std::env::temp_dir().join(format!("skill-compat-{}-{}", std::process::id(), STAGING_ID.fetch_add(1, Ordering::Relaxed)));
        fs::create_dir_all(&root).unwrap();
        let root = root.canonicalize().unwrap();
        let env = RuntimeEnvironment {
            app_path: vec![], user_path: vec![], cwd: root.clone(),
            variables: [("HOME".into(), root.to_string_lossy().into_owned()),
                        ("USERPROFILE".into(), root.to_string_lossy().into_owned())].into(),
        };
        let target = root.join(".agents/skills/multi-search");
        fs::create_dir_all(&target).unwrap();
        record_target(&env, &target, true).unwrap();
        let mut marker = serde_json::json!({
            "managed_by": "multi-search-desktop", "skill": SKILL_NAME,
            "skill_version": "2b87d243e3033adb",
            "files": FILES.iter().map(|(name, _)| *name).collect::<Vec<_>>(),
            "requirements": {"search": ["--old-skill-required"]}
        });
        fs::write(target.join(MARKER), serde_json::to_vec(&marker).unwrap()).unwrap();
        let required = installed_requirements(&env).expect("an older managed Skill is still verifiable");
        assert!(required["search"].contains(&"--old-skill-required".to_string()));
        assert!(required.contains_key("doctor"));
        marker["requirements"] = serde_json::json!({"search": ["invalid-flag"]});
        fs::write(target.join(MARKER), serde_json::to_vec(&marker).unwrap()).unwrap();
        assert!(installed_requirements(&env).unwrap_err().contains("capability contract"));
        marker.as_object_mut().unwrap().remove("requirements");
        fs::write(target.join(MARKER), serde_json::to_vec(&marker).unwrap()).unwrap();
        assert_eq!(installed_requirements(&env).unwrap(), skill_common::requirements());
        marker["managed_by"] = serde_json::json!("another-app");
        fs::write(target.join(MARKER), serde_json::to_vec(&marker).unwrap()).unwrap();
        assert!(installed_requirements(&env).unwrap_err().contains("unknown managed Skill"));
        fs::remove_dir_all(&root).unwrap();
    }
}
