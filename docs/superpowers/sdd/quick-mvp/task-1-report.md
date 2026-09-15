# Quick MVP — Task 1 report

## Remediation (2026-09-14)

- Moved verified top-level Codex flags before `exec`.
- Moved stdin delivery to a daemon writer, so launch-time timeout covers a
  16 MiB prompt even when the child never consumes stdin.
- Reject result-file directory entries via `lstat` before launch (including
  dangling links) and use a descriptor-backed bounded final-result read.
- Codex 0.154.0 is now explicitly unavailable for the reasoning-only MVP:
  its read-only sandbox does not natively disable shell execution. Adapter
  preflight and discovery reject the profile rather than making that claim.
- Declared pointer-safe Windows Job Object ctypes signatures. If Job creation
  or assignment is not confirmed, timeout cleanup is reported as unconfirmed
  (`cancelled`), preventing automatic relaunch.

## Scope delivered

- Added provider-neutral `WorkerInput`, `LaunchSpec`, `WorkerOutput`, and `Adapter` contracts.
- Added argv-only `execute_worker` with scratch/result-path validation, strict result decoding boundary, 8 MiB bounded stdout/stderr retention, 1 MiB final-result limit, timeout handling, and process-tree teardown.
- Added `CodexAdapter` and an explicit live-only smoke entry point:
  `py -m mathresearch.adapters.codex_smoke --live`.
- Left fake runner, dispatch, durable contracts/store, and CLI unchanged.

## Local preflight evidence (2026-09-14)

- `codex` resolved to `C:\Users\Chinmay\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe`.
- `codex --version` reported `codex-cli 0.154.0`.
- `codex exec --help` verified: stdin prompt (`-`), `--ask-for-approval`, `--sandbox`, `--skip-git-repo-check`, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--model`, `--output-schema`, and `--output-last-message`.
- `claude` also resolved to `C:\Users\Chinmay\.local\bin\claude.exe`; `claude --version` reported `2.1.237 (Claude Code)`. It was inspected only for availability and was not substituted.

The observed Codex argv uses only those verified flags. `--ignore-user-config`
and `--ignore-rules` prevent configured MCP servers and rule files from being
loaded; no `--search` flag is supplied; and the sandbox is read-only. Codex
still has read-only shell access, so it must not be used for this MVP profile.

## Verification

```
$env:PYTHONPATH='src'; $env:TEMP=(Resolve-Path '.'); $env:TMP=$env:TEMP;
py -m unittest tests.unit.test_worker_process tests.unit.test_codex_adapter -v

Ran 14 focused tests ... OK
```

Coverage includes dedicated result-file parsing, malformed JSON, nonzero exit,
bounded captures, a non-reading stdin child, timeout, spawned-descendant
cleanup, dangling-link and scratch escape refusal, Windows Job declarations,
capability refusal, and exact locally verified Codex argv construction.

## Live smoke status

The smoke harness is intentionally opt-in and was **not invoked** during ordinary
tests. It currently refuses the mandatory capability preflight, which is the
correct behavior until a provider has native no-shell controls.
