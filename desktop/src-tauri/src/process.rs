//! Owned CLI child processes: lifecycle, output bounds, and the environment
//! boundary.
//!
//! The child receives only `child_environment`'s curated allowlist; provider
//! credentials in the desktop environment never cross the boundary.
//!
//! Known trade-off: the search query is passed as a positional CLI argument,
//! so it is visible in the process command line to other processes running as
//! the same user. Moving it to stdin would change the public CLI contract, so
//! the desktop documents the exposure in README.md instead. See ticket 06.
use crate::RuntimeEnvironment;
#[cfg(windows)]
use std::os::windows::{io::AsRawHandle, process::CommandExt};
use std::{
    collections::BTreeMap,
    io::{self, Read},
    path::Path,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};
#[cfg(windows)]
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE},
    System::{
        Diagnostics::ToolHelp::{
            CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
        },
        JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
        Threading::{
            OpenThread, ResumeThread, CREATE_NO_WINDOW, CREATE_SUSPENDED, THREAD_SUSPEND_RESUME,
        },
    },
};

const OUTPUT_LIMIT: usize = 4 * 1024 * 1024;

/// Environment variables passed to every CLI child process.
///
/// The desktop process holds the user's full environment, including provider
/// credentials exported by other tools. Passing that environment through would
/// hand `TAVILY_API_KEY`, `GITHUB_TOKEN`, etc. to the CLI even though the CLI
/// reads credentials from `config.sqlite` + DPAPI. Only the entries below are
/// forwarded.
///
/// Notes on the choices:
/// - `PATH` is needed to resolve runtime DLLs and child tooling.
/// - `USERPROFILE`/`HOME`/`HOMEDRIVE`/`HOMEPATH` let the CLI resolve the
///   default `~/.multi-search/config.sqlite` when `MULTI_SEARCH_CONFIG_DB` is
///   not set (the desktop normally sets it).
/// - Windows process/runtime basics (`SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`,
///   `COMSPEC`, `PATHEXT`, `TEMP`, `TMP`) are required by the Windows loader,
///   DPAPI, and Python's temp-file handling.
/// - `PYTHONIOENCODING` is set by `RuntimeEnvironment::system()` so CLI output
///   is UTF-8 regardless of console code page.
/// - `MULTI_SEARCH_*` carries the desktop's own configuration selectors
///   (`MULTI_SEARCH_CONFIG_DB`, `MULTI_SEARCH_CREDENTIAL_NAMESPACE`) and the
///   compile-time acceptance boundary. None of these are secret values.
///
/// Any name matching a sensitive marker (`*_API_KEY`, `*_TOKEN`, `*_SECRET`,
/// `*_PASSWORD`, ...) is additionally rejected even if it somehow matched an
/// allowlist entry, except for the desktop-owned `MULTI_SEARCH_*` namespace,
/// whose names are fixed and non-secret.
const ENV_ALLOWLIST: &[&str] = &[
    "PATH",
    "PATHEXT",
    "COMSPEC",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "USERPROFILE",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "TEMP",
    "TMP",
    "TMPDIR",
    "PYTHONIOENCODING",
];

/// Prefixes forwarded wholesale. `MULTI_SEARCH_*` is desktop-owned
/// configuration, not provider credentials.
const ENV_ALLOWED_PREFIXES: &[&str] = &["MULTI_SEARCH_"];

/// Substrings that mark a variable as secret material. Checked
/// case-insensitively against names that matched the allowlist.
const ENV_SECRET_MARKERS: &[&str] = &[
    "API_KEY",
    "APIKEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "CREDENTIAL",
];

/// Test-only environment names.
///
/// These drive the fixture CLI in `tests/fixture_cli.rs`. They are compiled in
/// only for debug builds (`debug_assertions`), which excludes release
/// packaging, and they carry no secret values. The release build never
/// forwards them.
#[cfg(debug_assertions)]
const TEST_ENV_ALLOWLIST: &[&str] = &[
    "FIXTURE_VERSION",
    "FIXTURE_STORAGE",
    "FIXTURE_HELP",
    "FIXTURE_ARGS_PATH",
    "FIXTURE_CHILD_PID",
    "FIXTURE_FAIL_ACTIVE_ROOT",
    "FIXTURE_BLOCK_RESTORE",
    "FIXTURE_SECRET",
    "CLI_FIXTURE_FUTURE",
    "CLI_FIXTURE_NO_HTTP",
    "CLI_FIXTURE_KEYLESS",
];

