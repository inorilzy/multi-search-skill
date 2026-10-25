use crate::RuntimeEnvironment;
use std::collections::BTreeMap;
#[cfg(windows)]
use std::os::windows::{io::AsRawHandle, process::CommandExt};
use std::{
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
                return Err(io::Error::other("无法恢复受管的 CLI 进程"));
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

/// Non-secret variables a CLI child may inherit: OS/runtime plumbing, the user profile roots the
/// CLI derives its config/state/keys-file paths from, proxy and CA settings, and the product's own
/// non-secret selectors. Anything else (API keys, tokens, unrelated secrets) is dropped unless the
/// caller names it as a credential for this one invocation.
const BASE_VARIABLES: &[&str] = &[
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "ALLUSERSPROFILE", "PUBLIC",
    "USERNAME", "USERDOMAIN", "COMPUTERNAME", "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "LANG", "LC_ALL", "LC_CTYPE", "PYTHONIOENCODING", "PYTHONUTF8",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "MULTI_SEARCH_CONFIG", "MULTI_SEARCH_CONFIG_DB", "MULTI_SEARCH_CREDENTIAL_NAMESPACE",
    "MULTI_SEARCH_STATE_DB", "MULTI_SEARCH_STATE",
];

/// Substrings that mark a variable as secret material. Checked case-insensitively against names
/// that would otherwise pass the allowlist, except for the desktop-owned `MULTI_SEARCH_*`
/// namespace, whose names are fixed and non-secret (a selector, not a credential).
pub(crate) const ENV_SECRET_MARKERS: &[&str] = &[
    "API_KEY",
    "APIKEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "CREDENTIAL",
    "JINA_KEY",
    "SERPAPI_KEY",
];

fn is_secret_name(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    if upper.starts_with("MULTI_SEARCH_") {
        return false;
    }
    // Fixture-only names are test drivers (`FIXTURE_SECRET` names a synthetic value the fixture
    // deliberately echoes to exercise redaction). Debug-only.
    if cfg!(debug_assertions) && upper.starts_with("FIXTURE_") {
        return false;
    }
    ENV_SECRET_MARKERS
        .iter()
        .any(|marker| upper.contains(marker))
}

fn named(list: &[&str], name: &str) -> bool {
    list.iter().any(|item| item.eq_ignore_ascii_case(name))
}

/// The environment a CLI child actually receives: the non-secret base plus exactly the
/// `credentials` (variable names) this invocation needs. Names are matched case-insensitively,
/// as Windows does.
pub(crate) fn child_variables(environment: &RuntimeEnvironment, credentials: &[&str]) -> BTreeMap<String, String> {
    // `PYTHONPATH` is never forwarded: an injected interpreter path would let any parent
    // environment run arbitrary code inside the managed CLI. The installed-CLI acceptance
    // bootstrap arrives under a desktop-owned selector instead (see below).
    #[cfg(feature = "install-test-boundary")]
    let isolated = environment
        .variables
        .iter()
        .any(|(name, value)| name.eq_ignore_ascii_case("MULTI_SEARCH_TEST_ISOLATION") && value == "1");
    #[allow(unused_mut)]
    let mut child: BTreeMap<String, String> = environment
        .variables
        .iter()
        .filter(|(name, _)| {
            (named(BASE_VARIABLES, name) && !is_secret_name(name))
                || name.to_ascii_uppercase().starts_with("MULTI_SEARCH_")
                || named(credentials, name)
                // Debug-only seam for the fixture CLI used by the native tests; never in a release build.
                || (cfg!(debug_assertions)
                    && (name.starts_with("FIXTURE_") || name.starts_with("CLI_FIXTURE_")))
        })
        .map(|(name, value)| (name.clone(), value.clone()))
        .collect();
    // Acceptance-only boundary (compiled only with `install-test-boundary`): the desktop supplies
    // the installed-CLI bootstrap under a desktop-owned selector, and exactly that value becomes the
    // child's PYTHONPATH. A release build never translates it.
    #[cfg(feature = "install-test-boundary")]
    if isolated {
        if let Some(value) = environment.variables.get(TEST_PYTHONPATH_KEY) {
            child.insert("PYTHONPATH".into(), value.clone());
        }
    }
    child
}

/// Installed-CLI acceptance bootstrap selector. Deliberately not named `PYTHONPATH`, so production
/// keeps blocking arbitrary interpreter-path injection.
#[cfg(feature = "install-test-boundary")]
const TEST_PYTHONPATH_KEY: &str = "MULTI_SEARCH_TEST_PYTHONPATH";

#[cfg_attr(not(any(test, feature = "test-fixtures")), allow(dead_code))]
/// The allowlisted child environment for a non-credential invocation. Exposed through
/// `process_fixture` so the boundary tests assert the real filter, not a copy.
pub(crate) fn child_environment(variables: &BTreeMap<String, String>) -> BTreeMap<String, String> {
    let environment = RuntimeEnvironment {
        app_path: vec![],
        user_path: vec![],
        variables: variables.clone(),
        cwd: std::env::temp_dir(),
    };
    child_variables(&environment, &[])
}

pub(crate) struct Output {
    pub code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
    /// True when a stream exceeded `OUTPUT_LIMIT` and was cut. Callers must treat the payload as
    /// incomplete instead of parsing a truncated JSON document.
    pub truncated: bool,
}
pub(crate) struct OwnedProcess {
    child: Child,
    #[cfg(windows)]
    job: OwnedJob,
    stdout: Arc<Mutex<Vec<u8>>>,
    stderr: Arc<Mutex<Vec<u8>>>,
    readers: Vec<thread::JoinHandle<()>>,
    truncated: Arc<std::sync::atomic::AtomicBool>,
}

fn reader(
    mut pipe: impl Read + Send + 'static,
    buffer: Arc<Mutex<Vec<u8>>>,
    truncated: Arc<std::sync::atomic::AtomicBool>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut chunk = [0; 8192];
        while let Ok(count) = pipe.read(&mut chunk) {
            if count == 0 {
                break;
            }
            // A panicking sibling must not wedge the reader: recover the poison and keep counting.
            let mut bytes = buffer.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            let remaining = OUTPUT_LIMIT.saturating_sub(bytes.len());
            if count > remaining {
                truncated.store(true, std::sync::atomic::Ordering::Relaxed);
            }
            bytes.extend_from_slice(&chunk[..count.min(remaining)]);
        }
    })
}
impl OwnedProcess {
    /// Start the CLI with a cleared environment: only the non-secret base and the named
    /// `credentials` are passed (see [`child_variables`]).
    pub(crate) fn spawn(
        program: &Path,
        args: &[String],
        environment: &RuntimeEnvironment,
        credentials: &[&str],
    ) -> io::Result<Self> {
        let mut command = Command::new(program);
        command
            .args(args)
            .env_clear()
            .envs(child_variables(environment, credentials))
            .current_dir(&environment.cwd)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        command.creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW);
        // Unix counterpart of the Job Object: the child leads a fresh process group, so the whole
        // tree it spawns (Python workers, fetchers) can be signalled together on cancel.
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
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
        let truncated = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let readers = vec![
            reader(child.stdout.take().unwrap(), stdout.clone(), truncated.clone()),
            reader(child.stderr.take().unwrap(), stderr.clone(), truncated.clone()),
        ];
        Ok(Self {
            child,
            #[cfg(windows)]
            job,
            stdout,
            stderr,
            readers,
            truncated,
        })
    }
    pub(crate) fn terminate(&mut self) {
        #[cfg(windows)]
        self.job.terminate();
        #[cfg(unix)]
        {
            // Signal the child's own group (pgid == child pid), stopping descendants the CLI
            // spawned instead of orphaning them. Only that group is touched, never the caller's.
            let group = format!("-{}", self.child.id());
            let _ = Command::new("kill").args(["-KILL", "--", &group]).status();
            let _ = self.child.kill();
        }
        #[cfg(not(any(windows, unix)))]
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
            truncated: self.truncated.load(std::sync::atomic::Ordering::Relaxed),
            stdout: String::from_utf8_lossy(
                &self.stdout.lock().unwrap_or_else(std::sync::PoisonError::into_inner),
            )
            .into_owned(),
            stderr: String::from_utf8_lossy(
                &self.stderr.lock().unwrap_or_else(std::sync::PoisonError::into_inner),
            )
            .into_owned(),
        }
    }
}
impl Drop for OwnedProcess {
    fn drop(&mut self) {
        self.terminate();
        let _ = self.child.wait();
    }
}

