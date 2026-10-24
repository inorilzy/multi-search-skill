//! Windows Credential Manager access for the Tavily key.
//!
//! Mirrors `multi_search_mcp/src/support/credential_store.py`: one generic
//! credential named `<namespace>/<provider>` holding UTF-8 JSON
//! `{"v":1,"key":<secret>,"saved_at":<unix seconds>}`. Change both together.
//!
//! Secrets never leave this module except through the CLI's stdin-free env path
//! (never argv) and are never included in returned errors or status values.

use serde::Serialize;
use serde_json::Value;

pub(crate) const NAMESPACE_ENV: &str = "MULTI_SEARCH_CREDENTIAL_NAMESPACE";
pub(crate) const DEFAULT_NAMESPACE: &str = "multi-search";
pub(crate) const MAX_KEY_LENGTH: usize = 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CredentialError {
    /// Store is denied or unavailable. Message never includes secret material.
    Unavailable(String),
    /// Entry exists but cannot be parsed as the versioned blob.
    Unreadable,
    /// Input key failed validation; message never echoes the value.
    Invalid(&'static str),
}

impl std::fmt::Display for CredentialError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unavailable(message) => f.write_str(message),
            Self::Unreadable => f.write_str("已保存的凭据无法读取"),
            Self::Invalid(message) => f.write_str(message),
        }
    }
}

/// Backend seam so tests can run against an in-memory store without touching Windows.
pub(crate) trait CredentialBackend: Send + Sync {
    fn read(&self, target: &str) -> Result<Option<Vec<u8>>, CredentialError>;
    fn write(&self, target: &str, blob: &[u8]) -> Result<(), CredentialError>;
    fn delete(&self, target: &str) -> Result<bool, CredentialError>;
}

/// Validate and trim a key. Errors never echo the value.
pub(crate) fn validate_key(key: &str) -> Result<String, CredentialError> {
    let text = key.trim();
    if text.is_empty() || text.len() > MAX_KEY_LENGTH {
        return Err(CredentialError::Invalid(
            "API Key 必须为 1 到 1024 个字符，且不能包含控制字符",
        ));
    }
    if text.chars().any(|c| (c as u32) < 32 || c as u32 == 127) {
        return Err(CredentialError::Invalid(
            "API Key 必须为 1 到 1024 个字符，且不能包含控制字符",
        ));
    }
    Ok(text.to_string())
}

/// Namespace from the environment, matching Python `credential_namespace`.
pub(crate) fn namespace(variables: &std::collections::BTreeMap<String, String>) -> String {
    variables
        .get(NAMESPACE_ENV)
        .filter(|value| !value.is_empty())
        .cloned()
        .unwrap_or_else(|| DEFAULT_NAMESPACE.to_string())
}

pub(crate) fn target(namespace: &str, provider: &str) -> String {
    format!("{namespace}/{provider}")
}

pub(crate) fn encode_blob(key: &str, saved_at: f64) -> Vec<u8> {
    serde_json::json!({ "v": 1, "key": key, "saved_at": saved_at })
        .to_string()
        .into_bytes()
}

/// Returns the stored key and saved timestamp, or `Unreadable` without echoing content.
pub(crate) fn decode_blob(blob: &[u8]) -> Result<(String, f64), CredentialError> {
    let text = std::str::from_utf8(blob).map_err(|_| CredentialError::Unreadable)?;
    let data: Value = serde_json::from_str(text).map_err(|_| CredentialError::Unreadable)?;
    let key = data.get("key").and_then(Value::as_str).unwrap_or_default();
    let saved_at = data.get("saved_at").and_then(Value::as_f64);
    if data.get("v").and_then(Value::as_i64) != Some(1) || key.is_empty() {
        return Err(CredentialError::Unreadable);
    }
    let saved_at = saved_at.ok_or(CredentialError::Unreadable)?;
    Ok((key.to_string(), saved_at))
}

/// Windows Credential Manager backend (advapi32 CredRead/CredWrite/CredDelete).
/// Reached only through `with_native`, which the native-window build wires up.
#[cfg(windows)]
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) struct WindowsCredentialBackend;

#[cfg(windows)]
impl CredentialBackend for WindowsCredentialBackend {
    fn read(&self, target: &str) -> Result<Option<Vec<u8>>, CredentialError> {
        use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
        use windows_sys::Win32::Security::Credentials::{
            CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
        };
        let wide = to_wide(target);
        let mut out: *mut CREDENTIALW = std::ptr::null_mut();
        unsafe {
            if CredReadW(wide.as_ptr(), CRED_TYPE_GENERIC, 0, &mut out) == 0 {
                let code = GetLastError();
                if code == ERROR_NOT_FOUND {
                    return Ok(None);
                }
                return Err(store_error(code));
            }
            let cred = &*out;
            let bytes = if cred.CredentialBlobSize == 0 || cred.CredentialBlob.is_null() {
                Vec::new()
            } else {
                std::slice::from_raw_parts(cred.CredentialBlob, cred.CredentialBlobSize as usize)
                    .to_vec()
            };
            CredFree(out as *const std::ffi::c_void);
            Ok(Some(bytes))
        }
    }

