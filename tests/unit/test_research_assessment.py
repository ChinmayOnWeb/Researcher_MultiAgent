from __future__ import annotations

import copy
import unittest

from mathresearch.research.provenance import assess
from tests.unit.test_research_prompts import audit, draft, snapshot, source_record, tool_receipt


class ResearchAssessmentTests(unittest.TestCase):
    def test_unsupported_critical_claim_stays_inconclusive_when_audit_says_finish(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        review = audit() | {"recommended_action": "finish"}
        review["checks"][0]["verdict"] = "unsupported"
        result = assess(candidate, {}, {"check-one": tool_receipt()}, audit=review)
        self.assertEqual(result["answer_status"], "inconclusive")

    def test_failed_bound_challenge_overrides_positive_check(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0]["kind"] = "deduction"
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
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        review = audit()
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0]["outcome"] = "fails"
        result = assess(candidate, {}, {"check-one": tool_receipt()}, audit=review)
        self.assertNotEqual(result["answer_status"], "refuted")

    def test_missing_critical_challenge_is_inconclusive_not_invalid_evidence(self) -> None:
        candidate = draft("candidate")
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        candidate["claims"].append({"id": "claim-two", "statement": "definition", "critical": False,
            "kind": "definition", "citations": [], "step_ids": [], "tool_ids": [], "depends_on": []})
        review = audit()
        review["checks"][0]["verdict"] = "supported"
        review["checks"].append({"claim_id": "claim-two", "verdict": "supported", "reasoning": "definition", "checked_step_ids": []})
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
