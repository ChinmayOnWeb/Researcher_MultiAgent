# Research evaluation comparison

Status: incomplete; completion: 0.2777777777777778
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Missing grades | Mean score / 10 | Critical failures |
|---|---:|---:|---:|---:|
| baseline | 0 | 6 | unknown | 0 |
| sequential_review | 0 | 6 | unknown | 0 |
| pipeline | 0 | 6 | unknown | 0 |

Matched assessable pairs: 0 / 6; mean score difference: None.
Baseline ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': None, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Acceptance rate |
|---|---:|---:|---:|---:|---:|
| baseline | 2 | 1 | 1 | 0 | 50.0% |
| sequential_review | 2 | 2 | 0 | 0 | 100.0% |
| pipeline | 3 | 2 | 0 | 1 | 100.0% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | {'answered': 2} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| sequential_review | {'supported_within_scope': 2} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| pipeline | {'awaiting_human': 1, 'inconclusive': 1, 'supported_within_scope': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Launches observed |
|---|---:|---:|---:|---:|---:|
| baseline | 1 | 1 | 0 | 0 | 2 |
| sequential_review | 2 | 0 | 0 | 0 | 2 |
| pipeline | 2 | 1 | 0 | 0 | 3 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 2 | 0 | 53.110000000015134 | unknown | unknown | unknown |
| sequential_review | 9 | 0 | 177.14000000001397 | unknown | unknown | unknown |
| pipeline | 16 | 1 | 389.98399999999674 | unknown | unknown | unknown |

## Budget-matched architecture comparisons

| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 2 | 0 | unknown | 2 / 53.110000000015134 | 9 / 177.14000000001397 |
| baseline | pipeline | 2 | 0 | unknown | 2 / 53.110000000015134 | 16 / 389.98399999999674 |
| sequential_review | pipeline | 2 | 0 | unknown | 9 / 177.14000000001397 | 16 / 389.98399999999674 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=2, unmatched/incomplete=4, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Grades require an identified reviewer, reasons tied to proof steps or errors, and the frozen artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
