//! Install the CLI from a controlled, checksum-verified source into a managed directory.
//!
//! No production release source is configured: `layout` returns no source outside the
//! isolated acceptance mode, so the production install is reported as unconfigured.
//! Nothing here touches the user's PATH, registry, or an existing unknown installation.
use crate::{process, DesktopManager, RuntimeEnvironment};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

const ARTIFACT: &str = "multi-search.exe";
const MARKER: &str = "multi-search-install.json";
const ACTIVE: &str = "active.json";
const MANIFEST: &str = "manifest.json";
const OWNER: &str = "multi-search-desktop";

#[derive(Deserialize)]
struct Manifest {
    version: String,
    sha256: String,
    size: u64,
}

#[derive(Serialize, Deserialize)]
struct Active {
    version: String,
    sha256: String,
}

#[derive(Serialize, Deserialize)]
struct Marker {
    owner: String,
    schema: u32,
}

#[derive(Clone, Serialize)]
pub struct InstallPlan {
    pub status: String,
    pub root: String,
    pub bin: String,
    pub version: Option<String>,
    pub reason: String,
    pub path_hint: String,
}

#[derive(Clone, Serialize)]
pub struct InstallStep {
    pub name: String,
    pub ok: bool,
    pub detail: String,
}

#[derive(Clone, Serialize)]
pub struct InstallOutcome {
    pub status: String,
    pub steps: Vec<InstallStep>,
    pub version: Option<String>,
    pub bin: Option<String>,
    pub path_hint: String,
    pub reason: String,
}

struct Layout {
    root: PathBuf,
    source: Option<PathBuf>,
}

#[derive(PartialEq)]
enum Ownership {
    Absent,
    Owned,
    Unknown,
}

