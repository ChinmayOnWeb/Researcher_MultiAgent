# Portable AI research pipeline — design and durability boundary

Status: architecture proposed for review, with a bounded implemented quick-workflow slice. Public `mathresearch init`, `mathresearch run --adapter codex`, `mathresearch dispatch --adapter fake`, and `mathresearch status` commands provide durable initialization, replay/repair, and coordinator-owned four-stage quick orchestration. The currently installed Codex CLI is deliberately unavailable for this no-shell profile, so a live provider result is not claimed.

## Objective

Turn the supplied AI Research Workflow into a reusable, resumable process that works across capable language models through installed command-line agent tools. Preserve its ten phases, human participation, competing hypotheses, explicit evidence standards, and useful failures.

The system can enforce records, dependencies, and checkpoints. It cannot guarantee truth, make a weak model competent in every domain, or establish independence merely by assigning different role names. These limits must remain visible in the output.

## Execution model and current slice

Build a model-independent protocol, role prompts, and a small local Python coordinator. The future execution model is a coordinator-launched adapter for an installed agent CLI: the adapter starts the configured CLI with a bounded task packet, gathers its structured submission, and returns it for coordinator validation and event recording. The adapter—not a skill or an ambient agent host—defines the process boundary. It can support a particular installed CLI without making the durable run format depend on that CLI's model API or framework.

The coordinator runs on Windows, macOS, and Linux using the Python standard library. A single coordinator owns each run. When execution adapters are added, workers will return submissions for it to ingest; parallel research remains optional. An adapter unable to provide isolated worker contexts must execute branches sequentially or disclose the weaker isolation.

The implemented slice covers versioned run contracts, per-run locking, atomic initialization, event replay/repair, legacy fake Frame dispatch, and a fixed Quick graph: Frame, Investigate, Verify, and Explain. The coordinator persists configuration, intent packets, bounded provider captures, normalized results, acceptance, and a deterministic report; it alone decides the next stage and terminal status. A committed successful outcome resumes without a replacement launch; an intent without an outcome becomes visibly blocked rather than silently relaunched. The public Codex adapter remains unavailable because its verified CLI controls cannot enforce disabled shell execution, so no live-provider completion is claimed.

Three delivery options were considered:

| Option | Advantages | Tradeoffs |
| --- | --- | --- |
| Instructions and templates only | Broadest portability; almost no setup | Phase order, missing evidence, and pause behavior rely entirely on the agent |
| Protocol plus local coordinator and installed-CLI adapter — recommended | Portable, persistent state and machine-checked requirements; explicit execution boundary | Requires an installed CLI and a configured adapter; adapter behavior must be disclosed |
| Standalone application calling model APIs | Direct scheduling and concurrency | Provider setup, API costs, credentials, and tool security become part of the first release |

The portable protocol is the shared foundation. Standalone execution can be added through adapters later. No web application, database service, model API integration, or automatic paid calls are proposed for the first release.

## Run input and capability discovery

Each run records the question, actual goal, context, constraints, audience level, mode, stakes, learning preference, and budgets. Missing required inputs produce a focused clarification task. Unknown facts remain unknown; defaults are explicitly recorded as assumptions.

At initialization the configured adapter declares whether its installed CLI can browse, read local evidence, execute code safely, run workers, isolate their contexts, and obtain human responses. These are capability declarations, not claims that any particular check has succeeded.

When execution is implemented, the coordinator creates only tasks the adapter declares it can perform. Without browsing, evidence collection is restricted to supplied materials and clearly marked as such. Without execution, proposed experiments are labeled unexecuted. Without independent workers, a second attempt is labeled a separate reasoning route with limited context independence. Missing capabilities never generate fabricated results.

## State and artifacts

Each run has an isolated directory with:

- `request.json`: original request, capabilities, budgets, and defaults.
- `events/`: immutable, sequential event records written by the coordinator.
- `state.json`: a rebuildable projection of those events.
- `tasks/`: bounded assignments and their accepted submissions.
- `sources/`: source metadata and supplied or retrieved evidence artifacts.
- `experiments/`: proposed methods and, where executed, commands and results.
- `research-log.md`: generated hypotheses, evidence, failures, open questions, and change-of-mind conditions.
- `report.md`: generated conclusion, explanation, alternatives, and limitations.

Events are authoritative; `state.json` is only a rebuildable projection. Submission processing is atomic from the reader's perspective: an event becomes committed only after its temporary file is renamed into place, and an interrupted or stale projection is rebuilt from committed events. A nonblocking, OS-backed per-run lock rejects simultaneous writers; the persistent lock-file path is not itself a claim of ownership. Duplicate submission IDs are idempotent; conflicting duplicates are rejected. Stale submissions against a superseded task revision are rejected with an actionable explanation.

