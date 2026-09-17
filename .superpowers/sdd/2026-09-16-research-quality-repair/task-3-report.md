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

## Fix round 1 follow-up

The remaining structural store boundary is now closed without defining Task 6 semantics. `tools/<action-id>/` is legal only for a committed successful action whose recorded action kind is `tool`; it must contain exactly a regular, non-link `receipt.json` whose canonical bytes equal that action's committed result object. `sources/<source-id>/` is legal only when a successful `fetch_source` tool result structurally exposes that source ID; it must contain exactly a regular, non-link `source.json` with matching canonical bytes. Worker actions cannot authorize tool directories, and arbitrary source directories cannot become evidence.

The store now uses the legacy `_verify_temporary_hardlink_aliases` routine for root, event, action, source, and tool projection directories. Every entry, including a dot-prefixed writer temporary, is classified as a documented temporary alias or rejected; aliases are accepted only when the immutable target identity and hardlink count verify.

Task 3 validates the Section 6 local action structure through Task 2's `validate_action`, enforces contiguous action lifecycle/dependencies and terminal/gate legality, and deliberately defers Section 7 routing-table reason-code selection to Task 7. It does not make route policy decisions.

## Fix round 2

Tool result handling is now operation-bound at replay. Until Task 6 supplies each broker operation's semantic schema, only `fetch_source` has a durable structural result shape: an exact result object containing `source`, with an identifier-validated source ID and a bounded canonical JSON encoding. Other tool result shapes are rejected rather than treated as authority. This validation occurs before store materialization, so traversal strings, absolute paths, separators, dot names, invalid identifiers, and oversized payloads cannot reach `sources/<source-id>`.

Gate response idempotence is keyed by the pair of gate ID and response ID. A reused pair requires the identical canonical response digest; a different gate cannot reuse that authorization. Persisted `noop` decisions are rejected: Section 6 permits a no-op return value, not a no-op event. Capture files are included in the immutable-target alias verifier while SHA-256 capture checks remain mandatory.

Initialization now rechecks the destination while holding the run lock before creating `events/` or publishing an event. The unavoidable empty directory creation is only used to obtain that lock target.

Verification run:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
```

Exit code: `0`. Result: `Ran 43 tests in 3.753s — OK`.

The focused existing tests exercised capture corruption, link/reparse/hardlink and legacy v1/v2 compatibility through `test_run_store`. New dedicated Task 3 fault-injection and v2-byte fixture tests were not added in this round and are not claimed as evidence.

## Fix round 3

`decision_recorded` now requires its decision kind and embedded Action kind to agree, so a worker decision cannot launch a tool Action or vice versa. Replay also rejects `research_finished` while a human gate remains open, independently of Task 7 routing reasons.

Targeted reducer verification:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events -v
```

Exit code: `0`. Result: `Ran 7 tests in 0.007s — OK`.

The required decision/intent/capture/finish/gate/final-report fault-injection matrix and a dedicated hand-authored v2 byte-preservation fixture remain missing. They are not claimed as implemented in this commit.

## Fix round 3 follow-up

Added a legacy-store byte-preservation regression: it hand-authors a legacy request, initializes the legacy run, snapshots every committed file's relative path and bytes, calls legacy `load_run_status`, and requires exact equality afterward. The targeted test passed with `Ran 4 tests ... OK`; the required combined suite then passed with `Ran 45 tests in 3.495s — OK`.

The requested v3 fault-injection matrix remains incomplete and is not claimed as covered by this follow-up. Existing `test_run_store` continues to exercise projection publication faults, link/reparse/hardlink checks, stale temporary alias validation, and immutable evidence repair for the legacy store.
