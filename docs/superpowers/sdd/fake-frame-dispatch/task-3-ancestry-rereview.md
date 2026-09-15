# Task 3 ancestry-hardening re-review

## Verdict

**Accepted for Task 4.** No Critical, Important, or Minor findings.

`run_fake_frame_attempt()` now takes an explicit `run_dir` and derives the sole
allowed attempt location as:

```
<run_dir>/tasks/task-frame/attempts/attempt-frame-<attempt:03d>
```

It absolute-normalizes the supplied paths, requires `packet.json` in that
exact directory, requires the two fixed capture children there, and rejects
any mismatch before launching the child. It also `lstat`s every directory in
the ancestry and rejects links/reparse points, so lexical lookalikes and
symlink aliases cannot gain run-storage authority.

## Evidence checked

- A noncanonical attempt directory is rejected before process launch.
- A complete canonical-looking tree outside the supplied `run_dir` is rejected
  before process launch.
- A symlinked attempt ancestry is rejected before process launch.
- The materialized-store integration creates the canonical task and attempt
  under `open_locked_run()`, runs the worker with that `run_dir`, appends the
  process outcome, and successfully reopens status.

## Fresh verification

```powershell
$env:PYTHONPATH='src'
py -m unittest tests.unit.test_fake_frame_process tests.unit.test_run_store -v
```

Result: **45 tests passed**, exit code 0.
