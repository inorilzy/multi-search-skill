//! Shared Skill definition used by both install (`skill.rs`) and lifecycle
//! management (`skill_manage.rs`). This module exists so neither of those
//! modules has to import the other: previously `skill.rs` called into
//! `skill_manage::safe_managed_paths` while `skill_manage.rs` imported
//! `skill::{FILES, MARKER, ...}`, forming a cycle.
use crate::{windows_util, RuntimeEnvironment};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

pub(crate) const SKILL_NAME: &str = "multi-search";
/// Content release of the shipped Skill files. Bump when `FILES` changes.
pub(crate) const SKILL_VERSION: &str = "1";
/// Marker format version. Unlike `SKILL_VERSION` (content), this identifies
/// the marker schema itself, so a marker can be classified as "older schema"
/// without guessing from `skill_version`.
pub(crate) const MARKER_SCHEMA: u32 = 2;
pub(crate) const MARKER: &str = ".multi-search-install.json";
pub(crate) const OWNER: &str = "multi-search-desktop";

/// Files shipped with this product release, embedded so the desktop app never
/// reads a loose copy.
pub(crate) const FILES: [(&str, &str); 3] = [
    ("SKILL.md", include_str!("../../skill/multi-search/SKILL.md")),
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
    (
        "search",
        &["--route", "--expand", "--format", "--source", "--count", "--timeout"],
    ),
    ("fetch", &["--full-content", "--format", "--url"]),
    ("read", &["--keyword", "--offset", "--format", "--limit"]),
    ("doctor", &["--no-keys", "--format"]),
];

pub(crate) type Requirements = BTreeMap<String, Vec<String>>;

pub(crate) fn requirements() -> Requirements {
    REQUIRED_FLAGS
        .iter()
        .map(|(command, flags)| {
            (
                command.to_string(),
                flags.iter().map(|f| f.to_string()).collect(),
            )
        })
        .collect()
}

pub(crate) fn file_names() -> Vec<String> {
    FILES.iter().map(|(name, _)| (*name).to_string()).collect()
}

pub(crate) fn home_directory(environment: &RuntimeEnvironment) -> Option<PathBuf> {
    environment
        .variables
        .get("USERPROFILE")
        .or_else(|| environment.variables.get("HOME"))
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
}

/// Resolves the skill directory; the parent `.claude` directory is the only
/// one this module creates.
pub(crate) fn target_directory(
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

/// Every ancestor matters: references/ or the target itself may be a junction.
pub(crate) fn safe_managed_paths(directory: &Path) -> bool {
    for ancestor in directory.ancestors() {
        if let Ok(metadata) = fs::symlink_metadata(ancestor) {
            if windows_util::is_link(&metadata) || !metadata.is_dir() {
                return false;
            }
        }
    }
    for (name, _) in FILES.iter().copied().chain(std::iter::once((MARKER, ""))) {
        let path = directory.join(name);
        if let Some(parent) = path.parent() {
            if let Ok(metadata) = fs::symlink_metadata(parent) {
                if windows_util::is_link(&metadata) || !metadata.is_dir() {
                    return false;
                }
            }
        }
        match fs::symlink_metadata(path) {
            Ok(metadata) if windows_util::is_link(&metadata) || !metadata.is_file() => return false,
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => return false,
            _ => {}
        }
    }
    true
}

pub(crate) fn sha256_hex(content: &str) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(content.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Write the shipped files and a schema-tagged marker, then verify.
/// Hashes let later status/update checks tell an unmodified file from a user edit.
pub(crate) fn write_directory(directory: &Path) -> Result<(), String> {
    for (name, content) in FILES {
        let path = directory.join(name);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("Cannot create {name}: {e}"))?;
        }
        fs::write(&path, content).map_err(|e| format!("Cannot write {name}: {e}"))?;
    }
    let hashes: serde_json::Map<String, serde_json::Value> = FILES
        .iter()
        .map(|(name, content)| {
            (
                (*name).to_string(),
                serde_json::Value::String(sha256_hex(content)),
            )
        })
        .collect();
    let marker = serde_json::json!({
        "managed_by": OWNER,
        "skill": SKILL_NAME,
        "marker_schema": MARKER_SCHEMA,
        "skill_version": SKILL_VERSION,
        "files": file_names(),
        "hashes": hashes,
        "requirements": requirements(),
    });
    fs::write(directory.join(MARKER), format!("{marker}\n"))
        .map_err(|e| format!("Cannot write {MARKER}: {e}"))?;
    verify_directory(directory)
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
        .map_err(|_| "The install marker is missing".to_string())?;
    let marker: serde_json::Value =
        serde_json::from_str(&marker).map_err(|_| "The install marker is invalid".to_string())?;
    if marker["managed_by"] != OWNER
        || marker["skill"] != SKILL_NAME
        || marker["skill_version"] != SKILL_VERSION
    {
        return Err("The install marker does not match this release".into());
    }
    Ok(())
}

/// Parsed view of our marker as written by `write_directory` or an older release.
#[derive(Debug)]
pub(crate) struct ParsedMarker {
    pub(crate) skill_version: String,
    /// `None` for markers written before the schema field existed.
    pub(crate) marker_schema: Option<u32>,
    /// `None` for markers written before hashes were recorded.
    pub(crate) hashes: Option<BTreeMap<String, String>>,
}

/// Parse and validate ownership. `None` means the folder is not ours.
pub(crate) fn read_marker(directory: &Path) -> Option<ParsedMarker> {
    if !safe_managed_paths(directory) {
        return None;
    }
    let text = fs::read_to_string(directory.join(MARKER)).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    if value["managed_by"] != OWNER || value["skill"] != SKILL_NAME {
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
    let skill_version = value["skill_version"].as_str()?.to_string();
    let marker_schema = match value.get("marker_schema") {
        None => None,
        Some(schema) => Some(schema.as_u64()? as u32),
    };
    let hashes = match value.get("hashes") {
        None => None,
        Some(hashes) => Some(
            hashes
                .as_object()?
                .iter()
                .map(|(k, v)| Some((k.clone(), v.as_str()?.to_string())))
                .collect::<Option<BTreeMap<_, _>>>()?,
        ),
    };
    Some(ParsedMarker {
        skill_version,
        marker_schema,
        hashes,
    })
}
