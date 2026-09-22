# Task 11 progress: paired evaluation foundation

## Implemented

- Added strict case/rubric loading and a worker projection that excludes expected obligations, forbidden claims, and evaluator checks.
- Added immutable evaluation manifests with case/rubric hashes, explicit model and effort, Git SHA, call/time caps, and alternating paired order.
- Added incremental trial/grade storage, report/source hash checks, explicit human/advisory grades, ambiguity-safe trial intents, and call/time budget reservations.
- Added paired score, critical-failure, Deep quality, Quick call-count, latency, and unknown-cost aggregation. Missing grades, incomplete trials, mismatched source snapshots, or invalid report hashes keep the result incomplete.
- Connected `research evaluate` to offline evaluation initialization/re-aggregation and provider-backed paired trials. Live mode requires explicit call/time caps, records intent before launch, and writes incremental trial records. Session-usage prompts are disabled by the user's standing preference. Ambiguous outcomes are never relaunched. Baseline and pipeline receive identical persisted source/check inputs; the pipeline run sits inside its trial wrapper.
- Added optional case selection and replicate count so Task 12 can run its bounded smoke cases independently before the full comparison. Offline manifest preparation for odd-sum, bounded-search, and perfect-six at one replicate passed without provider calls.
- Guarded each paired execution with the research store's OS-backed nonblocking output-directory lock, preventing concurrent runners from racing call reservations or launching duplicate trial intents.
- Added synthetic fixed-output evaluator coverage for a completed but circular response and an explicitly graded qualified response.
- Updated the binding comparison protocol per Astra decisions RQ-003/RQ-004: effort is selected once on the supported adjustable effort control and frozen across both conditions; limits are 240 calls and 7,200 active seconds.
- User preference update: use `gpt-5.6-terra` with medium effort for tests and product runs unless explicitly overridden. Live evaluation no longer asks for the five-hour quota reading; it records `session_usage_monitoring=disabled_by_user` and relies on the call and wall-time caps.

## Verification

Commands: `python -m compileall -q src/mathresearch/research/evaluation.py src/mathresearch/research/cli.py tests/unit/test_research_evaluation.py`; `git diff --check`; focused unittest suite shown below; direct quota-boundary probe.

Result: compilation passed and `git diff --check` passed. The direct quota-boundary probe passed: with 55% five-hour quota remaining at baseline, 50% remaining continues and 45% remaining stops. The focused suite ran 44 tests before the incremental-cap clarification but could not pass in this environment: Windows denied writes under Python-created temporary directories, first under the profile temp directory and again after redirecting `TEMP` into the workspace. Failures affected existing integration/store tests and evaluator fixtures before assertions could execute. The updated focused suite still needs a rerun in a normal writable-temp environment.

## Still open

An initial live smoke was attempted in `runs/research-quality-smoke-20260921/` and was stopped after four failed conditions. The pipeline failures were caused by the worker scratch parent resolving to the profile temp directory, which Windows denied; baseline diagnostics were not preserved by the original implementation. The evaluator now uses a trial-local worker temp directory, preserves stdout/stderr and structured provider outcomes, stops after a failed or ambiguous condition, records Ctrl+C as ambiguous, excludes operator prompt time from active wall time, and returns a non-success CLI status for a stopped smoke. The saved attempt consumed no valid completed trial evidence and must not be graded as a comparison. A fresh smoke can run with only explicit call and wall-time caps; it will not ask for a five-hour quota reading. The retry reached Terra medium and recorded the observed model and effort, but the provider exited unsuccessfully before producing a result, so no comparison evidence was graded. The 317-test offline suite passes after these repairs. Task 12 smoke, grading, and the full comparison remain open.
