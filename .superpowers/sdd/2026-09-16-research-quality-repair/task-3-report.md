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

## Fix round 1

Root cause analysis found that the initial store verified captures only while iterating surviving action directories. A deleted finished-action directory was therefore invisible to the capture check and could be followed by state repair. The reducer also accepted a successful result before relating it to the recorded action role, compared timestamp source strings, and did not retain completed gate identities.

The fix now requires an existing safe action directory and both digest-verified canonical captures for every committed `action_finished` record before any materialization. Successful worker results are validated through `validate_result(action.role, result)` during replay. Event timestamps are normalized to UTC instants before chronology comparison. Gate IDs cannot be reopened after answer; repeated response IDs are accepted only when their canonical payload digests match. `noop` is recognized as a decision kind and constrained to terminal/open-gate states. Initialization creates the events directory only while the acquired run lock is held.

New red-green regressions cover deleted finished captures, arbitrary successful worker JSON, and equivalent offset UTC instants. The focused regression command passed after the changes, followed by the required suite:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
```

Exit code: `0`. Result: `Ran 43 tests in 3.813s — OK`.

### Remaining review scope

The action-result-to-source/receipt projection schemas, full route-table authorization, and atomic temporary hardlink alias rules require the downstream Task 6 broker schemas and the existing private temporary-alias verifier to be integrated. They are not fully addressed by this round's changes and must not be represented as complete fixes.
