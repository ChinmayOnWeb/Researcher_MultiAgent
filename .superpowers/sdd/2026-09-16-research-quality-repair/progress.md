# SDD ledger — plan: docs/superpowers/plans/2026-09-16-research-quality-repair.md

## Preflight

Baseline commit: `51932d2e871d98708c9e4bc1cca58460f90b4a71`.

The plan is the binding specification. No separate reachable specification file was named; `docs/research-pipeline-design.md` is background only.

The workspace is isolated at `.worktrees/research-quality-repair` on branch `codex-research-quality-repair`. Existing `runs/` evidence is preserved and excluded from implementation changes.

Baseline verification: the legacy suite exercises successfully through the existing storage/security tests, but the Windows command did not emit a final completion summary within the harness window. This remains an open baseline verification item and is not treated as a pass.

## Preflight interface and conflict scan

| Tasks | Shared contract/file | Finding | Ruling |
| --- | --- | --- | --- |
| 1 -> 2/6/11 | Fixtures, request/evidence contracts, evaluation cases | Task 1 fixes exact offline inputs consumed later; no conflict found. | Follow plan order. |
| 2 -> 3/4/6/7 | Research contracts and strict validation | Task 2 produces schemas used by replay, prompts, provenance, and routing; no conflicting field definitions found. | Contracts are authoritative. |
| 3 -> 8/9/10 | v3 events, replay, store | Task 3 establishes durable snapshot semantics consumed by engine, CLI, and reporting; no conflict found. | Preserve v1/v2 untouched. |
| 4 -> 8 | Packet visibility and prompts | Task 4 packet rules constrain engine launches; no conflict found. | Blind branch visibility remains enforced. |
| 5 -> 8/11 | Provider configuration and telemetry | Task 5 separates requested and observed settings; no conflict found. | Unknown observations remain null. |
| 6 -> 7/8 | Provenance and broker receipts | Task 6 outputs are inputs to routing and execution; no conflict found. | Worker output cannot create evidence or permissions. |
| 7 -> 8 | Pure decision function | Task 7 decisions are executed by Task 8; no conflict found. | Replay never launches actions. |
| 8 -> 9/10/11 | Engine terminal state and projections | Task 8 wires earlier contracts and later CLI/report/evaluation consumers; no conflict found. | Final render is persisted exactly once. |
| 9 -> 11 | Public CLI and evaluator entrypoint | Task 9 exposes the workflow and Task 11 consumes it; no conflict found. | Test-only provider injection stays out of production CLI. |
| 10 -> 8/12 | Report/log rendering | Task 10 is pure and Task 8 performs final-event wiring; no conflict found. | No formatting provider call. |
| 11 -> 12 | Evaluation artifacts and release evidence | Task 11 supplies measured comparison for Task 12; no conflict found. | Missing grades make comparison incomplete. |
| 12 -> all | Final review, smoke, release docs | Task 12 depends on all prior contracts and evidence; no conflict found. | Completion requires explicit gates. |

| Task | Internal consistency scan | Ruling |
| --- | --- | --- |
| 1 | Fixtures and regression cases align with stated quality failures and later consumers. | Proceed. |
| 2 | Exact schemas and tests align; strict unknown-key and nullable-field requirements are consistent. | Proceed. |
| 3 | Event ordering, replay, and storage requirements are consistent with v3 isolation. | Proceed. |
| 4 | Prompt and packet requirements agree with blind-branch visibility. | Proceed. |
| 5 | Requested/observed configuration and resume checks agree with telemetry rules. | Proceed. |
| 6 | Broker operations, capability checks, and provenance requirements are bounded consistently. | Proceed. |
| 7 | Routing branches, repairs, and assessment gates fit the declared caps. | Proceed. |
| 8 | Engine fault recovery, budgets, and terminal rendering are consistent with durable events. | Proceed. |
| 9 | CLI commands, exits, and human continuation align with the request and engine contracts. | Proceed. |
| 10 | Report truthfulness requirements align with qualified statuses and formal-verification disclosure. | Proceed. |
| 11 | Paired evaluation controls and incomplete-grade behavior align with the release gates. | Proceed. |
| 12 | Integrated gates require evidence beyond unit-test success and preserve historical outputs. | Proceed. |

Ruling: use the plan's exact task order `1, 2, 3, 4, 5, 6, 7, 10, 8, 9, 11, 12`; this resolves the intentional Task 10-before-Task 8 dependency because reporting is specified as pure and engine wiring is deferred.

Task 1: complete (commits 51932d2..5875cc2, review clean)

Task 2: fix round 1/5 (5 addressed, 0 open; commits c69afe5..87395cf)
Task 2: complete (commits 51932d2..87395cf, review clean)

Task 3: blocked by missing packet canonicalization and projection authorization.
Ruling: Task 3 validates `action_intended.packet` as a strict JSON object and hashes canonical UTF-8 JSON using sorted keys, compact separators, and `ensure_ascii=false`; it treats packet contents as opaque until Task 4's substantive packet validator. `sources/` and `tools/` projections are authorized only by committed, validated `action_finished` results for the corresponding tool action; no standalone source/receipt event or mutable authority is introduced. Cost if wrong: later packet-shape or broker wiring would need a compatibility migration, but replay remains deterministic and tamper-evident.
Task 3: review failed — fix round 1 required for capture-before-repair, projection authorization, action-result validation, replay legality, UTC normalization, layout security, lock ordering, and required fault/security coverage.
Task 3: fix round 1/5 (capture verification and baseline replay fixes addressed; 7 findings open in scoped re-review).
Task 3: fix round 2/5 (security/projection/idempotence/lock findings addressed; local legality and mandatory test coverage open).
Task 3: fix round 3/5 (local legality and v2 byte test added; source binding and committed-projection fault coverage remained open).
Task 3: fix round 4/5 (fresh implementer; source authorization binding, committed-projection recovery, and complete v2 byte fixture addressed; review clean).
Task 3: complete (commits 87395cf..71b29f1, 3 parked/deferred downstream items: Task 6 semantic broker schemas, Task 7 route reason codes, no new Critical/Important findings)
Task 4: review failed — fix round 1 required for durable gate text projection and deep packet validation.
Ruling: `gate_answered` responses with `decision="supply"` and non-null text must replay into immutable Snapshot `additional_user_input` records exactly `{gate_id,response_id,text}`; no ambient reconstruction is allowed. Task 4 must deep-validate every packet field, including sources, tool results, and additional user input, before building the prompt. Cost if wrong: human-supplied context could be lost or malformed untrusted data could reach workers.
Task 4: fix round 1/5 (valid gate projection and packet validation added; malformed-response and nested-type gaps remained in re-review).
Task 4: fix round 2/5 (gate envelope and named nested regressions addressed; recursive source/tool/branch schema gaps remained).

Task 8: fix round 1/5 (2 addressed, 0 open; commit 6d2a0bc..578f69b).
Task 8: complete (commits 0cfc6b4..578f69b, review clean).
Task 9: in progress (starting from Task 8's reviewed head 578f69b).

Task 8: fix round 2 (gate cancellation now writes terminal incomplete/user_cancelled; focused unit + public CLI regression passed). Task 9 surfaced the missing contract; corrected directly after user requested no agents/skills.

Task 8: follow-up fix complete (gate cancel terminalization, request projection integrity), covered by the combined 47-test command. Task 9: implementation and integration verification complete (47 tests); no independent agent review per user instruction.