/// Installed-CLI acceptance bootstrap path. It is deliberately not named
/// `PYTHONPATH`, so production can keep blocking arbitrary interpreter-path
/// injection while this acceptance-only feature passes the guarded test
/// bootstrap through as the child's real `PYTHONPATH`.
#[cfg(feature = "install-test-boundary")]
const TEST_PYTHONPATH_KEY: &str = "MULTI_SEARCH_TEST_PYTHONPATH";

fn is_secret_name(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    // The desktop's own namespace is fixed and non-secret; `..._CREDENTIAL_NAMESPACE`
    // contains a marker but is a selector, not a credential.
    if upper.starts_with("MULTI_SEARCH_") {
        return false;
    }
    // Fixture-only names are test drivers (`FIXTURE_SECRET` names a synthetic
    // value the fixture deliberately echoes to exercise redaction). Debug-only.
    #[cfg(debug_assertions)]
    if TEST_ENV_ALLOWLIST
        .iter()
        .any(|allowed| allowed.eq_ignore_ascii_case(&upper))
    {
        return false;
    }
    ENV_SECRET_MARKERS
        .iter()
        .any(|marker| upper.contains(marker))
}

fn is_allowed_name(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    if ENV_ALLOWLIST.iter().any(|allowed| allowed.eq_ignore_ascii_case(&upper)) {
        return true;
    }
    if ENV_ALLOWED_PREFIXES
        .iter()
        .any(|prefix| upper.starts_with(prefix))
    {
        return true;
    }
    #[cfg(debug_assertions)]
    if TEST_ENV_ALLOWLIST
        .iter()
        .any(|allowed| allowed.eq_ignore_ascii_case(&upper))
    {
        return true;
    }
    false
}

