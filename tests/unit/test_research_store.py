from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mathresearch.research.events import ResearchEvent, canonical_json_bytes
from mathresearch.research.store import initialize_research, load_research_status, open_research_run
from mathresearch.run_store import initialize_run, load_run_status
from tests.unit.test_research_events import ACTION, DETAILS, PACKET, TELEMETRY
from tests.unit.test_research_contracts import valid_request_payload
from tests.helpers import valid_run_request_payload


class ResearchStoreTests(unittest.TestCase):
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
