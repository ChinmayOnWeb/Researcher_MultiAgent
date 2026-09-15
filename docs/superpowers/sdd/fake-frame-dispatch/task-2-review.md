# Task 2 review — multi-event durable run store

## Verdict

**Changes required before Task 3.** One Important durable-layout validation gap was found. No Critical findings.

## Critical

None.

## Important

1. **A partially materialized multi-attempt tree can hide unsafe contents in an existing attempt directory.**

   In `src/mathresearch/run_store.py`, `_checked_materialization_layout()` builds the expected set of attempt directories, then returns early when any expected directory is missing:

   ```python
   if set(attempt_entries) != {_attempt_directory_name(attempt) for attempt in attempts}:
       return
   ```

   That early return happens before it validates the contents of the directories that *are* present. For a valid history with intents for attempts 1 and 2, create `tasks/task-frame/attempts/attempt-frame-001/` with an undeclared file (or a link), but omit `attempt-frame-002/`. `load_run_status()` accepts the layout, writes/replaces `packet.json`, and leaves the undeclared artifact in attempt 1. This contradicts the Task 2 requirement for a strict checked task layout that rejects unknown or unsafe artifacts while still allowing interrupted, missing materializations.

   Validate every existing allowed attempt directory regardless of whether other expected attempt directories are absent; only the absent directories should remain repairable. Add a regression test covering an incomplete multi-attempt cache with an unsafe/unknown artifact in its existing directory.

## Minor

None.

## Verification

Executed with workspace-local temporary storage:

```powershell
$env:TEMP=(Resolve-Path '.review-temp')
$env:TMP=$env:TEMP
$env:PYTHONPATH='src'
py -m unittest tests.unit.test_contracts tests.unit.test_run_records tests.unit.test_frame_records tests.unit.test_run_store -v
```

Result: **61 tests passed**. The test suite does not cover the partial multi-attempt layout above.
