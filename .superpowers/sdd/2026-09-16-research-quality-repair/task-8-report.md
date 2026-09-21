# Task 8 report — engine integration, recovery, budgets, and telemetry

## Scope and contract reconciliation

Implemented and continued the Task 8-owned research engine and its integration tests. The engine persists decisions, intents, captures, finishes, gate state, telemetry, and prospective terminal report/log text through the v3 store; recovery never relaunches an intended action.

Section 4 requires `provider_factory(request, *, recorded_config)`. The inherited engine called factories with only `request`, which was incompatible. The engine now passes `recorded_config=None` for first configuration and the immutable `provider_configured` body on recovery. It validates that the adapter's requested model/effort match the immutable request and that a resumed adapter reports exactly the durable configuration. `create_research_provider` accepts the same keyword and rejects a persisted request/config disagreement.

## Red/green evidence

The initial focused invocation without `PYTHONPATH=src` exited 1 before test collection (`ModuleNotFoundError: mathresearch`). A sandboxed invocation with `PYTHONPATH=src` then exited 1 because restricted execution cannot write `TemporaryDirectory` files. This was environmental and occurred before the provider-factory regression entered the engine. The managed test command below exercised the completed regression and passed.

## Verification

| Command | Exit | Tests | Result |
| --- | ---: | ---: | --- |
| `PYTHONPATH=src python -m unittest tests.unit.test_research_engine -v` | 0 | 9 | passed |
| `PYTHONPATH=src python -m unittest tests.unit.test_research_engine tests.unit.test_research_store tests.unit.test_research_routing -v` | 0 | 33 | passed |
| `PYTHONPATH=src python -m unittest discover -v` | 0 | 274 | passed |
| `PYTHONPATH=src python -m unittest tests.unit.test_research_engine -v` (after the factory contract type update) | 0 | 9 | passed |

The full-suite command was run once after integration. Test discovery contains 274 `test_*` methods across 29 files; the completed runner returned success.

## Files to commit

- `src/mathresearch/research/engine.py`
- `src/mathresearch/research/provider.py`
- `tests/unit/test_research_engine.py`
- `.superpowers/sdd/2026-09-16-research-quality-repair/task-8-report.md`

No historical run evidence or other task-owned modifications were staged.

## Fix round 1 — reviewer findings

### Root causes and changes

1. `_execute_action` accepted a remaining-time value computed before `action_intended` and reused it after the intent hook. It now recomputes the deadline from persisted initialization immediately after intent and before creating either worker or broker child. An expired deadline records a durable `launch_failed` action with `deadline_before_launch`, empty captures, and consumed intent budget; no child is launched. The engine then finishes `budget_exhausted` with that reason.
2. `LockedResearchRun.append` materialized terminal projections immediately after writing the event, leaving no fault boundary between immutable persistence and projection publication. It now accepts an internal post-persist callback. The engine uses it only for `research_finished` to expose `after_final_event_persisted_before_projection`. Restarting the terminal run reconstructs `report.md` and `research-log.md` from the durable event without provider resolution.

### Regression evidence

| Command | Exit | Tests | Result |
| --- | ---: | ---: | --- |
| `PYTHONPATH=src python -m unittest tests.unit.test_research_engine -v` (red) | 1 | 10 | two new regressions failed as expected: launch occurred after intent-time clock advance; no post-persist/pre-projection hook existed |
| `PYTHONPATH=src python -m unittest tests.unit.test_research_engine -v` (green) | 0 | 10 | passed |
| `PYTHONPATH=src python -m unittest tests.unit.test_research_engine tests.unit.test_research_store tests.unit.test_research_routing -v` | 0 | 34 | passed |

Changed files for this round: `src/mathresearch/research/engine.py`, `src/mathresearch/research/store.py`, `tests/unit/test_research_engine.py`, and this report.
