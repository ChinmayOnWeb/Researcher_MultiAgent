"""Hand-authored v3 event histories; never produced by the reducer under test."""

from __future__ import annotations

import copy
import hashlib
import unittest

from mathresearch.research.events import ResearchEvent, replay_research_events
from tests.unit.test_research_contracts import valid_request_payload


def event(sequence: int, kind: str, body: dict[str, object]) -> dict[str, object]:
    return {"schema_version": 3, "record_type": "research_event", "sequence": sequence,
            "event_type": kind, "run_id": "odd-perfect-run",
            "occurred_at": f"2026-09-16T00:00:0{sequence}.000000Z", "body": body}


ACTION = {"id": "a0001", "kind": "worker", "role": "frame", "branch": None, "round": 0,
          "dependencies": [], "payload": {"prompt_version": "research-v1"}}
DETAILS = {"selected_draft_id": None, "audit_id": None, "question_status": None,
           "blockers": [], "finish_status": None, "round": 0}
PACKET = {"opaque": ["packet"], "version": 3}
SHA = hashlib.sha256(b'{"opaque":["packet"],"version":3}').hexdigest()
TELEMETRY = {"duration_ms": 1, "input_bytes": 1, "output_bytes": 1, "model_observed": None,
             "effort_observed": None, "input_tokens": None, "output_tokens": None,
             "reasoning_tokens": None, "cost_usd": None}


def quick_complete() -> list[dict[str, object]]:
    return [
        event(1, "research_initialized", {"request": valid_request_payload()}),
        event(2, "decision_recorded", {"decision_id": "d0001", "kind": "worker", "reason_code": "initial_approach", "action": ACTION, "details": DETAILS}),
        event(3, "action_intended", {"action_id": "a0001", "packet": PACKET, "packet_sha256": SHA}),
        event(4, "action_finished", {"action_id": "a0001", "outcome": "succeeded", "exit_code": 0,
              "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64, "result": {"task_type": "exploration", "deliverables": ["d"], "subquestions": ["q"], "missing_inputs": [], "proposed_checks": [], "source_needs": []}, "error": None, "telemetry": TELEMETRY}),
        event(5, "research_finished", {"status": "complete", "assessment": {"status": "unresolved"}, "reason": "assessment_satisfied", "report_markdown": "# Report\n", "log_markdown": "# Log\n"}),
    ]


class ResearchEventTests(unittest.TestCase):
    def test_hand_authored_quick_complete_replays(self) -> None:
        snapshot = replay_research_events([ResearchEvent.from_json(item) for item in quick_complete()])
        self.assertEqual(snapshot.status, "complete")
        self.assertIn("a0001", snapshot.results)

    def test_contiguous_and_single_initialization_are_required(self) -> None:
        history = quick_complete(); history[1]["sequence"] = 3
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
        history = quick_complete(); history.insert(1, event(2, "research_initialized", {"request": valid_request_payload()}))
        for i, item in enumerate(history, 1): item["sequence"] = i
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])

    def test_rejects_unknown_event_packet_hash_wrong_finish_and_terminal_action(self) -> None:
        unknown = event(1, "unknown", {})
        with self.assertRaises(ValueError): ResearchEvent.from_json(unknown)
        history = quick_complete(); history[2]["body"]["packet_sha256"] = "2" * 64
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
        history = quick_complete(); history[3]["body"]["action_id"] = "a0002"
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
        history = quick_complete(); history.append(event(6, "decision_recorded", {"decision_id": "d0002", "kind": "worker", "reason_code": "initial_approach", "action": ACTION, "details": DETAILS}))
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])

    def test_finish_without_intent_and_gate_conflicts_fail(self) -> None:
        history = quick_complete(); del history[2]
        for i, item in enumerate(history, 1): item["sequence"] = i
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
        init = event(1, "research_initialized", {"request": valid_request_payload()})
        duplicate = copy.deepcopy(gate); duplicate["sequence"] = 3
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in [init, gate, duplicate]])

    def test_success_result_must_match_the_recorded_worker_role(self) -> None:
        history = quick_complete()
        history[3]["body"]["result"] = {"arbitrary": "json"}
        with self.assertRaises(ValueError):
            replay_research_events([ResearchEvent.from_json(item) for item in history])

    def test_normalizes_equivalent_utc_instants_for_chronology(self) -> None:
        history = quick_complete()
        history[1]["occurred_at"] = "2026-09-15T17:00:02-07:00"
        self.assertEqual(replay_research_events([ResearchEvent.from_json(item) for item in history]).sequence, 5)
