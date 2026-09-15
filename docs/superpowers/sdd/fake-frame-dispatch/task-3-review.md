# Task 3 review — fake Frame worker and process boundary

## Verdict

Changes required before Task 4. Five Important findings and one Minor finding. No Critical findings.

Reviewed `fake_worker.py`, `process_runner.py`, their four tests, the Task 3 report, and their interfaces with the accepted Frame contracts and Task 2 store. No implementation or test source files were changed.

## Critical

None.

## Important

### 1. Plan-required capture names make a successfully executed run fail store validation

**Locations:** `src/mathresearch/run_store.py:45`, `src/mathresearch/run_store.py:46`, `src/mathresearch/run_store.py:330`; `tests/unit/test_fake_frame_process.py:52`.

Task 2 reserves only `stdout.txt` and `stderr.txt`. Task 3 uses the required `stdout.bin` and `stderr.log`. Running the real child against a store-materialized `attempt-frame-001/packet.json` succeeds with exit code 0, but the next `load_run_status()` raises `RunCorruptError: unexpected materialization artifact: stderr.log`. Explicit materialization uses the same rejecting layout check. Task 4 cannot compose these accepted interfaces into a resumable run.

**Fix:** Make `stdout.bin` and `stderr.log` the canonical names in the store and runner, preferably through shared layout constants. Update recognition of their writer temporary files through the same constants. Do not work around the conflict by putting capture files outside the checked attempt tree or weakening unknown-file validation. Add a real-child integration test that materializes an intent, executes it, appends its process outcome, and successfully reopens/statuses the run while preserving capture bytes. No compatibility requirement for the unused `.txt` reservations has been established.

### 2. Capture checks permit path collisions and do not establish attempt containment

**Locations:** `src/mathresearch/process_runner.py:61`, `src/mathresearch/process_runner.py:71`, `src/mathresearch/process_runner.py:123`, `src/mathresearch/process_runner.py:132`.

The runner checks each target independently for filesystem type, but never checks its relationship to the packet, the other capture, or an authorized attempt directory. Reproduced with real child calls:

- Setting both capture paths to the same file returns success, but the stderr write replaces stdout; the stored bytes no longer equal `result.stdout`.
- Setting `stdout_path=packet_path` returns success and replaces the input packet with the submission.
- A capture in a sibling directory is accepted.
- A path with a symlink ancestor and a regular immediate parent is accepted and writes through the link. Checking only `path.parent.lstat()` does not detect that ancestor. Input validation likewise checks only the leaf file.

These are pre-existing layouts and ordinary arguments; no concurrent filesystem replacement is needed to reproduce them. Although the forthcoming coordinator will construct these paths, the runner's advertised safe capture boundary does not currently enforce them.

**Fix:** Establish an explicit trusted attempt directory and derive or require its fixed, distinct `packet.json`, `stdout.bin`, and `stderr.log` paths. Reject collisions, traversal/outside destinations, and relevant symlink/reparse-point path components before launching or writing. Keep the existing regular-file and hardlink checks. Add rejection tests asserting no launch and no alteration of packet or outside files. This does not require promising protection against hostile concurrent filesystem replacement.

### 3. Valid requests with unknown goal or context make the deterministic worker fail

**Locations:** `src/mathresearch/fake_worker.py:28`, `src/mathresearch/fake_worker.py:30`.

`RunRequest` explicitly permits `actual_goal=None` and `context=None`. The fake worker inserts these values into string arrays, so otherwise valid Frame packets produce invalid submissions. Real subprocess reproductions returned exit code 1 with `frame.success_criteria[0]: must be a string` for a null goal and `frame.assumptions[0]: must be a string` for null context.

**Fix:** Emit valid empty arrays when the corresponding information is absent, and represent relevant unknown inputs explicitly in `missing_inputs` rather than inventing goal/context text. Add deterministic builder and subprocess tests for each null independently and both together. The fake worker should support the accepted packet domain.

### 4. Invalid successful output discards the completed process result needed for its outcome event

