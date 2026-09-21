from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from mathresearch.research.provenance import check_provenance
from tests.unit.test_research_contracts import valid_draft


class ResearchProvenanceTests(unittest.TestCase):
    def source(self, text: str = "A supplied mathematical note.") -> dict[str, object]:
        return {"id": "note-a", "origin": "user_text", "title": "Note A", "url": None,
                "published_at": None, "captured_at": "2026-09-16T00:00:00Z", "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(), "retrieval_receipt": None}

    def cited_draft(self, *, source_id: str = "note-a", quote: str = "supplied") -> dict[str, object]:
        draft = valid_draft()
        draft["claims"][0].update({"kind": "source_assertion", "citations": [
            {"source_id": source_id, "start": 2, "end": 2 + len(quote), "quote": quote}]})
        return draft

    def test_exact_citation_and_hash_pass_without_claiming_truth(self) -> None:
        source = self.source()
        self.assertEqual(check_provenance(self.cited_draft(), {"note-a": source}, {}), [])

    def test_unknown_source_and_quote_or_hash_mismatch_fail(self) -> None:
        self.assertIn("unknown_source:claim-one:agent-frame", check_provenance(
            self.cited_draft(source_id="agent-frame"), {}, {}))
        bad_quote = self.cited_draft(quote="wrong")
        self.assertIn("citation_quote_mismatch:claim-one:note-a", check_provenance(
            bad_quote, {"note-a": self.source()}, {}))
        corrupted = self.source(); corrupted["sha256"] = "0" * 64
        self.assertIn("source_hash_mismatch:note-a", check_provenance(
            self.cited_draft(), {"note-a": corrupted}, {}))

    def test_only_successful_receipts_can_support_tool_references(self) -> None:
        draft = valid_draft()
        draft["tool_requests"] = [{"id": "proposal-one", "operation": "check_integer", "arguments": {"n": 6}}]
        draft["claims"][0]["tool_ids"] = ["check-one"]
        request = {"id": "request-one", "operation": "check_integer", "arguments": {"n": 6}}
        invalid = {"tool_id": "check-one", "request": request, "status": "failed",
                   "result": None, "error": "failed", "scope": "initial",
                   "implementation_version": "mathresearch-broker-v1"}
        self.assertIn("unknown_successful_tool:claim-one:check-one", check_provenance(draft, {}, {"check-one": invalid}))
        self.assertIn("invalid_tool_receipt:check-one", check_provenance(draft, {}, {"check-one": invalid | {"hidden": True}}))
        successful = invalid | {"status": "succeeded", "result": {"n": 6,
            "proper_divisors": [1, 2, 3], "proper_divisor_sum": 6, "is_perfect": True}, "error": None}
        self.assertEqual(check_provenance(draft, {}, {"check-one": successful}), [])
        audit = {"checks": [{"claim_id": "claim-one", "verdict": "supported",
            "reasoning": "The encoded check matches.", "checked_step_ids": []}],
            "challenges": [{"claim_id": "claim-one", "attack": "Check the divisors.",
                "result": "The receipt sums to six.", "outcome": "survives", "tool_ids": ["check-one"]}],
            "missing_evidence": [], "tool_requests": [], "recommended_action": "finish"}
        self.assertEqual(check_provenance(draft, {}, {"check-one": successful}, audit=audit), [])
        audit["challenges"][0]["tool_ids"] = ["future-one"]  # type: ignore[index]
        self.assertIn("unknown_successful_tool:challenge:claim-one:future-one",
                      check_provenance(draft, {}, {"check-one": successful}, audit=audit))

    def test_audit_receipt_catalog_is_validated_before_challenges_can_cite_it(self) -> None:
        draft = valid_draft()
        request = {"id": "request-one", "operation": "check_integer", "arguments": {"n": 6}}
        successful = {"tool_id": "check-one", "request": request, "status": "succeeded",
            "result": {"n": 6, "proper_divisors": [1, 2, 3], "proper_divisor_sum": 6,
                       "is_perfect": True}, "error": None, "scope": "initial",
            "implementation_version": "mathresearch-broker-v1"}
        audit = {"checks": [{"claim_id": "claim-one", "verdict": "supported",
            "reasoning": "Checked.", "checked_step_ids": []}],
            "challenges": [{"claim_id": "claim-one", "attack": "Check the value.",
            "result": "The receipt agrees.", "outcome": "survives", "tool_ids": ["check-one"]}],
            "missing_evidence": [], "tool_requests": [], "recommended_action": "finish"}

        issues = check_provenance(draft, {}, {}, audit=audit, audit_sources={},
                                  audit_tool_results={"check-one": successful | {"hidden": True}})

        self.assertIn("invalid_tool_receipt:check-one", issues)
        self.assertIn("unknown_successful_tool:challenge:claim-one:check-one", issues)

    def test_historical_frame_success_criterion_cannot_be_a_v3_source(self) -> None:
        fixture_path = Path(__file__).parents[1] / "fixtures" / "research" / "observed_circular_support.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        draft = self.cited_draft(source_id="frame-success-criterion", quote="open problem")
        issue = check_provenance(draft, {}, {})
        self.assertIn("unknown_source:claim-one:frame-success-criterion", issue)
        self.assertEqual(fixture["historical_behavior"], "defective")


if __name__ == "__main__":
    unittest.main()
