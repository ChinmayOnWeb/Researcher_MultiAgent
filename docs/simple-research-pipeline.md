# Simple research experiment

This separate MVP tests whether independent attempts, critique, and revision
improve answer quality. It does not establish an improvement merely by finishing.
Semantic scores remain explicitly ungraded for an independent evaluator to judge
from the final answer text.

## Architecture reduction

The historical `codex-research-quality-repair` branch and its diagnostics are
preserved at `b8b7d63`. This implementation starts from that commit on
`codex/simple-research-pipeline`. No historical engine code is changed.

Reuse is limited to `CodexAdapter` launch flags/model/effort/preflight controls,
`execute_worker` subprocess timeouts and process cleanup, and their low-level
dependencies. The simple provider overrides adapter decoding: the simple parser
interprets the original response bytes once; the launcher's old payload and
semantic fields are ignored. Offline execution imports none of those components.

The old `research` package, routing, proof contracts, provenance graphs, event
replay, materialization, and structural repair workers are bypassed. No old
research request or event objects are created.

| Module | Responsibility |
| --- | --- |
| `simple/models.py` | Two small envelopes and fixed model/effort/timeout settings |
| `simple/parsing.py` | One transport parser and conservative answer recovery |
| `simple/provider.py` | Deterministic fake provider and thin Codex launcher bridge |
| `simple/pipeline.py` | Three explicitly written condition flows and prompts |
| `simple/evaluation.py` | Generate full experiment order once, write artifacts, compare outcomes |
| `simple/cli.py` | Offline-by-default command |

| Condition | Fixed call graph | Calls when completed |
| --- | --- | ---: |
| single | answer | 1 |
| sequential | draft → critique → revision | 3 |
| pipeline | branch A + branch B → synthesis → critique → revision | 5 |

Initial answers receive the original question and shared fixed context. Both
branches receive identical prompts in separate fresh calls; execution is serial
but neither sees the other's answer. Synthesis receives both afterward. Critique
receives the question, context, and candidate. Revision receives those inputs and
the critique. Model and effort are fixed across the complete experiment. Stage
labels and call indices occur only in local metadata, not provider envelopes.

No recursive loops, adaptive allocation, model repair, or application retries
exist. Provider-internal network retries, if any, are outside this call count.
A `pass` critique still leads to the fixed revision call. A provider failure or
unusable intermediate output makes the condition incomplete. Available earlier
answers and all call artifacts remain readable. Independent branch B is still
attempted if A fails. Other experimental conditions may continue.

## Offline use

From the new worktree in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
python -m mathresearch.simple.cli evaluate --question 'Explain why sqrt(2) is irrational.' --provider fake --out-dir runs/simple-offline-smoke
python -m unittest discover -s tests/simple -v
```

The fake provider returns deterministic fixture text, not meaningful answers to
the question. A successful offline run makes nine fake invocations and zero live
provider calls. The test suite additionally exercises malformed answer envelopes,
provider failures, and the provider bridge using mocks. It never calls Terra.

For several cases, `--cases path.json` accepts a JSON list:

```json
[{"id":"example","question":"What follows?","context":"Fixed supplied evidence."}]
```

Only these three input fields are accepted, keeping grader truth out of worker
prompts. All three conditions run once per case. The complete cross-case schedule
is shuffled once with `--order-seed` (default 0) and recorded before any call in
`manifest.json`. Reading that schedule is sufficient to see the actual order.

Codex is available only with both `--provider codex` and `--live`. It defaults to
`gpt-5.6-terra`, medium effort; `--model`, `--effort`, and `--timeout-seconds`
override those settings. It uses fresh ephemeral processes with the same disabled
tool controls for all conditions. Installed CLI compatibility, authentication,
network access, and quota remain external prerequisites. They are not exercised
by offline fixtures. No live execution is part of this implementation task.

## Artifacts and interpretation

```text
run/
  manifest.json
  CASE/single/answer/{prompt.txt,raw.txt,parsed.json,semantic.txt,metadata.json}
  CASE/single/result.json
  CASE/sequential/{draft,critique,revision}/...
  CASE/sequential/result.json
  CASE/pipeline/{branch-a,branch-b,synthesis,critique,revision}/...
  CASE/pipeline/result.json
  comparison.json
```

`raw.txt` stores exact bytes, even for malformed JSON. `parsed.json` exists when
there is one parsable object, including an invalid envelope. `semantic.txt` exists
when readable output was retained. Metadata separates parse/envelope errors,
provider return/success, and semantic availability. Codex calls also preserve
stdout/stderr diagnostics and their provider scratch directory.

The parser accepts one JSON object, an ordinary JSON code fence, or one object
surrounded by prose. Competing objects, duplicate keys, nonfinite constants, and
broken outer containers are rejected. It never invents evidence or chooses among
competing answers. A complete answer string can survive a malformed surrounding
envelope; plain text is also retained. Format acceptance never checks proof
topology or decides mathematical correctness.

`status: complete` means the fixed graph returned usable output, including when
recoverable text allowed it to finish despite `protocol_valid: false`. Read both
fields. `semantic_quality` remains `ungraded`, even when protocol validity is
true. The condition result identifies the answer's producing stage so partial
answers cannot masquerade as completed revisions. Independent grading uses the
final prose; comparison artifacts make no quality claim without such grading.

Costs record provider invocations, reported calls, elapsed time, and nullable
token/cost totals. Missing telemetry stays null; fake calls are labeled `fake`.
Unexpected provider exceptions leave actual provider calls unknown rather than
inventing a zero. The provider call index is the experiment-wide invocation order.

Directories are created fresh and never resumed or overwritten by this path.
Writes happen once; there is no event replay, journal, crash recovery, or resume.
If execution dies before `comparison.json`, the run is incomplete. Persisted
files can be inspected directly. This is the intended stopping boundary of the
MVP; no further orchestration features are included.
