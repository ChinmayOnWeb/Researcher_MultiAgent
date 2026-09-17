"""Strict contracts for the version-three research workflow."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from mathresearch.contracts.research_request import ResearchRequest, build_request_payload
from mathresearch.contracts.validation import ValidationError
from mathresearch.research.contracts import (
    _validate_shape, result_schema, validate_action, validate_audit_for_draft,
    validate_decision_details, validate_result,
)


def valid_request_payload() -> dict[str, object]:
    return {
        "schema_version": 3, "record_type": "research_request", "run_id": "odd-perfect-run",
        "question": "Are there any odd perfect numbers?", "goal": "Investigate carefully.",
        "context": None, "constraints": [], "audience": "unspecified", "objective": "investigate",
        "mode": "deep", "stakes": "ordinary", "learning_mode": False,
        "provider": {"adapter": "codex", "model": "gpt-test", "reasoning_effort": "high"},
        "capabilities": {"fetch_sources": False, "math_checks": True},
        "budgets": {"max_model_calls": 7, "max_tool_calls": 6, "max_repairs": 1,
                    "max_branches": 2, "max_wall_seconds": 900, "per_call_seconds": 180,
                    "max_input_bytes": 131072},
        "sources": [],
    }


def valid_draft() -> dict[str, object]:
    return {
        "answer": "The supplied definition is sufficient for this scoped deduction.",
        "question_status": "unresolved",
        "claims": [{"id": "claim-one", "statement": "This is a definition.", "critical": True,
                    "kind": "definition", "citations": [], "step_ids": [], "tool_ids": [], "depends_on": []}],
        "proof_steps": [], "approaches": [], "open_questions": [], "tool_requests": [], "change_log": [],
    }


def valid_frame() -> dict[str, object]:
    return {"task_type": "exploration", "deliverables": ["Map the supplied evidence."],
            "subquestions": ["What does the evidence state?"], "missing_inputs": [],
            "proposed_checks": [], "source_needs": []}


def valid_audit() -> dict[str, object]:
    return {"checks": [{"claim_id": "claim-one", "verdict": "supported",
                         "reasoning": "The definition is stated explicitly.", "checked_step_ids": []}],
            "challenges": [{"claim_id": "claim-one", "attack": "Check its scope.",
                            "result": "It is only a definition.", "outcome": "survives", "tool_ids": []}],
            "missing_evidence": [], "tool_requests": [], "recommended_action": "finish"}


class ResearchRequestTests(unittest.TestCase):
    def test_intent_roundtrip_is_lossless(self) -> None:
        payload = valid_request_payload()
        payload["question"] = 'Are there any odd numbers that are "perfect"?\nExplain π-related analogies only if relevant.'
        payload["goal"] = None
        self.assertEqual(ResearchRequest.from_json(payload).to_json(), payload)

    def test_builder_defaults_without_injecting_goal(self) -> None:
        payload = build_request_payload(run_id="question-only", question="q", objective="answer",
                                        mode="quick", model="gpt-test")
        self.assertIsNone(payload["goal"])
        self.assertEqual(payload["audience"], "unspecified")
        self.assertEqual(payload["provider"]["reasoning_effort"], "medium")
        self.assertEqual(payload["budgets"]["max_model_calls"], 1)

    def test_file_request_requires_all_fields(self) -> None:
        payload = valid_request_payload(); del payload["provider"]["reasoning_effort"]
        with self.assertRaisesRegex(ValidationError, "provider.*missing required"):
            ResearchRequest.from_json(payload)

    def test_request_rejects_invalid_profile_inputs_with_stable_fields(self) -> None:
        cases = [
            ("budgets.max_model_calls", True, "budgets.max_model_calls"),
            ("budgets.max_model_calls", 8, "budgets.max_model_calls"),
            ("capabilities.unknown", True, "capabilities"),
            ("provider.model", "", "provider.model"),
            ("stakes", "high", "unsupported_workflow"),
            ("learning_mode", True, "unsupported_workflow"),
        ]
        for dotted, value, field in cases:
            with self.subTest(dotted=dotted):
                payload = valid_request_payload(); target: dict[str, object] = payload
                parts = dotted.split(".")
                for part in parts[:-1]: target = target[part]  # type: ignore[assignment,index]
                target[parts[-1]] = value
                with self.assertRaises(ValidationError) as raised:
                    ResearchRequest.from_json(payload)
                self.assertEqual(raised.exception.field, field)

    def test_request_rejects_unknown_fields_malformed_urls_and_quick_tools(self) -> None:
        payload = valid_request_payload(); payload["extra"] = None
        with self.assertRaisesRegex(ValidationError, "research_request"):
            ResearchRequest.from_json(payload)
        payload = valid_request_payload(); payload["capabilities"]["fetch_sources"] = True; payload["sources"] = [{"id": "source-one", "kind": "url", "title": "T", "text": None, "url": "http://example.test", "published_at": None}]
        with self.assertRaisesRegex(ValidationError, r"sources\[0\].url"):
            ResearchRequest.from_json(payload)
        payload = valid_request_payload(); payload["mode"] = "quick"; payload["capabilities"]["math_checks"] = True
        payload["budgets"] = {"max_model_calls": 1, "max_tool_calls": 0, "max_repairs": 0, "max_branches": 1, "max_wall_seconds": 180, "per_call_seconds": 180, "max_input_bytes": 131072}
        with self.assertRaisesRegex(ValidationError, "capabilities"):
            ResearchRequest.from_json(payload)


class WorkerResultTests(unittest.TestCase):
    def test_role_results_validate_and_schemas_are_strict(self) -> None:
        for role, payload in (("frame", valid_frame()), ("branch", valid_draft()), ("audit", valid_audit())):
            with self.subTest(role=role):
                self.assertEqual(validate_result(role, payload), payload)
                self.assertFalse(result_schema(role).get("additionalProperties", True))

    def test_model_output_cannot_supply_coordinator_fields(self) -> None:
        draft = valid_draft(); draft["run_status"] = "complete"
        with self.assertRaises(ValidationError):
            validate_result("branch", draft)

    def test_draft_and_audit_cross_references_are_strict(self) -> None:
        draft = valid_draft(); draft["claims"] = []
        with self.assertRaisesRegex(ValidationError, "claims"):
            validate_result("answer", draft)
        draft = valid_draft(); draft["proof_steps"] = [{"id": "step-one", "statement": "s", "justification": "j", "depends_on": ["step-one"], "citations": []}]
        draft["claims"][0]["step_ids"] = ["step-one"]  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, "proof_steps"):
            validate_result("branch", draft)
        audit = valid_audit(); audit["checks"][0]["claim_id"] = "absent"  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, "checks"):
            validate_audit_for_draft(audit, valid_draft())

    def test_draft_tool_ids_must_be_proposed_by_the_draft(self) -> None:
        draft = valid_draft()
        draft["claims"][0]["tool_ids"] = ["tool-one"]  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, r"claims\[0\].tool_ids"):
            validate_result("branch", draft)

    def test_audit_step_and_tool_ids_must_belong_to_current_draft(self) -> None:
        draft = valid_draft()
        draft["proof_steps"] = [{"id": "step-one", "statement": "s", "justification": "j",
                                  "depends_on": [], "citations": []}]
        audit = valid_audit()
        audit["checks"][0]["checked_step_ids"] = ["absent"]  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, r"checks\[0\].checked_step_ids"):
            validate_audit_for_draft(audit, draft)
        audit = valid_audit()
        audit["challenges"][0]["tool_ids"] = ["absent"]  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, r"challenges\[0\].tool_ids"):
            validate_audit_for_draft(audit, valid_draft())

    def test_recursive_validator_accepts_only_json_null_for_null_schema(self) -> None:
        self.assertIsNone(_validate_shape(None, {"type": "null"}, "value"))
        with self.assertRaisesRegex(ValidationError, "value"):
            _validate_shape("null", {"type": "null"}, "value")

    def test_fixture_records_are_available_for_downstream_contract_tests(self) -> None:
        fixture = Path(__file__).parents[1] / "fixtures" / "research" / "valid_records.json"
        records = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(validate_result("frame", records["frame"]), records["frame"])
        self.assertEqual(validate_result("branch", records["draft"]), records["draft"])
        self.assertEqual(validate_result("audit", records["audit"]), records["audit"])

    def test_action_rejects_coordinator_shape_violations(self) -> None:
        action = {"id": "action-one", "kind": "worker", "role": "branch", "branch": "a", "round": 0,
                  "dependencies": [], "payload": {"prompt_version": "research-v1"}}
        self.assertEqual(validate_action(action), action)
        action["payload"]["run_status"] = "complete"  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, "action.payload"):
            validate_action(action)

    def test_structural_values_reject_wrong_json_types_with_validation_errors(self) -> None:
        action = {"id": "action-one", "kind": "worker", "role": "branch", "branch": [], "round": 0,
                  "dependencies": [], "payload": {"prompt_version": "research-v1"}}
        with self.assertRaises(ValidationError) as raised:
            validate_action(action)
        self.assertEqual(raised.exception.field, "action.branch")
        action["branch"] = None; action["round"] = []
        with self.assertRaises(ValidationError) as raised:
            validate_action(action)
        self.assertEqual(raised.exception.field, "action.round")
        details = {"selected_draft_id": None, "audit_id": None, "question_status": [], "blockers": [],
                   "finish_status": None, "round": 0}
        with self.assertRaises(ValidationError) as raised:
            validate_decision_details(details)
        self.assertEqual(raised.exception.field, "decision.details.question_status")

    def test_coordinator_arrays_enforce_item_and_length_limits(self) -> None:
        action = {"id": "action-one", "kind": "worker", "role": "branch", "branch": None, "round": 0,
                  "dependencies": ["action-two"] * 25, "payload": {"prompt_version": "research-v1"}}
        with self.assertRaisesRegex(ValidationError, "action.dependencies"):
            validate_action(action)
        details = {"selected_draft_id": None, "audit_id": None, "question_status": None,
                   "blockers": ["x" * 4001], "finish_status": None, "round": 0}
        with self.assertRaisesRegex(ValidationError, r"decision.details.blockers\[0\]"):
            validate_decision_details(details)


if __name__ == "__main__":
    unittest.main()
