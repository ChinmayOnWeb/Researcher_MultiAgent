### Task 2: Implement strict request, evidence, draft, audit, and packet contracts

**Files:** create `contracts/research_request.py`, `research/__init__.py`, `research/contracts.py`, `tests/unit/test_research_contracts.py`, `tests/fixtures/research/valid_records.json`.

**Consumes:** Sections 3 and 5. **Produces:** ResearchRequest, role schemas/validators, Action/Decision structural definitions (Section 6), shared valid fixtures.

- [ ] Write failing exact-intent test with newline/quotes/Unicode; verify from_json/to_json preserves fields without stripping. Test no goal injection when null.
- [ ] Write strict validation cases: bool budgets, excessive caps, unknown capability, missing model/effort, unknown fields, high-stakes/learning request, >6 sources, malformed URL descriptor, Quick tool permissions. Assert stable ValidationError fields, not generic exceptions.
- [ ] Implement defaults in `build_request_payload(...)` for the CLI builder; file-based parser accepts no missing required fields. Keep v1 SCHEMA_VERSION unchanged.
- [ ] Implement reusable schema declarations and recursive validator for object/array/string/integer/boolean/null/enum with explicit field limits. Add graph/cross-ID checks outside generic shape checks. Unknown keys always rejected.
- [ ] Add exact Draft/Audit/Frame fixtures and invalid variations (missing critical claim, duplicate IDs, empty claims, cyclic steps, nonexistent audit claim).

```python
def test_intent_roundtrip_is_lossless(self):
    payload = valid_request_payload()
    payload["question"] = 'Are there any odd numbers that are "perfect"?\nExplain π-related analogies only if relevant.'
    payload["goal"] = None
    self.assertEqual(ResearchRequest.from_json(payload).to_json(), payload)

def test_model_output_cannot_supply_coordinator_fields(self):
    draft = valid_draft()
    draft["run_status"] = "complete"
    with self.assertRaises(ValidationError):
        validate_result("branch", draft)
```

- [ ] Run `py -m unittest tests.unit.test_research_contracts tests.unit.test_contracts tests.unit.test_quick_records -v`. Verify every provider array has typed items and every nested object is strict. Commit.

