# Implementation plan for GPT-5.6 Luna: reliable research evaluation

Drafted 2026-09-24 against commit `fc900e45e4028edbad314e6096afbbb0394011c9`, branch `codex-research-quality-repair`, worktree `D:\UCB\MathResearcher\.worktrees\research-quality-repair`.

## Objective and working rules

Repair the demonstrated protocol, assessment, accounting, and scheduling faults; then measure whether additional research stages improve results on tasks with genuine room for improvement. The ten-style corpus remains an easy-task regression suite. It does not establish a general failure or success of the architecture.

- GPT-5.6 Luna implements this plan directly and sequentially. No skills or delegated implementation. Ask Astra only for a focused unresolved design question or review if needed under the user's existing preference.
- All live test conditions and the product remain GPT-5.6 Terra at medium reasoning effort. Luna is the implementation model, not a replacement experimental condition.
- This document is a draft implementation handoff. Drafting it does not launch implementation or live experiments. Once implementation is requested, complete the offline work without repeated confirmation prompts.
- Preserve existing run evidence and historical failures. Changes belong in new runs and versioned schemas; never rewrite old trials into successes.
- Do not ask for quota percentages. Keep the effort control. Enforce explicit machine-readable call and wall limits internally, stop on provider usage-limit errors, and leave unknown token/cost data as unknown.
- Do not add problem IDs, expected answers, theorem-name allowlists, or fixture-specific shortcuts to production routing or assessment.
- Implement one task per commit-sized change. Record changed files, meaningful tests, and remaining limitations. A task is not complete merely because its live run reaches a terminal state.

## Findings that determine the implementation order

The supplied independent judgment correctly identifies a ceiling effect, dormant evidence capabilities, three distinct outcomes (mathematical quality, protocol reliability, status calibration), and unbalanced execution order.

The inspected code adds concrete constraints:

| Location | Current behavior | Required consequence |
| --- | --- | --- |
| `research/evaluation.py:make_manifest`, `research/cli.py:_evaluate` | Order depends on case index after filtering. A single selected case starts pipeline-first at replicate 1. | Freeze global ordering before selection; execution filters must not create new orderings. |
| `research/engine.py:_execute_action` | Structural repair launches another worker inside one action; its prompt omits the previous JSON and says to use empty dependencies when unsure. | Record and budget each launch; repair the actual payload without deleting semantic dependencies to pass validation. |
| `research/contracts.py:_validate_draft` | Claim and proof-step dependency namespaces are already separate and strictly validated. | Improve instructions, errors, and bounded repair; do not remove validation or claim this distinction is missing altogether. |
| `research/provenance.py:assess` | Critical `model_knowledge` is always unverified; `assumption` is always conditional. | Represent question premises and auditable standard results explicitly. Do not blanket-trust recalled claims. |
| `research/routing.py:assess_latest` versus `_next_decision` | Final assessment uses draft/audit-visible evidence; routing also calls `assess` with current global evidence. | Use one assessment context and one current draft/audit identity for decisions and reporting. |
| `research/cli.py:_run_evaluation_trial` | Empty `checks` disables tools; nonempty checks become evaluator-supplied text, not actual in-run tool receipts. | Separate receipt-assisted comparisons from experiments exercising real broker actions. |
| `research/math_checks.py` | Operations cover integer divisors, perfect-number search, and univariate polynomial checks. | Do not pretend arbitrary graph counting or algebraic certificates are supported. Add only a bounded operation needed by a declared case. |

Implement Tasks 1–6 first. Tasks 7–8 are a separately identifiable experiment extension, following the reliability repairs.

## Task 1 — Preserve evidence and define separate outcomes

**Files:** `diagnostics/ten-styles-20260923/comparison.md`, new `diagnostics/ten-styles-20260923/methodology-addendum.md`, new `tests/fixtures/research/diagnostic_regressions/`, `research/evaluation.py`, `tests/unit/test_research_evaluation.py` (Python paths are under `src/mathresearch/`).

1. Add the narrower interpretation to an addendum: elementary guided questions, one replicate, all checks empty, pipeline-first per-case execution, later baseline recoveries, and no causal interpretation of quota failures. Preserve the original result and reference the addendum from it.
2. Extract minimal captured JSON for the four dependency failures, accepted-premise/induction failures, stale-objection case, and structural retries. Store source run/action paths and hashes. Exclude unrelated provider log content. If a capture is unavailable, label its replacement synthetic; do not claim observed reproduction.
3. Define independent result fields: execution outcome and failure class; protocol validity; semantic correctness/coverage grades with grader and artifact hash; final status and calibration judgment; resources. Permit semantic grading of a rejected payload without changing its protocol failure.
4. Preserve raw-answer/payload hashes for schema failures. A missing answer has unavailable semantic grade, not an invented zero mathematical score. Report missingness and completion rate separately.