    fn write(&self, target: &str, blob: &[u8]) -> Result<(), CredentialError> {
        use windows_sys::Win32::Foundation::GetLastError;
        use windows_sys::Win32::Security::Credentials::{
            CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
        };
        let mut wide = to_wide(target);
        let mut cred: CREDENTIALW = unsafe { std::mem::zeroed() };
        cred.Type = CRED_TYPE_GENERIC;
        cred.TargetName = wide.as_mut_ptr();
        cred.CredentialBlobSize = blob.len() as u32;
        cred.CredentialBlob = blob.as_ptr() as *mut u8;
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE;
        unsafe {
            if CredWriteW(&cred, 0) == 0 {
                return Err(store_error(GetLastError()));
            }
        }
        Ok(())
    }

    fn delete(&self, target: &str) -> Result<bool, CredentialError> {
        use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
        use windows_sys::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};
        let wide = to_wide(target);
        unsafe {
            if CredDeleteW(wide.as_ptr(), CRED_TYPE_GENERIC, 0) != 0 {
                return Ok(true);
            }
            let code = GetLastError();
            if code == ERROR_NOT_FOUND {
                return Ok(false);
            }
            Err(store_error(code))
        }
    }
}

#[cfg(windows)]
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
fn to_wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(Some(0)).collect()
}

#[cfg(windows)]
#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
fn store_error(code: u32) -> CredentialError {
    use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
    if code == ERROR_ACCESS_DENIED {
        CredentialError::Unavailable("Windows 凭据库访问被拒绝".into())
    } else {
        CredentialError::Unavailable(format!(
            "Windows 凭据库不可用（Windows 错误 {code}）"
        ))
    }
}

/// Read and decode the stored key. `Ok(None)` means no entry.
pub(crate) fn load(
    backend: &dyn CredentialBackend,
    namespace: &str,
    provider: &str,
) -> Result<Option<(String, f64)>, CredentialError> {
    match backend.read(&target(namespace, provider))? {
        None => Ok(None),
        Some(blob) => decode_blob(&blob).map(Some),
    }
}

/// Validate, then persist a trimmed key with a timestamp. Returns the saved_at stamp.
pub(crate) fn save(
    backend: &dyn CredentialBackend,
    namespace: &str,
    provider: &str,
    key: &str,
    saved_at: f64,
) -> Result<f64, CredentialError> {
    let value = validate_key(key)?;
    backend.write(&target(namespace, provider), &encode_blob(&value, saved_at))?;
    Ok(saved_at)
}

pub(crate) fn remove(
    backend: &dyn CredentialBackend,
    namespace: &str,
    provider: &str,
) -> Result<bool, CredentialError> {
    backend.delete(&target(namespace, provider))
}

/// Provenance and saved state only. Never carries the key value.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct CredentialStatus {
    /// "present" | "absent" | "unavailable" | "unreadable"
    pub state: String,
    pub saved_at: Option<f64>,
    pub error: String,
}

/// Maps a backend-level result into a status row. Never exposes the key.
pub(crate) fn status_of(result: Result<Option<(String, f64)>, CredentialError>) -> CredentialStatus {
    match result {
        Ok(Some((_key, saved_at))) => CredentialStatus {
            state: "present".into(),
            saved_at: Some(saved_at),
            error: String::new(),
        },
        Ok(None) => CredentialStatus {
            state: "absent".into(),
            saved_at: None,
            error: String::new(),
        },
        Err(CredentialError::Unreadable) => CredentialStatus {
            state: "unreadable".into(),
            saved_at: None,
            error: CredentialError::Unreadable.to_string(),
        },
        Err(error) => CredentialStatus {
            state: "unavailable".into(),
            saved_at: None,
            error: error.to_string(),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn target_is_namespaced_per_provider() {
        assert_eq!(target("ns", "tavily"), "ns/tavily");
        assert_eq!(target("ns", "brave"), "ns/brave");
        assert_eq!(target("multi-search", "github"), "multi-search/github");
    }

    #[test]
    fn every_store_provider_is_a_distinct_target() {
        let providers = &crate::source_catalog::catalog().credential_store_providers;
        let targets: std::collections::BTreeSet<String> =
            providers.iter().map(|provider| target("ns", provider)).collect();
        assert_eq!(targets.len(), providers.len());
        assert!(!providers.is_empty());
    }

    /// Python parity (CREDENTIAL_STORE_PROVIDERS in keys.py) is enforced by
    /// tests/test_source_catalog.py against the same generated catalog.
    #[test]
    fn store_providers_match_python_contract_order_free() {
        let mut providers = crate::source_catalog::catalog().credential_store_providers.clone();
        providers.sort();
        let mut expected: Vec<String> = [
            "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github",
        ]
        .iter()
        .map(|provider| provider.to_string())
        .collect();
        expected.sort();
        assert_eq!(providers, expected);
    }
}
