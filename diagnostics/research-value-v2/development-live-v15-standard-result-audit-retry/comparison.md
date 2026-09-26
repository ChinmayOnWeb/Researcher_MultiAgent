# Research evaluation comparison

Status: complete
Primary comparison: pipeline versus baseline.
Scheduled trial records: 3 / 3.
Protocol-complete trial rate: 0.3333333333333333 of scheduled trials.
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Unavailable | Missing grades | Mean score / 10 | Critical-failure labels |
|---|---:|---:|---:|---:|---:|
| baseline | 1 | 0 | 0 | 10 | 0 |
| sequential_review | 1 | 0 | 0 | 10 | 0 |
| pipeline | 1 | 0 | 0 | 10 | 0 |

Matched assessable pairs: 1 / 1; mean score difference: 0.
Reference ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 1, 'mean_comparison_delta_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': 0, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Assessable | Acceptance (valid/assessable) |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1 | 0 | 1 | 0 | 1 | 0.0% |
| sequential_review | 1 | 1 | 0 | 0 | 1 | 100.0% |
| pipeline | 1 | 0 | 1 | 0 | 1 | 0.0% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | {'answered': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 1} |
| sequential_review | {'inconclusive': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 1} |
| pipeline | {'unverified': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 1} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Provider calls |
|---|---:|---:|---:|---:|---:|
| baseline | 0 | 1 | 0 | 0 | 1 |
| sequential_review | 1 | 0 | 0 | 0 | 4 |
| pipeline | 0 | 1 | 0 | 0 | 3 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1 | 0 | 36.71900000004098 | unknown | unknown | unknown |
| sequential_review | 4 | 0 | 138.65600000001723 | unknown | unknown | unknown |
| pipeline | 3 | 0 | 90.15599999995902 | unknown | unknown | unknown |

## Paired architecture comparisons

The strict baseline uses one call. Quick pipeline trials also have a one-call cap, matching baseline. Deep and Research review arms can use larger per-trial call and wall caps; actual calls and time are shown below.
No Quick wrapper rows are included.
Condition-specific tool capabilities differ for: none.
| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 1 | 1 | 0 | 1 / 36.71900000004098 | 4 / 138.65600000001723 |
| baseline | pipeline | 1 | 1 | 0 | 1 / 36.71900000004098 | 3 / 90.15599999995902 |
| sequential_review | pipeline | 1 | 1 | 0 | 4 / 138.65600000001723 | 3 / 90.15599999995902 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=1, capability-mismatch=0, source-mismatch=0, unmatched/incomplete=0, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Semantic grades distinguish unavailable answers from incorrect answers and retain the reviewed artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
