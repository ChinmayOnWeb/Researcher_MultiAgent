# Development Deep architecture comparison v12

## Setup

- Six Deep development cases: finite subset enumeration, rational-expression domain, a universal-claim counterexample, a conflicting-record amendment, a flawed irrationality proof, and cross-record shipment inference.
- Conditions: strict one-call baseline, sequential review, and full pipeline.
- Model/effort: GPT-5.6 Terra, medium; one replicate per case.
- Frozen cap: 102 provider calls and 12,060 seconds. Actual use: 66 calls and 1,850.91 seconds.
- One Quick wrapper case was excluded because the 7-case schedule projected 104 calls. Quick wrapper evidence remains in v8–v10.
- No quota-remaining percentages were requested or polled. Token and cost totals remain unknown.

## Results

| Condition | Assessable mean score | Valid schemas | Provider calls | Wall seconds |
|---|---:|---:|---:|---:|
| Strict baseline | 9.33 / 10 | 6 / 6 | 6 | 160.08 |
| Sequential review | 10 / 10 | 6 / 6 | 19 | 507.89 |
| Full pipeline | 10 / 10 | 5 / 6 | 41 | 1,182.03 |

Astra blind-graded all 18 frozen packets. All grades passed packet and artifact integrity checks. The full-pipeline arm had one schema rejection on the flawed-proof case; its captured answer was still semantically gradable. Baseline had one critical cross-record linkage error on the shipment case, scoring 6/10; both review arms explicitly qualified that missing linkage and scored 10/10. The other cases scored 10/10 in all three arms.

One case (`dev-rational-domain-2`) gave math-check capability to review arms but not the strict baseline. After Astra confirmed this changes the available action space, the evaluator excluded it from equal-input paired quality and latency summaries while retaining it in descriptive per-arm results. The fair comparison therefore has five pairs: both review arms average +0.8 points over baseline; full pipeline and sequential review tie at 0 points difference. The mismatch case is separately disclosed in the comparison report.

## Interpretation and limits

This is a small, one-replicate development pilot, not a general efficacy finding. It suggests review can catch an evidence-linkage assumption that the one-call baseline missed. The extra full pipeline did not improve on sequential review in these five equal-capability pairs: both scored identically, while the pipeline used 41 versus 19 calls and 1,182 versus 508 seconds. The pipeline also had lower schema acceptance (5/6 versus 6/6). The evaluator's quality gate is descriptive here and does not override those resource and sample limitations.

Do not run held-out evaluation from this result alone. The next useful work is to diagnose the pipeline schema rejection, harmonize capability policies for future paired comparisons, then run a preregistered multi-replicate development calibration before considering held-out cases.
