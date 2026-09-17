# Task 4 report: substantive prompts and blind packets

## Delivered

Created `src/mathresearch/research/prompts.py` with `PROMPT_VERSION = "research-v1"`, `build_packet`, and `build_prompt`.

`build_packet` accepts only the supplied `ResearchRequest`, `ResearchSnapshot`, and validated worker Action. It creates the exact required top-level packet keys, copies only canonical JSON-compatible values, applies the request's `max_input_bytes` limit before an execution intent can be recorded, and rejects an oversize packet instead of truncating it. It does not read run files, history, rubrics, or any ambient state.

Role inputs are restricted to the Task 4 matrix:

- answer and frame receive `{}`;
- branch a receives only Frame `deliverables` and `subquestions`;
- branch b receives `{}`;
- branch c receives only Audit `missing_evidence` as `targeted_obligations`;
- synthesis receives dependency-addressed branch outputs;
- audit and revise receive the selected current Draft and, for revise, the selected Audit.

The source catalog begins with the original request descriptors and overlays the Snapshot's captured source records by source ID. This preserves raw request sources while retaining the durable captured evidence projection. Tool receipts come only from `snapshot.tool_results`.

`build_prompt` strict-validates the exact packet envelope, role schema, and allowed input shape before appending canonical packet JSON after the required literal COMMON and role-specific instruction content. Branch b receives the explicit independent-approach instruction; branch c receives the required another-route instruction. No legacy quick-workflow `_prompt()` code changed.

## Tests

Created `tests/unit/test_research_prompts.py` with seven tests covering:

1. Exact packet keys, role inputs, versions, and output schemas for all roles and branch variants.
2. Blind branch b exclusion of a sentinel false Frame/branch-a answer while retaining original request and source data.
3. Source instruction injection preserved solely as source text, without packet permissions or command fields.
4. Rejection of hidden Action and packet fields.
5. Rejection before intent when canonical packet bytes exceed `max_input_bytes`.
6. Distinct substantive prompt markers for every worker role.
7. Audit selection of a revised Draft as the current Draft after repair.

The tests were written before implementation. The first configured red run failed because `mathresearch.research.prompts` did not exist. A later red run demonstrated the repaired-Draft regression before extending the dependency selector. The repository requires `PYTHONPATH=src`; the unqualified command cannot import the src-layout package.

Final focused verification:

```powershell
$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_prompts -v
```

Result: `Ran 7 tests ... OK`.

## Concern for downstream integration

The Task 3 `ResearchSnapshot` contract currently has no durable `additional_user_input` collection. To preserve the authoritative Snapshot boundary, Task 4 emits the required `additional_user_input` key as an empty list and does not reconstruct gate text from ambient event history or run files. The Section 7.4 requirement to append supplied gate text needs a future Snapshot projection or an explicit immutable packet input from the owner of gate routing; Task 4 must not infer it outside the supplied contract.
