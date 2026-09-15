# Task 3 report — deterministic fake Frame worker

## Delivered

- Added `mathresearch.fake_worker`, a narrow child-worker protocol that reads a Frame packet and emits one deterministic, compact JSON `FrameSubmission` on stdout.
- Added `mathresearch.process_runner.run_fake_frame_attempt()`, which validates the packet, invokes the worker as a child process, writes exact raw child bytes to caller-supplied `stdout.bin` and `stderr.log` paths, and parses one successful submission through the strict Frame contract.
- Added `ProcessResult`, carrying captured bytes, child exit code, and the validated submission. Its `process_outcome(sequence, occurred_at)` creates the exact `FrameProcessOutcomeEvent` Task 4 can append without reconstructing process identity.
- Capture paths are checked for regular-file safety before atomic replacement; linked, reparse-point, directory, and hardlinked targets are refused.

## Review remediation (2026-09-14)

- Reconciled the checked store layout and runner through shared canonical names: `packet.json`, `stdout.bin`, and `stderr.log`. A real worker/store integration now verifies that captures remain readable after a replayed status operation.
- The runner now requires those three distinct, fixed names in one non-linked attempt directory, checks every ancestor for links/reparse points, and rejects collisions and outside destinations before process creation.
- Fake Frame output now accepts nullable `actual_goal` and `context`: it emits empty relevant arrays and identifies each unknown input in `missing_inputs`. Builder and real-child tests cover each nullable combination.
- `ProcessResult` preserves completed process facts even when a zero-exit worker output is malformed or mismatched; `submission` is `None` and `submission_error` identifies the validation failure, so Task 4 can persist the outcome before rejecting output.
- Process outcome records now preserve signed child return codes (including POSIX signal termination). Process creation `OSError`s are consistently wrapped as `ProcessRunnerError` and do not fabricate captures or outcomes.

## TDD evidence

1. Added `tests/unit/test_fake_frame_process.py` before the production modules existed.
2. Focused RED run failed with `ModuleNotFoundError: No module named 'mathresearch.fake_worker'`.
3. Implemented the worker and runner boundary.
4. Focused GREEN run passed all four tests, covering deterministic valid output, exact child-byte persistence, outcome creation, and linked-capture refusal.

## Verification

Executed with workspace-local temporary storage:

```powershell
$env:TEMP='D:\UCB\MathResearcher\test-temp-store'
$env:TMP=$env:TEMP
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

Result after remediation: **89 tests passed**.

## Scope retained

No dispatch orchestration, public CLI command, real adapter, or unrelated documentation was added. The child module's `main()` is only the internal subprocess protocol, not a coordinator CLI surface.

## Review fixes

- Aligned the checked attempt layout and process runner on canonical `stdout.bin` and `stderr.log`; real child captures now survive a later status replay.
- Nullable `actual_goal` and `context` now produce empty validated output lists and explicit `missing_inputs`, including through the real subprocess protocol.
- The runner requires fixed, distinct capture names beside `packet.json` in the canonical `attempt-frame-<n>` directory. It rejects collisions, outside paths, unsafe hardlinks, and symlink/reparse traversal before launch.
- Completed malformed output returns `ProcessResult(submission=None, submission_error=...)` after preserving exact captures, so Task 4 can append the known outcome without accepting the submission.
- Signed child return codes remain strict integer process outcomes (booleans excluded); a negative signal code serializes and replays as a failed outcome. Launch failure remains a typed runner error with no invented process result.

Focused Task 2/3 verification with workspace-local `TEMP`/`TMP` passed **55 tests**.

Final full-suite verification with the same workspace-local temporary storage passed **89 tests**:

```powershell
python -m unittest discover -s tests -v
```

## Post-review ancestry hardening (2026-09-14)

- `run_fake_frame_attempt()` now requires an explicit `run_dir` and only accepts the exact materialized attempt directory at `run_dir/tasks/task-frame/attempts/attempt-frame-<n>`.
- The runner continues to inspect every ancestor with `lstat`, so an alias, symlink, or reparse point cannot turn a lexically matching path into trusted run storage.
- Added a regression test proving that a complete lookalike `tasks/task-frame/attempts/attempt-frame-001` tree outside the supplied run directory is rejected before child-process launch. Existing real locked-store materialization coverage remains green.

The new regression test was written first; the focused run failed because the runner did not yet accept or enforce `run_dir`. After implementation, the focused process suite passed **11 tests** and the full suite passed **90 tests** with workspace-local `TEMP`/`TMP`.
