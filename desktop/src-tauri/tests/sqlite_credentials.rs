//! Real current-user DPAPI against unique disposable SQLite files and synthetic credentials only.
#![cfg(windows)]
use multi_search_desktop::credential_fixture as fixture;
use std::path::PathBuf;
struct Sandbox(PathBuf);
impl Sandbox { fn new(tag:&str)->Self { let p=std::env::temp_dir().join(format!("ms-dpapi-sqlite-{tag}-{}",std::process::id())); let _=std::fs::remove_dir_all(&p); std::fs::create_dir_all(&p).unwrap(); Self(p) } fn db(&self)->PathBuf {self.0.join("config.sqlite")} }
impl Drop for Sandbox { fn drop(&mut self) {let _=std::fs::remove_dir_all(&self.0);} }
#[test] fn synthetic_native_roundtrip_preserves_multi_keys_and_never_stores_plaintext() {
    let s=Sandbox::new("roundtrip"); let value=serde_json::json!(["synthetic-native-sqlite-0001","synthetic-native-sqlite-0002"]);
    fixture::native_write(&s.db(),"tavily",&value,1700000001.5).unwrap();
    assert_eq!(fixture::native_read(&s.db(),"tavily").unwrap(),Some(value.clone()));
    let c=rusqlite::Connection::open(s.db()).unwrap();
    let saved:f64=c.query_row("SELECT saved_at FROM credentials WHERE provider='tavily'",[],|r|r.get(0)).unwrap(); assert_eq!(saved,1700000001.5);
    let encrypted:Vec<u8>=c.query_row("SELECT encrypted_value FROM credentials WHERE provider='tavily'",[],|r|r.get(0)).unwrap(); assert!(!encrypted.starts_with(b"{")); drop(c);
    for file in std::fs::read_dir(&s.0).unwrap(){let bytes=std::fs::read(file.unwrap().path()).unwrap();for key in value.as_array().unwrap(){assert!(!bytes.windows(key.as_str().unwrap().len()).any(|w|w==key.as_str().unwrap().as_bytes()));}}
    let replaced=serde_json::json!("synthetic-replaced-key-0003");fixture::native_write(&s.db(),"tavily",&replaced,1700000002.0).unwrap();assert_eq!(fixture::native_read(&s.db(),"tavily").unwrap(),Some(replaced));
    assert!(fixture::native_delete(&s.db(),"tavily").unwrap());assert_eq!(fixture::native_read(&s.db(),"tavily").unwrap(),None);assert!(!fixture::native_delete(&s.db(),"tavily").unwrap());
}
#[test]fn malformed_dpapi_is_error_not_legacy_fallback(){let s=Sandbox::new("corrupt");fixture::native_write(&s.db(),"tavily",&serde_json::json!("synthetic-key"),1.0).unwrap();let c=rusqlite::Connection::open(s.db()).unwrap();c.execute("UPDATE credentials SET encrypted_value=?1 WHERE provider='tavily'",[b"not dpapi".as_slice()]).unwrap();assert!(fixture::native_read(&s.db(),"tavily").unwrap_err().contains("DPAPI"));}
#[test]fn failed_write_rolls_back_original_value(){let s=Sandbox::new("rollback");let old=serde_json::json!("synthetic-original");fixture::native_write(&s.db(),"tavily",&old,1.0).unwrap();let c=rusqlite::Connection::open(s.db()).unwrap();c.execute_batch("CREATE TRIGGER deny_key BEFORE UPDATE ON credentials BEGIN SELECT RAISE(ABORT,'denied'); END;").unwrap();assert!(fixture::native_write(&s.db(),"tavily",&serde_json::json!("synthetic-new"),2.0).is_err());assert_eq!(fixture::native_read(&s.db(),"tavily").unwrap(),Some(old));}
#[test]fn jina_json_structure_is_preserved(){let s=Sandbox::new("jina");let jina=serde_json::json!([{"key":"synthetic-jina-0001","exhausted":true},{"key":"synthetic-jina-0002","exhausted":false}]);fixture::native_write(&s.db(),"jina",&jina,1.0).unwrap();assert_eq!(fixture::native_read(&s.db(),"jina").unwrap(),Some(jina));}
#[test]fn rust_python_product_credential_store_roundtrip() {
    let s=Sandbox::new("product-cross");
    let jina=serde_json::json!([{"key":"synthetic-jina-product-0001","exhausted":true},{"key":"synthetic-jina-product-0002","exhausted":false}]);
    fixture::native_write(&s.db(),"jina",&jina,1.5).unwrap();
    fixture::native_write(&s.db(),"tavily",&serde_json::json!(["synthetic-product-0001","synthetic-product-0002"]),1.5).unwrap();
    let root=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script=r#"
