# Task 5 report — fake Frame dispatch CLI

## Delivered

- Added `mathresearch dispatch --run-dir PATH --adapter fake [--timeout-seconds N] [--json]`.
- The command invokes the Task 4 durable fake Frame service.  It accepts only the local `fake` adapter; unavailable future adapter names such as `codex` and `claude` return the structured `unsupported_adapter` invocation error.
- A positive whole-second timeout is validated at the CLI boundary and passed through to the process runner.  A timeout preserves any partial `stdout.bin` and `stderr.log`, leaves the pre-launch intent as the safe recovery boundary, and returns a structured `dispatch_failed` result rather than a traceback.
- Successful and idempotent dispositions return JSON with `dispatch_status` and the replayed `state`.  Rejected or crash-window-blocked dispositions return readable/structured errors with the existing blocked exit code.
- Added a top-level README and updated the architecture document with the implemented lifecycle, durable layout, command examples, test command, and explicit non-scope: there are no real Codex/Claude/provider adapters in this milestone.

## Tests

- New CLI coverage executes `init -> dispatch --adapter fake -> status` through fresh Python processes, checks the durable task/attempt artifacts, and verifies repeat dispatch idempotence.
- New CLI coverage checks timeout forwarding, rejected/runner-failure visibility, unsupported adapter, missing run, and invalid timeout behavior.
- New process coverage checks timeout capture persistence and structured failure.

Fresh full-suite verification used workspace-local `TEMP`/`TMP` and `PYTHONPATH=src`:

```powershell
py -m unittest discover -s tests -v
```

Result: **101 tests passed**.
