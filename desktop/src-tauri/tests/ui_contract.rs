//! Deterministic emission and drift-checking of the UI contract
//! `desktop/ui/types.d.ts`, plus field-level cross-checks against the
//! hand-written boundary validator in `desktop/ui/payloads.js`.
//!
//! Every Tauri command payload type carries `#[derive(TS)]` plus
//! `#[ts(export_to = "types.d.ts")]`. We deliberately do NOT use `#[ts(export)]`:
//! that attribute makes `cargo test` spawn one exporter test per type and the
//! resulting concurrent writes to the shared `types.d.ts` make the artifact
//! depend on test scheduling. Instead, `emit_types_d_ts` calls `TS::export` for
//! every public command payload in a fixed order — ts-rs merges them into the
//! shared file deterministically.
//!
//! Two executable drift checks live here (no CI-only script required):
//!
//! * `types_d_ts_is_up_to_date` regenerates the declarations in memory and
//!   compares them to the committed file. It never writes; when the contract
//!   moves, run `cargo test --test ui_contract emit_types_d_ts`.
//! * `payloads_js_matches_rust_field_types` parses both the generated `.d.ts`
//!   and `payloads.js` and asserts the field name set and each field's
//!   primitive kind / nullability agree — not just a text search.
//!
//! `Validated` is internal to the settings writer and is intentionally excluded
//! from the contract.

use multi_search_desktop::contract;
use std::{collections::BTreeMap, path::PathBuf};
use ts_rs::TS;

// ts-rs rewrites the shared output once per type; readers must not see a
// partially emitted file when this test binary runs with its default parallelism.
static CONTRACT_FILE: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn ui_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("ui")
}

fn config() -> ts_rs::Config {
    // u64 execution ids are realistic small counters; the wire uses a JSON
    // number, so emit `number` (not `bigint`) to keep the type honest.
    ts_rs::Config::default().with_large_int("number")
}

/// Every public Tauri command payload type, in stable declaration order.
/// `settings_save` accepts `SettingsInput`; every other entry here is a
/// command return value.
macro_rules! for_each_contract_type {
    ($macro:ident) => {
        $macro!(
            contract::Discovery,
            contract::CliStatus,
            contract::SearchOptions,
            contract::ExecutionStatus,
            contract::InstallPlan,
            contract::InstallStep,
            contract::InstallOutcome,
            contract::SkillPlan,
            contract::SkillInstall,
            contract::InstallState,
            contract::SkillStatus,
            contract::UpdatePlan,
            contract::RemovePlan,
            contract::UpdateOutcome,
            contract::RemoveOutcome,
            contract::PathValue,
            contract::PathReceipt,
            contract::PathPlan,
            contract::CredentialStatus,
            contract::CredentialOverview,
            contract::CredentialValue,
            contract::TestOutcome,
            contract::ProviderInfo,
            contract::RouteConfig,
            contract::ScrapeBackendOption,
            contract::ScrapeMemoryRow,
            contract::ScrapeMemoryView,
            contract::SettingsInput,
            contract::SettingsView,
        );
    };
}

/// (TypeScript name, generated declaration) for every contract type.
fn generated_declarations() -> BTreeMap<String, String> {
    let cfg = config();
    let mut out = BTreeMap::new();
    macro_rules! collect {
        ($($ty:ty),* $(,)?) => {
            $(
                out.insert(<$ty as TS>::name(&cfg), <$ty as TS>::decl(&cfg));
            )*
        };
    }
    for_each_contract_type!(collect);
    out
}

/// Write `desktop/ui/types.d.ts`. Run when the Rust contract changes.
#[test]
fn emit_types_d_ts() {
    let _guard = CONTRACT_FILE.lock().unwrap();
    let out_dir = ui_dir();
    std::fs::create_dir_all(&out_dir).unwrap();
    let cfg = config().with_out_dir(&out_dir);

    macro_rules! export_one {
        ($($ty:ty),* $(,)?) => {
            $(
                <$ty as TS>::export(&cfg).unwrap_or_else(|e| {
                    panic!("could not emit {}: {e}", std::any::type_name::<$ty>())
                });
            )*
        };
    }
    for_each_contract_type!(export_one);

    let emitted = out_dir.join("types.d.ts");
    assert!(emitted.is_file(), "expected {} to be written", emitted.display());
}

