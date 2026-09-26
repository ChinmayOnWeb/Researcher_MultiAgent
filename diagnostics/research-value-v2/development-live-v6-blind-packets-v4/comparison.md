# Research evaluation comparison

Status: complete
Primary comparison: pipeline versus baseline.
Scheduled trial records: 18 / 18.
Protocol-complete trial rate: 0.6111111111111112 of scheduled trials.
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Unavailable | Missing grades | Mean score / 10 | Critical-failure labels |
|---|---:|---:|---:|---:|---:|
| baseline | 6 | 0 | 0 | 9.833333333333334 | 0 |
| sequential_review | 6 | 0 | 0 | 10 | 0 |
| pipeline | 5 | 1 | 0 | 10 | 0 |

Matched assessable pairs: 5 / 6; mean score difference: 0.2.
Reference ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 4, 'mean_comparison_delta_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': 0, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Acceptance rate |
|---|---:|---:|---:|---:|---:|
| baseline | 6 | 3 | 3 | 0 | 50.0% |
| sequential_review | 6 | 5 | 1 | 0 | 83.3% |
| pipeline | 6 | 3 | 3 | 0 | 50.0% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | {'answered': 4, 'refuted': 2} | {'calibrated': 6, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| sequential_review | {'inconclusive': 2, 'supported_within_scope': 3, 'unverified': 1} | {'calibrated': 3, 'overcautious': 3, 'overconfident': 0, 'not_assessed': 0} |
| pipeline | {'inconclusive': 1, 'supported_within_scope': 2, 'unverified': 3} | {'calibrated': 2, 'overcautious': 3, 'overconfident': 0, 'not_assessed': 1} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Provider calls |
|---|---:|---:|---:|---:|---:|
| baseline | 3 | 3 | 0 | 0 | 6 |
| sequential_review | 5 | 1 | 0 | 0 | 16 |
| pipeline | 3 | 3 | 0 | 0 | 28 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 6 | 0 | 190.93700000003446 | unknown | unknown | unknown |
| sequential_review | 16 | 0 | 386.2190000000119 | unknown | unknown | unknown |
| pipeline | 28 | 2 | 737.6090000000258 | unknown | unknown | unknown |

## Paired architecture comparisons

These comparisons are not equal-resource comparisons. The strict baseline uses one call; review arms can use larger shared caps. Actual calls and time are shown below.
Condition-specific tool capabilities differ for: dev-rational-domain-2.
| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 6 | 6 | 0.16666666666666666 | 6 / 190.93700000003446 | 16 / 386.2190000000119 |
| baseline | pipeline | 6 | 5 | 0.2 | 6 / 190.93700000003446 | 28 / 737.6090000000258 |
| sequential_review | pipeline | 6 | 5 | 0 | 16 / 386.2190000000119 | 28 / 737.6090000000258 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=6, unmatched/incomplete=0, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Semantic grades distinguish unavailable answers from incorrect answers and retain the reviewed artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
