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

An initial live smoke was attempted in `runs/research-quality-smoke-20260921/` and was stopped after four failed conditions. The pipeline failures were caused by the worker scratch parent resolving to the profile temp directory, which Windows denied; baseline diagnostics were not preserved by the original implementation. The evaluator now uses a trial-local worker temp directory, preserves stdout/stderr and structured provider outcomes, stops after a failed or ambiguous condition, records Ctrl+C as ambiguous, excludes operator prompt time from active wall time, and returns a non-success CLI status for a stopped smoke. The saved attempt consumed no valid completed trial evidence and must not be graded as a comparison. A fresh smoke can run with only explicit call and wall-time caps; it will not ask for a five-hour quota reading. Retry work fixed the provider schema union (`anyOf`), constrained IDs and check bounds, exposed the durable event error, and aligned prompts with proof graph rules. Terra medium completed paired odd-sum and perfect-six conditions. The bounded-search pipeline reached its intended human gate and stopped in the noninteractive smoke without a gate response. No comparison grade was produced because the paired set is incomplete. The 317-test offline suite passes after these repairs. Task 12 smoke, grading, and the full comparison remain open.

## Certificate smoke and structural repair

- Replaced the unsuitable prize-style smoke prompts with three finite certificate cases: constrained queens, an algebraic root certificate, and constrained domino tilings. Each case carries an explicit expected answer and an auditable certificate shape.
- Added noninteractive smoke handling for advisory human gates. The runner records a deterministic `continue_limited` response so a live smoke can complete without an operator prompt, while the gate decision remains in the durable event log.
- Added one bounded structural repair attempt after a worker returns JSON that fails the role contract. The original stdout/stderr are retained, the repair uses the same schema and Terra settings, and a second failure becomes an explicit `protocol_error`; invalid references are never silently normalized. Astra reviewed this design and confirmed the strict-validation boundary.
- Increased the deep/research model-call profiles by one to reserve that repair attempt. Session-usage monitoring remains disabled by user request; evaluation limits are provider calls and wall time.

Verification: the constrained-queens live smoke completed with `gpt-5.6-terra` at medium effort, 7 provider calls, and no quota prompt. The evaluation correctly returned `comparison_status=incomplete` because live outputs still require independent semantic grades. Contract tests pass (15 tests); engine tests remain blocked by the environment's Windows temporary-directory permission failure, not by an assertion failure. Structural repair was reviewed and the successful smoke confirms the surrounding pipeline still reaches a complete pipeline trial.

## Final certificate smoke attempt

- The fresh aggregate run `runs/research-quality-smoke-complete-20260922/` completed all three pipeline trials with Terra medium: constrained queens (7 calls), algebraic certificate (9 calls, using the Research wall budget in a temporary fixture), and domino tilings (5 calls). All three produced terminal reports; the algebraic and domino reports retained qualified uncertainty where the supplied certificate did not prove every mathematical premise.
- The aggregate evaluator stopped before the domino baseline because its reservation ledger reserved the full worst-case pipeline budgets. A separate domino Research retry completed the pipeline in 9 calls, but the paired retry's provider later exited unsuccessfully before a baseline was recorded. Therefore this is a completed pipeline smoke, not a complete paired comparison.
- The repair path now validates worker provenance and audit completeness before accepting an action. Invalid citation spans and incomplete audit coverage receive one bounded repair attempt; unknown proof references remain hard failures after the repair limit.

