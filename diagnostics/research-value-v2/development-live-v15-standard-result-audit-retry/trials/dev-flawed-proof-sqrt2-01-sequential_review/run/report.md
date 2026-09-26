# Research report

## Original question

```
A proof claims that sqrt(2) is rational: write sqrt(2)=a/b in lowest terms, square to get a^2=2b^2, and conclude that a and b are both even. Is the proof valid? Assess the conclusion and justify your answer.
```

## Explicit goal

```
Not specified
```

## Status

- Investigation status: **complete**
- Answer status: **inconclusive**
- Provenance status: **valid**
- Semantic status: **issues_found**
- Computation status: **not_performed**

## Answer

Candidate argument remains conditional or unresolved; no formal verification was performed.

> No. The claimed conclusion is false: √2 is irrational. The outlined argument becomes valid only after justifying that an integer with even square is even; then a lowest-terms representation would force both numerator and denominator to be divisible by 2, a contradiction.

## What was established

### Claim `claim-rational-assumption`: conditional

> Assume, for contradiction, that √2 is rational.

Assumption supplied by the Draft:

Reasons: `audit_conditional`.

### Claim `claim-lowest-terms`: model_reviewed_derivation

> Under the temporary assumption, there are integers a,b with b ≠ 0, √2 = a/b, and gcd(a,b)=1.

Checked step `step-lowest-terms`: > Choose integers a,b with b ≠ 0, √2 = a/b, and gcd(a,b)=1.

Reasons: `dependency_claim-rational-assumption_conditional`.

### Claim `claim-both-even`: model_reviewed_derivation

> The integers a and b are both even.

Checked step `step-a-even`: > a is even.

Checked step `step-b-even`: > b is even.

### Claim `claim-irrational`: model_reviewed_derivation

> √2 is irrational.

Checked step `step-contradiction`: > The temporary assumption that √2 is rational is false; therefore √2 is irrational.

Reasons: `dependency_claim-rational-assumption_conditional`.

## Approaches attempted

No branch approach was completed.

## Critique and revisions

- Claim `claim-rational-assumption`: outcome **survives**.
> Check whether the temporary rationality assumption is used outside its reductio scope or left undis­charged.
> Its scope lists every proof step that uses it, and step-contradiction explicitly closes the subproof by deriving a contradiction.

- Claim `claim-lowest-terms`: outcome **survives**.
> Check the reduced-fraction theorem's hypothesis and whether it supplies all stated properties.
> Under the temporary assumption that √2 is rational, the named theorem supplies integers a,b with b ≠ 0, √2=a/b, and gcd(a,b)=1, exactly as used.

- Claim `claim-both-even`: outcome **survives**.
> Check the parity inference, including the division used to obtain b²=2m².
> From a²=2b², a² is even. The explicit odd-square calculation gives a even; writing a=2m yields 4m²=2b², hence b²=2m², and the same odd-square argument gives b even. Division is by 2, not by zero.

- Claim `claim-irrational`: outcome **survives**.
> Check that the contradiction actually refutes rationality rather than merely the selected representation.
> The reduced-fraction theorem applies to every rational value and produces a coprime representation. Showing both a and b divisible by 2 contradicts that required coprimality, so the rationality assumption is discharged.

Revision log:
- > Retained the audited reductio argument but made the parity implication explicit for both a and b.
- > Named and explicitly applied the reduced-fraction representation theorem, including its hypothesis.
- > Recorded the rationality assumption as local and its discharge at the contradiction step.
- > No audit objection remains unresolved; no external sources or computational checks were supplied or used.

## Executed checks

No broker check or source-fetch receipt was recorded.

## Evidence

No source records were supplied or captured.

## Remaining uncertainty and useful next work

> critical_proof_steps_not_covered
> unmet obligation: critical_proof_steps_not_covered
> Expected new evidence: a revised proof addressing these audit findings.

## Run disclosure

- Requested model: `gpt-5.6-terra`
- Requested reasoning effort: `medium`
- Observed models: `gpt-5.6-terra`
- Observed reasoning effort: `medium`
- Provider attempt intents: 4
- Model calls: 4
- Historical v3 action-based call count: 0
- Tool calls: 0
- Observed local session ID markers: 4
- Session ID markers are supplemental local telemetry, not billing totals.
- Wall time: 138596 ms
- Summed child duration: 137983 ms
- Formal verification: not performed
- Input bytes: 66137
- Output bytes: 87245
- Input tokens: unknown
- Output tokens: unknown
- Reasoning tokens: unknown
- Recorded cost: unknown
