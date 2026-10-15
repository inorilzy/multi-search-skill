//! SQLite credential storage with current-user DPAPI encryption. Shared Python protocol v1.
use rusqlite::OptionalExtension;
use serde::Serialize;
use serde_json::Value;

pub(crate) const MAX_KEY_LENGTH: usize = 1024;
#[allow(dead_code)]
pub(crate) const STORE_PROVIDERS: &[&str] = &[
    "baidu",
    "brave",
    "parallel",
    "tavily",
    "exa",
    "firecrawl",
    "serpapi",
    "github",
    "jina",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CredentialError {
    Unavailable(String),
    Unreadable,
    Invalid(&'static str),
}
impl std::fmt::Display for CredentialError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unavailable(message) => f.write_str(message),
            Self::Unreadable => f.write_str("stored credential is unreadable"),
            Self::Invalid(message) => f.write_str(message),
        }
    }
}
/// Plain JSON backend boundary; native implementation encrypts before writing and decrypts on read.
/// Test memory implementations never access real user data.
pub(crate) trait CredentialBackend: Send + Sync {
    fn read(&self, provider: &str) -> Result<Option<Vec<u8>>, CredentialError>;
    fn write(&self, provider: &str, blob: &[u8]) -> Result<(), CredentialError>;
    fn delete(&self, provider: &str) -> Result<bool, CredentialError>;
}
pub(crate) fn validate_key(key: &str) -> Result<String, CredentialError> {
    let text = key.trim();
    if text.is_empty()
        || text.len() > MAX_KEY_LENGTH
        || text.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
    {
        return Err(CredentialError::Invalid(
            "key must be 1-1024 characters with no control characters",
        ));
    }
    Ok(text.to_string())
}
// Namespace no longer controls normal storage; provider is the database primary key.
pub(crate) fn namespace(_: &std::collections::BTreeMap<String, String>) -> String {
    String::new()
}
pub(crate) fn target(_: &str, provider: &str) -> String {
    provider.to_string()
}
fn validate_value(provider: &str, value: &Value) -> bool {
    match value {
        Value::String(s) => validate_key(s).is_ok(),
        Value::Array(items) => !items.is_empty() && items.iter().all(|v| (v.is_string() || provider == "jina" && v.is_object()) && validate_value(provider,v)),
        Value::Object(map) if provider == "jina" => map.get("key").and_then(Value::as_str).is_some_and(|s| validate_key(s).is_ok()) && map.get("exhausted").is_none_or(Value::is_boolean),
        _ => false,
    }
}
fn editor_value(text: &str) -> Result<Value, CredentialError> {
    let keys: Vec<String> = text.lines().map(validate_key).collect::<Result<_, _>>()?;
    if keys.is_empty() || keys.len() > 256 {
        return Err(CredentialError::Invalid("provide 1-256 keys, one per line"));
    }
    Ok(if keys.len() == 1 {
        Value::String(keys[0].clone())
    } else {
        serde_json::json!(keys)
    })
}
pub(crate) fn encode_blob(key: &Value, saved_at: f64) -> Vec<u8> {
    serde_json::json!({"v":1,"key":key,"saved_at":saved_at})
        .to_string()
        .into_bytes()
}
pub(crate) fn decode_blob(provider: &str, blob: &[u8]) -> Result<(Value, f64), CredentialError> {
    let data: Value = serde_json::from_slice(blob).map_err(|_| CredentialError::Unreadable)?;
    let key = data.get("key").ok_or(CredentialError::Unreadable)?.clone();
    let valid = validate_value(provider, &key);
    let saved_at = data
        .get("saved_at")
        .and_then(Value::as_f64)
        .filter(|v| v.is_finite())
        .ok_or(CredentialError::Unreadable)?;
    if data.get("v").and_then(Value::as_i64) != Some(1) || !valid {
        return Err(CredentialError::Unreadable);
    }
    Ok((key, saved_at))
}
pub(crate) fn load(
    backend: &dyn CredentialBackend,
    namespace: &str,
    provider: &str,
) -> Result<Option<(Value, f64)>, CredentialError> {
    backend
        .read(&target(namespace, provider))?
        .map(|blob| decode_blob(provider, &blob))
        .transpose()
}
pub(crate) fn save(
    backend: &dyn CredentialBackend,
    namespace: &str,
    provider: &str,
    key: &str,
    saved_at: f64,
) -> Result<f64, CredentialError> {
    let value = editor_value(key)?;
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

#[cfg_attr(not(feature = "native-window"), allow(dead_code))]
pub(crate) struct SqliteCredentialBackend {
    pub path: std::path::PathBuf,
}
impl SqliteCredentialBackend {
    fn connection(&self) -> Result<rusqlite::Connection, CredentialError> {
        if self.path.as_os_str().is_empty() {
            return Err(CredentialError::Unavailable("无法定位配置数据库".into()));
        }
        crate::config_db::open(&self.path).map_err(CredentialError::Unavailable)
    }
}
impl CredentialBackend for SqliteCredentialBackend {
    fn read(&self, provider: &str) -> Result<Option<Vec<u8>>, CredentialError> {
        if self.path.as_os_str().is_empty() {
            return Err(CredentialError::Unavailable("无法定位配置数据库".into()));
        }
        if !self.path.exists() {
            return Ok(None);
        }
        let connection = self.connection()?;
        let encrypted: Option<Vec<u8>> = connection
            .query_row(
                "SELECT encrypted_value FROM credentials WHERE provider=?1",
                [provider],
                |r| r.get(0),
            )
            .optional()
            .map_err(|_| CredentialError::Unavailable("无法读取配置数据库凭据".into()))?;
        encrypted.map(|blob| crypt(&blob, false)).transpose()
    }
    fn write(&self, provider: &str, blob: &[u8]) -> Result<(), CredentialError> {
        let (_, saved_at) = decode_blob(provider, blob)?;
        let encrypted = crypt(blob, true)?; // Encryption must succeed before touching database.
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|_| CredentialError::Unavailable("配置数据库事务失败".into()))?;
        transaction.execute("INSERT INTO credentials(provider,encrypted_value,saved_at) VALUES(?1,?2,?3) ON CONFLICT(provider) DO UPDATE SET encrypted_value=excluded.encrypted_value,saved_at=excluded.saved_at", rusqlite::params![provider, encrypted, saved_at])
            .map_err(|_| CredentialError::Unavailable("保存凭据失败，原值未改变".into()))?;
        transaction
            .commit()
            .map_err(|_| CredentialError::Unavailable("保存凭据失败，原值未改变".into()))
    }
    fn delete(&self, provider: &str) -> Result<bool, CredentialError> {
        if self.path.as_os_str().is_empty() { return Err(CredentialError::Unavailable("无法定位配置数据库".into())); }
        if !self.path.exists() {
            return Ok(false);
        }
        self.connection()?
            .execute("DELETE FROM credentials WHERE provider=?1", [provider])
            .map(|n| n > 0)
            .map_err(|_| CredentialError::Unavailable("删除凭据失败".into()))
    }
}
#[cfg(windows)]
pub(crate) fn crypt(bytes: &[u8], encrypt: bool) -> Result<Vec<u8>, CredentialError> {
    use windows_sys::Win32::{
        Foundation::{GetLastError, LocalFree},
        Security::Cryptography::{
            CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
        },
    };
    if bytes.len() > u32::MAX as usize {
        return Err(CredentialError::Unreadable);
    }
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output: CRYPT_INTEGER_BLOB = unsafe { std::mem::zeroed() };
    unsafe {
        let ok = if encrypt {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null_mut(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null_mut(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        };
        if ok == 0 {
            return Err(CredentialError::Unavailable(format!(
                "DPAPI {}失败 (Windows error {})",
                if encrypt { "加密" } else { "解密" },
                GetLastError()
            )));
        }
        let value = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        LocalFree(output.pbData as *mut std::ffi::c_void);
        Ok(value)
    }
}
#[cfg(not(windows))]
pub(crate) fn crypt(_: &[u8], _: bool) -> Result<Vec<u8>, CredentialError> {
    Err(CredentialError::Unavailable(
        "DPAPI is only available on Windows; no plaintext fallback".into(),
    ))
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct CredentialStatus {
    pub state: String,
    pub saved_at: Option<f64>,
    pub error: String,
}
pub(crate) fn status_of(result: Result<Option<(Value, f64)>, CredentialError>) -> CredentialStatus {
    match result {
        Ok(Some((_, saved_at))) => CredentialStatus {
            state: "present".into(),
            saved_at: Some(saved_at),
            error: String::new(),
        },
        Ok(None) => CredentialStatus {
            state: "absent".into(),
            saved_at: None,
            error: String::new(),
        },
        Err(error) => CredentialStatus {
            state: if error == CredentialError::Unreadable {
                "unreadable"
            } else {
                "unavailable"
            }
            .into(),
            saved_at: None,
            error: error.to_string(),
        },
    }
}
