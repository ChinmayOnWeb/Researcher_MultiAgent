# Methodology addendum

This addendum narrows how to read the ten-style diagnostic. It preserves the original trial records and does not reinterpret failed trials as successful product runs.

## Scope and ordering

- The ten questions were elementary, guided proof tasks. One attempt per style is a regression sample, not evidence about broad mathematical research performance.
- The case set supplied no evaluator checks (`checks: []`). It therefore did not exercise the autonomous broker/tool path.
- The execution filter selected one case at a time. The manifest's alternating order was calculated after filtering, so those runs were pipeline-first for replicate 1. Order was not counterbalanced across this selected-case sequence.
- Two baseline recoveries were run after their pipeline trials hit provider usage limits. These provide useful output examples, but they are temporally recovered and not contemporaneous matched successes.
- Provider usage-limit failures are availability outcomes. They do not establish mathematical error or success, and later recoveries do not erase the earlier failure.

## Separate product and semantic outcomes

A baseline provider response may contain a mathematically sound proof and still fail as a product result because its structured output was rejected. Semantic review of that captured answer is a separate outcome; it does not change protocol validity, terminal status, or completion rate. Conversely, a failed provider request with no answer has no assessable semantic grade and must not be assigned a zero mathematical score.

Four captured schema-rejected answers are stored under `tests/fixtures/research/diagnostic_regressions/`. Each fixture has its exact response payload, a SHA-256 digest, source run/trial/file, provider outcome, protocol classification, and recorded validation error. The files contain only the provider payload and the minimal provenance needed to identify it. Historical trial artifacts remain unchanged.

The same fixture directory also contains concise, hash-linked assessment snapshots for the induction and geometry pipeline runs, an excerpt showing the induction run's stale uncertainty text, and per-action stderr marker counts paired with action telemetry. The marker fixture records 64 local `session id:` occurrences across 58 captures; six actions have multiple markers. This is evidence of process/session activity in local logs, not a billing or remote-request measurement.

The original report's session counts are local log observations. Token and billing totals were unavailable. These limitations prevent cost-per-quality conclusions.
