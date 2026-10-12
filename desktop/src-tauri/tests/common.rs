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
        let fixture = FIXTURE.get_or_init(|| {
            let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/fixture-cli.exe");
            let output = Command::new("rustc")
                .args(["--edition=2021", "tests/fixture_cli.rs", "-o"])
                .arg(&path)
                .current_dir(env!("CARGO_MANIFEST_DIR"))
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
            path
        });
        std::fs::copy(fixture, root.join("multi-search.exe")).unwrap();
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
