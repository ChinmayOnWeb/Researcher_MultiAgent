# Task 2 independent review — Quick workflow contracts and durable store

Verdict: **Changes required before Task 3.**

Focused verification run:

```powershell
$env:PYTHONPATH='src'
py -m unittest tests.unit.test_quick_records tests.unit.test_quick_store tests.unit.test_run_store -v
```

Result: 37 passed.  The reviewed focused suite does not exercise the three cases below.

## Important

1. **Quick capture digests are never verified during replay.**  `LockedRun.write_capture` returns a SHA-256 digest (`src/mathresearch/run_store.py:99-115`) and a `quick_attempt_finished` records both digest fields, but `_checked_quick_materialization_layout` (`:404-421`) only permits the filenames.  It neither requires captures for a finished attempt nor hashes any present `stdout.bin`/`stderr.log` and compares them to the committed event.  A modified diagnostic capture is consequently accepted by `status`, even though the finished event claims different bytes.  This defeats the durable capture-hash contract and makes corruption/tampering undetectable.  Require/verify the committed capture files once a finished event exists (while preserving the intended crash semantics), and add mismatch/missing regression coverage.

2. **The store weakens legacy fake-run layout validation by allowing `report.md`.**  The root allowlist unconditionally includes `report.md` (`src/mathresearch/run_store.py:164-173`), but report timing is checked only on the quick branch (`_checked_quick_materialization_layout`, `:404-414`).  A version-one fake/Frame history can therefore contain an arbitrary root `report.md` and still replay successfully.  The Task 2 requirement says to preserve the existing fake layout without weakening it; make `report.md` quick-only (or reject it for legacy histories) and test this compatibility-security boundary.

3. **Intent packets do not enforce the fixed prerequisite-input graph.**  `_validate_packet` (`src/mathresearch/contracts/quick.py:50-58`) validates only that `request`, `inputs`, `output_schema`, and `capabilities` are objects.  The reducer’s intent branch (`:236-239`) checks stage ordering but never checks that the packet request matches the initialized request or that `inputs` is exactly the previously accepted prerequisite payload set.  Thus a durable history can claim an `investigate`, `verify`, or `explain` packet containing arbitrary/missing stage data while satisfying every event transition.  Task 2 explicitly requires `inputs` to contain only accepted prerequisite stage payloads selected by the fixed workflow.  Validate the stage-specific expected keys and equality to accepted payloads in replay, and add malformed/altered-packet fixtures.

## Minor

None.

## Positive checks

- Schema-v2 workflow event bodies use strict exact-key validation and quick/legacy event mixing is rejected.
- Event file sequence/name checks occur before projection repair.
- Quick derived packet, acceptance, and report projections are rebuilt from workflow events, and `write_capture` restricts names, stage/attempt, ancestry, and uses atomic new-file publication.
- Version-one focused compatibility tests still passed in the focused verification run.
