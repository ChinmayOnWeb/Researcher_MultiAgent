# v19 live retry notes

One fresh paired retry was scheduled for `dev-flawed-proof-sqrt2` with GPT-5.6 Terra, medium effort, and the v18 ceiling of 9 reserved provider calls / 600 seconds. The evaluation ended incomplete with no grades.

- Baseline: one provider call completed and produced a readable answer candidate. The trial was recorded as failed; protocol validity is unavailable.
- Pipeline: one provider call completed and its attempt result and event were persisted. Local result materialization then raised `KeyError: 'action_id'` before the action finished. The trial was marked ambiguous and was not relaunched.
- The machine comparison reports zero pipeline calls because the runner raised before returning its call count. The durable pipeline state records one model call, so two provider calls actually completed across both arms.
- Observed wall time was 73.516 seconds. Token and cost totals are unavailable. Session usage monitoring was disabled for the run.

This is an infrastructure-failed retry, not a valid baseline-versus-pipeline quality comparison. Preserve it as a failed run; do not treat its comparison scores or provider availability counts as results.
