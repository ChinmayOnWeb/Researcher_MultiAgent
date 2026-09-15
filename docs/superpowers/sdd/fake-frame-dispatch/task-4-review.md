# Task 4 independent review — fake Frame dispatch orchestration

## Verdict

**Changes required before Task 5.** One Important recovery/durability finding; no
Critical findings. The normal success, failed-child, and intent-only crash paths
are implemented cleanly, but a crash after recording a successful process outcome
and before recording acceptance is incorrectly and irreversibly classified as a
rejection.

## Important findings

### 1. A committed successful outcome without acceptance is treated as a permanent rejection

**Locations:** `src/mathresearch/dispatch.py:37-43`, `src/mathresearch/dispatch.py:78-84`.

`_frame_history()` reduces every `FrameProcessOutcomeEvent` to the same
`has_outcome` boolean. On a subsequent invocation, `dispatch_fake_frame()` returns
`already_rejected` whenever that boolean is true and no acceptance event exists.
That includes this durable crash window:

1. the child has exited successfully and its valid submission has been captured;
2. `frame_process_outcome` with `exit_code == 0` has been committed; and
3. the coordinator crashes before `frame_submission_accepted` is committed.

The authoritative history then says the attempt completed successfully, while the
raw capture contains a valid result, but replay reports an active run with zero
accepted submissions. The next dispatch neither accepts that result nor reports a
blocked/pending state; it labels it `already_rejected`. No event identifies the
submission as rejected, so the same representation is also used for malformed
zero-exit output. This loses the durable result-acceptance recovery guarantee and
can strand a successful Frame forever.

**Required fix:** represent the terminal disposition durably. For example, add a
validated rejection event for malformed successful output and, for a successful
outcome lacking acceptance, recover by validating the already-captured submission
and appending acceptance without relaunching the worker. If the design instead
requires manual intervention, return and durably expose a distinct blocked-pending-
acceptance state—not `already_rejected`. Add a regression test that simulates the
post-outcome/pre-acceptance crash window and proves the worker is not relaunched
while the valid Frame becomes accepted (or is explicitly blocked by the chosen
durable policy).

## Confirmed behavior

- The run lock spans history replay, task creation, durable intent publication,
  local child execution, process-outcome publication, and acceptance.
- Intent is appended and materialized before `run_fake_frame_attempt()` is called;
  an intent-only history returns `blocked_interrupted` without a new launch.
- The normal path creates only `task-frame` revision 1 and `attempt-frame-001`;
  an accepted or completed failed attempt is not re-launched.
- Normal success remains `active` with exactly one accepted Frame submission.
- Malformed, nonzero, and negative process results append their signed process
  outcome and are not accepted. Capture-path and locked-store safeguards from
  Tasks 2 and 3 are used by the orchestration path.

## Fresh verification

Ran the focused store, contract, process, and dispatch suites with workspace-local
`TEMP`/`TMP` and `PYTHONPATH=src`:

```powershell
py -m unittest tests.unit.test_fake_frame_dispatch tests.unit.test_fake_frame_process tests.unit.test_run_store tests.unit.test_frame_records -v
```

Result: **60 tests passed**. The suite does not cover the committed-outcome /
pre-acceptance crash window described above.
