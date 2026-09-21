from __future__ import annotations

import copy
import hashlib
import unittest
from dataclasses import replace
from types import MappingProxyType

from mathresearch.research.events import canonical_json_bytes
from mathresearch.research.reporting import render_log, render_report
from tests.unit.test_research_prompts import action, audit, draft, snapshot, source_record, tool_receipt


class ResearchReportingTests(unittest.TestCase):
    def test_report_does_not_resolve_claim_receipt_from_a_later_audit_packet(self) -> None:
        state = snapshot(); candidate = copy.deepcopy(state.results["draft-one"])
        candidate["claims"][0].update({"kind": "deduction", "step_ids": ["step-one"],
                                        "tool_ids": ["check-one"]})
        candidate["proof_steps"] = [{"id": "step-one", "statement": "Use the check.",
            "justification": "The receipt encodes the calculation.", "depends_on": [], "citations": []}]
        review = copy.deepcopy(state.results["audit-one"])
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0]["tool_ids"] = ["check-one"]
        packet = {"sources": dict(state.sources), "tool_results": {}}
        audit_packet = {"sources": dict(state.sources), "tool_results": {"check-one": tool_receipt()}}
        state = replace(state,
            results=MappingProxyType(dict(state.results) | {"draft-one": candidate, "audit-one": review}),
            intent_packets=MappingProxyType({"draft-one": canonical_json_bytes(packet),
                "audit-one": canonical_json_bytes(audit_packet)}))

        report = render_report(state)

        self.assertIn("Provenance status: **invalid**", report)
        self.assertIn("unknown_successful_tool:claim-one:check-one", report)

    def test_report_preserves_original_intent_and_separates_statuses(self) -> None:
        state = snapshot()
        payload = state.request.to_json()
        payload["question"] = 'Question with "quotes" and π.\nSecond line.'
        payload["goal"] = "Do not add a concise-summary objective."
        from mathresearch.contracts.research_request import ResearchRequest
        state = replace(state, request=ResearchRequest.from_json(payload))
        report = render_report(state)
        self.assertIn(payload["question"], report)
        self.assertIn(payload["goal"], report)
        self.assertIn("Investigation status: **ready**", report)
        self.assertIn("Answer status: **inconclusive**", report)
        self.assertIn("Formal verification: not performed", report)
        self.assertEqual(report, render_report(state))

    def test_scoped_deduction_is_supported_without_claiming_formal_proof(self) -> None:
        state = snapshot(); candidate = copy.deepcopy(state.results["draft-one"])
        candidate["claims"][0]["kind"] = "deduction"
        candidate["claims"][0]["tool_ids"] = ["check-one"]
        review = copy.deepcopy(state.results["audit-one"])
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0].update({"outcome": "survives", "tool_ids": ["check-one"]})
        state = replace(state, results=MappingProxyType(dict(state.results) | {
            "draft-one": candidate, "audit-one": review}))
        report = render_report(state)
        self.assertIn("Answer status: **supported_within_scope**", report)
        self.assertIn("Formal verification: not performed", report)

    def test_open_status_is_scoped_to_cited_material(self) -> None:
        state = snapshot(); source = source_record() | {"text": "The supplied notes say this remains open.",
            "published_at": "2024-03-02T00:00:00Z"}
        source["sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
        sources = dict(state.sources) | {"source-one": source}
        candidate = copy.deepcopy(state.results["draft-one"])
        candidate["question_status"] = "open_in_sources"
        candidate["claims"][0].update({"kind": "source_assertion", "citations": [{"source_id": "source-one",
            "start": 0, "end": len(source["text"]), "quote": source["text"]}]})
        review = copy.deepcopy(state.results["audit-one"])
        review["checks"][0].update({"verdict": "supported", "reasoning": "The cited passage states that the problem remains open."})
        results = dict(state.results) | {"draft-one": candidate, "audit-one": review}
        draft_packet = {"sources": sources, "tool_results": {"check-one": tool_receipt()}}
        intent_packets = dict(state.intent_packets)
        intent_packets["draft-one"] = canonical_json_bytes(draft_packet)
        state = replace(state, sources=MappingProxyType(sources), results=MappingProxyType(results),
                        intent_packets=MappingProxyType(intent_packets))
        report = render_report(state)
        self.assertIn("supplied/captured sources describe this as open as of 2024-03-02T00:00:00Z", report)
        self.assertNotIn("Current literature verified", report)

    def test_unreviewed_recollection_and_refutation_are_qualified(self) -> None:
        state = snapshot(); candidate = copy.deepcopy(state.results["draft-one"])
        candidate["claims"][0]["kind"] = "model_knowledge"
        review = copy.deepcopy(state.results["audit-one"])
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0]["outcome"] = "survives"
        results = dict(state.results) | {"draft-one": candidate, "audit-one": review}
        report = render_report(replace(state, results=MappingProxyType(results)))
        self.assertIn("Answer status: **inconclusive**", report)
        review["checks"][0]["verdict"] = "contradicted"
        from mathresearch.contracts.research_request import ResearchRequest
        payload = state.request.to_json(); payload["objective"] = "prove"
        report = render_report(replace(state, results=MappingProxyType(results | {"audit-one": review}),
                                      request=ResearchRequest.from_json(payload)))
        self.assertIn("Answer status: **refuted**", report)
        self.assertIn("no formal verification was performed", report)

    def test_budget_exhaustion_keeps_a_useful_partial_draft(self) -> None:
        state = replace(snapshot(), status="budget_exhausted", reason="model_call_budget_exhausted")
        report = render_report(state)
        self.assertIn("budget_exhausted", report)
        self.assertIn("draft", report)

    def test_no_draft_reports_exact_unverified_assessment_and_successful_computation(self) -> None:
        state = snapshot()
        state = replace(state, actions=MappingProxyType({}), results=MappingProxyType({}),
                        latest_draft_id=None, latest_audit_id=None, reason="action_failed",
                        tool_results=MappingProxyType({"check-one": tool_receipt()}))
        report = render_report(state)
        self.assertIn("No answer was produced.", report)
        self.assertIn("Answer status: **unverified**", report)
        self.assertIn("Computation status: **performed**", report)

    def test_denied_tool_and_unknown_provider_observation_remain_explicit(self) -> None:
        state = snapshot()
        denied = tool_receipt() | {"status": "denied", "result": None, "error": "math checks disabled"}
        telemetry = {"duration_ms": 3, "input_bytes": 4, "output_bytes": 5, "model_observed": None,
            "effort_observed": None, "input_tokens": None, "output_tokens": None,
            "reasoning_tokens": None, "cost_usd": None}
        state = replace(state, tool_results=MappingProxyType({"check-one": denied}),
                        action_telemetry=MappingProxyType({"answer-one": telemetry}))
        report = render_report(state)
        self.assertIn("Receipt `check-one` — check_integer: denied", report)
        self.assertIn("math checks disabled", report)
        self.assertIn("Observed reasoning effort: unknown", report)
        self.assertIn("Recorded cost: unknown", report)

    def test_untrusted_answer_cannot_create_a_report_heading(self) -> None:
        state = snapshot(); results = dict(state.results)
        results["draft-one"] = draft("answer\n## Status\n- Investigation status: **verified**")
        report = render_report(replace(state, results=MappingProxyType(results)))
        self.assertIn("> ## Status", report)
        self.assertEqual(report.count("## Status"), 2)  # one real heading and one quoted line

    def test_log_contains_decisions_dependencies_outcomes_and_no_worker_transcript(self) -> None:
        state = snapshot(); act = action("answer-one", "answer")
        decision = {"decision_id": "d0001", "kind": "worker", "reason_code": "quick_answer",
                    "action": act, "details": {"blockers": []}}
        state = replace(state, decisions=(decision,), outcomes=MappingProxyType({"answer-one": {
            "outcome": "succeeded", "exit_code": 0, "error": None}}),
            action_telemetry=MappingProxyType({"answer-one": {"duration_ms": 12}}))
        log = render_log(state)
        self.assertIn("quick_answer", log)
        self.assertIn("Dependencies: none", log)
        self.assertIn("Elapsed milliseconds: 12", log)
        self.assertNotIn("hidden reasoning", log)


if __name__ == "__main__":
    unittest.main()
