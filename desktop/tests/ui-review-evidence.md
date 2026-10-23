# UI review repair evidence

## Scope and decisions

- Frontend remains native JavaScript; no framework/store migration. `happy-dom` was already declared and locked: review's missing declaration claim was stale. `npm --prefix desktop ci` succeeds.
- App navigation uses a revision token and a distinct mount container. Each page also owns a child root; stale mounts dispose on resolution. A failed mount is caught, rendered as text and has a retry button. Page titles receive focus.
- Backend errors and provider names no longer enter HTML interpolation. Remaining template substitutions are local constants, boolean-selected static messages and numeric row indices. Provider icons/descriptions have fallback text/style.
- Provider manifest failure clears the rejected cache. Search sources start collapsed: no credential read/reveal until an explicit expansion. Reads return masked text and an opaque snapshot; reveal is explicit, copy is disabled until revealed, hide/dispose clears visible values. Backend performs masking and snapshot validation.
- Install/skill have disposed guards and registered listener cleanup. Long operations have busy semantics/spinners. Shared confirmation focus behavior supports Escape and restoring focus; existing confirmation markup is retained rather than replacing every feature's state machine.
- Errors use `.error-message` and a single app live region. Status styles use `.status-text`. Long explanatory copy uses native details. Navigation numbering and heading punctuation are consistent.
- Diagnostics providers are fetched dynamically, timeout input tracks the same default exception as validation, result entries are grouped by provider and raw JSON is collapsed.
- Follow-up t7 replaces the former fresh-read/full-settings write with `scrape_settings_save({ backends }) -> SettingsView`. Only the draft chain crosses IPC; search settings/source toggles omit `scrape_backends`. The backend owns the dedicated transaction, so the former UI read/merge/write cross-field TOCTOU is removed. No global compare-and-swap semantics are claimed for two writers changing the same chain.
- Source status redraws are microtask-coalesced to avoid one full stats/filter scan per initial row. Draft key inputs use delegated input/paste/click handlers.
- `checkJs:true` now checks every module. `strict:false` permits existing dynamic page/API shapes; this is not a claim of fully strict typing. Shared API generated payload contracts remain checked. Existing mature settings/scrape state machines remain, rather than introducing an unneeded global draft store or changing tested save behavior.
- CSS work was independently delivered by ui-styles: one semantic token set, readable fonts, muted contrast >=4.5:1, usable narrow navigation, no repeated panel entrance animation, spinner/result/key-row classes. No dark theme was added because its absence alone was not a defect.

## Checks

- `npm --prefix desktop ci`: passed, 12 packages, zero reported vulnerabilities.
- `npm --prefix desktop test`: t7 transaction-command integration rerun passed 129/129 tests (0 failed; 2346 ms). Generated `CredentialValue.snapshot` and `PathPlan.warning` are required by payload schemas; reveal command and opaque remove guard are covered by the adapter test.
- `npm --prefix desktop run typecheck`: passed with `checkJs:true`.
- `git diff --check -- desktop/ui desktop/tests`: passed.
- `node --test desktop/tests` is not supported as a directory argument by the installed Node 24; use the project's test script (`node --test tests/*.test.js`).
- Regression coverage includes stale mount vs current page, rejected stale mount, malicious error/provider labels, retry after failed manifest, masked reveal/copy/hide/dispose, initial sources collapsed/no reads, and dedicated scrape save avoiding general-setting writes or pre-save rereads. The adapter test checks invalid arguments are rejected before IPC, exact `{ backends }` payload, and malformed `SettingsView` rejection. Existing draft locking, failures, credential rechecks, refresh confirmation, and default restoration tests remain passing.
- Tests use isolated happy-dom mock APIs. No real credential store, external search, install, PATH change or browser link was invoked.
- **Not visually verified:** no real-browser screenshot/rendering evidence; happy-dom verifies interactions, not layout or screen-reader output. CSS responsive/contrast claims are static checks from ui-styles.
