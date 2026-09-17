# Task 3 implementation report

## Controller ruling applied

The controller directed Task 3 to validate `action_intended.packet` as an opaque strict JSON object and to calculate `packet_sha256` over canonical UTF-8 JSON with sorted keys, compact separators, and `ensure_ascii=False`. `research/events.py` implements that byte representation in `canonical_json_bytes`; it does not invent Task 4 packet fields.

The controller also directed that `sources/` and `tools/` projections receive authority only from committed, validated `action_finished` records for the corresponding tool action. The store has no standalone mutable source or receipt authority and introduces no additional event type. Its layout verification rejects tool projection directories that do not correspond to a completed action.

## Delivered files

- `src/mathresearch/research/events.py`: strict version-three envelope/body validation, canonical packet hashing, immutable snapshot publication, chronology and action/gate/terminal replay checks.
- `src/mathresearch/research/store.py`: isolated v3 run layout, existing OS lock and checked atomic-file primitive reuse, immutable event append, canonical captures, projection recovery, and corruption-before-repair checks.
- `tests/unit/test_research_events.py`: hand-authored Quick-complete fixtures and reducer negative cases.
- `tests/unit/test_research_store.py`: initialization/recovery and strict-root-layout coverage.

## Behavior and recovery evidence

- Events must be contiguous, UTC-ordered, single-initialization immutable histories. Unknown events, duplicate initialization, packet hash changes, finishes without the pending intended action, duplicate gates, and post-terminal actions fail replay.
- `append()` commits immutable events first and then materializes derived packet/result/report/state projections. Therefore a projection failure leaves durable evidence available for recovery.
- `load_research_status()` validates the complete immutable event history and capture SHA-256 values before writing a missing or stale state projection. It rejects unknown root entries, unsafe directories, unapproved action directories, unexpected action files, packet projection mismatches, and capture mismatches.
- The v3 store imports only the explicitly permitted legacy primitives and leaves legacy v1/v2 code unchanged. The legacy store suite passed in the required focused command.

## Test evidence

Initial TDD red run (before Task 3 modules existed):

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store -v
```

Exit code: `1`. Both test modules failed with `ModuleNotFoundError` for the intentionally absent `mathresearch.research.events` and `mathresearch.research.store` modules.

Required focused verification after implementation:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
```

Exit code: `0`. Result: `Ran 40 tests in 3.588s — OK`.

## Limits carried to dependent tasks

Task 3 intentionally leaves worker-packet semantics opaque until Task 4 supplies the substantive validator. Source-record and broker-receipt schemas remain Task 6 ownership; Task 3 preserves their durable authority boundary without defining their content format.