**Acceptance:** a correct schema-rejected proof has semantic credit and protocol failure simultaneously; quota failure remains distinguishable from incorrect reasoning; each grade identifies the exact artifact reviewed. Report both all-attempt product results and quality among assessable answers, with denominators.

## Task 2 — Count and bound every provider attempt

**Files:** `research/engine.py`, `research/events.py`, `research/store.py`, `research/provider.py`, `research/evaluation.py`, `research/cli.py`, `research/reporting.py`; associated engine/events/store/evaluation/recovery tests.

1. Introduce durable attempt IDs under each action, including structural repairs. Persist an attempt intent before launch and a result afterward, with parent action, retry reason, prompt/schema hashes, captures, observed model/effort, duration, and available token/cost values.
2. Keep action count, reserved budget, attempted provider launches, and observed session IDs separate. Budget against every attempt intent, conservatively including ambiguous launches. Session-ID text is supplemental telemetry, not a production counting mechanism.
3. Before each initial call and repair, enforce the shared call budget and remaining wall deadline. Remove the repair path's `max(1, ...)` launch after deadline. Count the repair prompt's bytes. Check requested versus observed model/effort on repairs too.
4. Retain each attempt's artifacts separately; an aggregate action capture may remain for compatibility. Record quota rejection as `provider_usage_limit`, not a generic mathematical failure. Stop the experiment queue on this error.
5. Version changed durable contracts and prompts. Read existing v3 records using their old schema and label historical counts as action-based/unknown attempts. Write new records with the new version. Do not resume an old ambiguous intent by inventing attempt history or repeat it automatically.

**Acceptance:** an invalid response followed by a valid structural repair is two budgeted attempts and one action. With one attempt or no time remaining, repair never launches. A crash after attempt intent resumes as ambiguous, not as a duplicate call. Replay preserves counters. Unknown tokens/costs remain null, including aggregate displays.

## Task 3 — Make reference errors recoverable without changing the mathematics silently

**Files:** `research/contracts.py`, `research/prompts.py`, `research/engine.py`, `research/cli.py`; contract/prompt/engine/evaluation tests.

1. Retain the current namespaces: claim `depends_on` references claims, claim `step_ids` references proof steps, and proof-step `depends_on` references proof steps. Publish a compact valid example in every draft-producing role, including baseline.
2. Return structured validation details: JSON path, bad reference, expected namespace, and available IDs. Continue to reject nonexistent references, cycles, and duplicate IDs.
3. Build a shared bounded structural-repair path using the exact rejected payload plus validator errors and original input. Require a complete corrected payload and a recorded change explanation. Do not recommend empty dependencies as a general escape hatch; preserve the rejected payload and diff for review.
4. Keep the strict single-call baseline at one call with no repair. Add an explicitly named repair-enabled baseline condition when comparing protocol reliability with the pipeline; give both that condition and pipeline the same maximum structural retry policy. Never report a repaired baseline as single-call.

**Acceptance:** all four observed reference failures produce precise errors; a supplied corrected response passes; deleting required support, circular references, and wrong-namespace links remain rejected. Strict baseline makes one call even on failure. Repair attempts are included in Task 2 accounting.

## Task 4 — Calibrate proof status and remove stale repair state

**Status: implemented; 107 focused tests pass.** See `docs/superpowers/reports/research-quality/task-12.md`. Full-suite attempt: 317 tests; Task 4 paths passed, while pre-existing Task 3 evaluation fixtures still fail their legacy expected corpus/manifest counts (8 cases/24 rows versus current 3/9). No provider trials were run.

**Files:** `research/contracts.py`, `research/prompts.py`, `research/provenance.py`, `research/routing.py`, `research/reporting.py`, `research/events.py`; assessment/provenance/routing/reporting tests.

Use a versioned, explicit basis for claims rather than treating all `assumption` and `model_knowledge` entries as supported:

| Basis | Required support | Treatment |
| --- | --- | --- |
| Question premise | Exact reference to question or supplied user goal; audit confirms the premise applies | Accepted within the stated problem, disclosed as a premise |
| Additional assumption | Explicit statement not supplied by the question | Conditional until discharged or authorized as scope |
| Standard mathematical result | Result statement, hypotheses, application steps, and audit of those hypotheses | Model-reviewed use of a result; no claim of formal verification |
| External factual assertion | Appropriate source evidence and entailment review | Existing provenance rules apply |
| Conjecture or unsupported recollection | No sufficient justification | Remains unverified |

