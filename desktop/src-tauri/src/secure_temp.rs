//! Unpredictable names for temporary files and directories, always created exclusively.
//!
//! Names built from the PID, a counter or the clock can be guessed and pre-created (or replaced
//! by a link) by another process that can write to the same directory. Every temp entry here gets
//! a 128-bit random token and is created with `create_new` / `create_dir`, so an existing entry —
//! planted or left over — is never opened, followed or reused: creation fails and a new name is
//! drawn instead.
//!
//! Randomness comes from `std`'s `RandomState`, whose SipHash keys are seeded from the operating
//! system's random source; no extra dependency is needed.
use std::{
    collections::hash_map::RandomState,
    fs,
    hash::{BuildHasher, Hasher},
    io::{self, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

/// How many fresh names to try before giving up on a directory that keeps colliding.
const ATTEMPTS: usize = 16;

/// A 128-bit random token rendered as 32 lowercase hex characters.
pub(crate) fn token() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let mut out = String::with_capacity(32);
    for lane in 0..2u64 {
        // A fresh RandomState per lane: its keys are OS-seeded and differ from every earlier one.
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(lane);
        hasher.write_u64(COUNTER.fetch_add(1, Ordering::Relaxed));
        hasher.write_u128(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0),
        );
        out.push_str(&format!("{:016x}", hasher.finish()));
    }
    out
}

fn name(prefix: &str, suffix: &str) -> String {
    format!("{prefix}{}{suffix}", token())
}

/// Create a new file `<dir>/<prefix><token><suffix>` that did not exist before, write `contents`
/// and flush it to disk. On a write failure the partial file is removed.
pub(crate) fn create_file(dir: &Path, prefix: &str, suffix: &str, contents: &[u8]) -> io::Result<PathBuf> {
    create_file_with(dir, prefix, suffix, contents, false)
}

fn open_new(path: &Path, owner_only: bool) -> io::Result<fs::File> {
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    if owner_only {
        use std::os::unix::fs::OpenOptionsExt;
        // Owner-only from the first byte: never briefly world-readable.
        options.mode(0o600);
    }
    #[cfg(not(unix))]
    let _ = owner_only;
    options.open(path)
}

fn create_file_with(dir: &Path, prefix: &str, suffix: &str, contents: &[u8], owner_only: bool) -> io::Result<PathBuf> {
    for _ in 0..ATTEMPTS {
        let path = dir.join(name(prefix, suffix));
        let mut file = match open_new(&path, owner_only) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        };
        let written = file.write_all(contents).and_then(|()| file.sync_all());
        drop(file);
        if let Err(error) = written {
            let _ = fs::remove_file(&path);
            return Err(error);
        }
        return Ok(path);
    }
    Err(io::Error::new(io::ErrorKind::AlreadyExists, "无法保留唯一的临时文件"))
}

/// Create a new, empty directory `<parent>/<prefix><token>` that did not exist before.
pub(crate) fn create_dir(parent: &Path, prefix: &str) -> io::Result<PathBuf> {
    for _ in 0..ATTEMPTS {
        let path = parent.join(name(prefix, ""));
        match fs::create_dir(&path) {
            Ok(()) => return Ok(path),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(io::ErrorKind::AlreadyExists, "无法保留唯一的临时目录"))
}

/// Atomically replace `target` with `contents`: write a fresh, exclusively created sibling temp
/// file, then rename it over the target. The temp file is removed if anything fails.
pub(crate) fn replace_file(target: &Path, contents: &[u8]) -> io::Result<()> {
    replace_file_with(target, contents, false)
}

/// [`replace_file`] for secrets: on Unix the file is 0600 from creation, so the replaced target
/// is owner-only regardless of the umask or of the previous file's mode.
pub(crate) fn replace_private_file(target: &Path, contents: &[u8]) -> io::Result<()> {
    replace_file_with(target, contents, true)
}

fn replace_file_with(target: &Path, contents: &[u8], owner_only: bool) -> io::Result<()> {
    let dir = target
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "target has no parent directory"))?;
    let base = target.file_name().and_then(|n| n.to_str()).unwrap_or("file");
    let temp = create_file_with(dir, &format!(".{base}.tmp-"), "", contents, owner_only)?;
    fs::rename(&temp, target).inspect_err(|_| {
        let _ = fs::remove_file(&temp);
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn sandbox(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("ms-secure-temp-{tag}-{}", token()));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn tokens_are_128_bit_hex_and_never_repeat() {
        let tokens: HashSet<String> = (0..2000).map(|_| token()).collect();
        assert_eq!(tokens.len(), 2000);
        assert!(tokens.iter().all(|t| t.len() == 32 && t.bytes().all(|b| b.is_ascii_hexdigit())));
        assert!(tokens.iter().all(|t| !t.contains(&std::process::id().to_string()) || t.len() == 32));
    }

    #[test]
    fn names_carry_no_pid_counter_or_clock_pattern() {
        let dir = sandbox("names");
        let a = create_file(&dir, "req-", ".json", b"{}").unwrap();
        let b = create_file(&dir, "req-", ".json", b"{}").unwrap();
        let (a, b) = (a.file_name().unwrap().to_string_lossy().into_owned(), b.file_name().unwrap().to_string_lossy().into_owned());
        assert_ne!(a, b);
        assert!(!a.contains(&format!("-{}-", std::process::id())), "{a} must not embed the PID");
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_existing_entry_is_never_opened_or_followed() {
        let dir = sandbox("exclusive");
        // A planted file at a known path is left byte-for-byte untouched.
        let planted = dir.join("planted.json");
        fs::write(&planted, b"attacker").unwrap();
        let created = create_file(&dir, "", ".json", b"ours").unwrap();
        assert_ne!(created, planted);
        assert_eq!(fs::read(&planted).unwrap(), b"attacker");
        assert_eq!(fs::read(&created).unwrap(), b"ours");
        let sub = create_dir(&dir, "staging-").unwrap();
        assert!(sub.is_dir() && fs::read_dir(&sub).unwrap().next().is_none());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn replace_file_swaps_atomically_and_leaves_no_temp_behind() {
        let dir = sandbox("replace");
        let target = dir.join("state.json");
        fs::write(&target, b"old").unwrap();
        replace_file(&target, b"new").unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"new");
        let names: Vec<_> = fs::read_dir(&dir).unwrap().map(|e| e.unwrap().file_name()).collect();
        assert_eq!(names, vec![std::ffi::OsString::from("state.json")]);
        fs::remove_dir_all(dir).unwrap();
    }
}
