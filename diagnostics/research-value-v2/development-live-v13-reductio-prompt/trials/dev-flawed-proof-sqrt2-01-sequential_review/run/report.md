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

> No. The calculation does not prove that sqrt(2) is rational; it produces a contradiction from rationality. With the justified choice of a lowest-denominator representation below, the contradiction proves that sqrt(2) is irrational. The original presentation was incomplete unless it supplied the reduction-to-lowest-terms justification.

## What was established

### Claim `rational-definition`: model_reviewed_derivation

> A real number is rational if it equals p/q for integers p,q with q nonzero; it is irrational if it is not rational.

Checked step `step-rational-definition`: > A number is rational exactly when it is p/q for integers p,q with q nonzero; irrational means not rational.

### Claim `assume-rational`: conditional

> Assume temporarily that sqrt(2) is rational.

Assumption supplied by the Draft:

### Claim `denominator-set`: model_reviewed_derivation

> There is a nonempty set S of positive integers that occur as denominators in integer representations sqrt(2)=a/b.

Checked step `step-denominator-set`: > Let S be the set of positive integers n for which sqrt(2)=m/n for some integer m; then S is nonempty.

Reasons: `dependency_assume-rational_conditional`.

### Claim `minimal-denominator`: model_reviewed_derivation

> There are integers a and b with b positive, sqrt(2)=a/b, and b least among the positive denominators in S.

Checked step `step-minimal-denominator`: > Choose b least in S and an integer a such that b>0 and sqrt(2)=a/b.

### Claim `lowest-terms`: model_reviewed_derivation

> The selected integers a and b have no common positive divisor greater than 1.

Checked step `step-lowest-terms`: > a and b have no common positive divisor greater than 1.

### Claim `square-equation`: unverified

> a^2=2b^2.

Checked step `step-square`: > a^2=2b^2.

Reasons: `audit_unsupported`.

### Claim `parity-dichotomy`: model_reviewed_derivation

> Every integer is even or odd in the form 2k or 2k+1.

Checked step `step-a-even`: > There is an integer c such that a=2c.

Checked step `step-b-even`: > b is even.

### Claim `a-even`: conditional

> There is an integer c such that a=2c.

Checked step `step-a-even`: > There is an integer c such that a=2c.

Reasons: `audit_conditional`; `dependency_square-equation_unverified`.

### Claim `b-square-even`: conditional

> b^2=2c^2.

Checked step `step-substitute`: > b^2=2c^2.

Reasons: `audit_conditional`; `dependency_a-even_conditional`; `dependency_square-equation_unverified`.

### Claim `b-even`: conditional

> b is even.

Checked step `step-b-even`: > b is even.

Reasons: `audit_conditional`; `dependency_b-square-even_conditional`.

### Claim `sqrt2-irrational`: conditional

> sqrt(2) is irrational.

Checked step `step-contradiction`: > The temporary assumption that sqrt(2) is rational yields a contradiction; therefore sqrt(2) is irrational.

Reasons: `audit_conditional`; `counterexample_challenge_failed`; `dependency_assume-rational_conditional`; `dependency_a-even_conditional`; `dependency_b-even_conditional`.

## Approaches attempted

No branch approach was completed.

## Critique and revisions

- Claim `assume-rational`: outcome **survives**.
> The reductio must begin from the negation of “sqrt(2) is irrational,” and the temporary assumption must be discharged only after a contradiction is derived.
> By the stated definition, not irrational means rational. Every listed subproof step is within its scope, and step-contradiction derives the conflict and discharges it.

- Claim `sqrt2-irrational`: outcome **fails**.
> The conclusion requires both the contradiction and the defining fact that (sqrt(2))^2=2; otherwise squaring only yields (sqrt(2))^2=a^2/b^2.
> The contradiction from a common divisor is valid conditional on step-square, but step-square uses the uncited and unstated square-root defining property. Thus the unconditional conclusion is not fully established by the supplied self-contained steps.

Revision log:
- > Replaced the unjustified assumption of a lowest-terms representation with a least-positive-denominator construction.
- > Added explicit applications of the Well-Ordering Principle and Division Algorithm.
- > Scoped the temporary assumption as rationality alone and discharged it at the contradiction step.
- > Revised the conclusion: the argument refutes rationality rather than proves it.
- > No computational checks are proposed.

## Executed checks

No broker check or source-fetch receipt was recorded.

## Evidence

No source records were supplied or captured.

## Remaining uncertainty and useful next work

> A stated definition or derivation that (sqrt(2))^2=2 is needed for step-square and hence for the unconditional irrationality conclusion.
> critical_proof_steps_not_covered
> unmet obligation: A derivation, or an explicitly named and correctly applied standard result, that if sqrt(2) is rational then it has an integer representation a/b with b nonzero and no common factor greater than 1.
> unmet obligation: critical_proof_steps_not_covered
> Expected new evidence: a revised proof addressing these audit findings.

## Run disclosure

- Requested model: `gpt-5.6-terra`
- Requested reasoning effort: `medium`
- Observed models: `gpt-5.6-terra`
- Observed reasoning effort: `medium`
- Provider attempt intents: 5
- Model calls: 5
- Historical v3 action-based call count: 0
- Tool calls: 0
- Observed local session ID markers: 5
- Session ID markers are supplemental local telemetry, not billing totals.
- Wall time: 204647 ms
- Summed child duration: 203967 ms
- Formal verification: not performed
- Input bytes: 90077
- Output bytes: 131959
- Input tokens: unknown
- Output tokens: unknown
- Reasoning tokens: unknown
- Recorded cost: unknown
