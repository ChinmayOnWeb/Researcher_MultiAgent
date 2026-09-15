# Task 2 report — Run locking

## Delivered

- Added `src/mathresearch/locking.py` with `@contextmanager acquire_run_lock(run_dir: Path) -> Iterator[None]`.
- Each acquisition opens the durable `<run_dir>/.run.lock` file and keeps that descriptor open for the whole protected context. The file is never removed and its existence is never treated as proof of ownership.
- POSIX uses a branch-local `fcntl.flock(fd, LOCK_EX | LOCK_NB)` call. Windows uses a branch-local `msvcrt.locking(fd, LK_NBLCK, 1)` call, ensuring a byte exists at offset zero first so the Windows byte-range lock has a target.
- A contended nonblocking lock raises `RunLockedError`; other open/acquisition failures raise `RunStoreError`. Both expose stable machine codes and exit mappings: `run_locked` / `ExitCode.RUN_LOCKED` (22), and `run_store_error` / `ExitCode.RUN_STORE_ERROR` (23).
- Release and descriptor closure are in `finally`, so ordinary exits and protected-work exceptions both release the OS lock.
- Added `tests/unit/test_locking.py`, including a real pipe-synchronized child process with a five-second bound for acquire/release contention, sequential reacquisition, exception release, persistent lock-file retention, and simultaneous locks for separate run directories.

## TDD evidence

1. Added `tests/unit/test_locking.py` before the new error and locking modules existed.
2. Ran `$env:PYTHONPATH='src'; python -m unittest tests.unit.test_locking -v`.
   - Outcome: failed as expected with `ImportError: cannot import name 'RunLockedError' from 'mathresearch.errors'`.
3. Added the typed storage errors and the minimal platform-native context manager.
4. The first sandboxed green run was blocked before lock behavior ran: the test process received Windows `PermissionError` while creating child fixture directories. This was a sandbox filesystem restriction, not an assertion failure.
5. Re-ran the focused suite outside that sandbox restriction. All 5 lock tests passed, including real subprocess contention and release.

## Final verification

Ran `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` outside the filesystem-restricted sandbox because the lock contention fixture creates child run directories.

- Outcome: 28 tests run, all passed.
- Scope check: no `run_store`, CLI `init`/`status`, contract, or general documentation implementation was added. The only documentation change is this required Task 2 report.
