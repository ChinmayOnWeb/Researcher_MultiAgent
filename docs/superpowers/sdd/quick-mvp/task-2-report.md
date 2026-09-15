# Task 2 — Quick workflow contracts and durable store

Implemented the version-two quick-workflow persistence boundary while preserving version-one initialization and fake Frame replay.

## Public additions

- `contracts.quick.WorkflowEvent`: exact-key schema-v2 workflow events with strict bodies for configuration, intent, finished outcome, acceptance, stop, and completion.
- `contracts.quick.QuickState`: explicit nullable state projection fields and a pure `replay_quick_events` reducer for the fixed `frame -> investigate -> verify -> explain` graph.
- `run_store.load_run_status`: returns `RunState | QuickState`; legacy histories retain their version-one projection.
- `LockedRun.append`: accepts validated version-one or version-two records and rejects legacy Frame/quick mixing.
- `LockedRun.write_capture(stage, attempt, name, data)`: accepts only canonical diagnostic filenames for a committed quick intent, checks the complete run-tree ancestry, writes atomically, and returns SHA-256.

## Durable layout

Quick packets, accepted payloads, captures, and completed reports are all derived/checked beneath the documented fixed task paths. The store validates every present task/attempt directory even if other expected projections are absent; linked, nonregular, unknown, and stale-before-evidence artifacts are rejected. Missing derived projections are repaired only after complete immutable history replay succeeds.

## Verification

- Focused: `py -m unittest tests.unit.test_quick_records tests.unit.test_quick_store tests.unit.test_run_store -v` — 37 passed.
- Full suite using workspace-local `TEMP`/`TMP`: `py -m unittest discover -s tests -v` — 113 passed.

## Review remediation (2026-09-14)

- Replay now treats a finished quick event's `stdout_sha256` and `stderr_sha256`
  as commitments: both canonical captures must exist as safe regular files and
  their SHA-256 values must match before status can repair a projection.
- Root `report.md` remains a quick-completion projection only. Legacy
  version-one/fake histories containing it now fail layout validation.
- The reducer binds every quick intent packet to the exact initialized request
  and the exact accepted predecessor-result map for its fixed stage.
- Added real store/reducer regressions for tampered and missing captures,
  legacy reports, altered initialized requests, and missing prerequisite input.

### Fresh verification

- Focused remediation suite: **42 passed** (`test_quick_records`,
  `test_quick_store`, and `test_run_store`) using workspace-local `TEMP`/`TMP`.
- Complete suite: 121 passed, 1 failed. The failure is in the concurrently
  changed Task 1 CLI discovery expectation: `test_doctor_json_reports_missing_built_in_adapters`
  expects a bare unavailable Codex record, while the new provider preflight
  intentionally adds its reason. It is outside Task 2 files/behavior and was
  reported for integration resolution rather than changed here.
