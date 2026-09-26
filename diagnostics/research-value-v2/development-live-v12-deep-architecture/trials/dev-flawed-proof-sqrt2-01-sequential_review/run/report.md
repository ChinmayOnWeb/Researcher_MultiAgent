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

> No. The conclusion that √2 is rational is false. The parity argument is a contradiction proof: if √2 were rational, choose a representation with least positive denominator; then a²=2b² forces both a and b even, producing a representation with a smaller positive denominator. Thus √2 is irrational. This revised draft supplies the previously missing reduction-to-lowest-terms argument via the well-ordering principle.

## What was established

### Claim `claim-rational-assumption`: conditional

> Assume, for contradiction, that √2 is rational.

Assumption supplied by the Draft:

### Claim `claim-integer-representation`: model_reviewed_derivation

> Under the temporary assumption, √2=a/b for some integers a,b with b>0.

Checked step `step-positive-denominator`: > There is at least one representation √2=a/b with integers a,b and b>0.

Reasons: `dependency_claim-rational-assumption_conditional`.

### Claim `claim-minimal-denominator`: model_reviewed_derivation

> Under the temporary assumption, choose integers a,b with b>0 and √2=a/b such that b is least among all positive integer denominators of representations of √2.

Checked step `step-minimal-denominator`: > Choose a representation √2=a/b whose positive denominator b is least.

### Claim `claim-square-equation`: model_reviewed_derivation

> For the selected integers, a²=2b².

Checked step `step-square-equation`: > a²=2b².

### Claim `claim-a-even`: model_reviewed_derivation

> For the selected integers, a is even.

Checked step `step-a-even`: > a=2k for some integer k.

### Claim `claim-b-square-even`: model_reviewed_derivation

> For the selected integers, b² is even.

Checked step `step-b-square-even`: > b² is even.

### Claim `claim-b-even`: model_reviewed_derivation

> For the selected integers, b is even.

Checked step `step-b-even`: > b=2l for some integer l.

### Claim `claim-irrational`: model_reviewed_derivation

> √2 is irrational.

Checked step `step-contradiction`: > √2 is irrational.

Reasons: `dependency_claim-rational-assumption_conditional`.

## Approaches attempted

No branch approach was completed.

## Critique and revisions

- Claim `claim-integer-representation`: outcome **survives**.
> A rational representation might have a negative denominator, so minimality over positive denominators could be unavailable.
> step-positive-denominator changes p/q to -p/-q when q<0, yielding b>0. Thus the set used later is nonempty.

- Claim `claim-minimal-denominator`: outcome **survives**.
> The least-denominator choice could improperly assume that every nonempty set of positive integers has a least member.
> step-minimal-denominator explicitly applies the well-ordering principle to the nonempty set of positive denominators. This is a valid application of the named standard result.

- Claim `claim-square-equation`: outcome **survives**.
> Squaring or clearing denominators might introduce an invalid division-by-zero step.
> The chosen denominator satisfies b>0, hence b² is nonzero. Squaring and multiplying by b² are valid.

- Claim `claim-a-even`: outcome **survives**.
> From a² even, it does not generally follow without proof that a is even.
> step-a-even supplies the needed contrapositive calculation: an odd integer 2k+1 has odd square.

- Claim `claim-b-square-even`: outcome **survives**.
> After substituting a=2k, cancellation by 2 might be unjustified.
> The equality 4k²=2b² is an integer equality; dividing both sides by the nonzero integer 2 yields b²=2k².

- Claim `claim-b-even`: outcome **survives**.
> The same parity inference for b could be an unproved repetition.
> step-b-even again gives the explicit odd-square calculation and contradicts the established evenness of b².

- Claim `claim-irrational`: outcome **survives**.
> Halving a and b might yield a zero or nonintegral denominator, or fail to be smaller.
> With a=2k and b=2l, k,l are integers. Since b=2l>0, l>0, and l=b/2<b. Thus step-halved-representation supplies a forbidden smaller positive denominator.

- Claim `claim-irrational`: outcome **survives**.
> The contradiction may only refute the selected representation rather than the original rationality assumption.
> The selected representation was obtained from the temporary rationality assumption, and the contradiction is with its least-denominator property. Therefore the temporary assumption is discharged, yielding irrationality.

Revision log:
- > Replaced the unsupported inference from ‘no lowest-terms representation’ to irrationality with a minimal-positive-denominator construction.
- > Removed the unnecessary gcd condition: divisibility of both numerator and denominator by 2 directly contradicts denominator minimality.
- > Retained and made explicit the parity calculations establishing that an integer with even square is even.
- > The audit objection concerning reduction to lowest terms is addressed; no unresolved mathematical objection remains.

## Executed checks

No broker check or source-fetch receipt was recorded.

## Evidence

No source records were supplied or captured.

## Remaining uncertainty and useful next work

> critical_claim_missing_challenge
> critical_proof_steps_not_covered
> unmet obligation: A derivation, or an explicitly named and applied standard result, that if √2 is rational then it has an integer representation a/b with b ≠ 0 and gcd(a,b)=1.
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
- Wall time: 176916 ms
- Summed child duration: 176186 ms
- Formal verification: not performed
- Input bytes: 84030
- Output bytes: 122008
- Input tokens: unknown
- Output tokens: unknown
- Reasoning tokens: unknown
- Recorded cost: unknown
