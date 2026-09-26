# Quick-path schema diagnostic v10

## Setup

- Case: `dev-quick-odd-sum`
- Conditions: strict one-call baseline and pipeline-labeled Quick engine wrapper
- Model/effort: GPT-5.6 Terra, medium
- Three replicates per condition; six-call and 1,800-second manifest caps
- Usage percentage polling was disabled per the standing instruction.

## Outcome

Six provider calls ran in 160.64 seconds. Two of three baseline outputs passed the result schema; one failed schema validation. One of three Quick engine-wrapper outputs completed; two failed during provider/protocol execution. Three trials completed and three failed, so the scheduled execution completion rate was 50%. Cost and token totals are unknown.

Astra's blind grades scored all six captured mathematical answers 10/10. All three matched pairs had zero semantic-score difference. This does not mean all six trials were valid: failed trials can still contain a gradable captured answer. No quality gain was demonstrated, and the evaluator's quality gate did not pass.

Observed protocol issues included a proof-step dependency pointing to a claim ID, which mixes identifier namespaces, and a discharge step outside the local-assumption scope. The latter can be valid when the discharge depends on the scoped steps, so the validator and prompt were subsequently revised to represent scope and discharge separately. The run itself used the earlier prompt/validator and is a pre-fix diagnostic. One output also contained control characters in displayed mathematical text.

## Interpretation

This was one elementary induction proof family, not evidence about the multi-stage Deep/Research workflow. In Quick mode, a `pipeline` label means the fixed one-answer engine wrapper; it does not invoke the multi-stage pipeline. The sample is too small and score is at ceiling. Keep held-out trials gated: the broader development evaluation has not established a quality gain or cleared its Deep-pair coverage requirements.

Next, validate the namespace and local-assumption fixes with focused checks, then run a diverse development-only Deep comparison under its already authorized resource envelope. Do not infer product-wide effectiveness from this Quick control.
