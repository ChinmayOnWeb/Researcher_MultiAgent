# Task 4 report — fake Frame dispatch orchestration

## Delivered

- Added `mathresearch.dispatch.dispatch_fake_frame(run_dir: Path) -> DispatchResult` as the service-only coordinator boundary; no public CLI command was added.
- `DispatchResult` reports one of `accepted`, `rejected`, `blocked_interrupted`, `already_accepted`, or `already_rejected`, together with the replayed `RunState`.
- Extended `LockedRun` with a read-only `events` property so orchestration consumes the lock-held, replay-validated history rather than reopening event files.

## Durable lifecycle

1. Under one `open_locked_run()` scope, dispatch creates exactly `task-frame` revision 1 if absent.
2. It commits `frame_attempt_intended` for `attempt-frame-001` before starting a child. `LockedRun.append()` materializes the task packet before `run_fake_frame_attempt()` receives its canonical path and exact `run_dir`.
3. A completed child always contributes its signed `frame_process_outcome`, including malformed zero-exit output and nonzero/negative termination.
4. Only a zero-exit validated submission gets `frame_submission_accepted`; the active state then has one accepted Frame submission and is not marked complete.
5. A prior intent without an outcome returns `blocked_interrupted` and does not relaunch. A finished rejected attempt and an accepted attempt are also idempotent and do not create another task or attempt.

Launch failure is intentionally not fabricated as a process outcome: the already-durable intent remains the inspectable interrupted boundary.

## TDD and verification

- Added `tests/unit/test_fake_frame_dispatch.py` before `mathresearch.dispatch` existed. Its focused RED run failed with `ModuleNotFoundError: No module named 'mathresearch.dispatch'`.
- The integration tests cover success and duplicate idempotence, intent-only crash-window recovery without relaunch, malformed zero-exit output, ordinary nonzero failure, and negative termination.
- Fresh full-suite verification used workspace-local `TEMP`/`TMP` and `PYTHONPATH=src`:

```powershell
py -m unittest discover -s tests -v
```

Result: **94 tests passed**.

## Recovery remediation

- Added a RED integration regression for the crash boundary after
  `frame_process_outcome` is committed but before
  `frame_submission_accepted` is committed. It initially failed because a
  retry returned `already_rejected`.
- A retry now recognizes a successful completed outcome, safely revalidates the
  existing canonical `stdout.bin` against its materialized packet, and appends
  the acceptance event without starting a child or creating another task or
  attempt.
- The regression also confirms the recovered run is idempotent: a subsequent
  dispatch launches nothing and does not append a second acceptance.
- Malformed, nonzero, and signed-negative completed outcomes retain their
  existing non-acceptance behavior.

Fresh focused verification: **61 tests passed**.

Fresh full-suite verification with workspace-local `TEMP`/`TMP` and
`PYTHONPATH=src`: **95 tests passed**.

## Scope retained

No `dispatch` CLI command, documentation outside this implementation report, real provider adapter, retry policy, or human-gate workflow was added.
