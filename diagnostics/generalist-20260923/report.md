# Generalist diagnostic: graph count and false-note perturbation

Run: `runs/generalist-diagnostic-20260923` (2026-09-23). Model: `gpt-5.6-terra`, medium. One replicate, two paired cases, maximum 24 reserved provider calls and 2,400 wall seconds. The comparison runner reserved 18 calls and finished in 469 wall seconds. This was a diagnostic, not a statistical estimate of general performance.

## Ground truth and isolation

The answer is **10**. Two independent local calculations were completed before any model calls: enumerating all `C(10,4)=210` four-subsets and testing every pair, and a bitmask recursion that branches on inclusion/exclusion while rejecting adjacent vertices. Both returned 10. A short human proof: even and odd vertices each form an independent class of five; across classes, a vertex has only its antipode as a nonneighbor. Thus a mixed independent set has size at most two, and the four-sets are precisely the two disjoint families of `C(5,4)=5`.

The correct answer and grading obligations were stored only in evaluator fields and this rubric. Inspection of all 12 pipeline action packets, the two pipeline requests, and the baseline prompt construction found no `expected_obligations`, `forbidden_claims`, rubric wording, or hidden count string. The false value **12** appeared in the second worker's supplied synthetic note by design. This check establishes no observed evaluator-to-worker leakage in this run; it does not prove leakage is impossible elsewhere.

## Results

| Case | Condition | Answer and proof | Note handling | Reported calls | Observed Codex sessions | Wall time |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Clean graph | Single-call baseline | Correct 10, complete parity proof | N/A | 1 | 1 | 21.9 s |
| Clean graph | Pipeline | Correct 10, complete parity proof | N/A | 5 | 6 | 145.5 s |
| False note | Single-call baseline | Correct 10, complete circular-gap proof | Rejects 12 | 1 | 1 | 42.6 s |
| False note | Pipeline | Correct 10, complete parity proof; terminal answer status `inconclusive` | Rejects 12 | 7 | 8 | 258.8 s |

The baseline circular-gap proof is valid: the only possible consecutive gaps are a permutation of `(4,2,2,2)`, and all pairwise differences in such a set are even. Its rooted count `10*4/4=10` accounts for duplication. Both pipeline proofs also classify every independent four-set exactly once. Neither pipeline run executed a computational check, because the evaluation cases use `checks: []` and the CLI explicitly tells workers not to propose checks. Thus all proof reviews here are model reviews, not independent verification.

## Defects exposed

1. **Call accounting undercounts retries.** Each pipeline audit action (`a0005`) has two distinct Codex session IDs in its stderr log and one structural-repair marker, while the trial and comparison count that action as one call. The clean/false-note pipeline executions used 6/8 observed sessions rather than the reported 5/7. The comparison's `actual_provider_calls: 14` is the sum of action attempts; 16 Codex sessions are visible across all four trials. This matters for call caps and efficiency claims. A session log is evidence of a local Codex invocation; remote billing remains unknown.
2. **A source citation span can spoil the final status without spoiling the proof.** In the false-note pipeline, the first audit correctly caught an off-by-one citation end (`79` instead of `78`). The pipeline revised and audited again, but the final report still contains the invalid citation and marks the note assertion contradicted. This propagates to `Answer status: inconclusive` and conditional claim labels even though the mathematical answer is independently correct and the unsupported 12 is rejected. The repair did not close the cited defect.
3. **The extra stages added no demonstrated quality on this pair.** Both baselines were correct and complete in one call. The pipeline used 6 and 8 observed sessions and took 6.6 and 6.1 times as long, respectively. The second run's reported status is worse than its baseline's `answered` status. The comparison remains `incomplete` because independent semantic grades were not supplied; these are direct report observations, not a claim that the evaluator's quality gate passed or failed.

## Interpretation and next diagnostic

This clean/noisy pair shows no observed hidden-answer leak and no anchoring to an unsupported numerical note. It does show that the source/provenance machinery can dominate the final status and that retries escape call accounting. One graph-counting family cannot establish generality. The next matrix should span distinct proof styles (an algebraic identity with a subtle domain restriction, a small counterexample search, and a proof requiring a supplied source), with hidden truth, controlled false-note variants, independently checked answers, and exact session counts. Do not treat more calls as evidence of better research without paired quality gains.
