use crate::{process::OwnedProcess, DesktopManager};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

#[derive(Clone, Deserialize)]
pub struct SearchOptions {
    pub query: String,
    pub route: String,
    pub sources: Vec<String>,
    pub timeout: u32,
}
/// Whether the CLI accepts this `--source` value. Canonical names and every
/// catalog alias (for example `v2ex`, `github-repos`, `github`) resolve here;
/// scrape-only providers such as `jina` and unknown names do not.
pub(crate) fn is_allowed_source(name: &str) -> bool {
    crate::source_catalog::catalog()
        .source(name)
        .is_some_and(|source| source.searchable)
}

/// Keys the CLI's body-fetch stage may use for any search (Jina reader plus the scrape backends).
const FETCH_CREDENTIALS: &[&str] = &[
    "JINA_API_KEY", "JINA_KEY", "EXA_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY",
];

/// Credential variable names one test search may receive: the selected sources' own keys (or the
/// route's sources when none are selected) plus the fetch-stage keys. Every other key stays out of
/// the child environment. Source names, aliases and env names come from the shared catalog.
pub(crate) fn search_credentials(route: &str, sources: &[String]) -> Vec<&'static str> {
    let catalog = crate::source_catalog::catalog();
    let selected: Vec<&'static str> = if sources.is_empty() {
        crate::settings::route_sources(route).iter().map(String::as_str).collect()
    } else {
        sources.iter().filter_map(|name| catalog.source(name)).map(|entry| entry.name.as_str()).collect()
    };
    let mut names: Vec<&'static str> = FETCH_CREDENTIALS.to_vec();
    for source in selected {
        if source == "twitter" {
            names.push("TWITTER_COOKIES_PATH");
        }
        if let Some(entry) = catalog.source(source) {
            names.extend(entry.env.iter().map(String::as_str));
        }
    }
    names.sort_unstable();
    names.dedup();
    names
}

#[derive(Clone, Serialize)]
pub struct ExecutionStatus {
    pub id: u64,
    pub status: String,
    pub exit_code: Option<i32>,
    pub payload: Option<Value>,
    pub error: String,
}
pub(crate) struct Execution {
    pub state: ExecutionStatus,
    process: Option<OwnedProcess>,
    started: Instant,
    timeout: Duration,
    secrets: Vec<String>,
}

