# Development rubric

Keep this file out of worker inputs. Grade correctness, evidence/source handling,
coverage, challenge quality, and uncertainty from 0 to 2. Require a concise
reason per dimension and references to answer passages, claims, proof steps,
or errors. Accept any mathematically valid proof route. A finite computation
supports only its explicitly checked range unless a separate proof establishes
the universal claim.

## Challenge quality

Score the checks shown in the answer content, regardless of whether they came
from a separate critique stage or a single response. Do not award points merely
for having a review section or another agent.

- **0:** No relevant check tests a central risk, edge case, or possible error.
- **1:** At least one relevant check is present, but an important vulnerability
  remains untested or unresolved.
- **2:** The answer tests the central risk or a meaningful alternative and
  explains how that check affects the conclusion. Direct verification of a
  counterexample, excluded input, proof inference, or exhaustive partition can
  qualify; a separately labeled critique is not required.

If no semantic answer was produced, mark the semantic grade unavailable. Keep
that distinct from execution and protocol failures, which are recorded in the
trial results.
