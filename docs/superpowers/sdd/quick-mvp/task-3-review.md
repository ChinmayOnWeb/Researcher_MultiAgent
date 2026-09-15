# Task 3 independent review — quick workflow coordinator

## Scope and evidence

Reviewed `src/mathresearch/quick_workflow.py`, `src/mathresearch/reporting.py`,
their Quick contracts/store interactions, Task 3's report, and the focused
tests. No code was edited and no live provider was invoked.

Fresh verification:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_quick_workflow tests.unit.test_reporting -v
# 3 tests passed

$env:TEMP=(Resolve-Path '.verification-tmp'); $env:TMP=$env:TEMP
$env:PYTHONPATH='src'; py -m unittest discover -s tests -v
# 126 tests passed
```

## Findings

### Important — completed runs can fail before their required no-op return

`run_quick` invokes `adapter.preflight()` before it opens and examines the
durable run (`quick_workflow.py:24-31`). Consequently, a completed run can
raise `adapter_unavailable` if the provider executable/configuration is no
longer locally usable, instead of returning its durable `QuickState` with zero
worker launches. The plan requires that repeating a completed run is a no-op;
provider preflight belongs only on the path that could configure or launch a
new stage. Open/read the run first, validate matching persisted configuration,
return terminal state, and only then preflight before a new configuration or
intent.

### Important — an inconclusive result is not explicitly disclosed in the report

`render_quick_report` reads neither `verify["disposition"]` nor
`explain["conclusion"]` (`reporting.py:13-35`). A valid inconclusive Verify
payload can have all individual checks `supported` and no limitations; Explain
must use `conclusion="inconclusive"`, but that field is also omitted. The
rendered report can therefore look fully affirmative even though the durable
workflow is inconclusive. Render both the verification disposition and final
conclusion (with an unambiguous inconclusive label) from coordinator-validated
records. This is required for the plan's honest failed/inconclusive reporting
rule.

### Important — required recovery, gate, and budget test coverage is absent

`tests/unit/test_quick_workflow.py` contains only the happy-path/no-op test and
one acceptance-crash recovery test; `test_reporting.py` has one deterministic
render test. The Task 3 checklist specifically requires crash injection at
intent, capture publication, outcome, acceptance, and final-report
materialization, plus tests for malformed/failed/timeout/cancelled results,
intent-only blocking, budget/deadline exhaustion, Frame missing/escalation,
and Verify fail/inconclusive gates. None are present (the focused command ran
only 3 tests). The full suite passing does not supply evidence for those new
workflow requirements. Add focused tests for every listed path, including
asserting no replacement worker is launched during recovery.

## Minor

None.

## Verdict

**Changes required before Task 4.** The fixed four-stage happy path and
successful-finished recovery are present, and the full existing suite passes,
but the two observable MVP correctness issues and the missing mandatory
recovery/gate coverage must be addressed and independently re-reviewed.