/// Drift check: the committed declaration file must match what the Rust types
/// generate right now. This is the executable entry point — a payload change
/// that forgot to regenerate `types.d.ts` fails here.
#[test]
fn types_d_ts_is_up_to_date() {
    let _guard = CONTRACT_FILE.lock().unwrap();
    let committed = std::fs::read_to_string(ui_dir().join("types.d.ts"))
        .expect("desktop/ui/types.d.ts must be committed");

    for (name, decl) in generated_declarations() {
        let needle = format!("export type {name} = ");
        let start = committed.find(&needle).unwrap_or_else(|| {
            panic!(
                "types.d.ts is missing `export type {name}`; run \
                 `cargo test --test ui_contract emit_types_d_ts` to regenerate"
            )
        });
        let body = &committed[start + needle.len()..];
        // Comments may contain `;`; strip them before locating the terminator.
        let body_no_comments: String = body
            .lines()
            .filter(|line| {
                let t = line.trim();
                !t.starts_with("/**") && !t.starts_with('*') && !t.starts_with("*/")
            })
            .collect::<Vec<_>>()
            .join("\n");
        let end = body_no_comments.find(';').unwrap_or(body_no_comments.len());
        let actual = body_no_comments[..end].trim();
        let expected_no_comments: String = decl
            .split_once(" = ")
            .map(|(_, rest)| rest)
            .unwrap_or(&decl)
            .lines()
            .filter(|line| {
                let t = line.trim();
                !t.starts_with("/**") && !t.starts_with('*') && !t.starts_with("*/")
            })
            .collect::<Vec<_>>()
            .join("\n");
        let expected = expected_no_comments
            .trim()
            .trim_end_matches(';')
            .trim();
        assert_eq!(
            actual, expected,
            "types.d.ts is stale for `{name}`; run \
             `cargo test --test ui_contract emit_types_d_ts` to regenerate"
        );
    }
}

/// Parsed shape of one `.d.ts` object type: field -> normalised kind tag.
fn parse_d_ts_object(body: &str) -> BTreeMap<String, String> {
    // `decl()` returns `type Name = { ... }`; drop the prefix so the first
    // colon in the body belongs to the first field, not the type name.
    let body = body.split_once(" = ").map(|(_, rest)| rest).unwrap_or(body);
    let mut fields = BTreeMap::new();
    // Drop doc comments so they cannot confuse the field splitter.
    let body: String = body
        .lines()
        .filter(|line| {
            let t = line.trim();
            !t.starts_with("/**") && !t.starts_with('*') && !t.starts_with("*/")
        })
        .collect::<Vec<_>>()
        .join("\n");
    for chunk in body.split(',') {
        let Some((name, ty)) = chunk.split_once(':') else { continue };
        let name = name
            .trim()
            .trim_start_matches('{')
            .trim();
        if name.is_empty() || name.contains(' ') || name.contains('[') {
            continue;
        }
        let ty = ty.trim().trim_end_matches('}').trim();
        if ty.is_empty() {
            continue;
        }
        fields.insert(name.to_string(), normalise_ts_type(ty));
    }
    fields
}

fn normalise_ts_type(ty: &str) -> String {
    let ty = ty.trim();
    if let Some((inner, suffix)) = ty.split_once('|') {
        if suffix.trim() == "null" {
            return format!("{}|null", normalise_ts_type(inner.trim()));
        }
    }
    match ty {
        "string" => "s".into(),
        "number" => "n".into(),
        "boolean" => "b".into(),
        "Array<string>" => "sa".into(),
        "JsonValue" => "x".into(),
        // String unions (InstallState) are validated as a plain string so a
        // new Rust variant degrades to the raw wire value.
        "InstallState" => "s".into(),
        _ if ty.starts_with("Array<") => {
            let inner = ty.trim_start_matches("Array<").trim_end_matches('>');
            format!("{inner}[]")
        }
        _ if ty.starts_with("{ [key in string]: ") => {
            let inner = ty
                .trim_start_matches("{ [key in string]: ")
                .trim_end_matches(" }");
            if inner == "number" {
                "NumMap".into()
            } else if inner == "RouteConfig" {
                "RouteMap".into()
            } else {
                format!("Map:{inner}")
            }
        }
        other => other.into(),
    }
}

