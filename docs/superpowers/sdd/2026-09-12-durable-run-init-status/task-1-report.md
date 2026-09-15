# Task 1 report — Run contracts

## Delivered

- Added `src/mathresearch/contracts/run.py` with version-one `RunInitializedEvent` and `RunState` contracts.
- Both readers require their exact JSON fields and reject unknown or missing fields.
- Event records require `schema_version: 1`, `record_type: "run_event"`, `sequence: 1`, `event_type: "run_initialized"`, a valid `run_id`, a matching nested `RunRequest`, and a strict UTC microsecond timestamp.
- State records require `schema_version: 1`, `record_type: "run_state"`, `status: "initialized"`, `last_event_sequence: 1`, a valid `run_id`, and the same strict timestamp format.
- Numeric validation uses the existing integer validators, which reject booleans and floats.
- Added `project_initialization(request, initialized_at)`, which creates the first event and its matching initialized-state projection from a validated request and aware UTC `datetime`.
- Added the shared request fixture at `tests/helpers.py` and moved the existing contract tests to use it.

## TDD evidence

1. Added `tests/unit/test_run_records.py` before `run.py` existed.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_records -v`.
   - Outcome: failed as expected with `ModuleNotFoundError: No module named 'mathresearch.contracts.run'`.
3. Implemented the minimal contract module.
4. Re-ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_contracts tests.unit.test_run_records -v`.
   - Outcome: 14 tests passed, including constructed-record checks that prevent boolean serialization for numeric fields.

During final contract review, the two constructed-record checks were added before their serialization guards. Their focused test run failed as expected because `True == 1` in Python; after applying the integer validators at serialization, the focused suite passed.

## Final verification

Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v`.

- Outcome: 18 tests run, all passed.
- Scope check: no CLI, storage, locking, or plan/documentation files were changed other than this required implementation report.

## Review fix round 1

### Changes

- Replaced the timestamp regex's Unicode-aware `\d` tokens with ASCII `[0-9]` tokens. Event and state readers now reject full-width digit timestamps.
- Added writer-boundary validation for `RunInitializedEvent` and `RunState`: serialization validates numeric fields, top-level run identifiers, UTC timestamps, initialized status, and event/request ID agreement.
- Revalidates a `RunRequest` by its JSON contract before an event serializes it or `project_initialization` uses it. This prevents frozen but manually constructed invalid request instances from entering durable records.
- Added reader tests for invalid `record_type`, `event_type`, `status`, and top-level `run_id`, plus writer tests for constructed event/state/request invariants.

### Regression test evidence

1. Added the regression tests before changing `run.py`.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_run_records -v`.
   - Outcome: 16 tests run; 2 failed as expected because constructed invalid state IDs and manually constructed invalid requests were serialized/projected without validation.
3. Implemented the minimal boundary validation and ASCII timestamp pattern.
4. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_contracts tests.unit.test_run_records -v`.
   - Outcome: 19 tests passed.
5. Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v`.
   - Outcome: 23 tests passed.
