# Task 5 report — CLI and integration tests

## Delivered

- Added `mathresearch init --request PATH --run-dir PATH [--json]` and `mathresearch status --run-dir PATH [--json]`.
- Both commands dispatch directly to the accepted `initialize_run` and `load_run_status` storage APIs; no adapters, agents, scheduler, or task dispatch are invoked.
- JSON success output is the stable `RunState.to_json()` contract. Readable output reports `run_id`, `status`, `initialized_at`, and `last_event_sequence`.
- Typed `RunStoreError` failures preserve each error's stable code and declared exit code. JSON errors are emitted to stderr as `{code, message}`; readable errors include the code and message without a traceback.
- `KeyboardInterrupt` is reported as `cancelled` with `ExitCode.CANCELLED` (21).
- Existing invalid-invocation and doctor behavior remains covered by the CLI suite.

## Tests and TDD evidence

1. Added fresh-process and direct cancellation/error tests to `tests/unit/test_cli.py` before implementing the new CLI dispatch.
2. Ran the focused suite before implementation; it failed because `init`/`status` were rejected as invalid commands and the dispatch functions were absent.
3. Implemented parser commands, state/error renderers, and controlled exception handling.
4. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_cli -v` — 9 tests passed.
5. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_cli tests.unit.test_contracts tests.unit.test_run_records -v` — 28 tests passed.
6. Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` — CLI and contract tests passed, but existing locking/run-store tests were blocked by the environment's Windows permission errors when `tempfile.TemporaryDirectory()` creates mode-0700 directories. No CLI failure was reported.

## Scope

Only `src/mathresearch/cli.py`, `tests/unit/test_cli.py`, and this required report were changed. No durability storage internals, scheduling, adapters, agents, or general documentation were modified.
