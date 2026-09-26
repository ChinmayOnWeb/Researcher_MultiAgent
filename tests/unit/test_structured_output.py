from __future__ import annotations

import copy
import json
import unittest

from mathresearch.contracts.validation import ValidationError
from mathresearch.research.contracts import validate_result
from mathresearch.research.prompts import structural_repair_prompt
from mathresearch.structured_output import (parse_json_object, semantic_artifact,
    validate_payload, validation_issue)


def draft() -> dict:
    return {"answer": "The conclusion follows by the stated argument.",
        "question_status": "answered", "claims": [{"id": "claim-one",
            "statement": "The conclusion follows.", "critical": True,
            "kind": "deduction", "citations": [], "step_ids": ["step-one"],
            "tool_ids": [], "depends_on": [], "basis": "derivation",
            "basis_reference": "Derived in step-one", "scope_step_ids": [],
            "discharged_by_step_ids": []}],
        "proof_steps": [{"id": "step-one", "statement": "Apply the given rule.",
            "justification": "The rule's hypotheses hold.", "depends_on": [],
            "citations": []}], "approaches": [], "open_questions": [],
        "tool_requests": [], "change_log": []}


class StructuredOutputTests(unittest.TestCase):
    def test_perfect_json_and_utf8_bom_are_parsed_without_mutating_raw_bytes(self):
        raw = b'\xef\xbb\xbf {"answer":"kept"}  '
        original = bytes(raw)
        parsed = parse_json_object(raw)
        self.assertEqual(parsed.value, {"answer": "kept"})
        self.assertIn("removed_utf8_bom", parsed.normalization)
        self.assertEqual(raw, original)

    def test_markdown_fence_is_a_deterministic_transport_cleanup(self):
        parsed = parse_json_object('```json\n{"answer":"x"}\n```')
        self.assertEqual(parsed.value["answer"], "x")
        self.assertEqual(parsed.normalization, ("removed_markdown_fence",))

    def test_one_object_surrounded_by_prose_is_extracted_but_two_objects_are_rejected(self):
        parsed = parse_json_object('Result follows:\n{"answer":"x"}\nDone.')
        self.assertEqual(parsed.value, {"answer": "x"})
        self.assertIn("extracted_single_json_object_from_prose", parsed.normalization)
        with self.assertRaisesRegex(ValueError, "more than one"):
            parse_json_object('{"answer":"x"} and {"answer":"y"}')

    def test_root_array_is_rejected_even_when_it_contains_an_object(self):
        with self.assertRaisesRegex(ValueError, "root must be a JSON object"):
            parse_json_object('[{"answer":"not a root result"}]')

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_json_object('{"answer":"first","answer":"second"}')
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parse_json_object('{"answer":"x","score":NaN}')

    def test_malformed_json_stays_invalid_and_keeps_human_answer_text(self):
        raw = b'{"answer":"useful result", "claims": [}'
        with self.assertRaises(ValueError):
            parse_json_object(raw)
        self.assertEqual(semantic_artifact(raw), "useful result")

    def test_unknown_claim_reference_has_machine_readable_path_and_namespace(self):
        value = draft()
        value["claims"][0]["depends_on"] = ["base-case"]
        with self.assertRaises(ValidationError) as raised:
            validate_result("answer", value, prompt_version="research-v8")
        issue = validation_issue(raised.exception)
        self.assertEqual(issue["path"], "claims[0].depends_on[0]")
        self.assertEqual(issue["category"], "unknown_reference")
        self.assertEqual(issue["found"], "base-case")
        self.assertEqual(issue["expected_namespace"], "claims")
        self.assertEqual(issue["available_ids"], ["claim-one"])
        self.assertTrue(issue["model_repair_permitted"])
        self.assertFalse(issue["deterministic_repair_permitted"])

    def test_step_id_in_claim_namespace_is_rejected_without_guessing(self):
        value = draft()
        value["proof_steps"].append({"id": "step-two", "statement": "Other.",
            "justification": "Other.", "depends_on": [], "citations": []})
        value["claims"][0]["depends_on"] = ["step-two"]
        with self.assertRaises(ValidationError) as raised:
            validate_result("answer", value, prompt_version="research-v8")
        issue = validation_issue(raised.exception)
        self.assertEqual(issue["expected_namespace"], "claims")
        self.assertEqual(issue["found"], "step-two")
        self.assertEqual(value["claims"][0]["depends_on"], ["step-two"])

    def test_missing_id_is_reported_at_its_path(self):
        value = draft()
        del value["claims"][0]["id"]
        with self.assertRaises(ValidationError) as raised:
            validate_result("answer", value, prompt_version="research-v8")
        issue = validation_issue(raised.exception)
        self.assertEqual(issue["category"], "missing_field")
        self.assertIn("claims", issue["path"])

    def test_duplicate_ids_and_circular_dependencies_are_distinct_failures(self):
        value = draft()
        value["proof_steps"].append(copy.deepcopy(value["proof_steps"][0]))
        with self.assertRaises(ValidationError) as raised:
            validate_result("answer", value, prompt_version="research-v8")
        self.assertEqual(validation_issue(raised.exception)["category"], "duplicate_id")
        value = draft()
        value["proof_steps"][0]["depends_on"] = ["step-one"]
        with self.assertRaises(ValidationError) as raised:
            validate_result("answer", value, prompt_version="research-v8")
        self.assertEqual(validation_issue(raised.exception)["category"], "circular_dependency")

    def test_protocol_validity_does_not_claim_mathematical_correctness(self):
        value = draft()
        value["answer"] = "1 + 1 = 3."
        result = validate_payload(value, lambda item: validate_result(
            "answer", item, prompt_version="research-v8"))
        self.assertEqual(result.protocol_status, "valid")
        self.assertEqual(result.value["answer"], "1 + 1 = 3.")

    def test_invalid_structure_retains_the_semantic_answer_as_separate_data(self):
        value = draft()
        value["claims"][0]["depends_on"] = ["missing-claim"]
        result = validate_payload(value, lambda item: validate_result(
            "answer", item, prompt_version="research-v8"))
        self.assertEqual(result.protocol_status, "invalid")
        self.assertIsNone(result.value)
        self.assertEqual(semantic_artifact(b"", value), value["answer"])
        self.assertEqual(result.issues[0]["category"], "unknown_reference")

    def test_repair_prompt_uses_raw_output_and_only_the_reported_error(self):
        raw = b'{"answer":"keep this", "claims": [}'
        error = {"path": "claims[0].id", "category": "missing_field",
            "explanation": "required id is missing", "model_repair_permitted": True}
        prompt = structural_repair_prompt("original task and schema", None, error,
                                         raw_output=raw)
        self.assertIn("Preserve the mathematical/research answer", prompt)
        self.assertIn(raw.decode(), prompt)
        self.assertIn('"path":"claims[0].id"', prompt)
        self.assertIn("do not solve the question again", prompt.lower())

    def test_v8_reductio_does_not_make_an_earlier_claim_depend_on_later_discharge(self):
        value = {"answer": "The temporary assumption leads to a contradiction.",
            "question_status": "answered", "claims": [
                {"id": "claim-assumption", "statement": "Assume the negation.",
                 "critical": True, "kind": "assumption", "citations": [],
                 "step_ids": [], "tool_ids": [], "depends_on": [],
                 "basis": "local_assumption", "basis_reference": "Temporary assumption.",
                 "scope_step_ids": ["step-assume", "step-contradiction"],
                 "discharged_by_step_ids": ["step-contradiction"]},
                {"id": "claim-contradiction", "statement": "A contradiction follows.",
                 "critical": True, "kind": "deduction", "citations": [],
                 "step_ids": ["step-contradiction"], "tool_ids": [],
                 "depends_on": ["claim-assumption"], "basis": "derivation",
                 "basis_reference": "The scoped derivation contradicts itself.",
                 "scope_step_ids": [], "discharged_by_step_ids": []}],
            "proof_steps": [
                {"id": "step-assume", "statement": "Assume not P.",
                 "justification": "Reductio assumption.", "depends_on": [], "citations": []},
                {"id": "step-contradiction", "statement": "Derive falsehood.",
                 "justification": "Use the temporary assumption and prior facts.",
                 "depends_on": ["step-assume"], "citations": []}],
            "approaches": [], "open_questions": [], "tool_requests": [], "change_log": []}
        self.assertEqual(validate_result("answer", value, prompt_version="research-v8"), value)
        # Older schemas keep their original local-assumption contract; use a
        # concrete later discharge link to demonstrate that versioned behavior.
        legacy = copy.deepcopy(value)
        legacy["claims"][1]["step_ids"] = ["step-contradiction"]
        self.assertEqual(validate_result("answer", legacy, prompt_version="research-v7"), legacy)

    def test_induction_direct_proof_cases_existential_and_theorem_application_share_contract(self):
        styles = []
        induction = draft()
        induction["proof_steps"] = [
            {"id": "step-base", "statement": "Base case.", "justification": "Check n=0.", "depends_on": [], "citations": []},
            {"id": "step-hypothesis", "statement": "Assume the claim at n.", "justification": "Induction hypothesis.", "depends_on": ["step-base"], "citations": []},
            {"id": "step-inductive", "statement": "Prove it at n+1.", "justification": "Apply the recurrence.", "depends_on": ["step-hypothesis"], "citations": []}]
        induction["claims"][0]["step_ids"] = ["step-base", "step-inductive"]
        styles.append(induction)
        cases = draft()
        cases["proof_steps"] = [
            {"id": "step-split", "statement": "Split into cases.", "justification": "Every input has one of two forms.", "depends_on": [], "citations": []},
            {"id": "step-left", "statement": "First case.", "justification": "Evaluate directly.", "depends_on": ["step-split"], "citations": []},
            {"id": "step-right", "statement": "Second case.", "justification": "Evaluate directly.", "depends_on": ["step-split"], "citations": []},
            {"id": "step-join", "statement": "Both cases imply the result.", "justification": "Exhaustive split.", "depends_on": ["step-left", "step-right"], "citations": []}]
        cases["claims"][0]["step_ids"] = ["step-join"]
        styles.append(cases)
        existential = draft()
        existential["claims"][0]["statement"] = "There exists x with P(x)."
        existential["proof_steps"][0].update({"statement": "Choose witness x=2 and verify P(2).",
            "justification": "Direct substitution."})
        styles.append(existential)
        theorem = draft()
        theorem["claims"][0].update({"basis": "standard_result",
            "basis_reference": "The intermediate value theorem applies on the closed interval."})
        theorem["proof_steps"][0].update({"statement": "Apply the intermediate value theorem.",
            "justification": "Continuity and endpoint signs satisfy its hypotheses."})
        styles.append(theorem)
        for value in styles:
            with self.subTest(answer=value["answer"]):
                self.assertEqual(validate_result("answer", value,
                    prompt_version="research-v8"), value)

    def test_ambiguous_dependencies_are_not_silently_inferred(self):
        value = draft()
        del value["claims"][0]["depends_on"]
        original = copy.deepcopy(value)
        with self.assertRaises(ValidationError):
            validate_result("answer", value, prompt_version="research-v8")
        self.assertEqual(value, original)


if __name__ == "__main__":
    unittest.main()