/// Build the child environment from the desktop environment. Exposed for
/// tests and for the ticket-06 assertion that secrets never cross the process
/// boundary.
pub(crate) fn child_environment(variables: &BTreeMap<String, String>) -> BTreeMap<String, String> {
    let filtered = || {
        variables
            .iter()
            .filter(|(name, _)| is_allowed_name(name) && !is_secret_name(name))
            .map(|(name, value)| (name.clone(), value.clone()))
            .collect::<BTreeMap<String, String>>()
    };
    #[cfg(feature = "install-test-boundary")]
    {
        let mut child = filtered();
        // Acceptance-only boundary: the desktop supplies the bootstrap under a
        // desktop-owned selector, and this feature build translates exactly that
        // one value into the interpreter path the CLI child needs.
        if variables.get("MULTI_SEARCH_TEST_ISOLATION").map(String::as_str) == Some("1") {
            if let Some(value) = variables.get(TEST_PYTHONPATH_KEY) {
                child.insert("PYTHONPATH".into(), value.clone());
            }
        }
        child
    }
    #[cfg(not(feature = "install-test-boundary"))]
    {
        filtered()
    }
}
#[cfg(windows)]
pub(crate) struct OwnedJob(HANDLE);
#[cfg(windows)]
unsafe impl Send for OwnedJob {}
#[cfg(windows)]
impl OwnedJob {
    fn attach(child: &Child) -> io::Result<Self> {
        unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            let job = Self(handle);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as _,
                std::mem::size_of_val(&limits) as u32,
            ) == 0
                || AssignProcessToJobObject(handle, child.as_raw_handle() as HANDLE) == 0
            {
                return Err(io::Error::last_os_error());
            }
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
            if snapshot == INVALID_HANDLE_VALUE {
                return Err(io::Error::last_os_error());
            }
            let mut entry: THREADENTRY32 = std::mem::zeroed();
            entry.dwSize = std::mem::size_of_val(&entry) as u32;
            let mut found = false;
            let mut available = Thread32First(snapshot, &mut entry) != 0;
            while available {
                if entry.th32OwnerProcessID == child.id() {
                    let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                    if !thread.is_null() {
                        found = ResumeThread(thread) != u32::MAX;
                        CloseHandle(thread);
                    }
                    break;
                }
                available = Thread32Next(snapshot, &mut entry) != 0;
            }
            CloseHandle(snapshot);
            if !found {
                return Err(io::Error::other("cannot resume owned CLI process"));
            }
            Ok(job)
        }
    }
    pub(crate) fn terminate(&self) {
        unsafe {
            TerminateJobObject(self.0, 1);
        }
    }
}
#[cfg(windows)]
impl Drop for OwnedJob {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

pub(crate) struct Output {
    pub code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
}
pub(crate) struct OwnedProcess {
    child: Child,
    #[cfg(windows)]
    job: OwnedJob,
    stdout: Arc<Mutex<Vec<u8>>>,
    stderr: Arc<Mutex<Vec<u8>>>,
    readers: Vec<thread::JoinHandle<()>>,
}

fn reader(
    mut pipe: impl Read + Send + 'static,
    buffer: Arc<Mutex<Vec<u8>>>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut chunk = [0; 8192];
        while let Ok(count) = pipe.read(&mut chunk) {
            if count == 0 {
                break;
            }
            let mut bytes = buffer.lock().unwrap();
            let remaining = OUTPUT_LIMIT.saturating_sub(bytes.len());
            bytes.extend_from_slice(&chunk[..count.min(remaining)]);
        }
    })
}
impl OwnedProcess {
    pub(crate) fn spawn(
        program: &Path,
        args: &[String],
        environment: &RuntimeEnvironment,
    ) -> io::Result<Self> {
        let mut command = Command::new(program);
        // Inherit nothing: the child sees only the explicit allowlist below,
        // so provider credentials in the desktop environment never leak.
        command
            .args(args)
            .env_clear()
            .envs(child_environment(&environment.variables))
            .current_dir(&environment.cwd)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        command.creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW);
        let mut child = command.spawn()?;
        #[cfg(windows)]
        let job = match OwnedJob::attach(&child) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        let stdout = Arc::new(Mutex::new(Vec::new()));
        let stderr = Arc::new(Mutex::new(Vec::new()));
        let readers = vec![
            reader(child.stdout.take().unwrap(), stdout.clone()),
            reader(child.stderr.take().unwrap(), stderr.clone()),
        ];
        Ok(Self {
            child,
            #[cfg(windows)]
            job,
            stdout,
            stderr,
            readers,
        })
    }
    pub(crate) fn terminate(&mut self) {
        #[cfg(windows)]
        self.job.terminate();
        #[cfg(not(windows))]
        {
            let _ = self.child.kill();
        }
    }
    pub(crate) fn poll(&mut self) -> io::Result<Option<i32>> {
        Ok(self.child.try_wait()?.map(|s| s.code().unwrap_or(1)))
    }
    pub(crate) fn finish(mut self, code: Option<i32>, timed_out: bool) -> Output {
        self.terminate();
        let _ = self.child.wait();
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
        Output {
            code,
            timed_out,
            stdout: String::from_utf8_lossy(&self.stdout.lock().unwrap()).into_owned(),
            stderr: String::from_utf8_lossy(&self.stderr.lock().unwrap()).into_owned(),
        }
    }
}
impl Drop for OwnedProcess {
    fn drop(&mut self) {
        self.terminate();
        let _ = self.child.wait();
    }
}

pub(crate) fn bounded(
    program: &Path,
    args: &[String],
    environment: &RuntimeEnvironment,
    timeout: Duration,
) -> io::Result<Output> {
    let mut process = OwnedProcess::spawn(program, args, environment)?;
    let started = Instant::now();
    loop {
        if let Some(code) = process.poll()? {
            return Ok(process.finish(Some(code), false));
        }
        if started.elapsed() >= timeout {
            return Ok(process.finish(None, true));
        }
        thread::sleep(Duration::from_millis(10));
    }
}
