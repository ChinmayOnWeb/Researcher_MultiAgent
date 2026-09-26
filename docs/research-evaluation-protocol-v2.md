# Research evaluation protocol v2

## Outcomes

Report five views independently: semantic answer quality, schema acceptance,
terminal-status calibration, provider availability, and resource use. A schema
rejection may still receive semantic credit when the rejected payload is
available; it remains a protocol failure. A missing answer is unavailable for
semantic grading and is not assigned a zero. Show missing-grade counts and
completion denominators alongside assessable-only means.

The named legacy policy legacy_pilot_thresholds_v1 retains the pilot gates:
Deep mean score of at least 8/10 and either a mean paired increase of at least
one point or a 25% material-failure reduction without lower coverage. It also
retains the 6x Deep and 1.5x Quick latency ceilings. These thresholds are
historical decision rules, not statistical guarantees.

## Blind grading

Run mathresearch research evaluate --prepare-grading-packets after outputs
exist. Review JSON packets in grading-packets/; do not open grading-key.json
until grading is complete. The key is kept outside the packet directory.
Packet and artifact hashes are frozen in grading-packets/index.json.

For each scored dimension, record a concise reason and one or more references
such as step:proof-step-3, claim:claim-2, error:invalid-inference, or
passage:answer-paragraph-2. Cite the specific mathematical assertion or
failure. Accept any valid proof that satisfies the obligations; do not require
the reference proof route. Do not score verbosity, polish, or number of stages.
Use assessability: unavailable when the artifact cannot be reviewed.

## Comparability and recoveries

First-attempt pairs are comparable only when the frozen question, source bytes,
model, effort, and evidence policy agree. Quota-truncated, unmatched, or
incomplete pairs are labeled separately. A later recovery is retained as a
separate attempt and never substituted into the original pair. Report its
resource use separately.

Token and cost data remain unknown when no provider supplied them. Tool calls,
provider calls, wall time, token counts, and known costs are separate measures.
An equal number of provider calls is not evidence of an equal token budget.
Session-ID markers are supplemental local telemetry.

## Limits

Small samples are descriptive. Easy cases can show a baseline ceiling effect;
no gain on a fully correct baseline answer is not evidence that longer output
improved quality. The ten-style suite remains a regression suite and does not
establish a general architecture effect.
