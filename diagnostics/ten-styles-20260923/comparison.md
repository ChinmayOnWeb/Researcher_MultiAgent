# Terra-medium comparison across ten proof styles

Date: 2026-09-23. One attempt per style. Requested model/effort were held at `gpt-5.6-terra` / `medium`. Cases cover induction, bijective counting, modular number theory, extremal graph theory, linear algebra, probability, improper integration, affine geometry, fixed-point counterexample/existence, and algorithm invariant/termination. The evaluator case file keeps expected obligations and forbidden claims outside worker packets; a scan of the saved pipeline packets found no rubric-field matches.

This is a small diagnostic, not a statistical performance estimate. All trial reports state that no formal verification or broker computation was performed. The mathematically sound/complete judgments below are Astra's review of the answers and structured outputs.

## Per-style comparison

| Proof style | Single-call baseline | Pipeline | Astra's assessment |
| --- | --- | --- | --- |
| Induction | Schema rejected; payload had correct base case and induction step | Correct complete proof; final status `inconclusive` | Pipeline status is too cautious: ordinary induction is an accepted proof principle, not an unresolved external claim. |
| Bijection | Correct, complete count 84 | Correct, complete; `inconclusive` | More detail, no material quality gain. |
| Number theory | Correct proof modulo 8 and 3, combined to 24 | Same proof quality; `inconclusive` | It treats elementary prime properties as unresolved dependencies. |
| Extremal graph | Schema rejected; payload's spanning-tree proof was sound | Correct longest-path proof; `inconclusive` | Valid alternative to the rubric's preferred spanning-tree route; status machinery mishandles accepted hypotheses. |
| Linear algebra | Correct multilinearity proof; covers zero vectors; determinant −2 | Equally correct; `supported_within_scope` | No quality gain shown. |
| Probability | Schema rejected; payload correctly derives expectation 6 and handles overlap | Correct derivation; `conditional` | Fairness and independence are premises of the question, but pipeline leaves them as unresolved conditions. |
| Calculus | Schema rejected; payload has correct integration by parts and boundary limit | Correct and complete; `supported_within_scope` | No quality gain shown. |
| Geometry | Provider returned usage-limit failure | Correct affine centroid proof; `inconclusive` | Proof is sound, but the report retains stale unsupported commentary. |
| Fixed point | Recovery baseline correct: identity refutes uniqueness; IVT proves existence | Provider returned usage-limit failure | No pipeline result to compare. |
| Euclidean algorithm | Recovery baseline correct: invariant, termination, gcd 18 | Provider returned usage-limit failure | No pipeline result to compare. |

## Execution, schema, and cost observations

- Baseline: 10 provider sessions across the ten cases; five reports completed and five trials failed. Four completed provider responses were rejected by schema validation for nonexistent dependency IDs (`base-case`, `ibp-epsilon`, `step-spanning-tree`, `state-def`). The geometry baseline hit the provider usage limit. The rejected payloads Astra reviewed contained sound mathematical arguments, but they remain product failures because the evaluator could not accept them.
- Pipeline: eight reports completed and two failed on provider usage limits. Of the eight completed reports, only the linear algebra and calculus reports were marked `supported_within_scope`; five were `inconclusive` and one `conditional`, despite Astra judging their main proofs sound. No completed case demonstrates correction of an incorrect baseline proof.
- Pipeline telemetry says seven calls for each completed case. Per-action logs show 7–9 distinct provider sessions. Across all ten pipeline attempts, telemetry counted 58 action calls while logs show 64 sessions. Combined with ten baseline sessions, the logs contain 74 sessions. This is local session evidence; billing/token totals are unavailable. Pipeline runs were roughly 2.3–4.1 minutes each, compared with about 22–40 seconds for completed baselines.
- The two pipeline usage-limit failures left the fixed-point and Euclidean-algorithm comparisons incomplete. Their single-call baselines were run afterward and completed. Those baseline recoveries do not erase the pipeline failures.
- The first unsandboxed launch failed before a provider call due local temporary-directory permissions and is excluded from the ten-style comparison. The later approved corpus was used. No quota was queried.

## Astra's prioritized fixes

1. **Correct final-status semantics.** Distinguish premises, discharged local assumptions, and standard proof principles from unresolved dependencies. Recompute status from the final revised draft and audit, and clear stale objections after repair.
2. **Repair dependency typing and validation.** Keep claim dependencies separate from proof-step references; validate each against its own namespace. Return a bounded repair opportunity instead of rejecting a sound answer over mismatched IDs.
3. **Make evaluation accounting reliable.** Record every provider session, retry, reservation, and recovery link. Separate usage-limit failures from schema failures and compare equal retry policies before drawing quality conclusions.

## Conclusion

This diagnostic found no demonstrated mathematical quality gain from the pipeline. It did find a large reliability difference in structured-output acceptance in the baseline, paired with overly cautious or stale terminal statuses in the pipeline. The pipeline used about six to nine times as many observed sessions per completed case and took several times longer. The two usage-limit failures and one replicate per style limit any broad conclusion.

See [the methodology addendum](methodology-addendum.md) for the scope limits and preserved schema-rejected payloads.
