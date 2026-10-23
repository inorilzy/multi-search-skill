# Scrape-chain integration and acceptance tickets

Date: 2026-10-22. Coordinator: main agent. Delivery: local main only.

## Scope and baseline

- Repository: `C:\Users\zhiyu_liu\multi-search-skill`.
- Working integration checkout: `C:\Users\zhiyu_liu\multi-search-scrape-integration`.
- Accepted feature commit: `2b4927d06be33deaf6b0267754782c46f417ab24`.
- C-drive main fast-forwarded from `3fd1aa1` to the feature commit. Existing untracked logs were hash-checked and preserved.
- C-drive main, D-drive main and integration code commit are `d058f7d` (runner correction after `39dcba0`). D untracked documents and `.zvec-grep/`, and C untracked desktop logs are preserved.
- Existing dirty ticket worktrees and deployed skills are out of scope. No push, installation into the real profile, paid provider calls, or real credential changes.

## DAG

```text
T0 land accepted feature
 |-- T1 independent review --------------------------|
 |-- T2 installed CLI acceptance --|                 |
 |-- T3 real bundle acceptance ----|-- T4 desktop UI -|-- T5 integrate and regress
```

## Tickets

| ID | Dependency | Owner / write scope | Acceptance | State |
| --- | --- | --- | --- | --- |
| T0 | None | Coordinator; C-drive main only | Fast-forward exact accepted commit; preserve user logs | PASS: main at 2b4927d |
| T1 | T0 | Read-only reviewer; report only | Adversarial review of 3fd1aa1..2b4927d, concrete findings and tests | PASS: reviewed; reset boundary fixed, settings regression added |
| T2 | T0 | CLI acceptance worker; scripts/desktop_native_acceptance.py, desktop/src-tauri/tests/installed_cli.rs, ticket-specific tests/evidence | Build/install current wheel in disposable environment; execute previously ignored installed CLI test; verify import provenance and isolation | PASS: d058f7d correction reviewed; default 3.12 real runner twice, 69 matching files and zero guard violations |
| T3 | T0 | Bundle worker; scripts/build_cli_release.py, scripts/test_build_cli_bundle.py, desktop/src-tauri/tests/install.rs, generated resources/cli-bundle.anchor, ticket-specific tests/evidence | Build current-source bundle; execute real_bundle_installs_against_the_compiled_anchor with actual pinned inputs | PASS: manifest 355e7199; real ignored test executed |
| T4 | T0 for local settings; T2,T3 for CLI integration | Coordinator; isolated desktop validation artifacts only | Actual desktop UI with temporary profile: chain edit/save/reload, key restrictions, Jina editor, pin/reset; no mock-DOM substitution | PARTIAL: native UI config/pin/Jina PASS; reset final click awaits user confirmation; CLI integration waits T2 |
| T5 | T1,T4 | Coordinator; final corrections, ledger, main integration | Review candidate diff, run required integrated tests, advance C/D local main, preserve dirty worktrees | PARTIAL: main at d058f7d; review and code regression complete, T4 gate outstanding |

## Directory inventory

| Directory | Role and treatment |
| --- | --- |
| `C:\Users\zhiyu_liu\multi-search-skill` | Main checkout; authoritative local main |
| `D:\0-code-project\multi-search-skill` | Separate clone; synchronized with a local bundle, not a push |
| `C:\Users\zhiyu_liu\multi-search-scrape-integration` | Final feature and correction source; integration/scrape-chain |
| `C:\Users\zhiyu_liu\multi-search-scrape-cli` | Initial CLI slice at 3fd1aa1 with dirty edits; preserved, not copied over final integration |
| `C:\Users\zhiyu_liu\multi-search-scrape-desktop` | Initial desktop slice at 3fd1aa1 with dirty edits; preserved, not copied over final integration |
| `C:\Users\zhiyu_liu\multi-search-t2-isolated` | T2 worker at 2b4927d with five owned file edits integrated in 39dcba0; original retained |
| `C:\Users\zhiyu_liu\.agents\skills\multi-search` | Deployed copy; not modified or synchronized |

Unrelated cleanup/ticket worktrees also exist; they are not additional scrape-chain delivery targets and were left untouched.

## Execution rules

- Writer T2 resumes in isolated worktree `C:\Users\zhiyu_liu\multi-search-t2-isolated`, branch `codex/scrape-t2-isolated`; it must not write the integration checkout. Reviewer is read-only. Only the coordinator stages, commits, or advances main. No further delegation.
- Each worker uses a separate temporary Cargo target and output directory; do not share generated wheels, scratch profiles, or test executables.
- Model and effort must be checked against the actual spawn interface; no silent model substitutions. Record runtime metadata when available, not agent self-identification.
- Preserve complete logs outside Git. Reports contain exact commands, exit codes, source SHA, input hashes, PASS/FAIL/NOT RUN and remaining gates.
- UI automation feasibility is a gate: if no supported native UI control is available, report NOT RUN and prepare a reproducible manual checklist rather than claim completion.
- Independent review findings create bounded follow-up fixes before final integration. Previously passing tests are not proof of new edits.

## Execution evidence

