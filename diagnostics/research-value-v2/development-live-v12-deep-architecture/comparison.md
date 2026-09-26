# Research evaluation comparison

Status: complete
Primary comparison: pipeline versus baseline.
Scheduled trial records: 18 / 18.
Protocol-complete trial rate: 0.9444444444444444 of scheduled trials.
Quality gate passed: True
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Unavailable | Missing grades | Mean score / 10 | Critical-failure labels |
|---|---:|---:|---:|---:|---:|
| baseline | 6 | 0 | 0 | 9.333333333333334 | 1 |
| sequential_review | 6 | 0 | 0 | 10 | 0 |
| pipeline | 6 | 0 | 0 | 10 | 0 |

Matched assessable pairs: 5 / 5; mean score difference: 0.8.
Reference ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 4, 'mean_comparison_delta_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': 0, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Assessable | Acceptance (valid/assessable) |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 6 | 6 | 0 | 0 | 6 | 100.0% |
| sequential_review | 6 | 6 | 0 | 0 | 6 | 100.0% |
| pipeline | 6 | 5 | 1 | 0 | 6 | 83.3% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | {'answered': 5, 'refuted': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 6} |
| sequential_review | {'inconclusive': 3, 'supported_within_scope': 3} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 6} |
| pipeline | {'inconclusive': 3, 'refuted': 1, 'supported_within_scope': 1, 'unverified': 1} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 6} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Provider calls |
|---|---:|---:|---:|---:|---:|
| baseline | 6 | 0 | 0 | 0 | 6 |
| sequential_review | 6 | 0 | 0 | 0 | 19 |
| pipeline | 5 | 1 | 0 | 0 | 41 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 6 | 0 | 160.07800000003772 | unknown | unknown | unknown |
| sequential_review | 19 | 0 | 507.8890000000247 | unknown | unknown | unknown |
| pipeline | 41 | 2 | 1182.0320000000065 | unknown | unknown | unknown |

## Paired architecture comparisons

The strict baseline uses one call. Quick pipeline trials also have a one-call cap, matching baseline. Deep and Research review arms can use larger per-trial call and wall caps; actual calls and time are shown below.
No Quick wrapper rows are included.
Condition-specific tool capabilities differ for: dev-rational-domain-2.
| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 5 | 5 | 0.8 | 6 / 160.07800000003772 | 19 / 507.8890000000247 |
| baseline | pipeline | 5 | 5 | 0.8 | 6 / 160.07800000003772 | 41 / 1182.0320000000065 |
| sequential_review | pipeline | 6 | 6 | 0 | 19 / 507.8890000000247 | 41 / 1182.0320000000065 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=5, capability-mismatch=1, source-mismatch=0, unmatched/incomplete=0, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Semantic grades distinguish unavailable answers from incorrect answers and retain the reviewed artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
