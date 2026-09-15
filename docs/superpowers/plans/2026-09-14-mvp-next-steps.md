# Real CLI Quick Research MVP Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the independent tasks below, following the user's established delegation preference. Task 1 and Task 2 can run concurrently; integrate once, then independently review the working product. Do not turn every helper into a separate milestone.

**Goal:** A user supplies a question, runs one command, and receives a durable research report produced by four fresh installed-agent CLI processes, with restart recovery and explicit verification limitations.

**Architecture:** Keep the accepted fake Frame lifecycle compatible. Add a small, fixed quick workflow (`frame -> investigate -> verify -> explain`) and one real provider first. The Python coordinator owns scheduling, packets, acceptance, budgets, and completion; each CLI process only returns a bounded stage result.

**Tech Stack:** Python >=3.11, standard library, existing unittest suite, installed and authenticated agent CLI.

**Spec:** `docs/research-pipeline-design.md`, especially its Quick mode and coordinator-owned execution boundary. This is an explicitly narrowed first product slice of that broader design, not a claim that all ten phases are implemented.

## Recommendation and finish line

The next release should produce a report, not stop after a real Frame response. Use Codex as the first provider if its installed executable supports the required noninteractive interface; use Claude first only if that local check fails. Supporting both providers is not on the critical path.

Deliver these two observable checkpoints within the same implementation:

1. First real stage: a normal installed CLI returns a validated Frame payload through the common process runner.
2. MVP: one invocation launches the four stages, writes `report.md`, reports `complete`, and repeats without launching another process.

A valid MVP demo question is: "Prove that the sum of the first n odd positive integers is n squared, using an algebraic argument and a geometric interpretation." Supplied context and reasoning are sufficient for this slice. The report must label checks as model reasoning rather than code execution or external verification.

## Global constraints

- Python floor remains `>=3.11`; runtime dependencies remain `[]`.
- Preserve the current fake command, stored version-one histories, and existing tests. The prior review reports 101 passing tests; that is historical evidence, not fresh verification for this plan.
- MVP execution supports `mode=quick`, `stakes=ordinary`, `learning_mode=false`. Reject unsupported modes/stakes/learning mode before any provider call, with an actionable error. Never silently downgrade a research request or skip a required human gate.
- MVP provider capability profile is reasoning over coordinator-supplied text. Browsing, file mutation, shell tools, and experiment execution are disabled. Reject requests requiring unavailable capabilities before launch. Native CLI configuration must enforce tool restrictions; a sentence in a prompt is not enforcement.
- Worker processes use a fresh context, no session-resume flag, and a scratch working directory outside the authoritative run tree. Run contents are supplied in the packet. Do not claim model-family independence when the same provider serves every stage.
- Keep the OS run lock across an invocation for this release. A simultaneous `status` or `run` may report `run_locked`; do not invent live progress from an unlocked stale snapshot.
- No daemon, app dashboard, provider-native subagent dependency, plugin system, database, or generalized scheduling engine is needed to ship this release.
- This workspace has no Git repository according to earlier inspection; do not make commits or worktree setup a prerequisite.

## Public interface

Keep `init`, `status`, `doctor`, and `dispatch --adapter fake` unchanged. Add one foreground orchestration command:

```powershell
$env:PYTHONPATH = 'src'
py -m mathresearch init --request examples/quick-proof.json --run-dir runs/proof --json
py -m mathresearch run --run-dir runs/proof --adapter codex --timeout-seconds 180 --json
py -m mathresearch status --run-dir runs/proof --json
Get-Content runs/proof/report.md
```

`run` starts or resumes a newly initialized quick run. Repeating it after completion performs no provider calls. A successful machine response is:

```json
{"run_status":"complete","accepted_submission_count":4,"report_path":"<absolute run directory>/report.md"}
```

Optional `--model NAME` is forwarded through a provider-specific argument, never interpolated into a shell string. The chosen provider, executable path, model selection, output protocol, and effective capabilities are recorded before the first attempt. If the provider chooses its own default model, persist `model=null` and disclose that the exact model is not known unless its output identifies it. A later resume with a conflicting explicitly supplied adapter/model fails before launch.

`run` outputs each stage transition to stderr in human mode; JSON mode emits only the final response/error on its respective stream. The foreground command works in an ordinary terminal. Backgrounding that terminal process is up to the caller; this milestone does not add a background service.

