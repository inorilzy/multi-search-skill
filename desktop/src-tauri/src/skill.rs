//! Installs the CLI-only Skill for Claude Code. The CLI stays the only search implementation.
use crate::{process, DesktopManager, RuntimeEnvironment};
use serde::Serialize;
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};

pub(crate) const SKILL_NAME: &str = "multi-search";
pub(crate) const SKILL_VERSION: &str = "1";
pub(crate) const MARKER: &str = ".multi-search-install.json";

/// Files shipped with this product release, embedded so the desktop app never reads a loose copy.
pub(crate) const FILES: [(&str, &str); 3] = [
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
pub(crate) const REQUIRED_FLAGS: [(&str, &[&str]); 4] = [
    ("search", &["--route", "--expand", "--format", "--source", "--count", "--timeout"]),
    ("fetch", &["--full-content", "--format", "--url", "--url-file"]),
    ("read", &["--keyword", "--offset", "--format", "--limit"]),
    ("doctor", &["--no-keys", "--format"]),
];

type Requirements = BTreeMap<String, Vec<String>>;
fn requirements() -> Requirements {
    REQUIRED_FLAGS.iter().map(|(command, flags)| (command.to_string(), flags.iter().map(|f| f.to_string()).collect())).collect()
}

fn registry_path(environment: &RuntimeEnvironment) -> Result<PathBuf, String> {
    Ok(home_directory(environment).ok_or("缺少用户目录")?.join(".multi-search/managed-skills.json"))
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
    fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("无法记录受管 Skill：{e}"))?;
    crate::secure_temp::replace_file(&path, &serde_json::to_vec(&targets).unwrap())
        .map_err(|e| format!("无法写入受管 Skill 记录：{e}"))
}

