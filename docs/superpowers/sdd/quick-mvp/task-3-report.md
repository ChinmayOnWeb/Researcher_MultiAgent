# Task 3 — quick workflow coordinator

Implemented `mathresearch.quick_workflow.run_quick` and
`mathresearch.reporting.render_quick_report`.

The coordinator owns the fixed `frame -> investigate -> verify -> explain`
sequence, durable event publication, acceptance, budgets, blocking decisions,
and deterministic report rendering. Provider workers only return one bounded
stage payload. The implementation uses the shared worker boundary and is
tested with a stubbed adapter; it makes no live provider calls.

Recovery behavior:

- a committed successful finished result is accepted without another launch;
- intent without a finished event is durably blocked rather than relaunched;
- malformed, failed, timed-out, or cancelled workers retain captures and
  result in an actionable blocked event;
- report projection is recoverable from the completed event via the store.

Validation run (workspace-local `TEMP` / `TMP`):

```powershell
$env:PYTHONPATH='src'; py -m unittest discover -s tests -v
```

Result: `126 tests passed`.

Task 4 remains responsible for public CLI wiring, a provider resolver, a
worked example, and any live provider demonstration.
