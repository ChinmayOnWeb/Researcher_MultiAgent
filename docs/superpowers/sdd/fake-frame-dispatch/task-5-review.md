# Task 5 independent review — fake Frame dispatch CLI

## Verdict

**Accepted.** No Critical, Important, or Minor findings.

## Scope checked

- `mathresearch dispatch --run-dir PATH --adapter fake [--timeout-seconds N] [--json]`
  is registered with the required arguments.  The timeout parser accepts only a
  positive whole integer and forwards the result to the durable fake-dispatch
  service.
- `fake` is the sole execution adapter in this milestone.  `codex`, `claude`,
  and other values fail with the stable structured `unsupported_adapter` error
  and exit 20; the README and architecture document explicitly say that real
  provider execution is not implemented.
- Successful JSON output has the stable envelope
  `{"dispatch_status": ..., "state": ...}`.  Human output exposes the same
  disposition and state fields.  Rejected and interrupted dispositions, storage
  failures, process-launch/timeout failures, cancellation, and invalid
  invocations use the established structured errors and declared exit codes.
- The CLI delegates timeout/partial-capture behavior to the checked process
  boundary: timeout preserves `stdout.bin` and `stderr.log`, leaves its durable
  intent as the recovery boundary, and reports `dispatch_failed` without a
  traceback.
- Fresh-process CLI integration covers `init -> dispatch -> status`, confirms
  the packet and capture artifacts, and proves repeated dispatch returns
  `already_accepted` without adding another acceptance.  The service-level
  coverage also checks interrupted intent, failed/malformed outcomes, and the
  post-outcome/pre-acceptance recovery path without relaunching a worker.

## Manual CLI checks

```powershell
$env:PYTHONPATH = 'src'
py -m mathresearch dispatch --help
py -m mathresearch dispatch --run-dir .\missing-review-run --adapter codex --json
py -m mathresearch dispatch --run-dir .\missing-review-run --adapter fake --timeout-seconds 0 --json
```

The help text exposes exactly the intended dispatch surface.  The unsupported
adapter and invalid timeout each produced the documented structured JSON error
and exit 20.

## Fresh verification

Ran the complete suite with workspace-local `TEMP`/`TMP` and `PYTHONPATH=src`:

```powershell
py -m unittest discover -s tests -v
```

Result: **101 tests passed**.