**Locations:** `src/mathresearch/process_runner.py:73`, `src/mathresearch/process_runner.py:112`, `src/mathresearch/process_runner.py:119`.

Both captures are written before parsing, which correctly preserves diagnostics. However, if a child exits 0 and emits malformed JSON, an invalid contract, or mismatched identity, parsing raises a message-only `ProcessRunnerError` before constructing `ProcessResult`. The caller receives neither the observed exit code nor a typed completed-process result. Task 4 therefore cannot use `process_outcome()` to commit the known completion while rejecting its submission. It would have to infer execution facts from exception text or treat a completed child as an uncertain attempt.

Reproduced with a mocked completed child returning exit code 0 and `b'{malformed'`: captures remain exact, but only `ProcessRunnerError` is exposed and it has no result payload.

**Fix:** Preserve the completed process facts independently of submission acceptance. Return a result carrying a validation failure and `submission=None`, or attach a typed completed result to a distinct output-validation exception. Task 4 must be able to append the actual process outcome without accepting malformed output. Test invalid UTF-8/JSON, multiple values, schema violations, and mismatched identities through that contract.

### 5. Signed subprocess termination codes cannot become outcome events

**Locations:** `src/mathresearch/process_runner.py:47`, `src/mathresearch/process_runner.py:79`; `src/mathresearch/contracts/run.py:274`.

The runner preserves `CompletedProcess.returncode`, but the event parser permits only nonnegative exit codes. A child terminated by a signal on POSIX has a negative return code. A simulated completed result with `returncode=-9` preserves captures and returns `ProcessResult`, then `process_outcome()` raises `ValidationError: exit_code: must be a nonnegative integer`. Task 4 cannot persist this completed failure with the current event interface.

**Fix:** Reconcile the process and event contracts before integration. Preserve the signed return code using strict integer validation that still excludes booleans, or explicitly represent signal termination in a documented event shape. Do not silently convert it to success or discard the observed termination information. Test parsing, serialization, replay, and `process_outcome()` for signal termination, with a real POSIX child test on that platform. This review simulated the negative code on Windows; it did not run a POSIX signal test.

## Minor

### 1. Process creation failures bypass the runner's exception type

**Location:** `src/mathresearch/process_runner.py:64`.

`subprocess.run()` is outside an `OSError` handler. A simulated executable launch failure escapes as `FileNotFoundError`, while packet, output-validation, and capture failures use `ProcessRunnerError`. This leaves Task 4 with an inconsistent expected-error boundary.

**Fix:** Wrap launch `OSError` in a distinct or clearly classified runner error with exception chaining. Preserve that no completed process result exists; do not fabricate a child exit code. Add a launch-failure test asserting that no new capture or process-outcome fact is invented.

## Verification and confirmed behavior

Fresh verification on 2026-09-14:

```powershell
$env:TEMP=(Resolve-Path '.review-temp').Path
$env:TMP=$env:TEMP
$env:PYTHONPATH='src'
py -m unittest discover -s tests -v
```

**81 tests passed**, exit code 0. The four new process tests cover deterministic builder output, ordinary exact-byte captures, a successful outcome object, and refusal of a leaf capture symlink. They do not cover the integration and error cases above.

Additional temporary-fixture checks established:

- Real subprocess reproduction of the store filename conflict, each nullable request field, and all four path cases in finding 2.
- Mocked nonzero completion (`7`) returns `submission=None`, preserves non-UTF-8 stdout bytes, and produces an outcome with code `7`.
- Eight malformed-output/identity cases are strictly rejected: invalid UTF-8, multiple JSON values, duplicate keys, nonfinite numeric input, and wrong run/task/revision/attempt. Each retains exact stdout and binary stderr bytes. The rejection logic is sound; finding 4 concerns the missing completed-result handoff.
- Mocked negative termination, malformed successful output, and process-creation failure exhibit findings 5, 4, and Minor 1 respectively.

The worker uses an argument-vector subprocess without a shell, and its normal output is deterministic compact JSON validated through `FrameSubmission`. The review does not require real adapters or Task 4 dispatch orchestration to be implemented in Task 3.
