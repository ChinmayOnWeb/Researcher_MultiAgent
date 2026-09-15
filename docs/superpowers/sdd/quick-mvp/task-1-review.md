# Quick MVP Task 1 — independent review

## Evidence reviewed

- `src/mathresearch/adapters/base.py`
- `src/mathresearch/adapters/codex.py`
- `src/mathresearch/worker_process.py`
- `src/mathresearch/adapters/codex_smoke.py`
- focused test modules, run with `PYTHONPATH=src`: **9 passed**
- local `codex-cli 0.154.0`, `codex --help`, and `codex exec --help`

## Critical

### C1 — The constructed Codex command is invalid on the verified installed CLI

`CodexAdapter.prepare()` creates `codex exec --ask-for-approval never ...`.
On the locally installed `codex-cli 0.154.0`, `--ask-for-approval` is a top-level
option, not an `exec` option.  The direct local check `codex exec
--ask-for-approval never --help` exits 2 with `unexpected argument
'--ask-for-approval'`.  `codex --ask-for-approval never exec --help` exits 0.
Thus every real worker and the documented live smoke fail before reaching the
model.  Move the top-level flag before `exec`, adjust the expected argv test,
and add a no-model command-shape/preflight regression test.

## Important

### I1 — The hard timeout does not cover blocking stdin delivery

`execute_worker()` performs `process.stdin.write(spec.stdin)` synchronously
before calling `process.wait(timeout=...)`.  A child which does not consume
stdin can fill the pipe when given a sufficiently large prompt; the write then
blocks indefinitely, so neither the timeout nor process-tree cleanup runs.
Deliver stdin through a bounded/deadline-aware writer (or use a coordinated
`communicate` strategy that still drains both capture pipes), and add the
non-reading-child regression test.

### I2 — A dangling `result.json` link is not rejected before the provider can write through it

`_validate_spec()` uses `target.exists()` to determine whether the requested
result file already exists.  `Path.exists()` returns false for a dangling
symlink, so a pre-existing `scratch/result.json` dangling link passes
validation.  The provider can then write through it outside scratch; the later
`lstat` rejection only notices the link after that write.  This violates the
required scratch/result link safety.  Reject any existing directory entry via
`lstat` (including dangling links) before launch, and use a race-safe final
result open/read strategy or otherwise close the lstat/read replacement window.

### I3 — The provider profile permits shell execution, contrary to the MVP's required capability boundary

The adapter correctly avoids falsely saying its `--sandbox read-only` command
has no shell, but its advertised `shell_read_only: true` means an actual worker
may run read-only shell commands.  The MVP constraints require shell tools and
experiments to be disabled by native configuration, not merely described in a
prompt or reduced to read-only.  Either establish and test a locally supported
Codex configuration that disables the shell tool, or do not use Codex for this
MVP profile and make adapter preflight reject it.  The current adapter cannot
be released as the plan's reasoning-only provider.

## Minor

### M1 — Windows Job Object FFI declarations are implicit and process-tree assurance is underspecified

`_WindowsJob` invokes `CreateJobObjectW`, `AssignProcessToJobObject`,
`TerminateJobObject`, and `CloseHandle` without `argtypes`/`restype`.
On 64-bit Windows the default ctypes return convention can truncate a handle.
The focused descendant test passed on this machine, which is useful evidence,
but the cleanup guarantee is too important to rely on defaults.  Declare the
Win32 signatures explicitly, preserve the assignment failure reason, and make
the timeout path return the documented blocked/no-relaunch result whenever Job
creation or assignment cannot be confirmed.

## Verdict

**Not accepted.** C1 prevents every real Codex invocation.  Resolve C1 and all
Important findings, add focused regressions, then request a new independent
review.  M1 should be fixed in the same remediation because it supports the
same process-tree safety boundary.
