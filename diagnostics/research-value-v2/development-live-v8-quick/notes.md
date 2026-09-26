# Quick-path live diagnostic v8

## Setup

- Case: `dev-quick-odd-sum` (registered before this run)
- Conditions: strict baseline and pipeline-labeled Quick engine wrapper (fixed one-answer path)
- Model/effort: GPT-5.6 Terra, medium
- One replicate; two-call and 600-second manifest caps
- Session usage polling was disabled per the standing instruction.

## Outcome

| Condition | Provider calls | Wall seconds | Protocol result | Blind semantic grade |
|---|---:|---:|---|---:|
| Baseline | 1 | 34.83 | Schema rejection | 10/10 |
| Pipeline | 1 | 19.97 | Complete, valid | 10/10 |

Astra graded both frozen, condition-blind packets 10/10. Both captured answers contain a valid induction proof. The baseline's provider response failed the strict output schema (`claims[2].discharged_by_step_ids` did not cover every proof step), while the pipeline output passed. This preserves the distinction between answer quality and protocol validity.

The paired semantic score delta is zero, with both answers at the ceiling. A baseline schema failure makes the matched latency ratio unavailable. Quick `pipeline` runs use the fixed one-answer engine wrapper; they do not execute the multi-stage Deep/Research pipeline. This case shows a protocol outcome difference between runners, not a general semantic, reliability, or efficiency effect. Token counts and costs are unknown.

## Failed first launch

`development-live-v7-quick` is preserved as an unusable attempt. The provider could not initialize its Codex state database in the sandbox, and the pipeline worker directory hit Windows access denied. The escalated v8 run resolved the provider-state restriction; its pipeline trial completed.

## Decision

Do not start the held-out comparison from this result. The development evidence still lacks complete assessable Deep pairs in the latest schedule, shows a baseline schema failure, and contains only one new Quick case. The held-out Quick triangular-sum case is registered with separate truth and a finite certificate check; it remains unrun.

## Astra review

Astra confirmed that both proofs are strong and that this `n=1` comparison cannot establish live effectiveness or a general latency advantage. Astra reviewed the mixed-corpus resume guard and found that a selected set with no eligible cases could silently run zero trials. The CLI now requires at least one selected, per-case-scheduled trial for every single-condition resume; the Quick-specific guard also prevents unsupported arms from being assigned to Quick cases.
