import json
import unittest

from mathresearch.contracts.records import RunRequest
from mathresearch.reporting import render_quick_report


class ReportingTests(unittest.TestCase):
    def test_report_is_deterministic_and_discloses_limits(self):
        request = RunRequest.from_json({"schema_version": 1, "record_type": "run_request", "run_id": "report-run", "question": "Why?", "actual_goal": None, "context": None, "constraints": [], "audience_level": "general", "mode": "quick", "stakes": "ordinary", "learning_mode": False, "capabilities": {}, "budgets": {"max_accepted_submissions": 4, "max_revision_cycles": 0, "elapsed_time_seconds": None}})
        accepted = {"frame": {"framed_question": "Why?", "success_criteria": [], "terms": [], "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"}, "investigate": {"answer": "A", "claims": [{"id": "c1", "statement": "S", "basis": "derived", "support": "proof"}], "alternatives": ["B"], "limitations": []}, "verify": {"checks": [{"claim_id": "c1", "verdict": "supported", "reasoning": "R"}], "disposition": "pass", "limitations": []}, "explain": {"summary": "yes", "explanation": "because", "conclusion": "supported", "limitations": []}}
        report = render_quick_report(request, accepted)
        self.assertIn("No external retrieval", report)
        self.assertIn("Cost and token usage are unknown", report)
        self.assertEqual(report, render_quick_report(request, accepted))

    def test_report_labels_an_inconclusive_verification_and_conclusion(self):
        request = RunRequest.from_json({"schema_version": 1, "record_type": "run_request", "run_id": "report-run", "question": "Why?", "actual_goal": None, "context": None, "constraints": [], "audience_level": "general", "mode": "quick", "stakes": "ordinary", "learning_mode": False, "capabilities": {}, "budgets": {"max_accepted_submissions": 4, "max_revision_cycles": 0, "elapsed_time_seconds": None}})
        accepted = {"frame": {"framed_question": "Why?", "success_criteria": [], "terms": [], "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"}, "investigate": {"answer": "A", "claims": [{"id": "c1", "statement": "S", "basis": "derived", "support": "proof"}], "alternatives": [], "limitations": []}, "verify": {"checks": [{"claim_id": "c1", "verdict": "supported", "reasoning": "R"}], "disposition": "inconclusive", "limitations": []}, "explain": {"summary": "not established", "explanation": "because", "conclusion": "inconclusive", "limitations": []}}

        report = render_quick_report(request, accepted)

        self.assertIn("Verification disposition: **inconclusive**", report)
        self.assertIn("Final conclusion: **inconclusive**", report)
