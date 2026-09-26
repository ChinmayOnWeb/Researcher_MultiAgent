# Quick-path three-replicate diagnostic v9

## Setup

- Case: `dev-quick-odd-sum`
- Conditions: strict single-call baseline and pipeline-labeled Quick engine wrapper (fixed one-answer path)
- Model/effort: GPT-5.6 Terra, medium
- Three replicates per condition; six-call and 1,800-second manifest caps
- Session usage polling was disabled per the standing instruction.

## Outcome

| Condition | Valid schema outputs | Attempts | Provider calls | Trial wall seconds | Mean semantic score |
|---|---:|---:|---:|---:|---:|
| Baseline | 2 | 3 | 3 | 54.17 | 10/10 |
| Pipeline | 3 | 3 | 3 | 56.98 | 10/10 |

Astra blind-graded all six outputs 10/10. Each replicate has a zero-point semantic difference. Baseline schema acceptance was 2/3; pipeline acceptance was 3/3. One baseline response was rejected because its standard-result claim lacked application steps. Both conditions used one provider call per trial. The median of the two complete pairs' pipeline/baseline latency ratios was 1.19×; pipeline used about 2.8 more trial seconds in aggregate. Cost and token totals are unknown.

## Interpretation

This single elementary proof family shows a possible protocol-reliability difference between the direct baseline runner and the fixed one-answer engine wrapper, with no semantic score gain and a small latency cost. The Quick arm does not run the multi-stage Deep/Research pipeline. Three replicates cannot establish reliability across proof styles, a general efficiency result, or research value. The score is at ceiling. The evaluator marks one baseline replicate failed, so only two replicates completed both protocols.

Do not start held-out trials yet. The broader development comparison has not cleared its Deep-pair coverage and quality gates. Next, diagnose the baseline output-schema failures and run a development-only, diverse Deep comparison that fits the already authorized resource envelope before reconsidering held-out evaluation.
