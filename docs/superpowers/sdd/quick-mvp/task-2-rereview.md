# Task 2 remediation re-review — Quick workflow contracts and durable store

Verdict: **Accepted.** No Critical or Important findings.

## Prior findings

1. **Capture digest verification — addressed.** Replay now calls
   `_checked_quick_capture_digests` after validating the quick projection
   layout and before repairing derived projections. Every committed finished
   attempt must have both canonical, safe regular capture files, and their
   SHA-256 values must equal the immutable event body. Missing and tampered
   capture regressions both fail with `RunCorruptError`.

2. **Legacy `report.md` authorization — addressed.** A report projection is
   permitted only on the quick-history branch and only after `quick_completed`.
   Version-one/fake histories with a root `report.md` now fail layout
   validation; the legacy compatibility suite remains green.

3. **Exact intent request/prerequisite graph — addressed.** Reducer replay
   compares each packet request with the initialized request JSON and requires
   its `inputs` mapping to exactly equal the accepted results of all preceding
   fixed stages. Regression coverage rejects both an altered request and a
   missing predecessor input.

## Verification

Focused remediation suite:

```powershell
$env:PYTHONPATH='src'
py -m unittest tests.unit.test_quick_records tests.unit.test_quick_store tests.unit.test_run_store -v
```

Result: **42 passed**.

Fresh full suite, after the concurrent provider changes settled:

```powershell
$env:PYTHONPATH='src'
py -m unittest discover -s tests -v
```

Result: **123 passed**. This resolves the earlier 121-pass/1-fail concurrent
Task 1 discovery mismatch as stale rather than a Task 2 regression.