`status` authoritatively replays committed initialization and Quick workflow events and atomically reconstructs missing or stale projections, including accepted stage payloads and a completed report. It refuses inconsistent or corrupt layouts. Before commit, initialization may accept an existing destination only when its sole persistent entry is `.run.lock`; it refuses any other nonempty or precommit destination rather than overwriting it. These rules reduce partial-write and concurrency risks; they do not promise recovery from every power loss, filesystem failure, rename-semantics failure, or external interference.

The model receives task-specific packets rather than the entire growing transcript. Every packet contains the objective, allowed inputs, output schema, completion criteria, capability limits, and remaining task budget. Artifacts outside the run directory are not written by the coordinator.

## Minimal data contracts

Records use stable IDs and explicit references. The coordinator rejects missing required fields, dangling references, invalid enum values, and cycles in task prerequisites.

| Record | Required information |
| --- | --- |
| Task | ID and revision; phase and role; objective; prerequisites; allowed input IDs; acceptance requirements; status |
| Hypothesis | Statement; assumptions; predictions; supporting and opposing evidence IDs; falsification conditions; status |
| Claim | Statement; epistemic type; provenance basis; importance; evidence and dependency IDs; scope; verification status |
| Source | Locator; title; author or publisher if known; source type; retrieval record if fetched; publication date if available; exact supporting excerpt or artifact location |
| Experiment | Hypothesis; method; expected discriminating outcome; inputs; proposed or executed status; execution record; result; interpretation; limitations |
| Critique | Target IDs; objection; evidence or proposed countercheck; severity; resolution and justification |
| Failed approach | Attempt; why it was promising; observed reason it failed; lesson; linked artifacts |
| Human gate | Trigger; decision packet; pending or answered status; human response; provenance; affected task revisions |

Epistemic type and provenance basis are separate fields. Epistemic type distinguishes facts, assumptions, estimates, opinions, hypotheses, and unknowns. Provenance basis distinguishes observed, derived, inferred, and speculative claims. A source's assertion is an observed assertion by that source; it is not automatically an established fact about the world.

Derived claims link their inputs, assumptions, and calculation or argument. Inferred claims state the interpretation and alternatives. Speculative claims explicitly state what evidence is missing. Confidence is qualitative with a written justification; numerical probabilities require a defensible method. Verification status is distinct from confidence.

## Research flow

The ten phases are task categories in a dependency graph, not a one-way checklist. Findings can create bounded follow-up work or invalidate dependent conclusions.

1. **Frame:** refine the question, success criteria, terminology, assumptions, missing inputs, and stakes. Do not issue a substantive conclusion here.
2. **Decompose:** create subquestions and dependencies; separate existing knowledge, derivations, external evidence, experiments, and unknowns.
3. **Explore:** propose genuinely different hypotheses and methods, with their evidence requirements and weaknesses. Preserve at least one substantive alternative for significant conclusions.
4. **Investigate:** pursue eligible branches using separate task packets. Record evidence both for and against hypotheses; prioritize primary sources where appropriate.
5. **Experiment:** test discriminating predictions, calculations, cases, and counterexamples where feasible. Store failures. Distinguish empirical tests, calculations, thought experiments, and mathematical proofs.
6. **Adversarial review:** give the reviewer the leading claims and evidence. Require specific objections, alternative explanations, and at least one concrete falsification attempt for significant conclusions. A written objection alone is not a completed search or experiment.
7. **Independent attempt:** issue the original framed question and necessary input materials without the leading answer, branch interpretations, or critique. Require a different route. Record what the worker could see and which assumptions, sources, methods, and model family are shared. Context isolation is only claimed where the host supports it.
8. **Synthesize:** compare surviving results, investigate material disagreements, and retain unresolved alternatives. Do not average incompatible results or count model votes as evidence.
9. **Verify:** check important claims, calculations, quotations, dates, units, definitions, attribution, and dependencies. A reference existing is a structural check, not verification that it supports a claim. Semantic verification needs an explicit evidence comparison or reproducible check record.
10. **Explain:** generate a report appropriate to the user's level, separating intuition, evidence, technical detail, implications, and limitations.

Independent tasks can run earlier to reduce exposure to the emerging conclusion. Their comparison still occurs before synthesis. Shared source dependence weakens apparent convergence and must be reported.

Serious critique findings, material disagreements, or failed verification create follow-up tasks and invalidate affected downstream work. A new revision preserves old artifacts and their failure history. Resolving an objection requires a recorded response and supporting check, not deletion.

## Human participation