impl Execution {
    fn complete(&mut self, code: i32) {
        let output = self.process.take().unwrap().finish(Some(code), false);
        self.state.exit_code = Some(code);
        match serde_json::from_str::<Value>(&output.stdout) {
            Ok(mut payload) if payload.is_object() => {
                crate::redaction::scrub_json(&mut payload, &self.secrets);
                let outcome = payload["outcome"].as_str().unwrap_or("failed");
                self.state.status = if code != 0 {
                    "failed"
                } else if ["success", "empty", "partial"].contains(&outcome) {
                    outcome
                } else {
                    "failed"
                }
                .into();
                self.state.payload = Some(payload);
            }
            _ => {
                self.state.status = "failed".into();
                self.state.error = "CLI did not return a valid JSON response".into();
            }
        }
        if !output.stderr.trim().is_empty() {
            self.state.error = crate::redaction::scrub(&output.stderr, &self.secrets);
        }
    }
}
impl DesktopManager {
    pub fn start_search(&self, options: SearchOptions) -> Result<u64, String> {
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("Desktop manager is closed".into());
        }
        if options.query.trim().is_empty()
            || options.query.len() > 2000
            || options.query.contains('\0')
        {
            return Err("Enter a query of 1–2000 bytes".into());
        }
        if crate::source_catalog::catalog().route(&options.route).is_none()
            || !(1..=60).contains(&options.timeout)
            || options.sources.len() > 16
            || options.sources.iter().any(|s| !is_allowed_source(s))
        {
            return Err("Unsupported search options".into());
        }
        let cli = self.execution_cli()?;
        let mut slot = self
            .execution_slot
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        if self.closed.load(std::sync::atomic::Ordering::Acquire) {
            return Err("Desktop manager is closed".into());
        }
        if slot
            .as_ref()
            .is_some_and(|s| s.lock().unwrap().state.status == "running")
        {
            return Err("A test search is already running".into());
        }
        let credentials = search_credentials(&options.route, &options.sources);
        let id = self
            .next_id
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let mut args = vec![
            "search".into(),
            options.query,
            "--route".into(),
            options.route,
            "--timeout".into(),
            options.timeout.to_string(),
            "--format".into(),
            "json".into(),
        ];
        for source in options.sources {
            args.push("--source".into());
            args.push(source);
        }
        let process = OwnedProcess::spawn(
            &cli,
            &args,
            &self.environment,
            &credentials,
        )
        .map_err(|_| "Could not start the CLI")?;
        let execution = Arc::new(Mutex::new(Execution {
            state: ExecutionStatus {
                id,
                status: "running".into(),
                exit_code: None,
                payload: None,
                error: String::new(),
            },
            process: Some(process),
            started: Instant::now(),
            timeout: Duration::from_secs((options.timeout + 10) as u64),
            secrets: crate::redaction::secrets(&self.environment),
        }));
        *slot = Some(execution.clone());
        thread::spawn(move || loop {
            {
                let mut run = execution.lock().unwrap();
                if run.state.status != "running" {
                    break;
                }
                let finished = run.process.as_mut().unwrap().poll();
                let timed_out = run.started.elapsed() >= run.timeout;
                match finished {
                    Ok(Some(code)) => run.complete(code),
                    Ok(None) if !timed_out => (),
                    _ => {
                        let _output = run.process.take().unwrap().finish(None, timed_out);
                        run.state.status = if timed_out { "timed_out" } else { "failed" }.into();
                        run.state.error = if timed_out {
                            "CLI exceeded the test execution deadline"
                        } else {
                            "CLI process could not be observed"
                        }
                        .into();
                    }
                }
            }
            thread::sleep(Duration::from_millis(20));
        });
        Ok(id)
    }
    pub fn cancel_search(&self, id: u64) -> Result<ExecutionStatus, String> {
        let slot = self
            .execution_slot
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        let mut run = slot
            .as_ref()
            .ok_or("No execution")?
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        if run.state.id != id {
            return Err("Unknown execution".into());
        }
        if run.state.status == "running" {
            let code = run
                .process
                .as_mut()
                .unwrap()
                .poll()
                .map_err(|_| "Cannot observe execution")?;
            if let Some(code) = code {
                run.complete(code);
            } else {
                let _ = run.process.take().unwrap().finish(None, false);
                run.state.status = "cancelled".into();
            }
        }
        Ok(run.state.clone())
    }

    pub fn shutdown(&self) {
        self.closed
            .store(true, std::sync::atomic::Ordering::Release);
        if let Ok(slot) = self.execution_slot.lock() {
            if let Some(execution) = slot.as_ref() {
                if let Ok(mut run) = execution.lock() {
                    if let Some(process) = run.process.take() {
                        let _ = process.finish(None, false);
                        run.state.status = "cancelled".into();
                    }
                }
            }
        }
    }

    pub fn execution(&self, id: u64) -> Result<ExecutionStatus, String> {
        let slot = self
            .execution_slot
            .lock()
            .map_err(|_| "Execution state unavailable")?;
        let state = slot
            .as_ref()
            .ok_or("No execution")?
            .lock()
            .map_err(|_| "Execution state unavailable")?
            .state
            .clone();
        if state.id != id {
            return Err("Unknown execution".into());
        }
        Ok(state)
    }
}

#[cfg(test)]
mod tests {
    use super::search_credentials;

    #[test]
    fn selected_sources_get_only_their_own_keys_plus_fetch_keys() {
        let names = search_credentials("default", &["brave".into()]);
        assert!(names.contains(&"BRAVE_SEARCH_API_KEY") && names.contains(&"BRAVE_API_KEY"));
        assert!(names.contains(&"JINA_API_KEY"), "body fetch may use Jina");
        assert!(!names.contains(&"GITHUB_TOKEN") && !names.contains(&"SERPAPI_API_KEY"));
        let github = search_credentials("default", &["github".into()]);
        assert!(github.contains(&"GITHUB_TOKEN") && github.contains(&"GH_TOKEN"), "aliases map to the source");
    }

    #[test]
    fn an_empty_source_list_uses_the_route_profile() {
        let dev = search_credentials("dev", &[]);
        assert!(dev.contains(&"GITHUB_TOKEN"));
        assert!(!dev.contains(&"BRAVE_SEARCH_API_KEY"));
        assert!(search_credentials("social", &[]).contains(&"TWITTER_COOKIES_PATH"));
    }
}
