# Task 4 report — Replay and repair

## Delivered

- Added `load_run_status(run_dir: Path) -> RunState` to `src/mathresearch/run_store.py`.
- Status takes the existing per-run OS lock, accepts only the canonical initialization layout, and strictly replays `events/000001.json` as the authoritative source of truth.
- Added typed storage failures with stable codes: `run_not_found`, `run_uninitialized`, and `run_corrupt`.
- The optional `request.json` copy is verified against the event when present. Its absence is accepted because the event contains the validated request.
- Only sibling temporary files made by the existing atomic writer are ignored. Unexpected artifacts, malformed event names, sequence gaps/extra events, links/hardlinks, invalid JSON, contract failures, and request mismatch are rejected as corruption.
- `state.json` is derived from the event and atomically rebuilt only when absent, malformed, or stale. A correct parsed projection is not rewritten. All validation precedes projection publication, so failures leave event/request evidence unchanged.

## Tests and TDD evidence

1. Added status tests and ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_store -v` before adding the loader/errors.
   - It failed as expected with `ImportError: cannot import name 'RunCorruptError' from 'mathresearch.errors'`.
2. Implemented the strict replay and repair path, then added focused regressions for optional request-copy absence and evidence preservation when state replacement fails.
3. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_store -v` with real temporary-directory filesystem access.
   - Result: 21 tests passed.
4. Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` with the same access.
   - Result: 49 tests passed.

## Scope

No CLI commands, scheduling, adapters, agents, or general documentation changes were added.

## Review fix round 1

### Root cause and changes

- An immutable publication uses `os.link(temp, target)` before it cleans the temporary path. If that cleanup is interrupted, the temporary name remains as a same-directory hardlink alias of the committed request or event. The original hardlink rejection classified this valid residue as corruption.
- Replay now verifies such aliases by target name, same-file identity, and exact link count. It accepts only aliases of their corresponding immutable request/event; unrelated hardlinks and state temporary hardlinks remain corrupt.
- Both replay and locking validate an existing `.run.lock` with `lstat` before opening it. The locking layer repeats validation against the opened descriptor before taking the platform lock, closing the check/open race before Windows can write its NUL lock byte.
- Symbolic links and Windows reparse points are rejected for run roots, events directories, artifacts, and lock targets.

### Regression evidence

1. Added regressions before the fix and ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_store.RunStoreStatusTests -v`.
   - The valid retained event alias failed as `run_corrupt`; a symlinked empty external lock target changed to `b"\\0"`; a directory lock target raised generic `RunStoreError`; and reparse-point coverage initially exposed missing detection.
2. Added the minimal validated-alias and pre-open/descriptor lock checks.
3. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_locking tests.unit.test_run_store.RunStoreStatusTests -v`.
   - Result: 21 tests passed.
4. Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v`.
   - Result: 55 tests passed.