1. Add validated basis metadata and corresponding audit fields. A model assigning a category cannot by itself upgrade status. Standard-result claims require an auditable application; conjectures, historical claims, and current facts cannot be promoted by renaming them.
2. Give local proof assumptions explicit scope and discharge links. An induction hypothesis cannot become an unconditional premise; it must be discharged by the induction step/conclusion. Preserve dependency and circularity checks.
3. Make routing and reporting call the same assessment helper with the selected draft ID/hash, its matching audit ID/hash, and the exact visible evidence. Derive active objections from that version; preserve prior objections in history.
   Follow dependency edges in their actual namespaces. The current assessor tests proof-step dependency IDs against the claim map even though the contract requires disjoint namespaces. Traverse proof-step dependencies as steps and propagate claim support through explicit claim links; test transitive coverage and unresolved support.
4. A revision log saying 'resolved' is insufficient. A fresh matching audit must cover the changed claim/step and close the objection. A revised proof that still contains the original flaw remains unresolved.
5. Separate a source's attributed statement from the truth of that statement and from citation validity. A citation offset error is a provenance defect, not evidence that the mathematical assertion is false. Disclose peripheral defects; allow them to block the central result only when its evidence/dependencies require them.

**Acceptance:** audited induction, the supplied fair-coin premises, and the centroid proof can be `supported_within_scope`; an added unstated assumption remains conditional; a conjecture remains unverified; a falsified premise attribution is rejected. Re-audit clears a genuinely repaired objection but preserves it in history. Unchanged bad algebra, unsupported historical commentary, stale audit IDs, fabricated receipts, and circular support remain detectable.

## Task 5 — Freeze balanced schedules and support honest recovery

**Files:** `research/evaluation.py`, `research/cli.py`, `diagnostics/ten-styles-20260923/run-remaining.ps1`; evaluation/recovery/CLI integration tests.

1. Create a single immutable manifest from the full ordered corpus before execution filtering. Store global case position, seed/order rule, replicate IDs, all condition orders, model/effort, capability/retry policy, source hashes, and code/schema versions.
2. Treat `--case-id` and `--condition` as execution selections of that manifest. A selected case must retain its original order, and existing manifests must be reused on resume. Condition-only reservations must cover only scheduled attempts, not a hidden paired minimum.
3. Continue to other scheduled trials after a recorded schema failure. Stop the whole queue on usage limit, global budget exhaustion, or an ambiguous execution requiring reconciliation. Keep both the failed condition and the unstarted partner visible.
4. Append separately identified recovery attempts linked to the original trial. Never replace it or silently pair a later recovery with an earlier run as though they were contemporaneous.
5. Retire the old per-case launch script from recommended usage with a clear historical note. Add a manifest-based resumable runner rather than rebuilding a schedule for every case.
6. For two conditions, use balanced case order and alternate per replicate. For three or more experimental arms, freeze a counterbalanced rotation over cases/replicates and report any residual imbalance from interrupted runs.

**Acceptance:** selecting a case individually preserves the same first condition as selecting the full suite. A ten-case one-replicate paired schedule has five starts per condition. Restart does not rerun completed trials. Quota failure prevents the next provider launch. A one-call-only selection can use a one-attempt budget.

## Task 6 — Build a fair, inspectable comparison report

**Files:** `research/evaluation.py`, `research/cli.py`, `research/reporting.py`; evaluation/recovery tests; new evaluation protocol document.

1. Produce separate tables for semantic quality, schema acceptance, terminal-status calibration, provider availability, and resource use. Show first attempts and recoveries separately. Preserve the existing pilot quality thresholds as a named legacy policy; do not lower them to manufacture a pass.
2. Prepare grading packets containing question, fixed evidence, raw answer/structured proof, and necessary output claims, with condition and cost labels hidden. Freeze output hashes before grading. Require reasons tied to proof steps or errors; accept mathematically valid alternative proofs instead of matching the reference method literally.
3. Show equal-input comparisons only when question/source hashes, model/effort, and evidence policies match. Label unmatched, temporally recovered, and quota-truncated pairs. Report small-sample limits and baseline ceiling effects.
4. Show actual calls and token data where available; do not present equal call counts as equal token budgets. No zero-valued cost totals when every cost is unknown. Keep latency and tools used visible.

**Acceptance:** a mixed fixture containing a correct protocol failure, a wrong valid JSON answer, an incorrect status, and a quota exit reports four distinct outcomes. Missing grades cannot become passing scores. Correct baseline answers at the ceiling produce no demonstrated gain even if pipeline wording is longer.

## Task 7 — Exercise evidence capabilities and budget controls

**Files:** new `evals/research-value-v2/` cases, truth programs and rubric; `research/evaluation.py`, `research/broker.py`, `research/math_checks.py`, `research/contracts.py`, `research/cli.py`; broker/math-check/case/evaluation tests.

