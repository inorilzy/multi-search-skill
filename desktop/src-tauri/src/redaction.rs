use crate::RuntimeEnvironment;
use serde_json::Value;

fn strings(value: &Value, out: &mut Vec<String>) {
    match value {
        Value::String(s) if !s.is_empty() => out.push(s.clone()),
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
pub(crate) fn secrets(environment: &RuntimeEnvironment) -> Vec<String> {
    let mut values = Vec::new();
    for (name, value) in &environment.variables {
        if !value.is_empty()
            && (name.ends_with("API_KEY")
                || name.ends_with("TOKEN")
                || name == "JINA_KEY"
                || name == "SERPAPI_KEY")
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
    if let Some(path) = crate::config_db::path(&environment.variables).filter(|p| p.exists()) {
        let backend = crate::credential::SqliteCredentialBackend { path };
        for provider in crate::credential::STORE_PROVIDERS {
            if let Ok(Some((value, _))) = crate::credential::load(&backend, "", provider) {
                strings(&value, &mut values);
            }
        }
    }
    values.sort_by_key(|s| std::cmp::Reverse(s.len()));
    values.dedup();
    values
}
pub(crate) fn scrub(text: &str, secrets: &[String]) -> String {
    secrets.iter().fold(text.to_string(), |value, secret| {
        value.replace(secret, "[REDACTED]")
    })
}
pub(crate) fn scrub_json(value: &mut Value, secrets: &[String]) {
    match value {
        Value::String(text) => *text = scrub(text, secrets),
        Value::Array(rows) => {
            for row in rows {
                scrub_json(row, secrets);
            }
        }
        Value::Object(rows) => {
            let previous = std::mem::take(rows);
            for (key, mut row) in previous {
                scrub_json(&mut row, secrets);
                rows.insert(scrub(&key, secrets), row);
            }
        }
        _ => (),
    }
}