Use existing exit codes where applicable: success `0`, invalid invocation `20`, and the existing blocked/cancelled/storage codes from `errors.py`. Add stable error codes `unsupported_workflow`, `adapter_unavailable`, `adapter_protocol_error`, `workflow_blocked`, and `budget_exhausted` without changing established fake-command errors.

New real workflow runs begin from initialization-only histories. If a legacy fake Frame attempt already exists, `run` reports `unsupported_workflow` and asks the caller to initialize a new run; do not reinterpret a fake answer as a real worker's answer.

## Shared implementation contracts

Define the following in `src/mathresearch/adapters/base.py`. These types intentionally do not depend on the durable store, allowing Task 1 and Task 2 to work independently.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

@dataclass(frozen=True)
class WorkerInput:
    stage: str
    prompt: str
    output_schema: Mapping[str, Any]

@dataclass(frozen=True)
class LaunchSpec:
    argv: tuple[str, ...]
    stdin: bytes
    cwd: Path
    result_file: Path | None

@dataclass(frozen=True)
class WorkerOutput:
    outcome: str  # succeeded, failed, timed_out, cancelled, launch_failed
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    payload: Mapping[str, Any] | None
    error: str | None

class Adapter(Protocol):
    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec: ...
    def decode(self, stdout: bytes, result_bytes: bytes | None) -> Mapping[str, Any]: ...

def execute_worker(adapter: Adapter, task: WorkerInput,
                   *, scratch: Path, timeout_seconds: int) -> WorkerOutput: ...
