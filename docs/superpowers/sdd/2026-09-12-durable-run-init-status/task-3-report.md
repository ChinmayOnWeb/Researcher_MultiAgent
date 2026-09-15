# Task 3 report — Atomic run initialization

## Delivered

- Added `src/mathresearch/run_store.py` with `initialize_run(request_path, run_dir) -> RunState`.
- Request JSON is parsed strictly: duplicate object keys and `NaN`/`Infinity` values are rejected before a run directory is created.
- Initialization validates the request, creates and locks the destination, accepts only an absent/empty directory (apart from the persistent `.run.lock`), then writes `request.json`, `events/000001.json`, and `state.json` in that order.
- Immutable request and event records are published without replacement; the initialization event is the commit point. State uses atomic replacement because it is rebuildable.
- Temporary files are placed beside their destination, flushed and file-synchronized before publication. POSIX directory metadata is synchronized after publication.
- Existing committed and precommit directories are refused without overwriting artifacts. A state-projection write failure leaves the committed initialization event in place for later repair work.

## Tests

- Added `tests/unit/test_run_store.py` with real `TemporaryDirectory` cases for the happy path, invalid inputs, strict duplicate/non-finite parsing, repeated initialization preservation, prepopulated-directory refusal, precommit fault refusal, and state-write failure after event commitment.
- The two fault cases patch only the atomic publication boundary to inject an otherwise impractical filesystem write failure; all record and directory assertions use real filesystem effects.

## TDD and verification evidence

1. Added the run-store behavior tests before `mathresearch.run_store` existed.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_store -v`.
   - Failed as expected with `ModuleNotFoundError: No module named 'mathresearch.run_store'`.
3. Implemented the minimal strict loader and atomic run initializer.
4. Ran the focused run-store suite again; 7 tests passed.
5. Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` with real temporary-directory filesystem access; 35 tests passed.

## Scope

No status replay, CLI commands, scheduler/adapters, documentation updates outside this required task report, or agent execution were added.

## Review fix round 1

### Changes

- A newly created run directory now synchronizes its parent directory before locking or publishing any artifact. Existing lock-only directories remain valid and are not treated as newly created directory entries.
- `request.json`, `events/000001.json`, and `state.json` are serialized and UTF-8 encoded before the run directory, lock, or events directory is created. A lone surrogate therefore fails without a precommit directory.
- Temporary-file cleanup now ignores cleanup errors so they cannot hide a primary publication failure.
- Event and state interruption tests now inject failures at `os.link` and `os.replace`, respectively, instead of replacing the whole atomic writer helper.

### Regression test evidence

1. Added regressions for parent-directory synchronization, lone-surrogate serialization, existing lock-only acceptance, cleanup error preservation, and primitive publication failures.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_store -v` before the fixes.
   - 3 failures reproduced the review findings: missing new-directory parent synchronization, a lone surrogate leaving the run directory behind, and cleanup masking the primary publication error.
3. Applied the durability and preflight-serialization fixes.
4. Re-ran the focused suite; 11 tests passed.