/// Convert a payloads.js tag to the same normalised vocabulary.
fn normalise_js_tag(tag: &str) -> String {
    let tag = tag.trim().trim_matches('\'');
    match tag {
        "s" => "s".into(),
        "n" => "n".into(),
        "b" => "b".into(),
        "sn" => "s|null".into(),
        "nn" => "n|null".into(),
        "sa" => "sa".into(),
        "san" => "sa|null".into(),
        "a" => "a".into(),
        "o" => "o".into(),
        "x" => "x".into(),
        "xn" => "x|null".into(),
        "RouteMapN" => "RouteMap|null".into(),
        // Compound type names are quoted in payloads.js (`'Discovery'`).
        other => other.to_string(),
    }
}

/// Extract `schemas.<Type>: schema({ ... })` blocks from payloads.js.
/// The file is hand-written in a fixed style; a style break fails loudly.
fn parse_payloads_js(source: &str) -> BTreeMap<String, BTreeMap<String, String>> {
    let mut out = BTreeMap::new();
    let mut rest = source;
    while let Some(start) = rest.find(": schema({") {
        let head = &rest[..start];
        let name_start = head
            .rfind(|c: char| !(c.is_alphanumeric() || c == '_'))
            .map(|i| i + 1)
            .unwrap_or(0);
        let name = head[name_start..].trim().to_string();
        let body_start = start + ": schema({".len();
        let body_end = rest[body_start..]
            .find("})")
            .expect("unterminated schema({ ... })")
            + body_start;
        let body = &rest[body_start..body_end];
        let mut fields = BTreeMap::new();
        for pair in body.split(',') {
            let Some((k, v)) = pair.split_once(':') else { continue };
            let k = k.trim();
            let v = v.trim();
            if k.is_empty() || v.is_empty() {
                continue;
            }
            fields.insert(k.to_string(), normalise_js_tag(v));
        }
        out.insert(name, fields);
        rest = &rest[body_end + 2..];
    }
    out
}

/// String unions (`InstallState`) are represented as an empty schema; they
/// are validated only for presence.
fn is_union_type(decl: &str) -> bool {
    !decl.contains('{')
}

/// Gap B: every `schemas.<Type>` in payloads.js must list exactly the fields
/// the Rust payload serialises, with matching primitive kind and nullability.
#[test]
fn payloads_js_matches_rust_field_types() {
    let _guard = CONTRACT_FILE.lock().unwrap();
    let payloads = std::fs::read_to_string(ui_dir().join("payloads.js"))
        .expect("desktop/ui/payloads.js must be committed");
    let js_schemas = parse_payloads_js(&payloads);

    for (name, decl) in generated_declarations() {
        if is_union_type(&decl) {
            assert!(
                js_schemas.contains_key(&name),
                "payloads.js is missing `schemas.{name}` for the union type"
            );
            continue;
        }
        let expected = parse_d_ts_object(&decl);
        let actual = js_schemas.get(&name).unwrap_or_else(|| {
            panic!(
                "payloads.js is missing `schemas.{name}`; add it next to the other \
                 command payload schemas"
            )
        });

        assert_eq!(
            actual.keys().collect::<Vec<_>>(),
            expected.keys().collect::<Vec<_>>(),
            "payloads.js `schemas.{name}` field set drifted from the Rust declaration"
        );
        for (field, want) in &expected {
            assert_eq!(
                &actual[field], want,
                "payloads.js `schemas.{name}.{field}` should be {want:?}, found {:?}",
                actual[field]
            );
        }
    }
}
