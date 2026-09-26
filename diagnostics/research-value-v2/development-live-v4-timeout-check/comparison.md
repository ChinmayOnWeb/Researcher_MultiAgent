# Research evaluation comparison

Status: incomplete; completion: 0.16666666666666666
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Missing grades | Mean score / 10 | Critical failures |
|---|---:|---:|---:|---:|
| pipeline | 0 | 6 | unknown | 0 |

Matched assessable pairs: 0 / 0; mean score difference: None.
Baseline ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': None, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Acceptance rate |
|---|---:|---:|---:|---:|---:|
| pipeline | 1 | 1 | 0 | 0 | 100.0% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| pipeline | {'supported_within_scope': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Launches observed |
|---|---:|---:|---:|---:|---:|
| pipeline | 1 | 0 | 0 | 0 | 1 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| pipeline | 8 | 0 | 217.68700000000536 | unknown | unknown | unknown |

## Budget-matched architecture comparisons

| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=0, unmatched/incomplete=0, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Grades require an identified reviewer, reasons tied to proof steps or errors, and the frozen artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
