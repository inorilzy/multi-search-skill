//! Bundle manifest parsing and filesystem verification.
//!
//! A manifest is trusted only when its raw bytes match the compiled-in trust
//! anchor; its structure and every listed file are then verified before the
//! installer touches the target directory.
use crate::windows_util;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
};

/// The CLI launcher filename on this platform. On macOS the bundle ships
/// `bin/multi-search` plus a bundled interpreter; Windows keeps its launcher.
pub(crate) const ARTIFACT: &str = crate::CLI_FILE_NAME;
pub(crate) const ARTIFACT_REL: &str = if cfg!(windows) {
    "bin/multi-search.exe"
} else {
    "bin/multi-search"
};
pub(crate) const MANIFEST: &str = "manifest.json";
const MANIFEST_SCHEMA: u32 = 1;
/// Windows device names that must never be used as bundle path segments.
const RESERVED_NAMES: [&str; 22] = [
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8",
    "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
];

pub(crate) type Failure = (&'static str, String);

#[derive(Deserialize)]
pub(crate) struct Manifest {
    pub(crate) version: String,
    pub(crate) files: Vec<ManifestFile>,
}

#[derive(Deserialize)]
pub(crate) struct ManifestFile {
    pub(crate) path: String,
    pub(crate) size: u64,
    pub(crate) sha256: String,
}

pub(crate) fn hex_digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub(crate) fn sha_file(path: &Path) -> std::io::Result<String> {
    let mut hasher = Sha256::new();
    std::io::copy(&mut fs::File::open(path)?, &mut hasher)?;
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

/// Plain relative POSIX path that is also safe on Windows. Raw text is checked segment by segment
/// (no normalisation) so `./a`, `a//b`, drive letters, UNC, backslashes and ADS are all refused.
fn check_rel_path(text: &str) -> Result<(), Failure> {
    let unsafe_path = || {
        (
            "integrity_failed",
            String::from("安装清单含非法路径，已拒绝安装"),
        )
    };
    if text.is_empty() || text.starts_with('/') || text.contains(['\\', ':']) {
        return Err(unsafe_path());
    }
    for part in text.split('/') {
        let stem = part.split('.').next().unwrap_or("").to_ascii_lowercase();
        if part.is_empty()
            || part == "."
            || part == ".."
            || part.ends_with(' ')
            || part.ends_with('.')
            || part.chars().any(|c| c.is_control() || "<>\"|?*".contains(c))
            || RESERVED_NAMES.contains(&stem.as_str())
        {
            return Err(unsafe_path());
        }
    }
    Ok(())
}

fn valid_version(version: &str) -> bool {
    !version.is_empty() && version.len() < 80 && !version.contains(char::is_whitespace)
}

/// Checks the raw manifest bytes against the anchor before any parsing, then validates its structure.
pub(crate) fn parse_manifest(raw: &[u8], expected_anchor: &str) -> Result<Manifest, Failure> {
    if hex_digest(raw) != expected_anchor {
        return Err((
            "integrity_failed",
            "安装清单未通过信任锚点校验，已拒绝安装".into(),
        ));
    }
    let manifest: Manifest = serde_json::from_slice(raw)
        .map_err(|_| ("integrity_failed", "安装清单无法解析，已拒绝安装".into()))?;
    if !valid_version(&manifest.version) {
        return Err((
            "integrity_failed",
            "安装清单与产物不一致，已拒绝安装".into(),
        ));
    }
    // `schema` is still deserialized by serde's deny-unknown behavior only if
    // present; keep accepting version-1 shape and reject a different schema.
    let schema = serde_json::from_slice::<serde_json::Value>(raw)
        .ok()
        .and_then(|value| value.get("schema").and_then(|v| v.as_u64()));
    if schema != Some(MANIFEST_SCHEMA as u64) {
        return Err((
            "integrity_failed",
            "安装清单与产物不一致，已拒绝安装".into(),
        ));
    }
    let mut files = HashSet::new();
    let mut dirs = HashSet::new();
    for file in &manifest.files {
        check_rel_path(&file.path)?;
        let key = file.path.to_ascii_lowercase();
        let parts: Vec<&str> = key.split('/').collect();
        for end in 1..parts.len() {
            dirs.insert(parts[..end].join("/"));
        }
        if !files.insert(key) {
            return Err((
                "integrity_failed",
                "安装清单含重复或大小写冲突的路径，已拒绝安装".into(),
            ));
        }
    }
    if files.iter().any(|key| dirs.contains(key)) {
        return Err((
            "integrity_failed",
            "安装清单中的文件与目录路径冲突，已拒绝安装".into(),
        ));
    }
    if !manifest.files.iter().any(|file| file.path == ARTIFACT_REL) {
        return Err((
            "integrity_failed",
            "安装清单缺少 CLI 产物，已拒绝安装".into(),
        ));
    }
    Ok(manifest)
}

/// Resolves a manifest path under `dir`, refusing symlinks and reparse points at every component.
pub(crate) fn resolve(dir: &Path, rel: &str) -> Result<PathBuf, Failure> {
    let parts: Vec<&str> = rel.split('/').collect();
    let mut current = dir.to_path_buf();
    for (index, part) in parts.iter().enumerate() {
        current.push(part);
        let meta = fs::symlink_metadata(&current)
            .map_err(|_| ("prerequisite_missing", format!("安装来源缺少 {rel}")))?;
        if windows_util::is_link(&meta) {
            return Err((
                "integrity_failed",
                format!("安装来源含链接或重解析点，已拒绝安装：{rel}"),
            ));
        }
        let last = index + 1 == parts.len();
        if (last && !meta.is_file()) || (!last && !meta.is_dir()) {
            return Err((
                "integrity_failed",
                format!("安装来源路径类型不符，已拒绝安装：{rel}"),
            ));
        }
    }
    Ok(current)
}

/// Every manifest-listed file must exist with the recorded size and SHA-256.
pub(crate) fn verify_files(dir: &Path, manifest: &Manifest) -> Result<(), Failure> {
    for file in &manifest.files {
        let path = resolve(dir, &file.path)?;
        let size = fs::metadata(&path).map(|m| m.len()).unwrap_or(u64::MAX);
        if size != file.size {
            return Err((
                "integrity_failed",
                "安装清单与产物不一致，已拒绝安装".into(),
            ));
        }
        let digest = sha_file(&path).map_err(|_| {
            (
                "integrity_failed",
                "无法读取安装来源文件，已拒绝安装".into(),
            )
        })?;
        if digest != file.sha256.to_ascii_lowercase() {
            return Err((
                "integrity_failed",
                "产物 SHA-256 校验失败，已拒绝安装".into(),
            ));
        }
    }
    Ok(())
}

/// On Unix the launcher and every bundled interpreter must be executable. `fs::copy`
/// carries permission bits into staging and `rename` keeps them on activation; checking
/// both the source and the staged copy means a dropped mode fails before activation
/// instead of surfacing later as an unlaunchable install.
#[cfg(unix)]
pub(crate) fn verify_executable_modes(dir: &Path, manifest: &Manifest) -> Result<(), Failure> {
    use std::os::unix::fs::PermissionsExt;
    for file in &manifest.files {
        let required = file.path == ARTIFACT_REL || file.path.starts_with("runtime/bin/");
        if !required {
            continue;
        }
        let path = resolve(dir, &file.path)?;
        let mode = fs::metadata(&path)
            .map(|metadata| metadata.permissions().mode())
            .map_err(|_| {
                (
                    "integrity_failed",
                    format!("无法读取安装来源文件，已拒绝安装：{}", file.path),
                )
            })?;
        if mode & 0o111 == 0 {
            return Err((
                "integrity_failed",
                format!("安装包可执行文件缺少执行权限，已拒绝安装：{}", file.path),
            ));
        }
    }
    Ok(())
}

#[cfg(not(unix))]
pub(crate) fn verify_executable_modes(_: &Path, _: &Manifest) -> Result<(), Failure> {
    Ok(())
}

/// Reads and fully verifies a source bundle. Returns the parsed manifest and its raw bytes.
pub(crate) fn read_source(dir: &Path, expected_anchor: &str) -> Result<(Manifest, Vec<u8>), Failure> {
    let raw = fs::read(dir.join(MANIFEST)).map_err(|_| {
        (
            "prerequisite_missing",
            "安装来源缺少 manifest.json".to_string(),
        )
    })?;
    let manifest = parse_manifest(&raw, expected_anchor)?;
    verify_files(dir, &manifest)?;
    verify_executable_modes(dir, &manifest)?;
    Ok((manifest, raw))
}
