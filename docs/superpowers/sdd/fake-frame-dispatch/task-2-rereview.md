# Task 2 re-review — partial materialization validation

## Verdict

Approved for this narrow re-review. The Important finding in `task-2-review.md` is fixed. No Critical, Important, or Minor findings remain in the reviewed change.

## Critical

None.

## Important

None.

## Minor

None.

## Implementation evidence

- `src/mathresearch/run_store.py:272` validates each existing level of the fixed task tree before descending. A missing directory permits recovery of that absent subtree; it does not skip checks on entries already present in its parent.
- `src/mathresearch/run_store.py:324` now iterates over every existing allowed attempt directory. The former early return on an incomplete set of attempt directories is gone.
- `src/mathresearch/run_store.py:335` rejects unknown entries, symlinks/reparse points, wrong filesystem types, and unverified hardlinks, including unsafe files using documented temporary names.
- `src/mathresearch/run_store.py:430` performs layout validation before `_materialize_history` can repair state or task caches. Both `load_run_status()` and `LockedRun.materialize()` reach this validation through `_load_locked_run()`.
- `tests/unit/test_run_store.py:394` reproduces the original two-attempt failure: the second attempt directory is missing while the first contains `unexpected.bin`. It now requires `RunCorruptError`.

Unknown or unsafe entries cause rejection; they are not deleted. They cannot be accepted through a successful status/materialization call. Safe documented temporary files remain recoverable as designed.

## Fresh verification

Executed on 2026-09-14 with workspace-local temporary storage:

```powershell
$env:TEMP=(Resolve-Path '.review-temp').Path
$env:TMP=$env:TEMP
$env:PYTHONPATH='src'
py -m unittest tests.unit.test_contracts tests.unit.test_run_records tests.unit.test_frame_records tests.unit.test_run_store -v
```

Result: **62 tests passed**, exit code 0, including the new regression.

An additional in-memory review harness reused the existing fixture helpers and exercised **28 independent cases**: both public entry points (`load_run_status` and `LockedRun.materialize`), either attempt as the surviving sibling, and seven layouts:

- undeclared file;
- `packet.json` symlink;
- `stdout.txt` hardlink to an outside fixture;
- directory named `stderr.txt`;
- symlink using a documented packet temporary filename;
- hardlink using a documented packet temporary filename;
- clean partial layout.

All 24 unsafe cases raised `RunCorruptError` before restoring either the missing sibling directory or a deliberately removed `state.json`. All four clean cases rebuilt the missing packet and returned event sequence 5. Every case preserved committed event bytes and the outside fixture's contents. Harness exit code: 0.

No implementation or test source files were changed. This verdict addresses only the previously reported partial-tree validation gap; it is not a review of later dispatch work.
