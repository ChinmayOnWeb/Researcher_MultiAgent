# MathResearcher

MathResearcher is a local Python CLI for durable, coordinator-owned research runs.  The currently implemented execution slice is intentionally small: it initializes a run, runs exactly one deterministic local **fake** Frame worker, and replays the resulting durable state.

It does not yet launch Codex, Claude, or any other external agent CLI.

## Try the implemented lifecycle

Create a request JSON that follows the version-one `run_request` contract, then run:

```powershell
$env:PYTHONPATH = 'src'
py -m mathresearch init --request request.json --run-dir runs/demo --json
py -m mathresearch dispatch --run-dir runs/demo --adapter fake --timeout-seconds 30 --json
py -m mathresearch status --run-dir runs/demo --json
```

`dispatch --adapter fake` materializes and executes the sole `frame` task.  A successful result is accepted and leaves the run `active`; it does not declare the research run complete.  Repeating the same dispatch is idempotent and reports `already_accepted`.  An intent recorded before a crash remains visible as `blocked_interrupted` and is never silently relaunched.

Only `fake` is accepted by `dispatch` in this milestone.  Supplying `codex`, `claude`, or another adapter returns a structured `unsupported_adapter` error.  The existing `doctor` command can report whether those installed CLIs are discoverable, but it does not execute them.

## Durable artifacts

The coordinator treats event history as authoritative and derives projections from it:

```text
runs/demo/
  request.json
  state.json
  events/000001.json ...
  tasks/task-frame/
    task.json
    accepted.json                 # after a successful acceptance
    attempts/attempt-frame-001/
      packet.json
      stdout.bin
      stderr.log
```

The run is protected by an OS lock while a coordinator operation runs.  `status` replays events and repairs only derived artifacts; it rejects corrupt or unsafe run layouts instead of guessing.

## Test

Run the suite with a workspace-local temporary directory on Windows:

```powershell
New-Item -ItemType Directory -Force '.verification-tmp' | Out-Null
$env:TEMP = (Resolve-Path '.verification-tmp')
$env:TMP = $env:TEMP
$env:PYTHONPATH = 'src'
py -m unittest discover -s tests -v
```

Remove `.verification-tmp` after the test process exits if desired.

## Not yet implemented

There are no real provider adapters, parallel worker scheduling, retry policy, human gates, evidence gathering, report generation, or a completed research workflow in this milestone.  The fake Frame worker is a deterministic local protocol used to verify the durable coordinator boundary before those capabilities are added.