```

`execute_worker` belongs in new `src/mathresearch/worker_process.py`; leave `process_runner.py` as the compatibility implementation for fake Frame until a safe later consolidation is useful. Its result contains provider output, not authority to append events or complete a task. The coordinator stamps task IDs, attempt numbers, and timestamps instead of asking a model to manufacture them.

For new workflows, use schema version two on new workflow records only; do not change the global version-one request constant. Introduce `QuickState` in `contracts/quick.py` and let public `load_run_status` return `RunState | QuickState`. Version-one histories keep their existing projection and serialized output. `QuickState` has `run_id`, `initialized_at`, `status`, `last_event_sequence`, `accepted_submission_count`, `current_stage`, `reason`, and `report_path`, with explicit nullable fields.

Use `WorkflowEvent` with common exact fields `schema_version`, `record_type`, `sequence`, `event_type`, `run_id`, `occurred_at`, `body`. Validate `body` separately for every event discriminator; reject unknown keys and invalid transitions. Keep old event parsers available.

New event types and exact bodies:

| Event | Body fields |
| --- | --- |
| `quick_configured` | `adapter`, `executable`, `model`, `protocol_version`, `capabilities`, `stages` |
| `quick_attempt_intended` | `stage`, `attempt`, `packet` |
| `quick_attempt_finished` | `stage`, `attempt`, `outcome`, `exit_code`, `stdout_sha256`, `stderr_sha256`, `result`, `error` |
| `quick_stage_accepted` | `stage`, `attempt` |
| `quick_stopped` | `status`, `reason` |
| `quick_completed` | `report_markdown` |

Allowed stages are exactly `frame`, `investigate`, `verify`, `explain`. MVP uses attempt `1` for each; automatic retries are deferred. `result` is the validated stage payload or null. A zero exit code with invalid payload is `failed` with a protocol error, never accepted. Acceptance references the successful finished event for that stage; it cannot introduce different content. `quick_completed` is legal only after all four acceptances and an eligible verification disposition.

The packet object has exact fields `stage`, `request`, `inputs`, `output_schema`, `capabilities`. `inputs` contains only accepted prerequisite stage payloads selected by the fixed workflow. Persist this packet in intent, so its materialization is derivable after a restart.

Stage payloads:

- Frame: reuse the six-field `frame` body from `FrameSubmission`: `framed_question`, `success_criteria`, `terms`, `assumptions`, `missing_inputs`, `stakes_assessment`. Strings and arrays follow the current strict validators. Nonempty missing inputs block downstream work. Stakes requiring escalation block this MVP rather than overriding the request.
- Investigate: `{answer: string, claims: [Claim], alternatives: [string], limitations: [string]}`. A Claim has exact fields `{id: string, statement: string, basis: "supplied"|"derived"|"inferred"|"unknown", support: string}`. IDs must be unique; support is an exact supplied-text excerpt or a written derivation, and is explicitly not an externally verified citation.
- Verify: `{checks: [Check], disposition: "pass"|"inconclusive"|"fail", limitations: [string]}`. A Check has `{claim_id: string, verdict: "supported"|"unsupported"|"contradicted", reasoning: string}`. Every investigative claim has exactly one check; reject unknown/duplicate claim references. Any contradicted claim requires `fail`. Any unsupported claim prevents `pass`. `inconclusive` permits an explicitly inconclusive final report.
- Explain: `{summary: string, explanation: string, conclusion: "supported"|"inconclusive", limitations: [string]}`. Reject a supported conclusion after inconclusive verification. The final Markdown also renders the accepted claims, alternatives, and checks directly so Explain cannot hide them.

## Task 1: Real provider boundary and a verified Frame smoke

**Files:** Create `adapters/base.py`, `adapters/codex.py`, `worker_process.py`, `tests/unit/test_worker_process.py`, `tests/unit/test_codex_adapter.py`. Modify `adapters/discovery.py` only if necessary to expose internal executable resolution while retaining doctor output compatibility.

**Consumes:** `WorkerInput` described above; the existing Frame body definition.

**Produces:** `CodexAdapter(executable: Path, model: str | None = None)` implementing Adapter, and `execute_worker(...) -> WorkerOutput`.

- [ ] Inspect installed `codex exec --help` and `codex --help`; record the exact tested version and flags. Resolve a native executable or an explicit trusted Node entrypoint on Windows. Do not depend on shell execution of `.cmd` wrappers or interpolate request text into command arguments.
- [ ] Write a stub child test that reads its prompt from stdin and emits a chosen result, with branches for valid output, malformed JSON, nonzero exit, timeout, and a spawned grandchild. Verify the timeout kills the entire process group/tree and preserves bounded captures.
- [ ] Implement argv-based subprocess launching with `shell=False`, binary capture, a hard timeout, and bounded output (8 MiB stdout, 8 MiB stderr, 1 MiB structured result). On POSIX use a new process session and terminate its group. On Windows use an owned Job Object or a tested equivalent that includes descendants; verify child-tree cleanup before treating cancellation as finished. If teardown cannot be confirmed, return a blocked execution outcome and do not relaunch.
- [ ] Build the Codex noninteractive command using its locally verified flags. Preferred shape is `codex --ask-for-approval never --sandbox read-only exec --skip-git-repo-check --ephemeral --output-schema SCHEMA --output-last-message RESULT -`, with prompt bytes on stdin. Supply only flags verified on the installed version. Disable execution tools and external MCP tools through supported local configuration; verify these controls with help/config evidence before advertising the capability profile.
- [ ] Parse the dedicated final result file as strict JSON, with duplicate-key/nonfinite rejection. Treat stdout as diagnostic provider output, not automatically as the research JSON. Keep final result handling inside the scratch directory, rejecting linked/reparse/nonregular files and oversized output.
- [ ] Add an explicit, opt-in live smoke harness that submits the six-field Frame schema and a harmless mathematical question. It must make one model call, print success/failure and provider version, and never run in ordinary unit tests. A real provider smoke is required before advertising installed-provider support; missing auth is a documented blocker, not a passing test.

Suggested failing assertion for the protocol boundary:

```python
self.assertEqual(output.outcome, "failed")
self.assertIsNone(output.payload)
self.assertEqual(output.stdout, b"not-json")
```

Run: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_worker_process tests.unit.test_codex_adapter -v`.

## Task 2: Fixed quick-workflow contracts and durable storage

**Files:** Create `contracts/quick.py`, `tests/unit/test_quick_records.py`, `tests/unit/test_quick_store.py`. Modify `contracts/run.py`, `run_store.py`, and focused compatibility tests as required.

**Consumes:** Exact event/state/stage contracts above; existing initialization event and `LockedRun` append boundary.

**Produces:** `WorkflowEvent.from_json/to_json`, `QuickState.from_json/to_json`, `replay_quick_events(events) -> QuickState`, and store support for mixed version-one initialization plus version-two quick events.

