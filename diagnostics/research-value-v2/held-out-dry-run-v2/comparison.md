# Research evaluation comparison

Status: incomplete; completion: 0.0
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Missing grades | Mean score / 10 | Critical failures |
|---|---:|---:|---:|---:|
| baseline | 0 | 18 | unknown | 0 |
| sequential_review | 0 | 18 | unknown | 0 |
| pipeline | 0 | 18 | unknown | 0 |

Matched assessable pairs: 0 / 18; mean score difference: None.
Baseline ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': None, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Acceptance rate |
|---|---:|---:|---:|---:|---:|
| baseline | 0 | 0 | 0 | 0 | unknown |
| sequential_review | 0 | 0 | 0 | 0 | unknown |
| pipeline | 0 | 0 | 0 | 0 | unknown |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | none recorded | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| sequential_review | none recorded | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| pipeline | none recorded | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Launches observed |
|---|---:|---:|---:|---:|---:|
| baseline | 0 | 0 | 0 | 0 | 0 |
| sequential_review | 0 | 0 | 0 | 0 | 0 |
| pipeline | 0 | 0 | 0 | 0 | 0 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 0 | 0 | unknown | unknown | unknown |
| sequential_review | 0 | 0 | 0 | unknown | unknown | unknown |
| pipeline | 0 | 0 | 0 | unknown | unknown | unknown |

## Budget-matched architecture comparisons

| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 0 | 0 | unknown | 0 / 0 | 0 / 0 |
| baseline | pipeline | 0 | 0 | unknown | 0 / 0 | 0 / 0 |
| sequential_review | pipeline | 0 | 0 | unknown | 0 / 0 | 0 / 0 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=0, unmatched/incomplete=18, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Grades require an identified reviewer, reasons tied to proof steps or errors, and the frozen artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
