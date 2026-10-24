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
        if value.chars().count() >= 8
            && crate::process::ENV_SECRET_MARKERS.iter().any(|marker| name.to_ascii_uppercase().contains(marker))
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
    let settings = crate::settings::view(environment);
    for path in environment.variables.get("TWITTER_COOKIES_PATH").into_iter().chain(settings.twitter_cookies_path.as_ref()) {
        values.push(path.clone());
        if let Ok(text) = std::fs::read_to_string(path) {
            if let Ok(data) = serde_json::from_str::<Value>(text.trim_start_matches('\u{feff}')) {
                strings(&data, &mut values);
            }
        }
    }
    if let Some(path) = crate::config_db::path(&environment.variables).filter(|p| p.exists()) {
        let backend = crate::credential::SqliteCredentialBackend { path };
        for provider in crate::credential::STORE_PROVIDERS.iter().copied().chain(std::iter::once(crate::cookie::PROVIDER)) {
            if let Ok(Some((value, _))) = crate::credential::load(&backend, "", provider) {
                strings(&value, &mut values);
            }
        }
    }
    values.retain(|s| s.chars().count() >= 8);
    values.sort_by_key(|s| std::cmp::Reverse(s.len()));
    values.dedup();
    values
}
pub(crate) fn scrub(text: &str, secrets: &[String]) -> String {
    secrets.iter().filter(|s| s.chars().count() >= 8).fold(text.to_string(), |value, secret| {
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

#[cfg(test)]
mod tests {
    #[test]
    fn short_values_never_destroy_normal_output() {
        assert_eq!(super::scrub("a token abcdefgh", &["a".into(), "abcdefgh".into()]), "a token [REDACTED]");
    }
}
