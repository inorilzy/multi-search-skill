use crate::RuntimeEnvironment;
use serde_json::Value;

/// Values shorter than this are never treated as secrets. Short strings in the keys
/// file or cookie file (`"1"`, `"en"`, `"true"`) are not credentials, and replacing
/// them everywhere made search output unreadable. Real provider keys are far longer.
pub(crate) const MIN_SECRET_LEN: usize = 8;

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
/// Secrets for the real environment: env vars, the keys file, and the cookie files.
pub(crate) fn secrets(environment: &RuntimeEnvironment) -> Vec<String> {
    finish(collect_values(environment))
}

fn finish(mut values: Vec<String>) -> Vec<String> {
    values.retain(|value| value.chars().count() >= MIN_SECRET_LEN);
    values.sort_by_key(|value| std::cmp::Reverse(value.len()));
    values.dedup();
    values
}

fn collect_values(environment: &RuntimeEnvironment) -> Vec<String> {
    let mut values = Vec::new();
    for (name, value) in &environment.variables {
        if value.chars().count() >= MIN_SECRET_LEN
            && crate::process::ENV_SECRET_MARKERS.iter().any(|marker| name.to_ascii_uppercase().contains(marker))
        {
            values.push(value.clone());
        }
    }
    // Read only: redaction never runs the legacy copy. Both locations may hold keys.
    let home = environment
        .variables
        .get("USERPROFILE")
        .or_else(|| environment.variables.get("HOME"))
        .map(std::path::PathBuf::from);
    let files = crate::keys_file::path(&environment.variables)
        .into_iter()
        .chain(home.as_ref().map(|home| home.join(crate::keys_file::LEGACY_FILE_NAME)))
        .chain(crate::cookie::managed_path(environment));
    for file in files {
        if let Ok(text) = std::fs::read_to_string(file) {
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
    values
}
pub(crate) fn scrub(text: &str, secrets: &[String]) -> String {
    secrets
        .iter()
        .filter(|secret| secret.chars().count() >= MIN_SECRET_LEN)
        .fold(text.to_string(), |value, secret| {
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
        // Object keys are field names the UI depends on, never secrets: keep them as-is and
        // scrub values only.
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
    #[test]
    fn short_values_never_destroy_normal_output() {
        assert_eq!(super::scrub("a token abcdefgh", &["a".into(), "abcdefgh".into()]), "a token [REDACTED]");
    }
}
