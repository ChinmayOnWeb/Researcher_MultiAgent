# Task 1 report — strict Frame contracts

## Delivered

- Added `FrameTask`, `FramePacket`, and `FrameSubmission` in `src/mathresearch/contracts/frame.py`.
- Added deterministic `build_frame_task()` and `build_frame_packet()` builders.  The single initial task is `frame`, revision `1`; its packet preserves the complete validated request and fixed Frame output requirements.
- Extended `contracts/run.py` with strict version-one parsers for `run_initialized`, `frame_task_created`, `frame_attempt_intended`, `frame_process_outcome`, and `frame_submission_accepted` events.
- Added a pure `replay_run_events()` reducer.  It requires contiguous ordered events and matching run/task/revision/attempt identities.  Submission acceptance requires the same attempt's recorded `exit_code: 0`; duplicate acceptance and all unsupported ordering are rejected.
- Extended `RunState` with the active Frame projection.  A successfully accepted Frame submission produces `status: "active"`, `accepted_submission_count: 1`, and never produces `complete`.
- Added complete hand-authored Frame fixtures and focused coverage in `tests/unit/test_frame_records.py`.

Every authoritative record requires its exact fields, schema version `1`, real (non-boolean) integer values, valid opaque IDs, and an ASCII UTC microsecond timestamp.  Constructed dataclasses are revalidated before serialization.

## TDD evidence

1. Added `tests/unit/test_frame_records.py` before `frame.py` existed.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_frame_records -v`.
   - Expected RED result: `ModuleNotFoundError: No module named 'mathresearch.contracts.frame'`.
3. Implemented the minimum Frame contracts and replay parser/reducer, then ran the focused suite.
4. Final focused verification:

   ```powershell
   $env:PYTHONPATH='src'
   python -m unittest tests.unit.test_contracts tests.unit.test_run_records tests.unit.test_frame_records -v
   ```

   Result: 26 tests passed.

## Full-suite note

`python -m unittest discover -s tests -v` reaches the Frame tests successfully, but the pre-existing filesystem/locking suites fail under the managed sandbox before their assertions: `tempfile.TemporaryDirectory()` cannot write or clean temporary paths (`PermissionError: [WinError 5] Access is denied`).  Redirecting `TEMP`/`TMP` to the workspace has the same restricted-write failure.  No task code touches the store, locking, CLI, subprocess, or adapter boundaries.

## Review fix round 1

### Changes

- `FrameSubmission.to_json()` now validates the exact original `frame` mapping before serialization.  It preserves unknown/missing/type failures rather than dropping fields, supplying defaults, or coercing strings into lists.  Canonical tuple-to-list conversion remains only for already validated in-memory list fields.
- The reducer now accepts a submission only for the current completed attempt.  A pending newer attempt, or a completed newer attempt, prevents acceptance of an earlier result.
- `replay_run_events()` round-trips each public event through its strict serializer/parser before state reduction.  Constructed dataclasses therefore cannot bypass boolean-integer, timestamp, nested submission identity, or other wire-contract checks.
- `parse_run_event()` validates `event_type` as a string before dispatch, so an unhashable/non-string value produces `ValidationError("event_type", ...)` rather than `TypeError`.

### Regression evidence

1. Added tests first for constructed malformed submission frames, stale acceptance with a pending newer attempt, constructed event revalidation (boolean attempt/exit code, naive timestamp, mismatched nested submission identity), and non-string event type.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_frame_records -v`.
   - Expected RED result: seven assertion failures plus two errors, demonstrating the original sanitization, stale acceptance, constructed-dataclass bypass, and unhashable event-type defects.
3. Applied the scoped contract/reducer fixes.
4. Final verification:

   ```powershell
   $env:PYTHONPATH='src'
   python -m unittest tests.unit.test_contracts tests.unit.test_run_records tests.unit.test_frame_records -v
   ```

   Result: 29 tests passed.
