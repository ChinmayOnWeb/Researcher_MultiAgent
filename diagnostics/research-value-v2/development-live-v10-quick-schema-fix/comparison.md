# Research evaluation comparison

Status: complete
Primary comparison: pipeline versus baseline.
Scheduled trial records: 6 / 6.
Protocol-complete trial rate: 0.5 of scheduled trials.
Quality gate passed: False
Legacy policy: legacy_pilot_thresholds_v1

## Semantic quality

| Condition | Assessable outputs | Unavailable | Missing grades | Mean score / 10 | Critical-failure labels |
|---|---:|---:|---:|---:|---:|
| baseline | 3 | 0 | 0 | 10 | 0 |
| sequential_review | 0 | 0 | 0 | unknown | 0 |
| pipeline | 3 | 0 | 0 | 10 | 0 |

Matched assessable pairs: 3 / 3; mean score difference: 0.
Reference ceiling effect: {'maximum_score': 10, 'pairs_at_ceiling': 3, 'mean_comparison_delta_at_ceiling': 0, 'mean_pipeline_delta_at_ceiling': 0, 'gain_demonstrated_at_ceiling': False}

## Schema acceptance

| Condition | Attempts | Valid | Invalid | Unavailable | Assessable | Acceptance (valid/assessable) |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 3 | 2 | 1 | 0 | 3 | 66.7% |
| sequential_review | 0 | 0 | 0 | 0 | 0 | unknown |
| pipeline | 3 | 1 | 0 | 2 | 1 | 100.0% |

## Terminal status calibration

| Condition | Final statuses | Calibration judgments |
|---|---|---|
| baseline | {'answered': 3} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 3} |
| sequential_review | none recorded | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 0} |
| pipeline | {'unverified': 3} | {'calibrated': 0, 'overcautious': 0, 'overconfident': 0, 'not_assessed': 3} |

## Provider availability

| Condition | Complete | Failed | Ambiguous | Usage limits | Provider calls |
|---|---:|---:|---:|---:|---:|
| baseline | 2 | 1 | 0 | 0 | 3 |
| sequential_review | 0 | 0 | 0 | 0 | 0 |
| pipeline | 1 | 2 | 0 | 0 | 3 |

## Resource use

| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 3 | 0 | 82.56299999996554 | unknown | unknown | unknown |
| sequential_review | 0 | 0 | 0 | unknown | unknown | unknown |
| pipeline | 3 | 0 | 77.76500000001397 | unknown | unknown | unknown |

## Paired architecture comparisons

The strict baseline uses one call. Quick pipeline trials also have a one-call cap, matching baseline. Deep and Research review arms can use larger per-trial call and wall caps; actual calls and time are shown below.
Quick `pipeline` rows use the fixed one-answer Quick engine wrapper; they do not run the multi-stage Deep/Research pipeline. Treat those rows as product-path protocol controls, not full-pipeline effectiveness evidence. Affected cases: dev-quick-odd-sum.
Condition-specific tool capabilities differ for: none.
| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | sequential_review | 0 | 0 | unknown | 3 / 82.56299999996554 | 0 / 0 |
| baseline | pipeline | 3 | 3 | 0 | 3 / 82.56299999996554 | 3 / 77.76500000001397 |
| sequential_review | pipeline | 0 | 0 | unknown | 0 / 0 | 3 / 77.76500000001397 |

Recoveries are separate and excluded from contemporaneous first-attempt pairs.
Recovery resources by condition: {'baseline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'sequential_review': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}, 'pipeline': {'attempts': 0, 'complete': 0, 'failed': 0, 'ambiguous': 0, 'provider_calls': 0, 'wall_seconds': 0}}
Pair reconciliation: equal-input=3, capability-mismatch=0, source-mismatch=0, unmatched/incomplete=0, temporally recovered=0, quota-truncated=0.
Small sample disclosure: Small sample: estimates are descriptive and do not establish a general effect.
Session IDs are supplemental telemetry, not billing totals.
Semantic grades distinguish unavailable answers from incorrect answers and retain the reviewed artifact hash. Alternative valid proofs are acceptable. Process completion is not a semantic grade.
