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
obtained in the initial implementation. The existing Task 1 review findings
remain relevant: process-tree cleanup and provider tool restrictions are
implemented in their own boundary. The release gate is intentionally not
claimed as passed.

## Round 1/5 provider-boundary remediation

An integrated review found two Task 4 boundary defects: the prior Codex profile
did not use the locally available native `shell_tool` disable switch, and the
public resolver ran before it could return an already durable completed state.

The adapter now uses only controls advertised by the installed `codex-cli
0.154.0`: `--strict-config`, `--disable shell_tool`, `--disable browser_use`,
`--disable computer_use`, `--disable apps`, `--ask-for-approval never`, and
`--sandbox read-only`, followed by `exec --ignore-user-config --ignore-rules`.
It omits `--search`. Its no-prompt preflight reads `codex features list` with
the native disable switches and requires all four features to report effective
state `false`, then invokes the complete disabled-tool command with `exec ...
--help` to confirm parser acceptance before an intent is recorded. Any failure
is an `adapter_unavailable` outcome.

The CLI now reads a completed Quick state and validates its persisted adapter
and model selection before provider resolution. This preserves report access
and no-op semantics after a provider disappears, while a model conflict remains
an `unsupported_workflow` error.

Fresh evidence:

- `py -m unittest tests.unit.test_codex_adapter tests.integration.test_quick_cli -v`
  passed 11 tests, including the installed feature-inventory preflight, an
  enabled-feature rejection regression, and a
  fresh-process unavailable-provider rerun of a completed stub run.
- `py -m unittest discover -s tests -v` exited 0 after the remediation.
- The review findings above are resolved in their Task 4 owning files; the
  existing process-tree cleanup and crash-recovery tests remain in the full
  suite.

No new live four-stage model run was made in this remediation. The quick
research MVP release label remains unclaimed pending that demonstration and an
independent end-to-end re-review.

## Round 2/5 completed-run fixture correction

The completed-run integration regression now passes `unavailable_provider=True`
on its repeated public CLI invocation, removing `codex` from that fresh
process's `PATH`. It therefore proves the intended ordering: a persisted
completed Quick state is returned without provider discovery or launch after
the provider disappears.

## Round 3/5 provider-schema remediation

A live Codex protocol attempt reported `invalid_json_schema`: provider-facing
array properties such as `assumptions` lacked required `items` schemas. The
coordinator now emits strict JSON Schema for all four stages: every string list
has `items: {"type": "string"}`, and the Investigate Claim and Verify Check
arrays define strict nested object schemas with all fields required, typed, and
enum-bounded where applicable. The Explain and Verify enum fields are also
explicit strings.

New regression coverage verifies all top-level objects are strict, every array
has `items`, Claim/Check nested objects are strict and complete, and
`CodexAdapter.prepare()` persists the generated schema unchanged to its output
schema file. Existing blocked/interrupted workflow coverage remains in the
focused run.

Evidence:

- `py -m unittest tests.unit.test_quick_workflow tests.unit.test_codex_adapter -v`
  passed 19 tests.
- `py -m unittest discover -s tests -v` exited 0.

## Round 4/5 live-provider verification

A fresh bounded live run was executed after the schema remediation:

```powershell
py -m mathresearch init --request examples/quick-proof.json --run-dir runs/live-codex-proof-2 --json
py -m mathresearch run --run-dir runs/live-codex-proof-2 --adapter codex --timeout-seconds 180 --json
py -m mathresearch status --run-dir runs/live-codex-proof-2 --json
```

The durable run completed with four accepted stages and `report.md`. The
provider accepted the repaired strict schemas at every stage and produced the
elementary odd-sums proof. The report records `supported` only after a passing
model-reasoning verification, and discloses that no external retrieval,
experiments, or code execution occurred. This validates provider protocol and
coordinator lifecycle; it is not a claim of mathematical proof beyond the
documented model-reasoning scope.