fn installed_requirements(environment: &RuntimeEnvironment) -> Result<Requirements, String> {
    let mut targets = managed_targets(environment)?;
    // Legacy global installs predate the registry; inspect this one known location, never scan projects.
    let global = target_directory(environment, "global", None)?;
    if fs::symlink_metadata(global.join(MARKER)).is_ok() && !targets.contains(&global) { targets.push(global); }
    let mut required = requirements();
    for target in targets {
        if !crate::skill_manage::safe_managed_paths(&target) {
            return Err(format!("unverified: unsafe managed Skill path {}", target.display()));
        }
        let raw = fs::read(target.join(MARKER)).map_err(|_| format!("unverified: missing managed Skill record {}", target.display()))?;
        let value: serde_json::Value = serde_json::from_slice(&raw).map_err(|_| "unverified: corrupt managed Skill record")?;
        if value["managed_by"] != "multi-search-desktop" || value["skill"] != SKILL_NAME || value["skill_version"] != SKILL_VERSION {
            return Err("unverified: unknown managed Skill record or version".into());
        }
        let files = value["files"].as_array().ok_or("unverified: missing Skill file inventory")?;
        if files.len() != FILES.len() || !FILES.iter().all(|(name, _)| files.iter().any(|v| v.as_str() == Some(name))) {
            return Err("unverified: unknown Skill file inventory".into());
        }
        let parsed = match value.get("requirements") {
            None => requirements(), // Legacy v1 maps to the full documented capability set.
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

pub(crate) fn file_names() -> Vec<String> {
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
pub(crate) fn target_directory(
    environment: &RuntimeEnvironment,
    scope: &str,
    project: Option<&Path>,
) -> Result<PathBuf, String> {
    let base = match scope {
        "global" => home_directory(environment)
            .ok_or_else(|| "用户目录不可用".to_string())?,
        "project" => {
            let project = project.ok_or_else(|| "请选择项目目录".to_string())?;
            if !project.is_absolute() || !project.is_dir() {
                return Err("请选择已存在的项目绝对路径".into());
            }
            project.to_path_buf()
        }
        _ => return Err("作用范围必须是全局或项目".into()),
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

pub(crate) fn verify_directory(directory: &Path) -> Result<(), String> {
    for (name, expected) in FILES {
        let actual = fs::read_to_string(directory.join(name))
            .map_err(|_| format!("{name} is missing after writing"))?;
        if actual != expected {
            return Err(format!("{name} does not match the released content"));
        }
    }
    let marker = fs::read_to_string(directory.join(MARKER))
        .map_err(|_| "安装标记缺失".to_string())?;
    let marker: serde_json::Value =
        serde_json::from_str(&marker).map_err(|_| "安装标记无效".to_string())?;
    if marker["managed_by"] != "multi-search-desktop" || marker["skill_version"] != SKILL_VERSION {
        return Err("安装标记与本版本不一致".into());
    }
    Ok(())
}

pub(crate) fn sha256_hex(content: &str) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(content.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub(crate) fn write_directory(directory: &Path) -> Result<(), String> {
    for (name, content) in FILES {
        let path = directory.join(name);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("无法创建 {name}：{e}"))?;
        }
        fs::write(&path, content).map_err(|e| format!("无法写入 {name}：{e}"))?;
    }
    // Hashes let later status and update checks tell an unmodified file from a user edit.
    let hashes: serde_json::Map<String, serde_json::Value> = FILES
        .iter()
        .map(|(name, content)| ((*name).to_string(), serde_json::Value::String(sha256_hex(content))))
        .collect();
    let marker = serde_json::json!({
        "managed_by": "multi-search-desktop",
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "files": file_names(),
        "hashes": hashes,
        "requirements": requirements(),
    });
    fs::write(directory.join(MARKER), format!("{marker}\n"))
        .map_err(|e| format!("无法写入 {MARKER}：{e}"))?;
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
                "目标目录已有 multi-search Skill，本版本不会覆盖。".into(),
                Some(target_text),
            );
        }
        let cli = self.detect_cli().user;
        if cli.status != "ready" {
            let reason = format!(
                "无法发现 CLI from the user environment ({}). Install the CLI first.",
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
            reason: "可以安装到上方显示的目标目录。".into(),
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
            return failed("目标无效 directory".into());
        };
        let staging = match crate::secure_temp::create_dir(base, ".multi-search-staging-") {
            Ok(staging) => staging,
            Err(error) => return failed(format!("无法准备安装目录：{error}")),
        };
        if let Err(reason) = write_directory(&staging) {
            let _ = fs::remove_dir_all(&staging);
            return failed(reason);
        }
        let Some(skills_dir) = target.parent() else {
            let _ = fs::remove_dir_all(&staging);
            return failed("目标无效 directory".into());
        };
        if let Err(error) = fs::create_dir_all(skills_dir) {
            let _ = fs::remove_dir_all(&staging);
            return failed(format!("无法创建 skills 目录：{error}"));
        }
        if fs::symlink_metadata(&target).is_ok() {
            let _ = fs::remove_dir_all(&staging);
            return blocked("目标目录出现了新的 multi-search Skill，未做任何修改。".into());
        }
        if let Err(error) = fs::rename(&staging, &target) {
            let _ = fs::remove_dir_all(&staging);
            return failed(format!("无法把 Skill 放到目标目录：{error}"));
        }
        match verify_directory(&target).and_then(|()| record_target(&self.environment, &target, true)) {
            Ok(()) => SkillInstall {
                status: "installed".into(),
                target: plan.target.clone(),
                verified: true,
                reason: "已安装并校验；请新开 Claude Code 会话以加载。".into(),
                files: file_names(),
            },
            Err(reason) => {
                // We created this folder with the rename above, so removing it leaves no user content behind.
                let _ = fs::remove_dir_all(&target);
                failed(format!("已安装文件未通过校验，已移除：{reason}"))
            }
        }
    }

    pub(crate) fn check_compatibility(&self, cli_path: &str) -> Result<(), String> {
        self.check_requirements(cli_path, requirements())
    }

    pub(crate) fn check_managed_compatibility(&self, cli_path: &str) -> Result<(), String> {
        self.check_requirements(cli_path, installed_requirements(&self.environment)?)
    }

    fn check_requirements(&self, cli_path: &str, required: Requirements) -> Result<(), String> {
        let cli = PathBuf::from(cli_path);
        for (subcommand, flags) in required {
            let output = process::bounded(
                &cli,
                &[subcommand.clone(), "--help".into()],
                &self.environment,
                Duration::from_secs(5),
            )
            .map_err(|_| "无法读取 CLI 帮助".to_string())?;
            if output.timed_out || output.code != Some(0) {
                return Err(format!("CLI 的 `{subcommand} --help` 执行失败；请更新 CLI。"));
            }
            let help_tokens: Vec<_> = output.stdout.split(|c: char| !(c.is_ascii_alphanumeric() || c == '-' || c == '_')).collect();
            if let Some(flag) = flags.iter().find(|flag| !help_tokens.contains(&flag.as_str())) {
                return Err(format!(
                    "已安装的 CLI 不支持 `{subcommand} {flag}`；请更新 CLI 以匹配该 Skill。"
                ));
            }
        }
        Ok(())
    }
}
