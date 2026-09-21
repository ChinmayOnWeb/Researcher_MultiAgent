# Task 2 fix review package

Base: c69afe5
Head: 87395cf

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md
index 7f9cd20..8a98598 100644
--- a/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md
@@ -35,3 +35,24 @@ The tests cover lossless quote/newline/Unicode intent round-trip, null-goal pres
 ## Controller decision status
 
 No `NEEDS_CONTROLLER_DECISION` was required. The specified `validate_result(role, payload)` signature has no Draft argument, so the plan's required Audit-to-Draft cross-ID validation is provided as `validate_audit_for_draft(audit, draft)`, explicitly outside generic shape validation as Section 3.2/Section 5.3 require. This leaves later router/store code able to supply the current Draft deterministically.
+
+## Round 1 review fixes
+
+Addressed every reported finding in `src/mathresearch/research/contracts.py` and added focused regressions in `tests/unit/test_research_contracts.py`.
+
+1. Draft claim `tool_ids` must now resolve to IDs in that Draft's `tool_requests`. `validate_audit_for_draft` now also requires every audit `checked_step_ids` entry to resolve to the current Draft's proof steps and every challenge `tool_ids` entry to resolve to the current Draft's tool requests.
+2. The shared recursive validator now supports `{"type": "null"}` and rejects every non-null value with `ValidationError`.
+3. `action.branch`, `action.round`, `decision.details.question_status`, `decision.details.finish_status`, and `decision.details.round` now type-check before enum membership checks. Malformed JSON collections therefore produce stable `ValidationError` fields instead of Python `TypeError`.
+4. Action dependencies are limited to 24 identifier items. Decision blockers are limited to 8 strings, each at most 4000 characters. These match the existing worker-result structural limits and normal-prose limit.
+
+### Round 1 validation evidence
+
+Targeted regressions:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_contracts.WorkerResultTests -v
+```
+
+Exit code: `0`. Result: `Ran 10 tests in 0.013s — OK`.
+
+The required focused suite was rerun after these changes; its result is recorded with the Round 1 commit.
diff --git a/src/mathresearch/research/contracts.py b/src/mathresearch/research/contracts.py
index 58f0a35..d43fa18 100644
--- a/src/mathresearch/research/contracts.py
+++ b/src/mathresearch/research/contracts.py
@@ -110,6 +110,10 @@ def _validate_shape(value: Any, schema: Mapping[str, Any], field: str) -> Any:
         return value
     if kind == "boolean":
         return require_boolean(value, field)
+    if kind == "null":
+        if value is not None:
+            raise ValidationError(field, "must be null")
+        return None
     raise RuntimeError(f"unsupported schema type {kind}")
 
 
@@ -161,7 +165,7 @@ def _validate_draft(data: dict[str, Any], role: str) -> None:
     _assert_dag(data["claims"], "claims"); _assert_dag(data["proof_steps"], "proof_steps")
     _unique_ids(data["approaches"], "approaches")
     requests = data["tool_requests"]
-    _unique_ids(requests, "tool_requests")
+    request_ids = _unique_ids(requests, "tool_requests")
     for index, request in enumerate(requests): _validate_tool_request(request, f"tool_requests[{index}]")
     for index, claim in enumerate(data["claims"]):
         prefix = f"claims[{index}]"
@@ -169,6 +173,8 @@ def _validate_draft(data: dict[str, Any], role: str) -> None:
             raise ValidationError(prefix + ".step_ids", "must refer to local proof steps")
         if any(dependency not in claim_ids for dependency in claim["depends_on"]):
             raise ValidationError(prefix + ".depends_on", "must refer to local claims")
+        if any(tool_id not in request_ids for tool_id in claim["tool_ids"]):
+            raise ValidationError(prefix + ".tool_ids", "must refer to draft tool requests")
         if claim["kind"] == "source_assertion" and not claim["citations"]:
             raise ValidationError(prefix + ".citations", "source assertions require a citation")
         if claim["kind"] == "deduction" and not (claim["step_ids"] or claim["tool_ids"]):
@@ -194,6 +200,14 @@ def validate_audit_for_draft(audit: Mapping[str, Any], draft: Mapping[str, Any])
     critical = {claim["id"] for claim in checked_draft["claims"] if claim["critical"]}
     if not critical <= {challenge["claim_id"] for challenge in checked_audit["challenges"]}:
         raise ValidationError("challenges", "must challenge every critical claim")
+    step_ids = {step["id"] for step in checked_draft["proof_steps"]}
+    tool_ids = {request["id"] for request in checked_draft["tool_requests"]}
+    for index, check in enumerate(checked_audit["checks"]):
+        if any(step_id not in step_ids for step_id in check["checked_step_ids"]):
+            raise ValidationError(f"checks[{index}].checked_step_ids", "must refer to current draft proof steps")
+    for index, challenge in enumerate(checked_audit["challenges"]):
+        if any(tool_id not in tool_ids for tool_id in challenge["tool_ids"]):
+            raise ValidationError(f"challenges[{index}].tool_ids", "must refer to current draft tool requests")
     return checked_audit
 
 
@@ -204,15 +218,13 @@ def validate_action(payload: Mapping[str, Any]) -> dict[str, Any]:
     action_id = require_identifier(data["id"], "action.id")
     kind = _enum_action(data["kind"], "action.kind", {"worker", "tool"})
     role = require_string(data["role"], "action.role")
-    branch = data["branch"]
-    if branch is not None and branch not in {"a", "b", "c"}:
-        raise ValidationError("action.branch", "must be null or one of a, b, c")
-    round_number = data["round"]
-    if isinstance(round_number, bool) or round_number not in {0, 1, 2}:
-        raise ValidationError("action.round", "must be 0, 1, or 2")
+    branch = _nullable_enum(data["branch"], "action.branch", {"a", "b", "c"})
+    round_number = _round(data["round"], "action.round")
     dependencies = data["dependencies"]
     if not isinstance(dependencies, list):
         raise ValidationError("action.dependencies", "must be an array")
+    if len(dependencies) > 24:
+        raise ValidationError("action.dependencies", "must have at most 24 items")
     checked_dependencies = [require_identifier(item, f"action.dependencies[{index}]") for index, item in enumerate(dependencies)]
     if len(checked_dependencies) != len(set(checked_dependencies)):
         raise ValidationError("action.dependencies", "must not contain duplicates")
@@ -242,24 +254,35 @@ def _enum_action(value: Any, field: str, allowed: set[str]) -> str:
     return item
 
 
+def _nullable_enum(value: Any, field: str, allowed: set[str]) -> str | None:
+    if value is None:
+        return None
+    return _enum_action(value, field, allowed)
+
+
+def _round(value: Any, field: str) -> int:
+    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1, 2}:
+        raise ValidationError(field, "must be 0, 1, or 2")
+    return value
+
+
 def validate_decision_details(payload: Mapping[str, Any]) -> dict[str, Any]:
     """Validate immutable routing metadata without accepting replacement prose."""
     data = require_object(payload, "decision.details")
     require_exact_fields(data, "decision.details", {"selected_draft_id", "audit_id", "question_status", "blockers", "finish_status", "round"})
     nullable_id = lambda value, field: None if value is None else require_identifier(value, field)
-    question_status = data["question_status"]
-    if question_status is not None and question_status not in {"answered", "open_in_sources", "unresolved", "refuted"}:
-        raise ValidationError("decision.details.question_status", "is invalid")
-    finish_status = data["finish_status"]
-    if finish_status is not None and finish_status not in {"complete", "incomplete", "blocked", "budget_exhausted"}:
-        raise ValidationError("decision.details.finish_status", "is invalid")
+    question_status = _nullable_enum(data["question_status"], "decision.details.question_status", {"answered", "open_in_sources", "unresolved", "refuted"})
+    finish_status = _nullable_enum(data["finish_status"], "decision.details.finish_status", {"complete", "incomplete", "blocked", "budget_exhausted"})
     blockers = data["blockers"]
     if not isinstance(blockers, list):
         raise ValidationError("decision.details.blockers", "must be an array")
+    if len(blockers) > 8:
+        raise ValidationError("decision.details.blockers", "must have at most 8 items")
     checked_blockers = [require_string(item, f"decision.details.blockers[{index}]") for index, item in enumerate(blockers)]
-    round_number = data["round"]
-    if isinstance(round_number, bool) or round_number not in {0, 1, 2}:
-        raise ValidationError("decision.details.round", "must be 0, 1, or 2")
+    if any(len(item) > 4000 for item in checked_blockers):
+        first = next(index for index, item in enumerate(checked_blockers) if len(item) > 4000)
+        raise ValidationError(f"decision.details.blockers[{first}]", "must be at most 4000 characters")
+    round_number = _round(data["round"], "decision.details.round")
     return {"selected_draft_id": nullable_id(data["selected_draft_id"], "decision.details.selected_draft_id"),
             "audit_id": nullable_id(data["audit_id"], "decision.details.audit_id"),
             "question_status": question_status, "blockers": checked_blockers,
diff --git a/tests/unit/test_research_contracts.py b/tests/unit/test_research_contracts.py
index cdfe631..2736a77 100644
--- a/tests/unit/test_research_contracts.py
+++ b/tests/unit/test_research_contracts.py
@@ -10,7 +10,8 @@ import unittest
 from mathresearch.contracts.research_request import ResearchRequest, build_request_payload
 from mathresearch.contracts.validation import ValidationError
 from mathresearch.research.contracts import (
-    result_schema, validate_action, validate_audit_for_draft, validate_result,
+    _validate_shape, result_schema, validate_action, validate_audit_for_draft,
+    validate_decision_details, validate_result,
 )
 
 
@@ -129,6 +130,30 @@ class WorkerResultTests(unittest.TestCase):
         with self.assertRaisesRegex(ValidationError, "checks"):
             validate_audit_for_draft(audit, valid_draft())
 
+    def test_draft_tool_ids_must_be_proposed_by_the_draft(self) -> None:
+        draft = valid_draft()
+        draft["claims"][0]["tool_ids"] = ["tool-one"]  # type: ignore[index]
+        with self.assertRaisesRegex(ValidationError, r"claims\[0\].tool_ids"):
+            validate_result("branch", draft)
+
+    def test_audit_step_and_tool_ids_must_belong_to_current_draft(self) -> None:
+        draft = valid_draft()
+        draft["proof_steps"] = [{"id": "step-one", "statement": "s", "justification": "j",
+                                  "depends_on": [], "citations": []}]
+        audit = valid_audit()
+        audit["checks"][0]["checked_step_ids"] = ["absent"]  # type: ignore[index]
+        with self.assertRaisesRegex(ValidationError, r"checks\[0\].checked_step_ids"):
+            validate_audit_for_draft(audit, draft)
+        audit = valid_audit()
+        audit["challenges"][0]["tool_ids"] = ["absent"]  # type: ignore[index]
+        with self.assertRaisesRegex(ValidationError, r"challenges\[0\].tool_ids"):
+            validate_audit_for_draft(audit, valid_draft())
+
+    def test_recursive_validator_accepts_only_json_null_for_null_schema(self) -> None:
+        self.assertIsNone(_validate_shape(None, {"type": "null"}, "value"))
+        with self.assertRaisesRegex(ValidationError, "value"):
+            _validate_shape("null", {"type": "null"}, "value")
+
     def test_fixture_records_are_available_for_downstream_contract_tests(self) -> None:
         fixture = Path(__file__).parents[1] / "fixtures" / "research" / "valid_records.json"
         records = json.loads(fixture.read_text(encoding="utf-8"))
@@ -144,6 +169,32 @@ class WorkerResultTests(unittest.TestCase):
         with self.assertRaisesRegex(ValidationError, "action.payload"):
             validate_action(action)
 
+    def test_structural_values_reject_wrong_json_types_with_validation_errors(self) -> None:
+        action = {"id": "action-one", "kind": "worker", "role": "branch", "branch": [], "round": 0,
+                  "dependencies": [], "payload": {"prompt_version": "research-v1"}}
+        with self.assertRaises(ValidationError) as raised:
+            validate_action(action)
+        self.assertEqual(raised.exception.field, "action.branch")
+        action["branch"] = None; action["round"] = []
+        with self.assertRaises(ValidationError) as raised:
+            validate_action(action)
+        self.assertEqual(raised.exception.field, "action.round")
+        details = {"selected_draft_id": None, "audit_id": None, "question_status": [], "blockers": [],
+                   "finish_status": None, "round": 0}
+        with self.assertRaises(ValidationError) as raised:
+            validate_decision_details(details)
+        self.assertEqual(raised.exception.field, "decision.details.question_status")
+
+    def test_coordinator_arrays_enforce_item_and_length_limits(self) -> None:
+        action = {"id": "action-one", "kind": "worker", "role": "branch", "branch": None, "round": 0,
+                  "dependencies": ["action-two"] * 25, "payload": {"prompt_version": "research-v1"}}
+        with self.assertRaisesRegex(ValidationError, "action.dependencies"):
+            validate_action(action)
+        details = {"selected_draft_id": None, "audit_id": None, "question_status": None,
+                   "blockers": ["x" * 4001], "finish_status": None, "round": 0}
+        with self.assertRaisesRegex(ValidationError, r"decision.details.blockers\[0\]"):
+            validate_decision_details(details)
+
 
 if __name__ == "__main__":
     unittest.main()
