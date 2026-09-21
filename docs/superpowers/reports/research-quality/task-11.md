# Task 11 progress: paired evaluation foundation

## Implemented

- Added strict case/rubric loading and a worker projection that excludes expected obligations, forbidden claims, and evaluator checks.
- Added immutable evaluation manifests with case/rubric hashes, explicit model and effort, Git SHA, call/time caps, and alternating paired order.
- Added incremental trial/grade storage, report/source hash checks, explicit human/advisory grades, ambiguity-safe trial intents, and call/time budget reservations.
- Added paired score, critical-failure, Deep quality, Quick call-count, latency, and unknown-cost aggregation. Missing grades, incomplete trials, mismatched source snapshots, or invalid report hashes keep the result incomplete.
- Connected `research evaluate` to offline evaluation initialization/re-aggregation and provider-backed paired trials. Live mode requires explicit call/time/session-usage caps, records intent before launch, requests an operator session-usage reading before each condition, and writes incremental trial records. Ambiguous outcomes are never relaunched. Baseline and pipeline receive identical persisted source/check inputs; the pipeline run sits inside its trial wrapper.
- Guarded each paired execution with the research store's OS-backed nonblocking output-directory lock, preventing concurrent runners from racing call reservations or launching duplicate trial intents.
- Added synthetic fixed-output evaluator coverage for a completed but circular response and an explicitly graded qualified response.
- Updated the binding comparison protocol per Astra decisions RQ-003/RQ-004: effort is selected once on the supported adjustable effort control and frozen across both conditions; limits are 240 calls, 7,200 active seconds, and a manually monitored 10 percentage-point allowance from the saved starting reading of the five-hour quota remaining meter.
- Saved the first five-hour quota reading as the evaluation's usage baseline; later checks stop before another trial once the quota remaining drops by 10 points. Astra clarified this as an incremental task allowance, not an absolute ceiling on total session consumption.

## Verification

Commands: `python -m compileall -q src/mathresearch/research/evaluation.py src/mathresearch/research/cli.py tests/unit/test_research_evaluation.py`; `git diff --check`; focused unittest suite shown below; direct quota-boundary probe.

Result: compilation passed and `git diff --check` passed. The direct quota-boundary probe passed: with 55% five-hour quota remaining at baseline, 50% remaining continues and 45% remaining stops. The focused suite ran 44 tests before the incremental-cap clarification but could not pass in this environment: Windows denied writes under Python-created temporary directories, first under the profile temp directory and again after redirecting `TEMP` into the workspace. Failures affected existing integration/store tests and evaluator fixtures before assertions could execute. The updated focused suite still needs a rerun in a normal writable-temp environment.

## Still open

No live provider call has been made. The five-hour usage allowance is manual: the runner records readings between trials, and the operator must monitor/interrupt during a long trial. Trial token counts and cost remain null when the Codex worker interface does not report them. Task 12 smoke, grading, and the full comparison remain open. Focused suite rerun is also needed in an environment that permits temporary-directory file writes.
