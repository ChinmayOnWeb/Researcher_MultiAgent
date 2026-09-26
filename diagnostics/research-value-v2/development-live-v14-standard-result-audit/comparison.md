# Research evaluation comparison

Status: incomplete
Primary comparison: pipeline versus baseline.
Scheduled trial records: 3 / 3.
Protocol-complete trial rate: 0.0 of scheduled trials.
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Unavailable | Missing grades | Mean score / 10 | Critical-failure labels |
|---|---:|---:|---:|---:|---:|
| baseline | 0 | 0 | 1 | unknown | 0 |
| sequential_review | 0 | 0 | 1 | unknown | 0 |
| pipeline | 0 | 0 | 1 | unknown | 0 |

Matched assessable pairs: 0 / 1; mean score difference: None.
Reference ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 0, 'mean_comparison_delta_at_ceiling': None, 'mean_pipeline_delta_at_ceiling': None, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Assessable | Acceptance (valid/assessable) |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1 | 0 | 0 | 1 | 0 | unknown |
| sequential_review | 1 | 0 | 1 | 0 | 1 | 0.0% |
| pipeline | 1 | 0 | 1 | 0 | 1 | 0.0% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | none recorded | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| sequential_review | {'unverified': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| pipeline | {'unverified': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Provider calls |
|---|---:|---:|---:|---:|---:|
| baseline | 0 | 1 | 0 | 0 | 1 |
| sequential_review | 0 | 1 | 0 | 0 | 1 |
| pipeline | 0 | 1 | 0 | 0 | 1 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1 | 0 | 2.437999999965541 | unknown | unknown | unknown |
| sequential_review | 1 | 0 | 0.4369999999762513 | unknown | unknown | unknown |
| pipeline | 1 | 0 | 0.46799999999348074 | unknown | unknown | unknown |

## Paired architecture comparisons

The strict baseline uses one call. Quick pipeline trials also have a one-call cap, matching baseline. Deep and Research review arms can use larger per-trial call and wall caps; actual calls and time are shown below.
No Quick wrapper rows are included.
Condition-specific tool capabilities differ for: none.
| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 1 | 0 | unknown | 1 / 2.437999999965541 | 1 / 0.4369999999762513 |
| baseline | pipeline | 1 | 0 | unknown | 1 / 2.437999999965541 | 1 / 0.46799999999348074 |
| sequential_review | pipeline | 1 | 0 | unknown | 1 / 0.4369999999762513 | 1 / 0.46799999999348074 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=1, capability-mismatch=0, source-mismatch=0, unmatched/incomplete=0, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Semantic grades distinguish unavailable answers from incorrect answers and retain the reviewed artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
