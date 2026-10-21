//! Deterministic emission of the UI contract `desktop/ui/types.d.ts`.
//!
//! Every Tauri command payload type carries `#[derive(TS)]` plus
//! `#[ts(export_to = "types.d.ts")]`. We deliberately do NOT use `#[ts(export)]`:
//! that attribute makes `cargo test` spawn one exporter test per type and the
//! resulting concurrent writes to the shared `types.d.ts` make the artifact
//! depend on test scheduling. Instead, this test calls `TS::export` for every
//! public command payload in a fixed order, which ts-rs merges into the shared
//! file deterministically.
//!
//! `git diff --exit-code` on `desktop/ui/types.d.ts` catches drift between
//! the Rust contract and the committed declaration file.
//!
//! The companion `desktop/ui/payloads.js` is a hand-written boundary
//! validator (not generated). `validators_cover_contract_types` below
//! cross-checks that it has a schema entry for every public payload type, so
//! the two cannot drift without breaking the build.

use multi_search_desktop::contract;
use std::path::PathBuf;
use ts_rs::TS;

fn ui_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("ui")
}

/// Every public Tauri command payload type, in stable declaration order.
/// `settings_save` accepts `SettingsInput`; every other entry here is a
/// command return value. `Validated` is internal to the settings writer and
/// is intentionally excluded.
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
            contract::SettingsInput,
            contract::SettingsView,
        );
    };
}

#[test]
fn emit_types_d_ts() {
    let out_dir = ui_dir();
    std::fs::create_dir_all(&out_dir).unwrap();
    // u64 execution ids are realistic small counters; the wire uses a JSON
    // number, so emit `number` (not `bigint`) to keep the type honest.
    let cfg = ts_rs::Config::default()
        .with_out_dir(&out_dir)
        .with_large_int("number");

    // Sequential calls go through ts-rs's `export_and_merge`, which uses a
    // process-wide mutex plus alphabetical merge. Single test → deterministic
    // file on disk.
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
    assert!(
        emitted.is_file(),
        "expected {} to be written",
        emitted.display()
    );
}

/// The boundary validator in `ui/payloads.js` declares one entry per command
/// payload under `schemas.<Type>`. This test lists the same type names and
/// asserts the JS file contains a matching schema entry, so the runtime
/// validator cannot silently drop a type when the contract grows.
#[test]
fn validators_cover_contract_types() {
    let source = std::fs::read_to_string(ui_dir().join("payloads.js"))
        .expect("desktop/ui/payloads.js must exist next to types.d.ts");

    for name in [
        "Discovery",
        "CliStatus",
        "SearchOptions",
        "ExecutionStatus",
        "InstallPlan",
        "InstallStep",
        "InstallOutcome",
        "SkillPlan",
        "SkillInstall",
        "InstallState",
        "SkillStatus",
        "UpdatePlan",
        "RemovePlan",
        "UpdateOutcome",
        "RemoveOutcome",
        "PathValue",
        "PathReceipt",
        "PathPlan",
        "CredentialStatus",
        "CredentialOverview",
        "CredentialValue",
        "TestOutcome",
        "ProviderInfo",
        "RouteConfig",
        "SettingsInput",
        "SettingsView",
    ] {
        let needle = format!("{name}:");
        assert!(
            source.contains(&needle),
            "desktop/ui/payloads.js is missing `schemas.{name}`; \
             add it next to the other command payload schemas"
        );
    }
}