- [ ] Write hand-authored event fixtures for initialization, configuration, four attempt/finish/accept sequences, and completion. Assert premature completion, phase reordering, duplicate acceptance, altered accepted data, malformed references, and mixed legacy Frame/quick histories are rejected.
- [ ] Implement exact-key validation and the small pure reducer. `quick_configured` must follow initialization. The accepted count is derived from acceptances; only the reducer permits `complete`, `blocked`, or `budget_exhausted`.
- [ ] Extend store type dispatch and strict layout checking without weakening the existing fake layout. Derive allowed stage/attempt directories from committed intent records. Every existing directory must be checked even when another expected directory is absent.
- [ ] Materialize each stage under `tasks/task-<stage>/attempts/attempt-<stage>-001/packet.json`, captures under the same attempt directory, accepted stage output as `tasks/task-<stage>/accepted.json`, and final `report.md` from `quick_completed.report_markdown`. Add only these documented files and writer temporary names to the allowlists.
- [ ] Add a checked `LockedRun.write_capture(stage: str, attempt: int, name: str, data: bytes) -> str` returning a SHA-256 hex digest. Accept only `stdout.bin` and `stderr.log` for a committed intended attempt, preserve ancestry/link checks, and publish captures atomically before the finished event. The normalized result in the finished event is authoritative for recovery; captures are retained diagnostics.
- [ ] Test missing projections, unchanged-state nonrewrite, corrupt later event preventing every repair, unsafe capture/attempt ancestry, and old fake initialization/dispatch/status compatibility. New quick state must deserialize without rewriting or invalidating old version-one state output.

Suggested failing reducer assertion:

```python
with self.assertRaises(ValidationError):
    replay_quick_events(events_through_frame_acceptance + [complete_event])
```

Run: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_quick_records tests.unit.test_quick_store tests.unit.test_run_store -v`.

## Task 3: Connect four real stages, recovery, and report generation

**Files:** Create `quick_workflow.py`, `reporting.py`, `tests/unit/test_quick_workflow.py`, `tests/unit/test_reporting.py`. Keep `dispatch.py` compatibility intact.

**Consumes:** Task 1's Adapter/execute_worker, Task 2's WorkflowEvent/QuickState and LockedRun.

**Produces:** `run_quick(run_dir: Path, adapter: Adapter, *, adapter_id: str, executable: Path, model: str | None, timeout_seconds: int = 180) -> QuickState`; `render_quick_report(request: RunRequest, accepted: Mapping[str, Mapping[str, Any]]) -> str`.

- [ ] Test the complete fixed graph with an injected stub adapter: exactly four process calls in order, exactly four acceptances, report completion, and zero extra calls when run again. Frame receives request only; Investigate receives request/Frame; Verify receives request/Frame/Investigate; Explain receives all accepted inputs.
- [ ] Implement provider preflight and supported-request validation before configuration/intent. Persist configuration once. Build role prompts and stage JSON schemas in Python, supply accepted inputs as data, and prohibit a worker result from issuing coordinator commands or setting completion state.
- [ ] For each stage: enforce budgets, append intent and packet, execute in scratch, validate output, durably write captures, append a finished event containing normalized output/error, then append acceptance. Keep coordinator IDs/timestamps outside worker-authored content.
- [ ] Recover successful finished-but-unaccepted stages from the persisted finished result, without decoding changing provider logs or launching a replacement. If an intent lacks a finished event, report blocked interruption and do not rerun it. Failed/malformed/timeout/cancelled execution stops with an actionable reason and preserved capture files.
- [ ] Enforce `max_accepted_submissions` before each next stage and configured elapsed time from the persisted initialization timestamp; per-call timeout is the smaller remaining deadline. No elapsed budget means only the per-call bound. A four-stage run with accepted budget below four cannot become complete. Record `budget_exhausted` before another launch. No implicit retries or revision cycles are performed in this MVP.
- [ ] Block on Frame missing inputs, escalated stakes, or failed Verify. For inconclusive Verify, permit only an inconclusive Explain. Add crash-injection tests at intent, capture publication, outcome, acceptance, and final report materialization.
- [ ] Render Markdown deterministically: question; conclusion; explanation; claims and support; alternatives; verification checks; missing evidence; capability/provider disclosures. Append mandatory disclosures from the coordinator: no external retrieval or executed experiments, same-provider reviewers when applicable, and unknown cost/token usage. An interrupted report write is repairable from the completed event.

Suggested recovery assertion:

```python
state = run_quick(run_dir, adapter, adapter_id="codex", executable=executable, model=None)
self.assertEqual(adapter.calls, ["investigate", "verify", "explain"])
self.assertEqual(state.status, "complete")
```

Here the fixture already contains a successful Frame finished event but no Frame acceptance; the assertion proves Frame was not relaunched.

Run: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_quick_workflow tests.unit.test_reporting -v`.

## Task 4: CLI, worked example, integration review, release gate