type Failure = (&'static str, String);

fn layout(env: &RuntimeEnvironment) -> Result<Layout, String> {
    let isolated = env.variables.get("MULTI_SEARCH_TEST_ISOLATION").map(String::as_str) == Some("1");
    if isolated {
        let root = env
            .variables
            .get("MULTI_SEARCH_DESKTOP_INSTALL_ROOT")
            .ok_or("测试安装目录未指定")?;
        let source = env
            .variables
            .get("MULTI_SEARCH_DESKTOP_INSTALL_SOURCE")
            .map(PathBuf::from);
        return Ok(Layout {
            root: PathBuf::from(root),
            source,
        });
    }
    // Production: the controlled release source is intentionally not configured yet.
    let base = env
        .variables
        .get("LOCALAPPDATA")
        .ok_or("无法确定本机安装目录")?;
    Ok(Layout {
        root: PathBuf::from(base).join("MultiSearch").join("cli"),
        source: None,
    })
}

fn sha_file(path: &Path) -> std::io::Result<String> {
    let mut hasher = Sha256::new();
    std::io::copy(&mut fs::File::open(path)?, &mut hasher)?;
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

fn ownership(root: &Path) -> Ownership {
    if !root.exists() {
        return Ownership::Absent;
    }
    let marker = fs::read_to_string(root.join(MARKER))
        .ok()
        .and_then(|text| serde_json::from_str::<Marker>(&text).ok());
    if marker.is_some_and(|m| m.owner == OWNER) {
        return Ownership::Owned;
    }
    let empty = fs::read_dir(root)
        .map(|mut entries| entries.next().is_none())
        .unwrap_or(false);
    if empty {
        Ownership::Absent
    } else {
        Ownership::Unknown
    }
}

/// Installed only when the pointer exists and the activated binary still matches it.
fn installed(root: &Path) -> Option<Active> {
    let active: Active = serde_json::from_str(&fs::read_to_string(root.join(ACTIVE)).ok()?).ok()?;
    let digest = sha_file(&root.join("bin").join(ARTIFACT)).ok()?;
    (digest == active.sha256).then_some(active)
}

fn read_source(dir: &Path) -> Result<(Manifest, PathBuf), Failure> {
    let missing = |what: &str| ("prerequisite_missing", format!("安装来源缺少{what}"));
    let text = fs::read_to_string(dir.join(MANIFEST)).map_err(|_| missing("manifest.json"))?;
    let manifest: Manifest = serde_json::from_str(&text)
        .map_err(|_| ("integrity_failed", "安装清单无法解析，已拒绝安装".into()))?;
    let artifact = dir.join(ARTIFACT);
    if !artifact.is_file() {
        return Err(missing("multi-search.exe"));
    }
    let size = fs::metadata(&artifact).map(|m| m.len()).unwrap_or(0);
    let valid_version = !manifest.version.is_empty()
        && manifest.version.len() < 80
        && !manifest.version.contains(char::is_whitespace);
    if !valid_version || size != manifest.size {
        return Err(("integrity_failed", "安装清单与产物不一致，已拒绝安装".into()));
    }
    let digest = sha_file(&artifact).map_err(|_| missing("可读取的 multi-search.exe"))?;
    if digest != manifest.sha256.to_ascii_lowercase() {
        return Err(("integrity_failed", "产物 SHA-256 校验失败，已拒绝安装".into()));
    }
    Ok((manifest, artifact))
}

fn probe(path: &Path, env: &RuntimeEnvironment) -> Result<String, String> {
    let output = process::bounded(path, &["--version".into()], env, Duration::from_secs(3))
        .map_err(|_| "无法执行安装的 CLI".to_string())?;
    if output.timed_out || output.code != Some(0) {
        return Err("CLI 版本检查失败，已回滚".into());
    }
    output
        .stdout
        .trim()
        .strip_prefix("multi-search ")
        .map(str::to_string)
        .ok_or_else(|| "CLI 版本输出无法识别，已回滚".into())
}

fn row(status: &str, root: &Path, version: Option<String>, reason: &str) -> InstallPlan {
    let bin_dir = root.join("bin");
    InstallPlan {
        status: status.into(),
        root: root.to_string_lossy().into_owned(),
        bin: bin_dir.join(ARTIFACT).to_string_lossy().into_owned(),
        version,
        reason: reason.into(),
        path_hint: format!(
            "安装后请将 {} 加入用户 PATH，并重启终端或 Agent 宿主",
            bin_dir.to_string_lossy()
        ),
    }
}

fn outcome(status: &str, steps: Vec<InstallStep>, installed: Option<(String, PathBuf)>, reason: String) -> InstallOutcome {
    let (version, bin) = match installed {
        Some((version, bin)) => (Some(version), Some(bin.to_string_lossy().into_owned())),
        None => (None, None),
    };
    InstallOutcome {
        status: status.into(),
        steps,
        path_hint: bin
            .as_ref()
            .and_then(|b| Path::new(b).parent())
            .map(|p| format!("安装后请将 {} 加入用户 PATH，并重启终端或 Agent 宿主", p.to_string_lossy()))
            .unwrap_or_default(),
        version,
        bin,
        reason,
    }
}

fn step(steps: &mut Vec<InstallStep>, name: &str, ok: bool, detail: &str) {
    steps.push(InstallStep {
        name: name.into(),
        ok,
        detail: detail.into(),
    });
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Failure> {
    let text = serde_json::to_string_pretty(value).map_err(|_| ("failed", "无法序列化安装状态".into()))?;
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, text).map_err(|e| ("failed", format!("无法写入安装状态：{e}")))?;
    fs::rename(&tmp, path).map_err(|e| ("failed", format!("无法提交安装状态：{e}")))
}

/// Removes only staging directories created by this installer inside an owned root.
fn clear_staging(root: &Path) {
    if ownership(root) != Ownership::Owned {
        return;
    }
    if let Ok(entries) = fs::read_dir(root) {
        for entry in entries.flatten() {
            if entry.file_name().to_string_lossy().starts_with("staging-") {
                let _ = fs::remove_dir_all(entry.path());
            }
        }
    }
}

fn perform(
    env: &RuntimeEnvironment,
    root: &Path,
    source: &Path,
    steps: &mut Vec<InstallStep>,
) -> Result<(String, PathBuf), Failure> {
    let (manifest, artifact) = read_source(source)?;
    step(steps, "检查安装来源与完整性", true, "manifest 与 SHA-256 一致");

    if let Some(active) = installed(root) {
        return Err(("already_installed", format!("已安装 CLI {}，本票据不覆盖已有安装", active.version)));
    }
    if ownership(root) == Ownership::Unknown {
        return Err(("unknown_existing", "安装目录已有非本工具内容，未做任何修改".into()));
    }
    fs::create_dir_all(root).map_err(|e| ("failed", format!("无法创建安装目录：{e}")))?;
    if !root.join(MARKER).exists() {
        write_json(
            &root.join(MARKER),
            &Marker {
                owner: OWNER.into(),
                schema: 1,
            },
        )?;
    }
    step(steps, "创建安装目录", true, &root.to_string_lossy());

    clear_staging(root);
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let staging = root.join(format!("staging-{nonce}"));
    fs::create_dir(&staging).map_err(|e| ("failed", format!("无法创建暂存目录：{e}")))?;
    let staged = staging.join(ARTIFACT);
    fs::copy(&artifact, &staged).map_err(|e| ("failed", format!("无法暂存产物：{e}")))?;
    if sha_file(&staged).ok().as_deref() != Some(manifest.sha256.to_ascii_lowercase().as_str()) {
        return Err(("integrity_failed", "暂存产物 SHA-256 校验失败，已拒绝安装".into()));
    }
    step(steps, "暂存并校验产物", true, "SHA-256 一致");

    let version = probe(&staged, env).map_err(|e| ("failed", e))?;
    if version != manifest.version {
        return Err(("failed", "CLI 版本与安装清单不一致，已拒绝安装".into()));
    }
    step(steps, "验证可执行性", true, &format!("multi-search {version}"));

    let bin_dir = root.join("bin");
    fs::create_dir_all(&bin_dir).map_err(|e| ("failed", format!("无法创建 bin 目录：{e}")))?;
    let bin = bin_dir.join(ARTIFACT);
    // Owned, not active: a residue from an interrupted earlier attempt, safe to replace.
    if bin.exists() {
        fs::remove_file(&bin).map_err(|e| ("failed", format!("无法替换残留文件：{e}")))?;
    }
    fs::rename(&staged, &bin).map_err(|e| ("failed", format!("无法激活 CLI：{e}")))?;
    write_json(
        &root.join(ACTIVE),
        &Active {
            version: version.clone(),
            sha256: manifest.sha256.to_ascii_lowercase(),
        },
    )?;
    step(steps, "激活安装", true, &bin.to_string_lossy());

    match probe(&bin, env) {
        Ok(found) if found == version => {
            step(steps, "重新检测安装结果", true, &format!("multi-search {found}"));
            Ok((version, bin))
        }
        _ => {
            let _ = fs::remove_file(root.join(ACTIVE));
            let _ = fs::remove_file(&bin);
            step(steps, "重新检测安装结果", false, "已回滚");
            Err(("failed", "安装后重新检测失败，已回滚".into()))
        }
    }
}

impl DesktopManager {
    pub fn install_plan(&self) -> InstallPlan {
        let lay = match layout(&self.environment) {
            Ok(lay) => lay,
            Err(reason) => return row("unavailable", Path::new(""), None, &reason),
        };
        if let Some(active) = installed(&lay.root) {
            return row("installed", &lay.root, Some(active.version), "CLI 已由本工具安装");
        }
        if ownership(&lay.root) == Ownership::Unknown {
            return row("unknown_existing", &lay.root, None, "安装目录已有非本工具内容，未做任何修改");
        }
        let Some(source) = lay.source else {
            return row("unconfigured", &lay.root, None, "未配置受控发布来源，无法安装");
        };
        match read_source(&source) {
            Ok((manifest, _)) => row("ready", &lay.root, Some(manifest.version), "将安装到以下目录"),
            Err((status, reason)) => row(status, &lay.root, None, &reason),
        }
    }

    pub fn install(&self) -> InstallOutcome {
        let lay = match layout(&self.environment) {
            Ok(lay) => lay,
            Err(reason) => return outcome("unavailable", Vec::new(), None, reason),
        };
        let Some(source) = lay.source else {
            return outcome("unconfigured", Vec::new(), None, "未配置受控发布来源，未做任何修改".into());
        };
        let mut steps = Vec::new();
        let result = perform(&self.environment, &lay.root, &source, &mut steps);
        clear_staging(&lay.root);
        match result {
            Ok(installed) => outcome("installed", steps, Some(installed), String::new()),
            Err((status, reason)) => {
                step(&mut steps, status, false, &reason);
                outcome(status, steps, None, reason)
            }
        }
    }
}
