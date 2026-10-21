//! Single home for Windows-facing primitives shared by environment discovery,
//! install, skill management, and PATH registration.
//!
//! Keeping these here means the registry read/`%VAR%` expansion/UTF-16 decode/
//! reparse-point checks have exactly one implementation instead of drifting
//! copies in each module.
use std::{collections::BTreeMap, fs};

#[cfg(windows)]
fn registry_string_raw(
    root: windows_sys::Win32::System::Registry::HKEY,
    subkey: &str,
    name: &str,
) -> Option<String> {
    use windows_sys::Win32::System::Registry::{
        RegGetValueW, RRF_NOEXPAND, RRF_RT_REG_EXPAND_SZ, RRF_RT_REG_SZ,
    };
    let sub: Vec<u16> = subkey.encode_utf16().chain(Some(0)).collect();
    let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    let mut bytes = 0;
    unsafe {
        if RegGetValueW(
            root,
            sub.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut bytes,
        ) != 0
        {
            return None;
        }
        let mut value = vec![0u16; bytes as usize / 2];
        if RegGetValueW(
            root,
            sub.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND,
            std::ptr::null_mut(),
            value.as_mut_ptr() as _,
            &mut bytes,
        ) != 0
        {
            return None;
        }
        // The raw value is expanded centrally below, avoiding API auto-expansion
        // leaving embedded NULs in the buffer.
        value.truncate(bytes as usize / 2);
        while value.last() == Some(&0) {
            value.pop();
        }
        Some(String::from_utf16_lossy(&value))
    }
}

/// Read a REG_SZ/REG_EXPAND_SZ value without expanding it.
#[cfg(windows)]
pub(crate) fn registry_string(
    root: windows_sys::Win32::System::Registry::HKEY,
    subkey: &str,
    name: &str,
) -> Option<String> {
    registry_string_raw(root, subkey, name)
}

#[cfg(not(windows))]
pub(crate) fn registry_string(_: usize, _: &str, _: &str) -> Option<String> {
    None
}

/// Expand `%NAME%` references (case-insensitive) up to four levels deep.
/// Unknown references are left intact.
pub(crate) fn expand(value: &str, variables: &BTreeMap<String, String>) -> String {
    let mut output = value.to_string();
    for _ in 0..4 {
        let prior = output.clone();
        let mut expanded = String::new();
        let mut rest = output.as_str();
        while let Some(start) = rest.find('%') {
            expanded.push_str(&rest[..start]);
            let after = &rest[start + 1..];
            let Some(end) = after.find('%') else {
                expanded.push_str(&rest[start..]);
                rest = "";
                break;
            };
            let name = &after[..end];
            if let Some((_, replacement)) = variables
                .iter()
                .find(|(key, _)| key.eq_ignore_ascii_case(name))
            {
                expanded.push_str(replacement);
            } else {
                expanded.push_str(&rest[start..start + end + 2]);
            }
            rest = &after[end + 1..];
        }
        expanded.push_str(rest);
        output = expanded;
        if output == prior {
            break;
        }
    }
    output
}

/// Decode a little-endian UTF-16 registry buffer, rejecting odd lengths,
/// invalid text, and embedded NULs.
#[cfg(windows)]
pub(crate) fn decode_utf16(bytes: &[u8]) -> Result<String, String> {
    if !bytes.len().is_multiple_of(2) {
        return Err("注册表 PATH 格式不支持".into());
    }
    let mut words: Vec<u16> = bytes
        .chunks_exact(2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .collect();
    if words.last() == Some(&0) {
        words.pop();
    }
    let text = String::from_utf16(&words).map_err(|_| "注册表 PATH 不是有效文本")?;
    if text.contains('\0') {
        return Err("注册表 PATH 包含无效字符".into());
    }
    Ok(text)
}

/// True when the metadata carries FILE_ATTRIBUTE_REPARSE_POINT (junction,
/// mount point, or other reparse tag).
#[cfg(windows)]
pub(crate) fn is_reparse_point(meta: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    meta.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
pub(crate) fn is_reparse_point(_: &fs::Metadata) -> bool {
    false
}

/// A symlink or Windows reparse point. Install/skill code must refuse both:
/// following either could write or delete outside the managed directory.
pub(crate) fn is_link(meta: &fs::Metadata) -> bool {
    meta.file_type().is_symlink() || is_reparse_point(meta)
}

#[cfg(all(test, windows))]
mod tests {
    #[test]
    fn machine_registry_path_has_no_embedded_nul_before_building_child_environment() {
        let path = super::registry_string(
            windows_sys::Win32::System::Registry::HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
            "Path",
        )
        .expect("机器 PATH 应可只读查询");
        assert!(!path.contains('\0'), "注册表读取生成了含 NUL 的子进程 PATH");
    }

    #[test]
    fn expand_is_case_insensitive_and_leaves_unknown_references() {
        let variables = std::collections::BTreeMap::from([
            ("USERPROFILE".to_string(), "C:/Users/x".to_string()),
            ("TEMP".to_string(), "C:/Temp".to_string()),
        ]);
        assert_eq!(
            super::expand("%userprofile%;%TEMP%", &variables),
            "C:/Users/x;C:/Temp"
        );
        assert_eq!(super::expand("%UNKNOWN%/x", &variables), "%UNKNOWN%/x");
        assert_eq!(super::expand("100%", &variables), "100%");
    }

    #[test]
    fn decode_utf16_rejects_odd_bytes_and_embedded_nul() {
        assert!(super::decode_utf16(&[0, 1, 2]).is_err());
        // A trailing terminator is stripped; an *embedded* NUL is rejected.
        assert_eq!(super::decode_utf16(&[0x41, 0, 0, 0]).unwrap(), "A");
        assert!(super::decode_utf16(&[0x41, 0, 0, 0, 0x42, 0]).is_err());
        assert_eq!(super::decode_utf16(&[0x41, 0]).unwrap(), "A");
    }
}
