use crate::credential::{self, CredentialBackend};
use crate::RuntimeEnvironment;
use serde_json::Value;

/// Values shorter than this are never treated as secrets. Short strings in the keys
/// file or cookie file (`"1"`, `"en"`, `"true"`) are not credentials, and replacing
/// them everywhere made search output unreadable. Real provider keys are far longer.
pub(crate) const MIN_SECRET_LEN: usize = 8;

fn strings(value: &Value, out: &mut Vec<String>) {
    match value {
        Value::String(s) => out.push(s.clone()),
        Value::Array(rows) => {
            for row in rows {
                strings(row, out);
            }
        }
        Value::Object(rows) => {
            for row in rows.values() {
                strings(row, out);
            }
        }
        _ => (),
    }
}

/// Secrets for the real environment: env vars, keys file, cookie file, and every
/// key saved in the platform credential store (the recommended storage location).
pub(crate) fn secrets(environment: &RuntimeEnvironment) -> Vec<String> {
    crate::credential_commands::with_native(|backend| collect(environment, backend))
}

/// Pure collection over an explicit store backend, so tests never touch the real store.
pub(crate) fn collect(environment: &RuntimeEnvironment, backend: &dyn CredentialBackend) -> Vec<String> {
    let mut values = Vec::new();
    for (name, value) in &environment.variables {
        if name.ends_with("API_KEY")
            || name.ends_with("TOKEN")
            || name == "JINA_KEY"
            || name == "SERPAPI_KEY"
        {
            values.push(value.clone());
        }
    }
    if let Some(home) = environment
        .variables
        .get("USERPROFILE")
        .or_else(|| environment.variables.get("HOME"))
    {
        if let Ok(text) =
            std::fs::read_to_string(std::path::Path::new(home).join(".search-keys.json"))
        {
            if let Ok(data) = serde_json::from_str::<Value>(text.trim_start_matches('\u{feff}')) {
                strings(&data, &mut values);
            }
        }
    }
    if let Some(path) = environment.variables.get("TWITTER_COOKIES_PATH") {
        if let Ok(text) = std::fs::read_to_string(path) {
            if let Ok(data) = serde_json::from_str::<Value>(&text) {
                strings(&data, &mut values);
            }
        }
    }
    // Credential Manager keys, one entry per allowlisted provider. An unavailable or
    // unreadable store contributes nothing; it never fails redaction.
    let namespace = credential::namespace(&environment.variables);
    for entry in crate::source_catalog::catalog().credential_sources() {
        if let Ok(Some((key, _saved_at))) = credential::load(backend, &namespace, &entry.key_provider) {
            values.push(key);
        }
    }
    values.retain(|value| value.chars().count() >= MIN_SECRET_LEN);
    values.sort_by_key(|s| std::cmp::Reverse(s.len()));
    values.dedup();
    values
}

pub(crate) fn scrub(text: &str, secrets: &[String]) -> String {
    secrets.iter().fold(text.to_string(), |value, secret| {
        value.replace(secret, "[REDACTED]")
    })
}