High-stakes decisions, conceptual leaps requiring user judgment, and consequential uncertain conclusions create a human gate before final synthesis. User-specified checkpoints also create gates. A learning-mode gate offers evidence and a scaffolded question before revealing the answer.

The gate packet contains the current question, competing explanations, relevant evidence, limitations, and the specific judgment requested. A provisional hypothesis is clearly labeled and is not presented as an endorsed final answer. In learning mode the pending answer is withheld from the user-facing packet.

While a gate is pending, the coordinator returns `awaiting_human`; independent work may continue only if it does not rely on the pending decision. No timeout, model-written approval, or empty response releases a gate. The adapter must deliver an actual human response through the dedicated response command. For a local CLI adapter this is a trusted boundary, not cryptographic proof of human identity.

User responses are evidence of preference, goals, or approval—not automatically evidence that a factual hypothesis is true. Disagreement is recorded and can trigger further investigation. A substantive change in the question or assumptions invalidates dependent tasks.

## Scaling, budgets, and stopping

| Mode | Required path |
| --- | --- |
| Quick | Frame, investigate, verify, explain; surface material uncertainty and alternatives where relevant |
| Deep | Frame, decompose, explore, investigate, critique, independent route for significant conclusions, synthesize, verify, explain |
| Research | All ten phases; multiple branches where appropriate; experiments or explicit infeasibility records; independent attempt; full evidence and failure log |

Difficulty, uncertainty, and consequences determine a recommended mode. Significant stakes cannot silently inherit the quick profile; the run surfaces the mismatch and the required human checkpoint.

Default bounds for the first release are 30 accepted task submissions and two revision cycles per task, configurable per run. The coordinator enforces these local bounds and any configured elapsed-time limit. Token and monetary costs are recorded only if supplied by a trustworthy host adapter; unavailable usage is marked unknown and is never invented.

Stop states are `awaiting_human`, `blocked`, `budget_exhausted`, and `complete`. Failed worker execution is retryable within limits. Insufficient evidence can still support a completed report concluding that the answer is unknown, provided the required process and verification disclosures are complete. Budget exhaustion produces an explicitly incomplete report, not a completed investigation.

## Proposed interface

The public CLI exposes `init`, `run --adapter codex [--model NAME] [--timeout-seconds N]`, `dispatch --adapter fake`, and `status`. `run` starts or resumes the fixed Quick graph and emits a final machine result only after a terminal state. A completed repeat makes zero provider calls. It rejects unsupported request profiles and conflicting resume configuration before launch. The only configured provider is deliberately unavailable for the required no-shell capability profile; this returns `adapter_unavailable`, rather than pretending a read-only shell is no shell. `dispatch` accepts only the deterministic local fake adapter, creates and executes the one legacy Frame task, and returns a durable disposition (`accepted`, `already_accepted`, `rejected`, `already_rejected`, or `blocked_interrupted`). JSON output enables integration; readable output supports direct use.

The planned package includes role prompts, adapter configuration, sample requests, and one entirely local worked example. An installed-CLI adapter launches the configured agent command with coordinator-issued packets; worker submissions are claims to be checked and never directly mark the overall run complete.

The coordinator and adapter never execute code supplied in a research result. Experiments are executed only through the adapter's existing permission model. Retrieved documents are evidence inputs, not instructions that can change workflow policy or authorize actions.

## Verification and acceptance

The integrated CLI tests demonstrate request-to-report behavior through a safe local argv stub: four fresh stage processes, a readable report, restart recovery, and a no-op repeated run. This is not a live-provider demonstration and is not evidence of research accuracy. A live release gate remains blocked until an installed authenticated provider can enforce the no-shell profile, complete the bounded demonstration, and undergo independent end-to-end review.

Targeted automated checks cover:

- malformed artifacts, dangling evidence references, and cyclic dependencies;
- premature synthesis without required alternatives, falsification records, or an independent attempt;
- independent task packets excluding the leading conclusion;
- pending gates preventing dependent work and final completion;
- duplicate submissions, stale revisions, restart recovery, and concurrent-writer rejection;
- material criticism and failed verification invalidating downstream conclusions;
- budget exhaustion and unavailable tools yielding explicit incomplete or limited results;
- reports distinguishing source assertions, derivations, inferences, speculation, and verification gaps.

These checks establish workflow behavior. Evaluating research quality additionally requires domain benchmarks and human review; a well-formed artifact is not proof of a sound conclusion.

## Decision for review

Approve or revise the first-version scope: portable role instructions and evidence contracts, a local coordinator, configured installed-CLI adapters, persistent research artifacts, explicit human gates, and a verified local example. A standalone application with model API calls would be a different execution adapter and requires choosing that deployment target first.
