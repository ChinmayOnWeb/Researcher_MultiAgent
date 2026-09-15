# Task 4 — CLI, example, integration gate

## Delivered

- Added `mathresearch run --run-dir PATH --adapter codex [--model NAME]
  [--timeout-seconds N] [--json]`; its timeout defaults to 180 seconds.
- Added a provider resolver which reports unavailable or capability-unsafe
  Codex before a worker launch. It does not substitute the fake worker.
- Added terminal Quick state rendering: a completion reports the absolute
  report path and accepted count; blocked, protocol, configuration, and budget
  outcomes use structured errors and existing exit-code families.
- Added `examples/quick-proof.json`, the documented elementary odd-sums
  request. It includes every version-one request field, is Quick/ordinary,
  disables external capabilities, and allows four accepted submissions.
- Updated the README and architecture document for the fixed four-stage
  workflow, durable Quick recovery, compatibility fake dispatch, and current
  provider limitation.
- Added fresh-process integration coverage using a local argv stub executable.
  Its launch-count file is outside the coordinator process and proves four
  distinct stage processes (`frame`, `investigate`, `verify`, `explain`) and a
  zero-launch completed rerun. Coverage also includes unavailable provider,
  malformed structured result, resume conflict, unsupported mode, verification
  failure, accepted-submission exhaustion, and ambiguous intent.

## Verification

Focused integration command (workspace-local `TEMP` / `TMP`):

```powershell
$env:PYTHONPATH='src'; $env:TEMP=(Resolve-Path '.verification-tmp');
$env:TMP=$env:TEMP; py -m unittest tests.integration.test_quick_cli -v
```

Result: 6 tests passed.

Full command, run once after integration with the same local temporary
directory:

```powershell
py -m unittest discover -s tests -v
```

Result: exit 0.

## Live-provider demonstration

Bounded command executed on 2026-09-15:

```powershell
py -m mathresearch init --request examples/quick-proof.json --run-dir .task4-live-demo/proof --json
py -m mathresearch run --run-dir .task4-live-demo/proof --adapter codex --timeout-seconds 180 --json
py -m mathresearch status --run-dir .task4-live-demo/proof --json
```

Installed provider version: `codex-cli 0.154.0`.

Result: initialization succeeded, then `run` returned exit 11 with
`adapter_unavailable`: Codex 0.154.0 cannot enforce disabled shell execution
for the reasoning-only MVP profile. Status remained `initialized`; no worker
was started, no report was written, and the demonstration did not claim a
mathematical result.

The local argv-stub integration demonstration is deliberately separate from
this live-provider result. It validates coordinator lifecycle mechanics, not
provider safety or proof accuracy. The required live four-stage proof report,
and therefore the "quick research MVP" release label, remain blocked until a
provider has native no-shell enforcement.

## Review status and limitations

The task request forbade delegation, so no independent end-to-end review was
obtained in this task. The existing Task 1 review findings remain relevant:
process-tree cleanup and provider tool restrictions are implemented in their
own boundary but a compliant live provider is still unavailable. The release
gate is intentionally not claimed as passed.
