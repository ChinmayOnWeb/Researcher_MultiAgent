from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mathresearch.research.events import ResearchEvent, canonical_json_bytes
from mathresearch.research.store import initialize_research, load_research_status, open_research_run
from mathresearch.run_store import load_run_status
from tests.unit.test_research_events import ACTION, DETAILS, PACKET, TELEMETRY
from tests.unit.test_research_contracts import valid_request_payload


class ResearchStoreTests(unittest.TestCase):
    def test_store_replays_supplied_gate_text_into_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = self._new_run(root / "gate-text")
            gate = self._event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
            response = {"schema_version": 3, "record_type": "research_gate_response", "gate_id": "g0001", "response_id": "r0001", "decision": "supply", "text": "exact\nπ", "sources": []}
            answer = self._event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001", "response": response})
            with open_research_run(run) as locked:
                locked.append(gate); locked.append(answer)
            self.assertEqual(load_research_status(run).additional_user_input, ({"gate_id": "g0001", "response_id": "r0001", "text": "exact\nπ"},))

    def _new_run(self, root: Path, payload: dict[str, object] | None = None) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        request = root / "request.json"; request.write_text(json.dumps(payload or valid_request_payload()), encoding="utf-8")
        run = root / "run"; initialize_research(request, run); return run

    def _event(self, sequence: int, event_type: str, body: dict[str, object]) -> ResearchEvent:
        return ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": sequence, "event_type": event_type, "run_id": "odd-perfect-run", "occurred_at": f"2099-01-01T00:00:{sequence:02d}Z", "body": body})

    def _decision(self) -> ResearchEvent:
        return self._event(2, "decision_recorded", {"decision_id": "d0001", "kind": "worker", "reason_code": "frame_request", "action": ACTION, "details": DETAILS})

    def _intent(self) -> ResearchEvent:
        return self._event(3, "action_intended", {"action_id": "a0001", "packet": PACKET, "packet_sha256": __import__("hashlib").sha256(canonical_json_bytes(PACKET)).hexdigest()})

    def test_v3_fault_matrix_preserves_committed_boundaries(self) -> None:
        """Every injected publication failure leaves only durable evidence recoverable once."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Decision commit: no event is published when immutable event creation fails.
            run = self._new_run(root / "decision")
            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("decision")):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.append(self._decision())
            self.assertFalse((run / "events" / "000002.json").exists())

            # Intent projection: event commit survives packet materialization failure and recovers once.
            run = self._new_run(root / "intent")
            with open_research_run(run) as locked: locked.append(self._decision())
            from mathresearch.research import store as store_module
            original_new = store_module._atomic_write_new
            def fail_packet(target: Path, data: bytes) -> None:
                if target.name == "packet.json": raise OSError("packet")
                original_new(target, data)
            with patch("mathresearch.research.store._atomic_write_new", side_effect=fail_packet):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.append(self._intent())
            self.assertTrue((run / "events" / "000003.json").exists()); load_research_status(run)
            self.assertEqual(len(list((run / "events").glob("*.json"))), 3)

            # First/second capture failures never invent a capture; completed intent remains unique.
            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("first")):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.write_capture("a0001", "stdout.bin", b"out")
            self.assertFalse((run / "actions" / "a0001" / "stdout.bin").exists())
            with open_research_run(run) as locked: locked.write_capture("a0001", "stdout.bin", b"out")
            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("second")):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.write_capture("a0001", "stderr.log", b"err")
            self.assertTrue((run / "actions" / "a0001" / "stdout.bin").exists()); self.assertFalse((run / "actions" / "a0001" / "stderr.log").exists())

            # Action-finish commit failure leaves no finish event; gate-response commit failure likewise.
            stdout = __import__("hashlib").sha256(b"out").hexdigest(); stderr = __import__("hashlib").sha256(b"err").hexdigest()
            finish = self._event(4, "action_finished", {"action_id": "a0001", "outcome": "succeeded", "exit_code": 0, "stdout_sha256": stdout, "stderr_sha256": stderr, "result": {"task_type": "exploration", "deliverables": ["d"], "subquestions": ["q"], "missing_inputs": [], "proposed_checks": [], "source_needs": []}, "error": None, "telemetry": TELEMETRY})
            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("finish")):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.append(finish)
            self.assertFalse((run / "events" / "000004.json").exists())

            run = self._new_run(root / "gate")
            gate = self._event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
            with open_research_run(run) as locked: locked.append(gate)
            answer = self._event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001", "response": {}})
            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("gate")):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.append(answer)
            self.assertFalse((run / "events" / "000003.json").exists())

            run = self._new_run(root / "report")
            final = self._event(2, "research_finished", {"status": "complete", "assessment": {}, "reason": "x", "report_markdown": "report", "log_markdown": "log"})
            original_replace = store_module._atomic_write_replace
            def fail_report(target: Path, data: bytes) -> None:
                if target.name == "report.md": raise OSError("report")
                original_replace(target, data)
            with patch("mathresearch.research.store._atomic_write_replace", side_effect=fail_report):
                with self.assertRaises(Exception):
                    with open_research_run(run) as locked: locked.append(final)
            self.assertTrue((run / "events" / "000002.json").exists()); load_research_status(run)
            self.assertEqual((run / "report.md").read_text(encoding="utf-8"), "report")

    def test_finished_tool_result_recovers_after_each_post_commit_projection_failure(self) -> None:
        """A committed finish repairs result, receipt, and source without republishing the action."""
        from mathresearch.research import store as store_module

        for failed_name in ("result.json", "receipt.json", "source.json"):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as temp:
                request_payload = valid_request_payload()
                request_payload["capabilities"]["fetch_sources"] = True
                source_url = "https://example.test/source"
                request_payload["sources"] = [{"id": "source-one", "kind": "url",
                                               "title": "Source one", "text": None,
                                               "url": source_url, "published_at": None}]
                run = self._new_run(Path(temp), request_payload)
                action = {"id": "a0001", "kind": "tool", "role": "fetch_source",
                          "branch": None, "round": 0, "dependencies": [],
                          "payload": {"id": "fetch-one", "operation": "fetch_source",
                                      "arguments": {"source_id": "source-one"}}}
                decision = self._event(2, "decision_recorded", {"decision_id": "d0001",
                                      "kind": "tool", "reason_code": "acquire_source",
                                      "action": action, "details": DETAILS})
                intent = self._event(3, "action_intended", {"action_id": "a0001",
                                    "packet": PACKET, "packet_sha256":
                                    __import__("hashlib").sha256(canonical_json_bytes(PACKET)).hexdigest()})
                with open_research_run(run) as locked:
                    locked.append(decision)
                    locked.append(intent)
                    stdout = locked.write_capture("a0001", "stdout.bin", b"out")
                    stderr = locked.write_capture("a0001", "stderr.log", b"err")
                source = {"id": "source-one", "url": source_url}
                finish = self._event(4, "action_finished", {"action_id": "a0001",
                                     "outcome": "succeeded", "exit_code": 0,
                                     "stdout_sha256": stdout, "stderr_sha256": stderr,
                                     "result": {"source": source}, "error": None,
                                     "telemetry": TELEMETRY})
                original_new = store_module._atomic_write_new

                def fail_selected_projection(target: Path, data: bytes) -> None:
                    if target.name == failed_name:
                        raise OSError(f"simulated {failed_name} publication failure")
                    original_new(target, data)

                with patch("mathresearch.research.store._atomic_write_new",
                           side_effect=fail_selected_projection):
                    with self.assertRaises(OSError):
                        with open_research_run(run) as locked:
                            locked.append(finish)

                event_paths_before = sorted((run / "events").glob("*.json"))
                self.assertEqual([path.name for path in event_paths_before],
                                 ["000001.json", "000002.json", "000003.json", "000004.json"])
                recovered = load_research_status(run)

                self.assertEqual(recovered.results["a0001"], {"source": source})
                self.assertEqual(json.loads((run / "actions" / "a0001" / "result.json").read_text(encoding="utf-8")), {"source": source})
                self.assertEqual(json.loads((run / "tools" / "a0001" / "receipt.json").read_text(encoding="utf-8")), {"source": source})
                self.assertEqual(json.loads((run / "sources" / "source-one" / "source.json").read_text(encoding="utf-8")), source)
                event_paths_after = sorted((run / "events").glob("*.json"))
                self.assertEqual(event_paths_after, event_paths_before)
                finished_events = [json.loads(path.read_text(encoding="utf-8"))
                                   for path in event_paths_after
                                   if json.loads(path.read_text(encoding="utf-8"))["event_type"] == "action_finished"]
                self.assertEqual(len(finished_events), 1)
    def test_initializes_and_repairs_state_from_immutable_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
            run = root / "run"
            initialize_research(request, run)
            (run / "state.json").unlink()
            state = load_research_status(run)
            self.assertEqual(state.status, "ready")
            self.assertTrue((run / "state.json").exists())

    def test_rejects_unexpected_root_and_unsafe_action_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
            run = root / "run"; initialize_research(request, run)
            (run / "unexpected").write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError): load_research_status(run)

    def test_missing_finished_capture_blocks_all_projection_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
            run = root / "run"; initialize_research(request, run)
            with open_research_run(run) as locked:
                base = {"schema_version": 3, "record_type": "research_event", "run_id": "odd-perfect-run", "occurred_at": "2099-09-16T00:00:02Z"}
                locked.append(ResearchEvent.from_json(base | {"sequence": 2, "event_type": "decision_recorded", "body": {"decision_id": "d0001", "kind": "worker", "reason_code": "frame_request", "action": ACTION, "details": DETAILS}}))
                packet = canonical_json_bytes(PACKET)
                locked.append(ResearchEvent.from_json(base | {"sequence": 3, "event_type": "action_intended", "body": {"action_id": "a0001", "packet": PACKET, "packet_sha256": __import__("hashlib").sha256(packet).hexdigest()}}))
                stdout = locked.write_capture("a0001", "stdout.bin", b"out"); stderr = locked.write_capture("a0001", "stderr.log", b"err")
                locked.append(ResearchEvent.from_json(base | {"sequence": 4, "event_type": "action_finished", "body": {"action_id": "a0001", "outcome": "succeeded", "exit_code": 0, "stdout_sha256": stdout, "stderr_sha256": stderr, "result": {"task_type": "exploration", "deliverables": ["d"], "subquestions": ["q"], "missing_inputs": [], "proposed_checks": [], "source_needs": []}, "error": None, "telemetry": TELEMETRY}}))
            shutil.rmtree(run / "actions" / "a0001")
            (run / "state.json").unlink()
            with self.assertRaises(RuntimeError): load_research_status(run)
            self.assertFalse((run / "state.json").exists())

    def test_complete_hand_authored_v2_status_preserves_every_file_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "v2-run"
            events_dir = run / "events"
            events_dir.mkdir(parents=True)
            (run / ".run.lock").write_bytes(b"\0")
            occurred_at = "2099-01-01T00:00:00.000000Z"
            request = {"schema_version": 1, "record_type": "run_request",
                       "run_id": "quick-v2-fixture", "question": "q", "actual_goal": None,
                       "context": None, "constraints": [], "audience_level": "general",
                       "mode": "quick", "stakes": "ordinary", "learning_mode": False,
                       "capabilities": {}, "budgets": {"max_accepted_submissions": 4,
                       "max_revision_cycles": 0, "elapsed_time_seconds": None}}
            frame = {"framed_question": "q", "success_criteria": ["answer"], "terms": [],
                     "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"}
            investigate = {"answer": "a", "claims": [{"id": "claim-one", "statement": "s",
                           "basis": "derived", "support": "calculation"}], "alternatives": [],
                           "limitations": []}
            verify = {"checks": [{"claim_id": "claim-one", "verdict": "supported",
                      "reasoning": "checked"}], "disposition": "pass", "limitations": []}
            explain = {"summary": "summary", "explanation": "explanation",
                       "conclusion": "supported", "limitations": []}
            packets = {
                "frame": {"stage": "frame", "request": request, "inputs": {},
                          "output_schema": {}, "capabilities": {}},
                "investigate": {"stage": "investigate", "request": request,
                                "inputs": {"frame": frame}, "output_schema": {},
                                "capabilities": {}},
                "verify": {"stage": "verify", "request": request,
                           "inputs": {"frame": frame, "investigate": investigate},
                           "output_schema": {}, "capabilities": {}},
                "explain": {"stage": "explain", "request": request,
                            "inputs": {"frame": frame, "investigate": investigate,
                                       "verify": verify}, "output_schema": {},
                            "capabilities": {}},
            }
            stdout = {stage: f"stdout-{stage}".encode("ascii")
                      for stage in ("frame", "investigate", "verify", "explain")}
            stderr = {stage: f"stderr-{stage}".encode("ascii")
                      for stage in ("frame", "investigate", "verify", "explain")}
            digest = __import__("hashlib").sha256

            def workflow(sequence: int, event_type: str,
                         body: dict[str, object]) -> dict[str, object]:
                return {"schema_version": 2, "record_type": "workflow_event",
                        "sequence": sequence, "event_type": event_type,
                        "run_id": "quick-v2-fixture", "occurred_at": occurred_at,
                        "body": body}

            events = [
                {"schema_version": 1, "record_type": "run_event", "sequence": 1,
                 "event_type": "run_initialized", "run_id": "quick-v2-fixture",
                 "occurred_at": occurred_at, "request": request},
                workflow(2, "quick_configured", {"adapter": "codex", "executable": "codex",
                         "model": None, "protocol_version": "1", "capabilities": {},
                         "stages": ["frame", "investigate", "verify", "explain"]}),
                workflow(3, "quick_attempt_intended", {"stage": "frame", "attempt": 1,
                         "packet": packets["frame"]}),
                workflow(4, "quick_attempt_finished", {"stage": "frame", "attempt": 1,
                         "outcome": "succeeded", "exit_code": 0,
                         "stdout_sha256": digest(stdout["frame"]).hexdigest(),
                         "stderr_sha256": digest(stderr["frame"]).hexdigest(),
                         "result": frame, "error": None}),
                workflow(5, "quick_stage_accepted", {"stage": "frame", "attempt": 1}),
                workflow(6, "quick_attempt_intended", {"stage": "investigate", "attempt": 1,
                         "packet": packets["investigate"]}),
                workflow(7, "quick_attempt_finished", {"stage": "investigate", "attempt": 1,
                         "outcome": "succeeded", "exit_code": 0,
                         "stdout_sha256": digest(stdout["investigate"]).hexdigest(),
                         "stderr_sha256": digest(stderr["investigate"]).hexdigest(),
                         "result": investigate, "error": None}),
                workflow(8, "quick_stage_accepted", {"stage": "investigate", "attempt": 1}),
                workflow(9, "quick_attempt_intended", {"stage": "verify", "attempt": 1,
                         "packet": packets["verify"]}),
                workflow(10, "quick_attempt_finished", {"stage": "verify", "attempt": 1,
                         "outcome": "succeeded", "exit_code": 0,
                         "stdout_sha256": digest(stdout["verify"]).hexdigest(),
                         "stderr_sha256": digest(stderr["verify"]).hexdigest(),
                         "result": verify, "error": None}),
                workflow(11, "quick_stage_accepted", {"stage": "verify", "attempt": 1}),
                workflow(12, "quick_attempt_intended", {"stage": "explain", "attempt": 1,
                         "packet": packets["explain"]}),
                workflow(13, "quick_attempt_finished", {"stage": "explain", "attempt": 1,
                         "outcome": "succeeded", "exit_code": 0,
                         "stdout_sha256": digest(stdout["explain"]).hexdigest(),
                         "stderr_sha256": digest(stderr["explain"]).hexdigest(),
                         "result": explain, "error": None}),
                workflow(14, "quick_stage_accepted", {"stage": "explain", "attempt": 1}),
                workflow(15, "quick_completed", {"report_markdown": "# Complete v2 report\n"}),
            ]

            def write_json(path: Path, payload: object) -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(json.dumps(payload, ensure_ascii=False,
                                            separators=(",", ":")).encode("utf-8"))

            write_json(run / "request.json", request)
            write_json(run / "state.json", {"schema_version": 2,
                       "record_type": "quick_state", "run_id": "quick-v2-fixture",
                       "initialized_at": occurred_at, "status": "complete",
                       "last_event_sequence": 15, "accepted_submission_count": 4,
                       "current_stage": None, "reason": None, "report_path": "report.md"})
            for sequence, payload in enumerate(events, 1):
                write_json(events_dir / f"{sequence:06d}.json", payload)
            for stage, result in (("frame", frame), ("investigate", investigate),
                                  ("verify", verify), ("explain", explain)):
                task_dir = run / "tasks" / f"task-{stage}"
                attempt_dir = task_dir / "attempts" / f"attempt-{stage}-001"
                write_json(task_dir / "accepted.json", result)
                write_json(attempt_dir / "packet.json", packets[stage])
                (attempt_dir / "stdout.bin").write_bytes(stdout[stage])
                (attempt_dir / "stderr.log").write_bytes(stderr[stage])
            (run / "report.md").write_bytes(b"# Complete v2 report\n")

            before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
            state = load_run_status(run)
            after = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}

            self.assertEqual(state.status, "complete")
            self.assertEqual(state.last_event_sequence, 15)
            self.assertEqual(after, before)
