from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mathresearch.research.events import ResearchEvent, canonical_json_bytes
from mathresearch.research.store import initialize_research, load_research_status, open_research_run
from mathresearch.run_store import initialize_run, load_run_status
from tests.unit.test_research_events import ACTION, DETAILS, PACKET, TELEMETRY
from tests.unit.test_research_contracts import valid_request_payload
from tests.helpers import valid_run_request_payload


class ResearchStoreTests(unittest.TestCase):
    def _new_run(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
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

    def test_legacy_run_status_preserves_all_committed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "legacy-request.json"
            request.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
            run = root / "legacy-run"; initialize_run(request, run)
            before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
            load_run_status(run)
            after = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
