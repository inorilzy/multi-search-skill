#![allow(dead_code)]
use multi_search_desktop::RuntimeEnvironment;
use std::{
    collections::BTreeMap,
    path::PathBuf,
    process::Command,
    sync::{
        atomic::{AtomicU64, Ordering},
        OnceLock,
    },
};
static NEXT: AtomicU64 = AtomicU64::new(0);
static FIXTURE: OnceLock<PathBuf> = OnceLock::new();

/// Build the fixture CLI once per test binary.
///
/// Every test binary gets its own output path (the file stem comes from the
/// running test executable), because `cargo test --tests` runs those binaries
/// in parallel. A shared `target/fixture-cli.exe` let one process truncate the
/// file while another was copying it, which surfaced as random `version_failed`
/// assertions. The compile goes to a temporary name first and is renamed into
/// place so a reader never observes a half-written executable.
pub fn fixture_cli() -> PathBuf {
    FIXTURE
        .get_or_init(|| {
            let stem = std::env::current_exe()
                .ok()
                .and_then(|path| path.file_stem().map(|stem| stem.to_string_lossy().into_owned()))
                .unwrap_or_else(|| "default".to_string());
            let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join(format!("target/fixture-cli-{stem}.exe"));
            let temp = path.with_extension(format!("tmp-{}", std::process::id()));
            let output = Command::new("rustc")
                .args(["--edition=2021", "tests/fixture_cli.rs", "-o"])
                .arg(&temp)
                .current_dir(env!("CARGO_MANIFEST_DIR"))
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
            std::fs::rename(&temp, &path).unwrap();
            path
        })
        .clone()
}

pub struct Profile {
    pub root: PathBuf,
    pub environment: RuntimeEnvironment,
}
impl Profile {
    pub fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "multi-search-native-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&root).unwrap();
        let fixture = fixture_cli();
        std::fs::copy(fixture, root.join(multi_search_desktop::CLI_FILE_NAME)).unwrap();
        let variables = BTreeMap::from([
            ("USERPROFILE".into(), root.to_string_lossy().into_owned()),
            ("HOME".into(), root.to_string_lossy().into_owned()),
        ]);
        let environment = RuntimeEnvironment {
            app_path: vec![root.clone()],
            user_path: vec![root.clone()],
            variables,
            cwd: root.clone(),
        };
        Self { root, environment }
    }
}
impl Drop for Profile {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[cfg(not(windows))]
#[allow(dead_code)]
pub fn process_alive(pid: u32) -> bool {
    // Signal 0 probes for existence without delivering anything.
    std::process::Command::new("kill")
        .args(["-0", &pid.to_string()])
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[cfg(windows)]
pub fn process_alive(pid: u32) -> bool {
    use windows_sys::Win32::{
        Foundation::CloseHandle,
        System::Threading::{GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION},
    };
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return false;
        }
        let mut code = 0;
        let ok = GetExitCodeProcess(handle, &mut code) != 0;
        CloseHandle(handle);
        ok && code == 259
    }
}
