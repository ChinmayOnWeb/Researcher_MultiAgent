# Standard-result and proof-structure retry v15

## Setup

- One Deep case: `dev-flawed-proof-sqrt2`; one replicate; strict baseline, sequential review, and full pipeline.
- GPT-5.6 Terra, medium effort; dry-run projection and frozen cap: 17 calls / 2,010 seconds. Actual use: 8 calls and 265.69 seconds.
- The v14 default-sandbox attempt is preserved separately; its worker temp-directory permissions prevented a usable comparison. V15 ran with elevated filesystem access.
- Astra blind-graded all three captured semantic answers from frozen packets. Protocol validity is reported separately from answer quality. Tokens and cost are unknown.

## Results

| Condition | Score / 10 | Schema accepted | Calls | Seconds |
|---|---:|---:|---:|---:|
| Strict baseline | 10 | no | 1 | 36.72 |
| Sequential review | 10 | yes | 4 | 138.66 |
| Full pipeline | 10 | no | 3 | 90.16 |

All three answers were semantically strong, so the matched quality delta was 0. The baseline failed because its dependent deduction omitted the reductio discharge step from `step_ids`. The pipeline failed because a non-local-assumption claim carried scope/discharge fields. These are protocol failures, not mathematical errors in the captured answers. The sequential arm was protocol-valid.

The one-case result does not show a quality gain from the pipeline. It also shows that the v4 prompt change did not fix structural reliability: schema acceptance was 0/1 for baseline and pipeline, and 1/1 for sequential review.

## Prompt follow-up

Prompt version 5 now states that only `local_assumption` claims may have nonempty scope/discharge arrays, and that the dependent reductio conclusion must include each discharge step in `step_ids`. It retains v4's standard-theorem guidance. The v5 prompt has passed offline prompt, contract, routing, and event tests; it has not been provider-tested.

## Limits and next work

This is a single development case with a ceiling-level baseline. Do not infer general architecture performance or start held-out evaluation from it. Next, improve and independently verify structured-output compliance offline, then run a fresh, counterbalanced development calibration with a frozen cap before considering held-out cases. No account usage percentages were polled.
