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


def fetch_history(*, requested_id: str = "source-one", result_id: str = "source-one",
                  descriptor_url: str = "https://example.test/source",
                  result_url: str = "https://example.test/source") -> list[dict[str, object]]:
    request = valid_request_payload()
    request["capabilities"]["fetch_sources"] = True
    request["sources"] = [{"id": "source-one", "kind": "url", "title": "Source one",
                           "text": None, "url": descriptor_url, "published_at": None}]
    action = {"id": "a0001", "kind": "tool", "role": "fetch_source", "branch": None,
              "round": 0, "dependencies": [], "payload": {"id": "fetch-one",
              "operation": "fetch_source", "arguments": {"source_id": requested_id}}}
    return [
        event(1, "research_initialized", {"request": request}),
        event(2, "decision_recorded", {"decision_id": "d0001", "kind": "tool",
              "reason_code": "acquire_source", "action": action, "details": DETAILS}),
        event(3, "action_intended", {"action_id": "a0001", "packet": PACKET,
              "packet_sha256": SHA}),
        event(4, "action_finished", {"action_id": "a0001", "outcome": "succeeded",
              "exit_code": 0, "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64,
              "result": {"source": {"id": result_id, "url": result_url}}, "error": None,
              "telemetry": TELEMETRY}),
    ]


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
    def test_provider_configuration_is_persisted_and_matches_request(self) -> None:
        config = {"executable": "C:/tools/codex.exe", "version": "codex 0.154.0",
                  "model_requested": "gpt-test", "effort_requested": "high",
                  "control_argv": ["--strict-config", "-c", 'model_reasoning_effort="high"'],
                  "prompt_version": "research-v1"}
        state = replay_research_events([ResearchEvent.from_json(event(1, "research_initialized", {"request": valid_request_payload()})),
                                        ResearchEvent.from_json(event(2, "provider_configured", config))])
        self.assertEqual(state.provider_config, config)
        for changed in ({"effort_requested": "medium"}, {"model_requested": "other"}):
            invalid = config | changed
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                replay_research_events([ResearchEvent.from_json(event(1, "research_initialized", {"request": valid_request_payload()})),
                                        ResearchEvent.from_json(event(2, "provider_configured", invalid))])

    def test_supplied_gate_text_is_immutable_snapshot_input(self) -> None:
        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
        response = {"schema_version": 3, "record_type": "research_gate_response", "gate_id": "g0001", "response_id": "r0001", "decision": "supply", "text": "quoted\nUnicode: π", "sources": []}
        snapshot = replay_research_events([ResearchEvent.from_json(event(1, "research_initialized", {"request": valid_request_payload()})), ResearchEvent.from_json(gate), ResearchEvent.from_json(event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001", "response": response}))])
        self.assertEqual(snapshot.additional_user_input, ({"gate_id": "g0001", "response_id": "r0001", "text": "quoted\nUnicode: π"},))

    def test_gate_response_rejects_mismatched_or_invalid_supply(self) -> None:
        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
        valid = {"schema_version": 3, "record_type": "research_gate_response", "gate_id": "g0001", "response_id": "r0001", "decision": "supply", "text": "text", "sources": []}
        for replacement in ({"gate_id": "g0002"}, {"text": None}, {"decision": "cancel", "text": "text"}, {"text": "x" * 16001}):
            response = copy.deepcopy(valid); response.update(replacement)
            history = [event(1, "research_initialized", {"request": valid_request_payload()}), gate, event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001", "response": response})]
            with self.subTest(replacement=replacement):
                with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])

    def test_gate_response_requires_complete_envelope_when_sources_is_omitted(self) -> None:
        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
        response = {"schema_version": 3, "record_type": "research_gate_response", "gate_id": "g0001", "response_id": "r0001", "decision": "supply", "text": "injected text"}
        history = [event(1, "research_initialized", {"request": valid_request_payload()}), gate, event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001", "response": response})]
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])

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

    def test_decision_action_kind_and_open_gate_finish_are_illegal(self) -> None:
        decision = event(2, "decision_recorded", {"decision_id": "d0001", "kind": "worker", "reason_code": "frame_request", "action": {**ACTION, "kind": "tool", "role": "fetch_source", "payload": {"id": "tool-one", "operation": "fetch_source", "arguments": {"source_id": "source-one"}}}, "details": DETAILS})
        with self.assertRaises(ValueError): ResearchEvent.from_json(decision)
        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
        finish = event(3, "research_finished", {"status": "incomplete", "assessment": {}, "reason": "x", "report_markdown": "", "log_markdown": ""})
        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(x) for x in [event(1, "research_initialized", {"request": valid_request_payload()}), gate, finish]])

    def test_fetch_result_must_match_an_authorized_requested_url_descriptor(self) -> None:
        snapshot = replay_research_events([ResearchEvent.from_json(item) for item in fetch_history()])
        self.assertEqual(snapshot.results["a0001"]["source"]["id"], "source-one")

        for history in (
            fetch_history(requested_id="not-authorized", result_id="not-authorized"),
            fetch_history(result_id="different-source"),
            fetch_history(result_id="../unsafe"),
            fetch_history(result_url="https://example.test/different"),
        ):
            with self.subTest(result=history[-1]["body"]):
                with self.assertRaises(ValueError):
                    replay_research_events([ResearchEvent.from_json(item) for item in history])

    def test_fetch_result_accepts_a_url_descriptor_from_an_accepted_gate(self) -> None:
        request = valid_request_payload()
        request["capabilities"]["fetch_sources"] = True
        gate_source = {"id": "gate-source", "kind": "url", "title": "Gate source",
                       "text": None, "url": "https://example.test/gate", "published_at": None}
        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "request_evidence",
                     "questions": ["Provide a source."], "allowed_response": ["supply"],
                     "resume_token": "0" * 64})
        answer = event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001",
                       "response": {"schema_version": 3, "record_type": "research_gate_response",
                       "gate_id": "g0001", "response_id": "r0001", "decision": "supply",
                       "text": None, "sources": [gate_source]}})
        action = {"id": "a0001", "kind": "tool", "role": "fetch_source", "branch": None,
                  "round": 0, "dependencies": [], "payload": {"id": "fetch-gate",
                  "operation": "fetch_source", "arguments": {"source_id": "gate-source"}}}
        history = [event(1, "research_initialized", {"request": request}), gate, answer,
                   event(4, "decision_recorded", {"decision_id": "d0001", "kind": "tool",
                         "reason_code": "acquire_source", "action": action, "details": DETAILS}),
                   event(5, "action_intended", {"action_id": "a0001", "packet": PACKET,
                         "packet_sha256": SHA}),
                   event(6, "action_finished", {"action_id": "a0001", "outcome": "succeeded",
                         "exit_code": 0, "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64,
                         "result": {"source": {"id": "gate-source", "url": gate_source["url"]}},
                         "error": None, "telemetry": TELEMETRY})]

        snapshot = replay_research_events([ResearchEvent.from_json(item) for item in history])

        self.assertEqual(snapshot.results["a0001"]["source"]["id"], "gate-source")
        rejected = copy.deepcopy(history)
        rejected[1]["body"]["allowed_response"] = ["continue_limited"]
        with self.assertRaises(ValueError):
            replay_research_events([ResearchEvent.from_json(item) for item in rejected])
