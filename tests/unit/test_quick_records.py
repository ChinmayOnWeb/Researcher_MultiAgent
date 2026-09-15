"""Contract tests for the fixed durable quick workflow."""

from datetime import datetime, timezone
import unittest

from mathresearch.contracts.quick import WorkflowEvent, replay_quick_events
from mathresearch.contracts.run import RunInitializedEvent
from mathresearch.contracts.records import RunBudgets, RunRequest
from mathresearch.contracts.validation import ValidationError


def request() -> RunRequest:
    return RunRequest("quick-run", "q", None, None, (), "general", "quick", "ordinary", False, {}, RunBudgets(4, 0, None))


class QuickRecordTests(unittest.TestCase):
    def test_rejects_completion_before_four_acceptances(self) -> None:
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        init = RunInitializedEvent("quick-run", at, request())
        complete = WorkflowEvent("quick-run", at, 2, "quick_completed", {"report_markdown": "# report"})
        with self.assertRaises(ValidationError):
            replay_quick_events((init, complete))

    def test_configured_event_round_trips_exactly(self) -> None:
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = WorkflowEvent("quick-run", at, 2, "quick_configured", {
            "adapter": "codex", "executable": "C:/codex.exe", "model": None,
            "protocol_version": "1", "capabilities": {"reasoning": True},
            "stages": ["frame", "investigate", "verify", "explain"],
        })
        self.assertEqual(WorkflowEvent.from_json(event.to_json()), event)

    def test_replay_rejects_intent_packet_with_altered_initialized_request(self) -> None:
        """A packet must not substitute request data before the first worker runs."""
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        init = RunInitializedEvent("quick-run", at, request())
        configured = WorkflowEvent("quick-run", at, 2, "quick_configured", {
            "adapter": "codex", "executable": "codex", "model": None,
            "protocol_version": "1", "capabilities": {},
            "stages": ["frame", "investigate", "verify", "explain"],
        })
        altered = request().to_json(); altered["question"] = "different question"
        intent = WorkflowEvent("quick-run", at, 3, "quick_attempt_intended", {
            "stage": "frame", "attempt": 1,
            "packet": {"stage": "frame", "request": altered, "inputs": {}, "output_schema": {}, "capabilities": {}},
        })
        with self.assertRaises(ValidationError):
            replay_quick_events((init, configured, intent))

    def test_replay_rejects_intent_packet_without_accepted_prerequisite(self) -> None:
        """Investigate may consume the accepted Frame payload, not an empty substitute."""
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        init = RunInitializedEvent("quick-run", at, request())
        configured = WorkflowEvent("quick-run", at, 2, "quick_configured", {
            "adapter": "codex", "executable": "codex", "model": None,
            "protocol_version": "1", "capabilities": {},
            "stages": ["frame", "investigate", "verify", "explain"],
        })
        packet = {"stage": "frame", "request": request().to_json(), "inputs": {}, "output_schema": {}, "capabilities": {}}
        frame = {"framed_question": "q", "success_criteria": [], "terms": [], "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"}
        finish = WorkflowEvent("quick-run", at, 4, "quick_attempt_finished", {
            "stage": "frame", "attempt": 1, "outcome": "succeeded", "exit_code": 0,
            "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64,
            "result": frame, "error": None,
        })
        investigate = WorkflowEvent("quick-run", at, 6, "quick_attempt_intended", {
            "stage": "investigate", "attempt": 1,
            "packet": {"stage": "investigate", "request": request().to_json(), "inputs": {}, "output_schema": {}, "capabilities": {}},
        })
        with self.assertRaises(ValidationError):
            replay_quick_events((
                init, configured,
                WorkflowEvent("quick-run", at, 3, "quick_attempt_intended", {"stage": "frame", "attempt": 1, "packet": packet}),
                finish,
                WorkflowEvent("quick-run", at, 5, "quick_stage_accepted", {"stage": "frame", "attempt": 1}),
                investigate,
            ))
