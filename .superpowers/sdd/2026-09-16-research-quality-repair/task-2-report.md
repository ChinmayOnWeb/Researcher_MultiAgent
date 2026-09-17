# Task 2 implementation report

Implemented the version-three request and worker-result contract boundary without changing legacy v1 request/Quick schemas or any `runs/` evidence.

## Delivered files

- `src/mathresearch/contracts/research_request.py`
  - Strict `ResearchRequest` and `SourceInput` parsing/serialization.
  - Exact required keys, rejection of unknown keys, non-coercing boolean/integer checks, profile budget caps, explicit model and effort, Quick capability denial, and source descriptor validation.
  - `build_request_payload(...)` profile defaults preserve supplied question/goal/context/constraints byte-for-character at the Python string level; it sets `goal` to `null` unless supplied.
- `src/mathresearch/research/__init__.py`
- `src/mathresearch/research/contracts.py`
  - Shared strict schema constructors: `obj`, `arr`, `enum`, `text`.
  - Recursive schema validator with strict nested objects and typed arrays.
  - Role schemas and `validate_result` for Frame, Draft roles, and Audit.
  - Internal Draft graph checks, role-specific change-log rules, typed operation argument checks, and external `validate_audit_for_draft` for checks/challenges that require the current Draft.
  - Section 6 Action and DecisionDetails structural validators for subsequent event/store work.
- `tests/unit/test_research_contracts.py`
- `tests/fixtures/research/valid_records.json`

## Validation evidence

The requested focused command was run with `PYTHONPATH=src` because this isolated worktree has no editable `mathresearch` installation and package installation was prohibited:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_contracts tests.unit.test_contracts tests.unit.test_quick_records -v
```

Exit code: `0`.

Result: `Ran 17 tests in 0.030s — OK`.

The tests cover lossless quote/newline/Unicode intent round-trip, null-goal preservation, builder defaults, missing/unknown request fields, boolean budget rejection, profile caps, unsupported high-stakes/learning requests, malformed source URLs, Quick broker permissions, strict coordinator-field rejection, Draft DAG/cross-ID rejection, Audit/Draft cross-reference rejection, shared fixtures, and legacy v1/Quick regression checks.

## Controller decision status

No `NEEDS_CONTROLLER_DECISION` was required. The specified `validate_result(role, payload)` signature has no Draft argument, so the plan's required Audit-to-Draft cross-ID validation is provided as `validate_audit_for_draft(audit, draft)`, explicitly outside generic shape validation as Section 3.2/Section 5.3 require. This leaves later router/store code able to supply the current Draft deterministically.

## Round 1 review fixes

Addressed every reported finding in `src/mathresearch/research/contracts.py` and added focused regressions in `tests/unit/test_research_contracts.py`.

1. Draft claim `tool_ids` must now resolve to IDs in that Draft's `tool_requests`. `validate_audit_for_draft` now also requires every audit `checked_step_ids` entry to resolve to the current Draft's proof steps and every challenge `tool_ids` entry to resolve to the current Draft's tool requests.
2. The shared recursive validator now supports `{"type": "null"}` and rejects every non-null value with `ValidationError`.
3. `action.branch`, `action.round`, `decision.details.question_status`, `decision.details.finish_status`, and `decision.details.round` now type-check before enum membership checks. Malformed JSON collections therefore produce stable `ValidationError` fields instead of Python `TypeError`.
4. Action dependencies are limited to 24 identifier items. Decision blockers are limited to 8 strings, each at most 4000 characters. These match the existing worker-result structural limits and normal-prose limit.

### Round 1 validation evidence

Targeted regressions:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_contracts.WorkerResultTests -v
```

Exit code: `0`. Result: `Ran 10 tests in 0.013s — OK`.

The required focused suite was rerun after these changes; its result is recorded with the Round 1 commit.