/// Scrub string values only. Object keys are field names the UI depends on, never
/// secrets, so they are kept as-is.
pub(crate) fn scrub_json(value: &mut Value, secrets: &[String]) {
    match value {
        Value::String(text) => *text = scrub(text, secrets),
        Value::Array(rows) => {
            for row in rows {
                scrub_json(row, secrets);
            }
        }
        Value::Object(rows) => {
            for row in rows.values_mut() {
                scrub_json(row, secrets);
            }
        }
        _ => (),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::credential::CredentialError;
    use std::{collections::BTreeMap, path::PathBuf, sync::Mutex};

    const STORE_KEY: &str = "synthetic-store-tavily-0001";

    #[derive(Default)]
    struct Memory(Mutex<BTreeMap<String, Vec<u8>>>);
    impl CredentialBackend for Memory {
        fn read(&self, target: &str) -> Result<Option<Vec<u8>>, CredentialError> {
            Ok(self.0.lock().unwrap().get(target).cloned())
        }
        fn write(&self, target: &str, blob: &[u8]) -> Result<(), CredentialError> {
            self.0.lock().unwrap().insert(target.into(), blob.to_vec());
            Ok(())
        }
        fn delete(&self, target: &str) -> Result<bool, CredentialError> {
            Ok(self.0.lock().unwrap().remove(target).is_some())
        }
    }

    struct Denied;
    impl CredentialBackend for Denied {
        fn read(&self, _target: &str) -> Result<Option<Vec<u8>>, CredentialError> {
            Err(CredentialError::Unavailable("denied".into()))
        }
        fn write(&self, _target: &str, _blob: &[u8]) -> Result<(), CredentialError> {
            Err(CredentialError::Unavailable("denied".into()))
        }
        fn delete(&self, _target: &str) -> Result<bool, CredentialError> {
            Err(CredentialError::Unavailable("denied".into()))
        }
    }

    fn environment(home: &std::path::Path, extra: &[(&str, &str)]) -> RuntimeEnvironment {
        let mut variables = BTreeMap::from([
            ("HOME".to_string(), home.to_string_lossy().into_owned()),
            (credential::NAMESPACE_ENV.to_string(), "redaction-test".to_string()),
        ]);
        for (name, value) in extra {
            variables.insert(name.to_string(), value.to_string());
        }
        RuntimeEnvironment { app_path: vec![], user_path: vec![], variables, cwd: PathBuf::new() }
    }

    fn temp_home(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("ms-redaction-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn credential_store_keys_are_redacted() {
        let home = temp_home("store");
        let backend = Memory::default();
        credential::save(&backend, "redaction-test", "tavily", STORE_KEY, 1.0).unwrap();
        let secrets = collect(&environment(&home, &[]), &backend);
        assert!(secrets.contains(&STORE_KEY.to_string()));
        let text = scrub(&format!("provider echoed {STORE_KEY}"), &secrets);
        assert!(!text.contains(STORE_KEY));
        assert!(text.contains("[REDACTED]"));
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn unavailable_store_contributes_nothing_and_does_not_fail() {
        let home = temp_home("denied");
        let secrets = collect(&environment(&home, &[("EXA_API_KEY", "synthetic-env-exa-0001")]), &Denied);
        assert_eq!(secrets, vec!["synthetic-env-exa-0001".to_string()]);
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn short_values_from_files_and_env_are_not_secrets() {
        let home = temp_home("short");
        std::fs::write(
            home.join(".search-keys.json"),
            r#"{"tavily":"synthetic-file-tavily-0001","flag":"1","lang":"en","on":"true"}"#,
        )
        .unwrap();
        let cookies = home.join("cookies.json");
        std::fs::write(&cookies, r#"{"ct0":"synthetic-cookie-ct0-value","lang":"en","dnt":"1"}"#).unwrap();
        let env = environment(
            &home,
            &[("TWITTER_COOKIES_PATH", cookies.to_str().unwrap()), ("GH_TOKEN", "abc")],
        );
        let secrets = collect(&env, &Memory::default());
        assert!(secrets.contains(&"synthetic-file-tavily-0001".to_string()));
        assert!(secrets.contains(&"synthetic-cookie-ct0-value".to_string()));
        for short in ["1", "en", "true", "abc"] {
            assert!(!secrets.contains(&short.to_string()), "{short}");
        }
        let text = scrub("lang en, enabled true, rank 1", &secrets);
        assert_eq!(text, "lang en, enabled true, rank 1");
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn scrub_json_keeps_object_keys_and_scrubs_values() {
        let secret = "synthetic-json-secret-0001".to_string();
        let mut value = serde_json::json!({
            "results": [{"title": format!("leak {secret}"), "url": "https://example.com"}],
            secret.clone(): "value under a secret-looking key",
        });
        scrub_json(&mut value, std::slice::from_ref(&secret));
        assert_eq!(value["results"][0]["title"], "leak [REDACTED]");
        assert_eq!(value["results"][0]["url"], "https://example.com");
        assert!(value.as_object().unwrap().contains_key("results"));
        assert!(value.as_object().unwrap().contains_key(&secret));
    }
}
