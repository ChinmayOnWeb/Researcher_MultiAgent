from __future__ import annotations

import copy
import unittest

from mathresearch.research.provenance import assess
from mathresearch.research.routing import assess_latest
from tests.unit.test_research_prompts import audit, draft, snapshot, source_record, tool_receipt
from mathresearch.research.events import canonical_json_bytes
from types import MappingProxyType
from dataclasses import replace


class ResearchAssessmentTests(unittest.TestCase):
    def test_v3_basis_rules_keep_assumptions_conditional_and_recollection_unverified(self) -> None:
        candidate = draft("candidate")
        claim = candidate["claims"][0]
        review = audit()
        review["checks"][0].update({"verdict": "supported", "basis_verdict": "applicable",
                                    "basis_reasoning": "Review basis."})
        review["challenges"][0].update({"outcome": "survives"})
        claim.update({"kind": "assumption", "basis": "additional_assumption"})
        self.assertEqual(assess(candidate, {}, {}, audit=review)["claim_findings"][0]["status"], "conditional")
        claim.update({"kind": "model_knowledge", "basis": "unsupported_recollection",
                      "step_ids": [], "depends_on": []})
        review["checks"][0]["basis_verdict"] = "unsupported"
        self.assertEqual(assess(candidate, {}, {}, audit=review)["claim_findings"][0]["status"], "unverified")

    def test_transitive_proof_steps_must_be_audited(self) -> None:
        candidate = draft("proof")
        claim = candidate["claims"][0]
        claim.update({"kind": "deduction", "basis": "derivation", "basis_reference": "step-two",
                      "step_ids": ["step-two"]})
        candidate["proof_steps"] = [
            {"id": "step-one", "statement": "base", "justification": "given", "depends_on": [], "citations": []},
            {"id": "step-two", "statement": "result", "justification": "uses base", "depends_on": ["step-one"], "citations": []}]
        review = audit()
        review["checks"][0].update({"verdict": "supported", "checked_step_ids": ["step-two"],
            "basis_verdict": "applicable", "basis_reasoning": "Application reviewed."})
        review["challenges"][0]["outcome"] = "survives"
        result = assess(candidate, {}, {}, audit=review, objective="prove")
        self.assertIn("critical_proof_steps_not_covered", result["unresolved"])

    def test_question_premise_requires_exact_question_text(self) -> None:
        candidate = draft("premise test")
        candidate["claims"][0].update({"kind": "assumption", "basis": "question_premise",
            "basis_reference": "n is even"})
        review = audit()
        review["checks"][0].update({"verdict": "supported", "basis_verdict": "applicable",
            "basis_reasoning": "The question states this."})
        review["challenges"][0]["outcome"] = "survives"
        self.assertEqual(assess(candidate, {}, {}, audit=review, question="Let n be even.")["claim_findings"][0]["status"], "unverified")
        candidate["claims"][0]["basis_reference"] = "Let n be even."
        self.assertEqual(assess(candidate, {}, {}, audit=review, question="Let n be even.")["claim_findings"][0]["status"], "accepted_premise")

    def test_local_assumption_discharge_needs_dependent_audited_steps(self) -> None:
        candidate = draft("local assumption")
        candidate["claims"] = [
            {"id": "claim-one", "statement": "Induction hypothesis", "critical": False,
             "kind": "assumption", "citations": [], "step_ids": [], "tool_ids": [], "depends_on": [],
             "basis": "local_assumption", "basis_reference": "At induction step k", "scope_step_ids": ["step-one"], "discharged_by_step_ids": ["step-one"]},
            {"id": "claim-two", "statement": "Conclusion", "critical": True,
             "kind": "deduction", "citations": [], "step_ids": ["step-one"], "tool_ids": [], "depends_on": ["claim-one"],
             "basis": "derivation", "basis_reference": "Induction step", "scope_step_ids": [], "discharged_by_step_ids": []}]
        candidate["proof_steps"] = [{"id": "step-one", "statement": "Inductive transition", "justification": "Apply the hypothesis", "depends_on": [], "citations": []}]
        review = audit()
        review["checks"] = [
            {"claim_id": "claim-one", "verdict": "conditional", "reasoning": "Local scope", "checked_step_ids": ["step-one"], "basis_verdict": "conditional", "basis_reasoning": "Scoped."},
            {"claim_id": "claim-two", "verdict": "supported", "reasoning": "Transition holds", "checked_step_ids": ["step-one"], "basis_verdict": "applicable", "basis_reasoning": "The transition uses the hypothesis."}]
        review["challenges"] = [{"claim_id": "claim-two", "attack": "Check transition", "result": "survives", "outcome": "survives", "tool_ids": []}]
        result = assess(candidate, {}, {}, audit=review, objective="prove")
        self.assertEqual(result["claim_findings"][0]["status"], "discharged_local_assumption")
        self.assertEqual(result["answer_status"], "supported_within_scope")

    def test_external_fact_reports_attribution_separately_from_truth(self) -> None:
        candidate = draft("source fact")
        candidate["claims"][0].update({"kind": "source_assertion", "basis": "external_fact",
            "basis_reference": "The cited source", "citations": [{"source_id": "source-one", "start": 0,
            "end": 14, "quote": "Source says X."}]})
        review = audit()
        review["checks"][0].update({"verdict": "supported", "basis_verdict": "source_attributed",
            "basis_reasoning": "The quote matches the captured source."})
        review["challenges"][0]["outcome"] = "survives"
        source = source_record() | {"text": "Source says X."}
        source["sha256"] = __import__("hashlib").sha256(source["text"].encode()).hexdigest()
        result = assess(candidate, {"source-one": source}, {}, audit=review)
        finding = result["claim_findings"][0]
        self.assertEqual(finding["status"], "source_attributed")
        self.assertEqual(finding["truth_status"], "not_established")

    def test_assessment_records_objection_history_and_selected_hashes(self) -> None:
        state = snapshot()
        audit_packet = {"sources": dict(state.sources), "tool_results": dict(state.tool_results),
                        "inputs": {"draft_id": "draft-one"}}
        state = replace(state, intent_packets=MappingProxyType(dict(state.intent_packets) |
            {"audit-one": canonical_json_bytes(audit_packet)}))
        result = assess_latest(state)
        self.assertEqual(result["draft_id"], "draft-one")
        self.assertEqual(len(result["draft_hash"]), 64)
        self.assertEqual(len(result["evidence_hash"]), 64)
        self.assertEqual(result["objection_history"][0]["draft_id"], "draft-one")
        self.assertTrue(result["objection_history"][0]["active"])

    def test_unsupported_critical_claim_stays_inconclusive_when_audit_says_finish(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0].pop("basis"); candidate["claims"][0].pop("basis_reference")
        candidate["claims"][0].pop("scope_step_ids"); candidate["claims"][0].pop("discharged_by_step_ids")
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["basis"] = "derivation"
        candidate["claims"][0]["basis_reference"] = "Derived in a proof step"
        candidate["claims"][0]["scope_step_ids"] = []
        candidate["claims"][0]["discharged_by_step_ids"] = []
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        review = audit() | {"recommended_action": "finish"}
        review["checks"][0]["verdict"] = "unsupported"
        result = assess(candidate, {}, {"check-one": tool_receipt()}, audit=review)
        self.assertEqual(result["answer_status"], "inconclusive")

    def test_failed_bound_challenge_overrides_positive_check(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0].pop("basis"); candidate["claims"][0].pop("basis_reference")
        candidate["claims"][0].pop("scope_step_ids"); candidate["claims"][0].pop("discharged_by_step_ids")
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["basis"] = "derivation"
        candidate["claims"][0]["basis_reference"] = "Derived in a proof step"
        candidate["claims"][0]["scope_step_ids"] = []
        candidate["claims"][0]["discharged_by_step_ids"] = []
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        review = audit()
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0]["outcome"] = "fails"
        review["challenges"][0]["tool_ids"] = ["check-one"]
        result = assess(candidate, {}, {"check-one": tool_receipt()}, audit=review)
        self.assertEqual(result["answer_status"], "refuted")
        self.assertEqual(result["claim_findings"][0]["status"], "contradicted")

    def test_unrelated_receipt_does_not_turn_a_failed_challenge_into_refutation(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0].pop("basis"); candidate["claims"][0].pop("basis_reference")
        candidate["claims"][0].pop("scope_step_ids"); candidate["claims"][0].pop("discharged_by_step_ids")
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["basis"] = "derivation"
        candidate["claims"][0]["basis_reference"] = "Derived in a proof step"
        candidate["claims"][0]["scope_step_ids"] = []
        candidate["claims"][0]["discharged_by_step_ids"] = []
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        review = audit()
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0]["outcome"] = "fails"
        result = assess(candidate, {}, {"check-one": tool_receipt()}, audit=review)
        self.assertNotEqual(result["answer_status"], "refuted")

    def test_missing_critical_challenge_is_inconclusive_not_invalid_evidence(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0].pop("basis"); candidate["claims"][0].pop("basis_reference")
        candidate["claims"][0].pop("scope_step_ids"); candidate["claims"][0].pop("discharged_by_step_ids")
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["basis"] = "derivation"
        candidate["claims"][0]["basis_reference"] = "Derived in a proof step"
        candidate["claims"][0]["scope_step_ids"] = []
        candidate["claims"][0]["discharged_by_step_ids"] = []
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        candidate["claims"].append({"id": "claim-two", "statement": "definition", "critical": False,
            "kind": "definition", "citations": [], "step_ids": [], "tool_ids": [], "depends_on": [],
            "basis": "derivation", "basis_reference": "A definition", "scope_step_ids": [], "discharged_by_step_ids": []})
        review = audit()
        review["checks"][0]["verdict"] = "supported"
        review["checks"].append({"claim_id": "claim-two", "verdict": "supported", "reasoning": "definition", "checked_step_ids": [], "basis_verdict": "applicable", "basis_reasoning": "This is a stated definition."})
        review["challenges"] = [{"claim_id": "claim-two", "attack": "check", "result": "survives", "outcome": "survives", "tool_ids": []}]
        result = assess(candidate, {}, {"check-one": tool_receipt()}, audit=review)
        self.assertEqual(result["provenance_status"], "valid")
        self.assertEqual(result["answer_status"], "inconclusive")

    def test_quick_mode_without_audit_is_unverified(self) -> None:
        state = snapshot()
        answer = draft("quick answer")
        result = assess(answer, {"source-one": source_record()}, {}, audit=None)
        self.assertEqual(result["answer_status"], "unverified")
        self.assertEqual(result["semantic_status"], "not_audited")


if __name__ == "__main__":
    unittest.main()
