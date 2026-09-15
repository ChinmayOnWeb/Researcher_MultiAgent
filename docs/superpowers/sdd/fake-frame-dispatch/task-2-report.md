# Task 2 report — multi-event durable run store

## Delivered

- Extended `run_store` from initialization-only status replay to strict sequential replay of canonical `events/000001.json` onward.  Every event filename, embedded sequence, parser result, and reducer transition is validated before any state or cache repair.
- Added `open_locked_run(run_dir)`, yielding `LockedRun` with the validated `request` and `state`, `append(event) -> RunState`, and `materialize() -> RunState`.  An append atomically publishes only the next immutable event and then repairs projections from the accepted history.
- Preserved `load_run_status(run_dir)` as the compatibility API; it now runs through the same locked full-history validation/materialization path.
- Materializes only values derived from events in the Astra layout:
  - `tasks/task-frame/task.json`
  - `tasks/task-frame/attempts/attempt-frame-001/packet.json` (and later sequential attempts)
  - `tasks/task-frame/accepted.json`
- Enforces the checked task layout, including safe regular files/directories, rejection of links/reparse points and unknown artifacts, recoverable writer-shaped temporary files, and hardlink-alias checks.  Fixed optional attempt `stdout.txt`/`stderr.txt` names are reserved for the later dispatcher.
- Retained initialization/status semantics, optional request-copy behavior, and immutable event hardlink safety.

## Tests added first

`tests/unit/test_run_store.py` now covers:

- canonical five-event Frame histories and all derived projections;
- interrupted task, intent/packet, and acceptance projection recovery;
- event gaps, filename/internal-sequence mismatch, and unknown event rejection before any valid-prefix repair;
- unsafe task materialization directories;
- locked-run request/state access and sequential append;
- refusal to append over a corrupt immutable event copy.

The first focused run was RED because `open_locked_run` did not exist.  The filesystem test initially could not create sandboxed temporary directories; the unrestricted verification below exercised the real test fixtures.

## Verification

```powershell
$env:PYTHONPATH='src'
python -m unittest tests.unit.test_contracts tests.unit.test_run_records tests.unit.test_frame_records tests.unit.test_run_store -v
```

Result: **61 tests passed**.

## Review fix — multi-attempt cache validation

- Removed the early return in `_checked_materialization_layout` that occurred when one expected attempt directory was absent.  Missing directories remain recoverable, while every existing attempt directory is now checked for links, hardlinks, and unknown artifacts.
- Added a regression with a valid two-attempt history, a missing `attempt-frame-002` cache, and an unexpected file in surviving `attempt-frame-001`.  Status now rejects the run instead of repairing the missing sibling and accepting the unsafe one.

Verification used workspace-local `TEMP`/`TMP` and the same focused command. Result: **62 tests passed**.

## Scope retained

No worker process, dispatch orchestration, CLI, real adapters, or user documentation was added.
