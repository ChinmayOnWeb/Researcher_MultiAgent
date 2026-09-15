# MathResearcher

MathResearcher is a local Python CLI for durable, coordinator-owned research
runs. Its quick workflow is fixed and foregrounded: `frame -> investigate ->
verify -> explain`. The coordinator, rather than the model, selects each
stage, validates each result, and writes the final report.

## Request to report

Create the parent directory first: `init` intentionally refuses to create a
missing parent directory.

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory -Force runs | Out-Null
py -m mathresearch init --request examples/quick-proof.json --run-dir runs/proof --json
py -m mathresearch run --run-dir runs/proof --adapter codex --timeout-seconds 180 --json
py -m mathresearch status --run-dir runs/proof --json
Get-Content runs/proof/report.md
```

A completed quick run returns a JSON object with `run_status: "complete"`,
`accepted_submission_count: 4`, and the absolute `report_path`. Repeating the
same `run` after completion is a durable no-op: it makes zero provider calls.

The bundled example is ordinary-stakes Quick mode, disables every external
capability, sets `learning_mode` to `false`, and allows exactly four accepted
submissions.

## Current provider status

`run` currently accepts only `--adapter codex`; `--model NAME` is optional and
`--timeout-seconds` defaults to 180. A request outside Quick/ordinary/
non-learning/no-external-capabilities is rejected before a provider launch.
An adapter or model that conflicts with the persisted configuration is likewise
rejected before relaunch.

The locally verified Codex CLI (`0.154.0`) uses native per-invocation controls:
strict configuration, disabled `shell_tool`, `browser_use`, `computer_use`,
and `apps` features, a read-only sandbox, ignored user configuration and rule
files, and no `--search` flag. Before a worker intent is recorded, the adapter
checks the installed feature inventory and verifies that this exact control set
is accepted by the CLI parser. If that check or executable resolution fails,
`run` returns `adapter_unavailable` without launching a worker. `doctor --json`
reports discovery without invoking a provider.

The repository's integration tests exercise the request-to-report lifecycle
with a local argv stub; they do not claim a live Codex result.

## Existing fake lifecycle

The original compatibility command remains available:

```powershell
py -m mathresearch dispatch --run-dir runs/demo --adapter fake --timeout-seconds 30 --json
```

It executes only the legacy deterministic Frame worker. It is not a quick
research report and does not substitute for `run`.

## Durable artifacts and recovery

Quick workflow histories record the provider configuration, intent packet,
captured diagnostics, normalized outcome, acceptance, and final report. A
successful outcome recorded before acceptance resumes from the durable result
without relaunching that stage. An intent without an outcome is visibly
`workflow_blocked` and is never relaunched automatically. `status` replays
committed events and repairs derived `state.json`, accepted payloads, and a
completed `report.md` when their durable source event exists.

## Limitations

- This round did not run a new four-stage live-provider demonstration. A
  schema-valid response is not a proof of research accuracy or tool safety.
- There are no retries, human-response commands, external evidence retrieval,
  code execution, parallel scheduling, or Deep/Research workflow execution.
- A schema-valid provider response is not evidence that the mathematical
  answer is accurate. Quick reports disclose that verification is model
  reasoning, with no external retrieval or executed experiments.

## Test

Run the suite with a workspace-local temporary directory on Windows:

```powershell
New-Item -ItemType Directory -Force '.verification-tmp' | Out-Null
$env:TEMP = (Resolve-Path '.verification-tmp')
$env:TMP = $env:TEMP
$env:PYTHONPATH = 'src'
py -m unittest discover -s tests -v
```
