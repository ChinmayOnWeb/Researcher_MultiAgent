# Quick MVP Task 1 — remediation re-review

## Scope and fresh evidence

Reviewed the Task 1 remediation against `task-1-review.md`, the MVP plan, and
the current provider/runner implementation. No implementation files were
changed during this review.

- Focused provider, worker, and CLI compatibility tests: **28 passed**.
- Full suite: **123 passed**.
- Local no-model command-shape check:
  `codex --ask-for-approval never --sandbox read-only exec --help` exited 0.
  The previously invalid ordering, `codex exec --ask-for-approval never
  --help`, exited 2.
- Installed Claude availability check only: `claude --version` reported
  `2.1.237 (Claude Code)`. No Claude model call was made.

The Codex executable emitted non-fatal local temporary-alias cleanup warnings
while printing help; the command itself exited 0 and no provider was invoked.

## Prior findings

### C1 — ADDRESSED

`CodexAdapter.prepare()` now places `--ask-for-approval never` and `--sandbox
read-only` before `exec`. Its exact-argv test matches that ordering, and the
locally installed CLI accepts the full pre-`exec` prefix without a model call.

### I1 — ADDRESSED

The timeout-owning thread no longer writes stdin. `_StdinWriter` is a daemon
worker while separate bounded readers drain both output streams, and the
non-reading-child regression uses a 16 MiB prompt with a one-second timeout.
It completed as `timed_out` in the fresh focused run.

### I2 — ADDRESSED

Prelaunch validation uses `lstat`, rejecting any pre-existing result entry,
including dangling links. Final result consumption rechecks a safe regular
file, opens it descriptor-first with no-follow when available, compares
directory-entry and descriptor identity, bounds size, and rejects replacement
during the read. The dangling-link regression passes.

### I3 — ADDRESSED

The adapter truthfully advertises `shell_execution: true`, its preflight always
rejects the unsupported reasoning-only profile, and discovery marks Codex
unavailable for that profile. It therefore cannot be selected as an installed
MVP provider merely because the executable is present. This is the required
safe result until a native no-shell control is verified.

### M1 — ADDRESSED

The Job Object API declares pointer-safe ctypes argument and result types. A
failed Job setup is retained as an unconfirmed condition; timeout cleanup then
returns `cancelled` rather than a relaunchable completion. The signature test
passes.

## Verdict

**Accepted.** No Critical, Important, or new Minor findings. Codex is correctly
kept unavailable for the reasoning-only MVP, so the next provider investigation
should target Claude's native noninteractive structured-output and no-shell
controls rather than attempting a Codex live call.
