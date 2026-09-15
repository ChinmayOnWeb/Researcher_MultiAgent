# Task 4 recovery remediation re-review

## Verdict

**Accepted for Task 5.** No Critical, Important, or Minor findings in the
recovery remediation.

## Recovery boundary checked

- A retry sees the replay-validated completed `frame_process_outcome` rather
  than treating every completed attempt as rejected. For a zero exit code,
  `dispatch_fake_frame()` calls `recover_fake_frame_submission()` against the
  locked run's canonical packet and `stdout.bin`; that helper starts no child
  and rewrites no capture.
- The recovered submission is parsed with the same strict packet identity and
  attempt checks as the initial worker path. When valid, the coordinator
  appends exactly one `frame_submission_accepted` event. The replay reducer
  then reports one accepted submission and the run remains `active`.
- The regression simulates the exact crash after the successful process
  outcome is durable and before acceptance publication. The next dispatch
  accepts the existing capture with `run_fake_frame_attempt` patched and
  asserted not called. A further dispatch is `already_accepted`, launches
  nothing, and leaves event sequence 5 unchanged.
- Intent-only histories remain `blocked_interrupted`; malformed zero-exit
  captures, nonzero exits, and signed-negative exits remain non-accepted. No
  recovery path can accept them.

## Fresh verification

Ran the focused dispatch, runner, store, and frame-contract suites using
workspace-local temporary storage and `PYTHONPATH=src`:

```powershell
py -m unittest tests.unit.test_fake_frame_dispatch tests.unit.test_fake_frame_process tests.unit.test_run_store tests.unit.test_frame_records -v
```

Result: **61 tests passed**.