import sys
from multi_search_mcp.src.support.credential_store import CredentialStore, SQLiteCredentialBackend
store=CredentialStore(SQLiteCredentialBackend(sys.argv[1]))
assert store.get('tavily')==['synthetic-product-0001','synthetic-product-0002']
assert store.get('jina')==[{'key':'synthetic-jina-product-0001','exhausted':True},{'key':'synthetic-jina-product-0002','exhausted':False}]
store.set('brave',['synthetic-python-product-0001','synthetic-python-product-0002'],saved_at=2.5)
store.set('jina',{'key':'synthetic-python-jina-product','exhausted':False},saved_at=2.5)
print('product implementation roundtrip passed')
"#;
    let out=std::process::Command::new("python").args(["-B","-c",script]).arg(s.db()).env("PYTHONPATH",root).env("HOME",&s.0).env("USERPROFILE",&s.0).env("MULTI_SEARCH_CONFIG_DB",s.db()).output().unwrap();
    assert!(out.status.success(),"{}",String::from_utf8_lossy(&out.stderr));
    assert_eq!(fixture::native_read(&s.db(),"brave").unwrap(),Some(serde_json::json!(["synthetic-python-product-0001","synthetic-python-product-0002"])));
    assert_eq!(fixture::native_read(&s.db(),"jina").unwrap(),Some(serde_json::json!({"key":"synthetic-python-jina-product","exhausted":false})));
}
#[test]
fn rust_editor_roundtrip_keeps_jina_exhausted_keys_out_of_python_rotation() {
    let s = Sandbox::new("jina-editor-cross");
    let original = serde_json::json!([
        {"key":"synthetic-jina-disabled","exhausted":true,"note":{"owner":"test"}},
        {"key":"synthetic-jina-active","exhausted":false},
        "synthetic-jina-plain",
        {"key":" synthetic-jina-padded ","exhausted":true,"note":[1,"kept"]}
    ]);
    fixture::native_write(&s.db(), "jina", &original, 1.0).unwrap();
    // This is the text shown by the editor, saved unchanged through production merge logic.
    fixture::native_editor_save(&s.db(), "jina", "synthetic-jina-disabled\nsynthetic-jina-active\nsynthetic-jina-plain\n synthetic-jina-padded ", 2.0).unwrap();
    assert_eq!(fixture::native_read(&s.db(), "jina").unwrap(), Some(original));
    let script = r#"
import sys
from multi_search_mcp.src.support.credential_store import CredentialStore, SQLiteCredentialBackend
from multi_search_mcp.src.state.keys import jina_config_keys
store = CredentialStore(SQLiteCredentialBackend(sys.argv[1]))
value = store.get('jina')
assert value[0] == {'key':'synthetic-jina-disabled', 'exhausted':True, 'note':{'owner':'test'}}
assert jina_config_keys(value) == ['synthetic-jina-active', 'synthetic-jina-plain']
assert 'synthetic-jina-disabled' not in jina_config_keys(value)
assert value[3] == {'key':'synthetic-jina-padded', 'exhausted':True, 'note':[1,'kept']}
print('Jina editor -> DPAPI SQLite -> Python rotation passed')
"#;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let out = std::process::Command::new("python").args(["-B", "-c", script]).arg(s.db())
        .env("PYTHONPATH", root).env("HOME", &s.0).env("USERPROFILE", &s.0)
        .env("MULTI_SEARCH_CONFIG_DB", s.db()).output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert!(String::from_utf8_lossy(&out.stdout).contains("Jina editor -> DPAPI SQLite -> Python rotation passed"));
}
#[test]fn invalid_jina_and_non_jina_objects_fail_before_persistence(){let s=Sandbox::new("invalid-jina");for value in [serde_json::json!({"keys":["invalid-shape"]}),serde_json::json!({"key":"synthetic","exhausted":"yes"}),serde_json::json!([{"key":"synthetic"},123])]{assert!(fixture::native_write(&s.db(),"jina",&value,1.0).is_err());}assert!(fixture::native_write(&s.db(),"tavily",&serde_json::json!({"key":"synthetic"}),1.0).is_err());assert!(!s.db().exists());}
#[test]fn rust_python_native_encryption_protocol_in_both_directions(){
    let s=Sandbox::new("cross-language");let key=serde_json::json!(["synthetic-cross-0001","synthetic-cross-0002"]);fixture::native_write(&s.db(),"tavily",&key,1700000001.5).unwrap();
    // Python standard library ctypes directly verifies the agreed protocol independent of app code.
    let script=r#"
import ctypes,json,sqlite3,sys
from ctypes import wintypes
class Blob(ctypes.Structure): _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
crypt=ctypes.WinDLL('crypt32',use_last_error=True); kernel=ctypes.WinDLL('kernel32',use_last_error=True)
for name in ('CryptProtectData','CryptUnprotectData'):
 f=getattr(crypt,name); f.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]; f.restype=wintypes.BOOL
kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
def run(value,encrypt):
 buf=(ctypes.c_ubyte*len(value)).from_buffer_copy(value);src=Blob(len(value),buf);out=Blob()
 assert getattr(crypt,'CryptProtectData' if encrypt else 'CryptUnprotectData')(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out))
 try:return ctypes.string_at(out.pbData,out.cbData)
 finally:kernel.LocalFree(out.pbData)
c=sqlite3.connect(sys.argv[1]);v=json.loads(run(c.execute("SELECT encrypted_value FROM credentials WHERE provider='tavily'").fetchone()[0],False));assert v=={'v':1,'key':['synthetic-cross-0001','synthetic-cross-0002'],'saved_at':1700000001.5}
payload={'v':1,'key':['synthetic-python-0001','synthetic-python-0002'],'saved_at':1700000002.5}
c.execute("INSERT INTO credentials(provider,encrypted_value,saved_at) VALUES('brave',?,?)",(run(json.dumps(payload,separators=(',',':')).encode(),True),payload['saved_at']));c.commit();print('protocol roundtrip passed')
"#;
    let out=std::process::Command::new("python").args(["-B","-c",script]).arg(s.db()).env("HOME",&s.0).env("USERPROFILE",&s.0).env("MULTI_SEARCH_CONFIG_DB",s.db()).output().unwrap();assert!(out.status.success(),"{}",String::from_utf8_lossy(&out.stderr));
    assert_eq!(fixture::native_read(&s.db(),"brave").unwrap(),Some(serde_json::json!(["synthetic-python-0001","synthetic-python-0002"])));
}
