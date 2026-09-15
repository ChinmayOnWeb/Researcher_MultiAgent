# Task 3 remediation re-review — fake Frame worker and process boundary

## Verdict

**Accepted for Task 4.** No Critical or Important findings remain. One Minor test/scope wording issue is noted below.

## Prior findings

1. **Capture/store filename conflict — addressed.** `run_store.py` now owns the shared `packet.json`, `stdout.bin`, and `stderr.log` names, and both the checked materialization layout and `process_runner.py` use them. I ran the real-child path that materializes an intent, launches the worker, appends its outcome, then reopens the run; status accepted the capture artifacts and their bytes remained readable.
2. **Capture containment and collisions — addressed.** The runner canonicalizes all paths, requires fixed distinct artifact names beside `packet.json`, rejects outside/colliding destinations before `subprocess.run`, and walks all directory ancestors with `lstat` to reject links/reparse points. The focused tests cover packet/capture collision, capture/capture collision, outside paths, and a linked ancestor with no launch.
3. **Nullable goal/context — addressed.** `fake_worker.py` uses empty string arrays for absent values and records `actual_goal`/`context` in `missing_inputs`. Builder and real-child cases cover each field independently and both together.
4. **Completed malformed output — addressed.** After every launched child, captures are persisted and `ProcessResult` is returned. Invalid zero-exit output yields `submission=None` plus `submission_error`, while `process_outcome()` still produces the exact completed-process event. The malformed-output test verifies the outcome and exact capture bytes.
5. **Signed terminations — addressed.** `FrameProcessOutcomeEvent` now strictly accepts signed integers while excluding booleans. Existing contract coverage parses, serializes, and replays `-9` as a failed outcome; the runner test constructs an outcome from the same termination code.
6. **Launch error type — addressed.** `OSError` from process creation is wrapped as `ProcessRunnerError` with exception chaining, before either capture is created; the focused test verifies this behavior.

## Minor

- `test_rejects_noncanonical_attempt_directory_and_symlink_ancestor_before_launch` only proves that a directory with the wrong *basename* is rejected. The current runner accepts any safe directory named `attempt-frame-001`, including one outside a run's `tasks/task-frame/attempts` tree. This is not an integration blocker: Task 4 receives and invokes it only on the store-materialized packet under its locked run, and the runner still prevents collision, traversal, and link escape. The test name and report wording should not imply full run-tree authorization until the runner is passed an explicit run-root/locked-run boundary. No additional production change is required for the approved Task 3 scope.

## Fresh verification

Ran with workspace-local temporary storage:

```powershell
$env:TEMP=(Resolve-Path '.review-temp').Path
$env:TMP=$env:TEMP
$env:PYTHONPATH='src'
py -m unittest discover -s tests -v
```

Result: **89 tests passed**, exit code 0. A focused runner/store/contracts run also passed **60 tests**.

