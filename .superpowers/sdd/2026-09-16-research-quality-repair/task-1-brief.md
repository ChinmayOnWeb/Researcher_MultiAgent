# Task 1: Freeze quality requirements and regression/evaluation fixtures

**Files:** create `tests/fixtures/research/observed_circular_support.json`, `evals/research-quality/cases.json`, `evals/research-quality/rubric.md`, `tests/unit/test_research_cases.py`.

**Consumes:** Sections 2 and 11; historical report files. **Produces:** eight exact case records, synthetic source snapshots, independent grading instructions.

- [ ] Record current HEAD/status and original reports' hashes in task report. Preserve runs and ignored artifacts. Work on `research-quality-repair` branch/worktree under workspace with user files preserved; no main-branch implementation.
- [ ] Create sanitized circular-support fixture from selected real fields. Include `expected_failure="agent_output_is_not_evidence"` and raw context.
- [ ] Create all eight case records using Section 11 text, objectives/modes, obligations, forbidden claims, and tool expectations. Give each at least one forbidden failure condition.
- [ ] Add dataset tests: IDs unique; exactly eight; every obligation/forbidden list nonempty; source-conflict has two opposing notes; raw odd-perfect question not replaced with a concise-summary goal.

```python
def test_cases_include_quality_failures_not_just_happy_path(self):
    cases = load_cases()
    self.assertEqual(len(cases), 8)
    self.assertEqual(len({case["id"] for case in cases}), 8)
    by_id = {case["id"]: case for case in cases}
    self.assertIn("division by zero", " ".join(by_id["false-cancellation"]["expected_obligations"]))
    self.assertEqual(len(by_id["source-conflict"]["sources"]), 2)
```

- [ ] Run `py -m unittest tests.unit.test_research_cases -v`; commit only fixture/rubric/tests after review. No live calls. Astra checks that benchmarks do not reward formatting or predetermine open-problem resolution.