**Files:** Modify `cli.py`, `README.md`, `docs/research-pipeline-design.md`; create `examples/quick-proof.json`, `tests/integration/test_quick_cli.py`, and `tests/integration/__init__.py`.

**Consumes:** `run_quick(...)`, `QuickState`, and the provider resolver.

**Produces:** Documented `mathresearch run` lifecycle and one real request-to-report demonstration.

- [ ] Register `run --run-dir PATH --adapter codex [--model NAME] [--timeout-seconds N] [--json]`. Default timeout is 180 seconds. Validate unsupported adapter/options consistently and preserve old init/status/doctor/fake behavior.
- [ ] Add the ordinary quick example with all existing version-one request fields, `learning_mode=false`, no enabled external capabilities, and budgets allowing four accepted submissions. Create the parent `runs` directory in the README setup command because existing `init` does not create missing parents.
- [ ] Test fresh-process `init -> run -> status -> report` through a stub provider executable. Test unavailable provider, invalid structured output, conflicting resume options, unsupported request modes, rejected verification, budget exhaustion, interrupted intent, and completed-run no-op. Stub launch counts are observable outside the CLI process.
- [ ] Run the full suite once after integration, using workspace-local TEMP/TMP as already documented. Fix actual regressions, then rerun affected tests; repeat the full suite only if final changes justify it.
- [ ] Perform one real, bounded four-stage demonstration with the installed authenticated CLI. Inspect report content against the elementary proof question and confirm four distinct fresh process invocations and a no-op second `run`. Record provider version, command, result, and limitations in the implementation report. Do not equate schema acceptance with research accuracy.
- [ ] Obtain one independent end-to-end review of the integrated slice, including crash recovery, provider tool restrictions, process-tree cleanup, and truthful report status. Resolve findings within their owning task and re-review changed areas. Do not gate unrelated independent task work on repeated broad reviews.
- [ ] Update README to lead with the working request-to-report commands and list the remaining product limitations. Update stale architecture paragraphs describing initialization-only recovery. Call the release "quick research MVP" only after the real demonstration and review succeed.

## Parallel execution and critical path

```text
Task 1: provider + runner ─┐
                         ├─ Task 3: four-stage coordinator ─ Task 4: CLI/demo/review
Task 2: contracts/store ──┘
```

Task 1 owns provider/process files. Task 2 owns new durable contracts and store changes. Freeze shared contracts in this document before delegation. Task 3 starts after their focused tests pass. Task 4's README/example preparation can begin after the interface is frozen, but integration tests and live demonstration depend on Task 3.

One implementer per owning task; one independent integrated reviewer. Review the real-provider boundary early if it exposes an execution-control question, but do not repeat the old pattern of several serial milestones before the user can obtain any report. Start agents once and use their completion notifications; do not continuously poll background workers.

## Immediately after the MVP

1. Add Claude using the same Adapter interface and the same four-stage acceptance suite. Verify its installed noninteractive and structured-output flags, tool restrictions, and fresh-session behavior rather than assuming Codex semantics.
2. Add a generic command adapter configured by an explicit argv array; stdin is the coordinator prompt/schema packet, stdout is exactly one structured JSON payload, stderr is diagnostics. Require declared capabilities and reject shell-string configurations. Do not pretend every arbitrary CLI already speaks this protocol.
3. Add human response/recovery commands and bounded retries. These unlock missing-input continuation, significant/high-stakes checkpoints, and learning mode without silent bypass.
4. Add supplied-file/retrieved-source evidence and genuinely executed checks, then Deep/Research modes, independent investigative branches, and all ten phases.

Defer provider-native subagents, concurrent process scheduling, generalized task DAGs, automatic model routing/fallback, monetary estimates without provider usage data, background dashboards, package publishing, and full benchmark suites until the complete quick slice works.

## Acceptance checklist

- [ ] An installed real agent CLI runs all four stages from one foreground command.
- [ ] The coordinator, not the model or a skill, selects and starts each stage process.
- [ ] A readable report and durable complete state exist; a repeated run makes zero model calls.
- [ ] Crash after recorded successful outcome resumes without duplicating that stage.
- [ ] Crash with ambiguous launch intent is visibly blocked.
- [ ] Failed/inconclusive verification and unavailable capabilities are honestly reflected.
- [ ] Existing fake lifecycle and historical run formats still work.
- [ ] Focused tests, final integrated tests, live demonstration, and independent review have evidence.