/// Run a credential-free CLI invocation (`--version`, `--help`, migration, …) to completion.
pub(crate) fn bounded(
    program: &Path,
    args: &[String],
    environment: &RuntimeEnvironment,
    timeout: Duration,
) -> io::Result<Output> {
    bounded_with(program, args, environment, &[], timeout)
}

/// `bounded` with the credential variable names this one invocation may receive.
pub(crate) fn bounded_with(
    program: &Path,
    args: &[String],
    environment: &RuntimeEnvironment,
    credentials: &[&str],
    timeout: Duration,
) -> io::Result<Output> {
    let mut process = OwnedProcess::spawn(program, args, environment, credentials)?;
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

#[cfg(test)]
mod tests {
    use super::child_variables;
    use std::sync::Mutex;
    use crate::RuntimeEnvironment;
    use std::{collections::BTreeMap, path::PathBuf};

    fn environment(pairs: &[(&str, &str)]) -> RuntimeEnvironment {
        RuntimeEnvironment {
            app_path: vec![],
            user_path: vec![],
            variables: pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect::<BTreeMap<_, _>>(),
            cwd: PathBuf::from("."),
        }
    }

    #[test]
    fn only_base_and_named_credentials_reach_the_child() {
        let env = environment(&[
            ("Path", "C:\\Windows"),
            ("USERPROFILE", "C:\\Users\\u"),
            ("TAVILY_API_KEY", "synthetic-tavily"),
            ("EXA_API_KEY", "synthetic-exa"),
            ("AWS_SECRET_ACCESS_KEY", "synthetic-aws"),
            ("PYTHONPATH", "C:\\inject"),
        ]);
        let vars = child_variables(&env, &["TAVILY_API_KEY"]);
        assert!(vars.contains_key("Path"), "base names match case-insensitively");
        assert!(vars.contains_key("USERPROFILE"));
        assert_eq!(vars.get("TAVILY_API_KEY").map(String::as_str), Some("synthetic-tavily"));
        assert!(!vars.contains_key("EXA_API_KEY"), "unrequested keys are dropped");
        assert!(!vars.contains_key("AWS_SECRET_ACCESS_KEY"));
        assert!(!vars.contains_key("PYTHONPATH"), "an injected interpreter path is never forwarded outside isolation");
        assert!(child_variables(&env, &[]).keys().all(|k| !k.ends_with("_KEY")));
    }

    #[test]
    fn reader_recovers_poison_and_marks_truncation() {
        use super::{reader, OUTPUT_LIMIT};
        use std::sync::Arc;
        let buffer = Arc::new(Mutex::new(Vec::new()));
        let poison = buffer.clone();
        let _ = std::thread::spawn(move || {
            let _guard = poison.lock().unwrap();
            panic!("synthetic poison");
        })
        .join();
        let truncated = Arc::new(std::sync::atomic::AtomicBool::new(false));
        reader(
            std::io::Cursor::new(vec![b'x'; OUTPUT_LIMIT + 1]),
            buffer.clone(),
            truncated.clone(),
        )
        .join()
        .unwrap();
        assert!(truncated.load(std::sync::atomic::Ordering::Relaxed));
        assert_eq!(
            buffer.lock().unwrap_or_else(std::sync::PoisonError::into_inner).len(),
            OUTPUT_LIMIT
        );
    }

    #[test]
    fn isolation_marker_never_forwards_an_interpreter_path() {
        let env = environment(&[("MULTI_SEARCH_TEST_ISOLATION", "1"), ("PYTHONPATH", "boot")]);
        let vars = child_variables(&env, &[]);
        assert_eq!(vars.get("MULTI_SEARCH_TEST_ISOLATION").map(String::as_str), Some("1"));
        assert!(!vars.contains_key("PYTHONPATH"), "only the boundary-build selector may set it");
    }

    #[test]
    fn proxy_and_ca_settings_reach_the_child_so_core_can_reach_the_network() {
        let env = environment(&[
            ("HTTPS_PROXY", "http://proxy.invalid:8080"),
            ("NO_PROXY", "localhost"),
            ("SSL_CERT_FILE", "/etc/ssl/cert.pem"),
        ]);
        let vars = child_variables(&env, &[]);
        for name in ["HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE"] {
            assert!(vars.contains_key(name), "{name}");
        }
    }
}