1. Keep the ten easy styles as regression controls. Build separate development and held-out case sets with six families: exact finite enumeration with a witness, symbolic identity with a domain trap, boundary counterexample, conflicting-source reconciliation, verification of a flawed proof, and multi-part inference requiring evidence from several supplied records.
2. Use solvable instances with independently established answers/certificates. Store truth and grading obligations outside worker packets. Remove proof-route hints from the harder questions. Freeze case generation seeds, reference answers, and rubric before trials. Record all development cases; do not select only cases the pipeline wins. A held-out null result remains a null result.
3. Make tool availability an explicit case capability policy independent of `checks: []`. Preserve exact shared source snapshots. Retain a receipt-assisted track that supplies the same pre-acquired transcripts to each condition and labels them as evaluator-supplied text.
4. Add an integration track that invokes the real broker and proves that requested checks can affect audit/repair. Start with supported polynomial checks; if finite graph enumeration needs a new operation, add a typed, deterministic operation with fixed size/work/output bounds and an independently written truth checker. Do not enable arbitrary worker shell code.
5. Freeze three architecture-comparison arms: strict one-call answer; bounded sequential self-review; full pipeline. Give the latter two equal total attempt and wall caps, equal tools/evidence access, and equal structural-repair allowances. Preserve independent branch isolation in the full pipeline. The strict one-call arm measures product value; only the budget-matched comparison helps test value beyond spending more calls.
6. Keep pre-acquired-evidence comparisons distinct from autonomous tool-use comparisons. A baseline receiving all receipts up front and a pipeline spending calls to discover them are not equal-information-at-each-step mechanisms; disclose setup and acquisition costs. Use common tool-policy access for the two budget-matched autonomous arms.

**Acceptance:** held-out truth never appears in worker prompts; incorrect source content remains untrusted; at least one real broker receipt is consumed by a draft and audit in the integration fixtures. Finite checks cannot establish universal results. Offline fake-provider tests cover all three arms without quota spend.

## Task 8 — Add an optional efficient route and pre-register the next live pilot

**Files:** `research/routing.py`, `research/contracts.py`, `research/prompts.py`, `src/mathresearch/contracts/research_request.py`, CLI/reporting; routing/request/CLI tests; evaluation protocol document.

1. Preserve explicit Quick, Deep, and Research modes. Add an opt-in adaptive policy, recorded in the request and manifest. Start with one draft and one audit. Finish when central obligations are covered and no active material objection remains; otherwise choose the smallest bounded action addressing a recorded gap (check, source, revision, or independent branch).
2. Escalation must name the unmet obligation and expected new evidence. Confidence language or branch agreement alone cannot justify acceptance. Do not silently downgrade an explicit request for Deep or Research. Record why every additional stage was scheduled.
3. Test easy-path completion and concrete escalations offline. Compare the adaptive policy only as an explicitly named experimental arm after the fixed full-pipeline comparison; never replace the full pipeline mid-run.
4. Produce a dry-run manifest and projected worst-case attempts before a live pilot. Use three replicates per case for the pilot, counterbalanced orders, frozen Terra-medium settings, and a small development calibration batch before the held-out run. Agree the live run's concrete resource envelope at execution if it has not already been authorized; do not invent quota readings or repeatedly ask for them. Stop cleanly on usage limits.
5. Use separate decision gates: easy-task regression/calibration; protocol reliability; hard-task semantic value versus one call; and architecture value versus budget-matched sequential review. Additional branch-removal or audit-removal experiments are only needed if a gain appears and attribution is still unclear.

**Acceptance:** an easy complete audited proof can finish in two calls on the adaptive policy; unresolved mathematical defects force a bounded next action or a qualified stop. Live findings must report failures and matched-pair counts. No architecture-wide success claim follows from a small pilot alone.

## Verification and handoff

Use the existing standard-library `unittest` suite. Add regression tests for the observed failures and the budget/replay boundaries above. Run targeted modules after each task, then the full unit and integration suites once at the end of the implementation phase. Example commands from this worktree:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests/unit -p "test_research_assessment.py"
python -m unittest discover -s tests/unit -p "test_research_engine.py"
python -m unittest discover -s tests/unit -p "test_research_evaluation.py"
python -m unittest discover -s tests/unit -p "test_evaluation_recovery.py"
python -m unittest discover -s tests/unit
python -m unittest discover -s tests/integration
```

Luna's completion report must distinguish: implemented and offline-tested repairs; historical artifacts replayed without new provider calls; benchmark definitions ready; and live conclusions still unmeasured. Include changed files, test results, schema compatibility behavior, and the next exact task. Do not claim live improvement based on offline tests or better status labels.

Suggested first handoff: **Implement Tasks 1 and 2 only, verify the captured failure/accounting regressions, and report the durable attempt contract before continuing to dependency and assessment changes.** The remaining tasks are ordered follow-on work, not a single oversized patch.