- Role binding check failed: the fixed reviewer attempted DeepSeek, so no worker started from that request. Switched explicitly to override-capable `default`, `auto/gpt-6-astra`, `high` for this batch; no persistent model configuration was changed.
- Child session turn_context metadata verified `model=auto/gpt-6-astra`, `effort=high` for all three agents (not self-identification).
- T1 agent: `01a1645b-de26-77f1-81a6-a8ea865bf35e`.
- T2 agent: `01a1645c-2a4e-7200-bec2-d70e75f2f65b`.
- T3 agent: `01a1645c-7690-7c90-8413-ebb4e65c0903`.
- Native Windows Computer Use is available. An existing user desktop window was discovered and left untouched; T4 must launch a separate temporary-profile instance.
- Earlier integration: C and D local main both reached `2b4927d`; D untracked files were preserved. Current HEAD is listed above. No remote push.
- Previous cleanup incorrectly reported 10 residual Rust files as semantic edits. Reviewer compared `rustfmt(HEAD, skip_children=true)` against work bytes: 8 more were pure formatting; only installed_cli payload diagnostics and scrape_memory scoped-reset tests were semantic. Parent removed the residual formatting with backup at `%TEMP%\multi-search-residue-recovery-sl_xt7mo`; original whole diff backup remains `%TEMP%\multi-search-fmt-repair-20261022`.
- T1 state-path finding was not accepted as a real-profile leak: standard acceptance redirects HOME/USERPROFILE. Native T4 pin was independently read by Python StateStore() in that same temporary HOME and reordered Firecrawl first, with no MULTI_SEARCH_STATE_DB override.
- T4 native executable SHA256 `d2e167980511a7d32513a9a82b364954ecda4c0d596999d5e7082995693fae4d`, isolated config/state paths in `%TEMP%\multi-search-T4-evidence-20261022\session.json`. UI save persisted `[exa,tavily,jina,firecrawl]`; refresh/navigation preserved it. Exa+Tavily-only chain disabled Save; adding anonymous Firecrawl reenabled Save. Jina editor saved synthetic exhausted metadata without putting it into Python rotation.
- T4 reset confirmation panel observed; final deletion click NOT RUN pending explicit action-time confirmation. Evidence `reset-confirmation-uia.txt`. No deletion performed.
- T3 refresh: all 69 current package Python files equal bundle-installed files; manifest hash equals compiled anchor `355e7199b63be135920a4b211bbd0661215bf384f0cb0e63910df44d5124fa64`. Real bundle ignored acceptance rerun exit 0, 1 passed; log `%TEMP%\multi-search-T5-main-evidence-20261022\real-bundle-refresh.log`.
- Current frontend tests: 113 passed, typecheck exit 0. These do not substitute for final post-integration tests.

## Final audit in progress (39dcba0)

- Reviewer `01a16614-d0f0-7d52-849c-fa2cea9572f6`: loaded/runtime `gpt-6.1-sol`, `xhigh`, verified in session turn_context. Found stale-venv false PASS and error-manifest writing into rejected directories. Neither earlier test success nor an expired reviewer was accepted as approval.
- Executor `01a16616-d4aa-7491-9bc2-8f83c560958a`: loaded/runtime `gpt-6.1-sol`, `high`, verified in session turn_context. Owns only runner plus focused Python tests; parent owns documentation and regression evidence.
- Full default Rust: 146 passed, 2 ignored, exit 0. Both ignored tests are installed-CLI tests that need the separate controlled runner.
- Python with fresh Rust settings handoff: 804 tests, 0 skipped, exit 0. Frontend: 113 passed; typecheck exit 0.
- Feature suites (`process_env`, `install`, `install_lifecycle`): 49 passed, 1 ignored, exit 0. Real bundle exact ignored test subsequently executed: 1 passed, exit 0.
- Real-bundle first attempt failed `prerequisite_missing` using the reused T2 target. After explicitly supplying the existing raw-manifest-verified anchor via the supported build environment variable, it passed. This binds the authentic bundle; no integrity check was weakened. Both logs retained.
- Bundle source check: 69 Python source files byte-identical; manifest SHA-256 `355e7199b63be135920a4b211bbd0661215bf384f0cb0e63910df44d5124fa64`.
- Formal `emit_types_d_ts` exact test exit 0; before/after SHA-256 `BB0374778105B288C09ED7D80B6B388CF39FBA12498844E792118444366C925F`, no diff.
- Evidence root: `D:\scrape-final-39dcba0`. This regression predates the pending runner-only correction and is not proof of its acceptance.
- Temporary native UI launcher session was polled live; PID 61352 still runs from the owned temporary executable. Final reset click remains NOT RUN, pending user action-time confirmation. Do not repeat the request or bypass it through IPC/SQLite.

## Review closure (d058f7d)

- Both reviewer blockers corrected and independently accepted: pip force-reinstalls the same-version wheel; failure handlers write only after acquiring evidence ownership. Installed .py bytes are compared with the wheel (69 files).
- The default 3.12 runtime exposed inherited 3.13 PYTHONHOME in the import proof and standalone CLI check. Removed PYTHONHOME from both test-process environments, retaining PYTHONPATH and all isolation variables. Earlier failures preserved as `import-pyhome-mismatch*` and `standalone-pyhome-mismatch*` logs/manifests; no switch to 3.13 used to claim final success.
- Corrected exact runner ran twice against the same `D:\scrape-final-39dcba0\t2-corrected` directory. Both PASS, each executes both ignored tests, both have guard violation_lines=0. `t2-first-manifest.json` and `t2-reuse-manifest.json` retain results. Pip reuse log confirms uninstall/reinstall rather than a same-version skip.
- Focused runner tests: 17 passed. Final full Python suite: 810 tests, 0 skipped, exit 0 (`python-final-frozen.log`). Rust/JS product bytes are unchanged from the full regression above.
- Main integration used `git merge --ff-only integration/scrape-chain` for the shared C repository and a local Git bundle for the separate D clone. No local-path fetch shell retry, remote push, deployment sync or user configuration changes.
- Post-integration runner executed from C main at d058f7d, fresh evidence directory `D:\scrape-final-39dcba0\t2-main-d058f7d`: PASS, exit 0. The real installed CLI proof is therefore not limited to a worker checkout.
