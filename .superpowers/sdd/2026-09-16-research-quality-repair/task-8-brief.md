### Task 8: Connect engine, budgets, packets, telemetry, and recovery

**Files:** create `research/engine.py`, `tests/unit/test_research_engine.py`; narrowly extend research events/store as required by exact contracts.

**Consumes:** Tasks 2–7 and Task 10's pure renderer. **Produces:** run_research, durable decisions/actions/gates, injectable provider/time boundaries.

- [ ] Write failing full Deep stub integration through real store: two branches, synthesis, audit, report; use actual runner with a trusted scripted child for at least one test. Verify exact action sequence and distinct worker invocations.
- [ ] Implement initialize/configure lazily: open/read durable run and return terminal/gate first; resolve provider only on a launch path. Non-model actions do not resolve Codex.
- [ ] Execute decision -> intend -> child -> validate/observe -> captures -> finished -> next decision. Source catalogs and receipts are derived only from authorized completed actions.
- [ ] At finish, construct an in-memory prospective terminal Snapshot with final status, assessment, and reason; render report/log from it; append one research_finished containing those exact strings; materialize projections afterward. The log includes a deterministic terminal summary, not the serialized final event (avoid a recursive log-in-event dependency). Renderer unit tests were completed in Task 10; now verify full final-event recovery through the engine.
- [ ] Deadline check before every launch, after preflight, and after completion. Effective child timeout = min(per-call limit, broker operation limit if applicable, floor(remaining seconds)); <=0 means no launch. If a worker finishes after deadline, retain outcome but finish budget_exhausted before further work. Local spent time counts even on process failure.
- [ ] Enforce max_input_bytes before intent. Reject rather than silently truncate evidence. Model/tool counters increment at intent. Timeout consumes budget. Gate waiting does not reset time.
- [ ] Record telemetry from clocks/captures/provider header only, never worker JSON. Capture mismatch/unknown as Section 9 requires.
- [ ] Fault-injection matrix: decision before intent, intent before launch, first capture, finish before routing, repair result before re-audit, response before resume, final event before report. Assert launched actions are never duplicated and ambiguous ones visibly block.

```python
def test_finished_branch_survives_restart_without_second_call(self):
    run, launches = run_until_fault("after_branch_a_finished")
    resumed = run_research(run, provider_factory=stub_factory, now=fixed_clock)
    self.assertEqual(launches.count("branch:a"), 1)
    self.assertEqual(resumed.status, "complete")

def test_deadline_uses_persisted_initialization(self):
    run = initialize_at("2026-01-01T00:00:00Z", max_wall_seconds=10)
    state = run_research(run, provider_factory=forbidden_factory,
                         now=lambda: utc("2026-01-01T00:00:11Z"))
    self.assertEqual(state.status, "budget_exhausted")
```

- [ ] Run engine/store/routing suites, then full unittest once after integration. Record session_id/exit_code if runner yields; poll the actual process to completion. Empty output from a yielded command is not success. Commit.

