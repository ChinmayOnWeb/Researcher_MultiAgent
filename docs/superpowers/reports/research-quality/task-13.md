# Task 13 report — standard-result audit and reductio schema follow-up

## Implementation

- Updated the basis guidance so drafts name each external theorem and list its application steps; audits check theorem statements, hypotheses, and applications without requiring a proof of a standard theorem.
- Added explicit structural guidance that only `local_assumption` claims may populate scope/discharge arrays and that reductio conclusions cite their discharge steps.
- Versioned the prompt as `research-v5`; v3 and v4 records continue to validate under their recorded versions, with v5 using the existing v3 basis schema.
- Added regression assertions for theorem-use guidance and v5 schema compatibility, including both v15 scope/discharge failure shapes.

## Verification

- `PYTHONPATH=src python -m unittest tests.unit.test_research_prompts tests.unit.test_research_contracts tests.unit.test_research_routing tests.unit.test_research_events -q` — 73 passed.
- `python -m compileall -q src/mathresearch/research` — passed.
- `git diff --check` — passed; Git emitted only existing line-ending conversion warnings.

## Live evidence

- v13 (research-v3 prompt): baseline 10/10, sequential 10/10, pipeline 7/10; all schema-valid. Astra identified a genuine mismatch: the pipeline invoked the Division Algorithm but described its dependency as the Well-Ordering Principle.
- v14 (research-v4 prompt): preserved as a failed default-sandbox attempt; Windows denied worker temporary-directory access.
- v15 retry (research-v4 prompt): baseline, sequential, and pipeline each scored 10/10 semantically. Only sequential review passed schema validation. Baseline omitted a reductio discharge reference; pipeline put scope/discharge fields on a non-local assumption. Actual use was 8 calls and 265.69 seconds under the 17-call / 2,010-second cap.
- Every live arm used GPT-5.6 Terra at medium effort. No token/cost totals or account usage percentages are available or were polled. The v5 prompt has not been provider-tested.

## Next

Repair the two structured-output failure patterns and verify them with offline fixtures. Then preregister and run a fresh, balanced development calibration under an explicit machine-readable envelope. Do not treat these one-case comparisons as general evidence or proceed to held-out cases yet.
