"""Durable projection and capture tests for quick records."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from mathresearch.contracts.quick import QuickState, WorkflowEvent
from mathresearch.errors import RunCorruptError
from mathresearch.run_store import initialize_run, open_locked_run, load_run_status


def request_payload() -> dict:
    return {"schema_version": 1, "record_type": "run_request", "run_id": "quick-store", "question": "q", "actual_goal": None, "context": None, "constraints": [], "audience_level": "general", "mode": "quick", "stakes": "ordinary", "learning_mode": False, "capabilities": {}, "budgets": {"max_accepted_submissions": 4, "max_revision_cycles": 0, "elapsed_time_seconds": None}}


def configured(at: datetime, sequence: int = 2) -> WorkflowEvent:
    return WorkflowEvent("quick-store", at, sequence, "quick_configured", {"adapter": "codex", "executable": "codex", "model": None, "protocol_version": "1", "capabilities": {"reasoning": True}, "stages": ["frame", "investigate", "verify", "explain"]})


class QuickStoreTests(unittest.TestCase):
    def test_intent_materializes_packet_and_capture_is_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(request_payload()), encoding="utf-8")
            run = root / "run"; initialize_run(request, run)
            packet = {"stage": "frame", "request": request_payload(), "inputs": {}, "output_schema": {}, "capabilities": {}}
            with open_locked_run(run) as locked:
                at = locked.events[0].occurred_at
                locked.append(configured(at))
                locked.append(WorkflowEvent("quick-store", at, 3, "quick_attempt_intended", {"stage": "frame", "attempt": 1, "packet": packet}))
                digest = locked.write_capture("frame", 1, "stdout.bin", b"diagnostic")
                self.assertEqual(digest, hashlib.sha256(b"diagnostic").hexdigest())
            state = load_run_status(run)
            self.assertIsInstance(state, QuickState)
            self.assertEqual(state.current_stage, "frame")
            self.assertEqual((run / "tasks" / "task-frame" / "attempts" / "attempt-frame-001" / "packet.json").read_text(encoding="utf-8"), json.dumps(packet, ensure_ascii=False, separators=(",", ":")))

    def test_replay_rejects_tampered_finished_capture(self) -> None:
        """Changing diagnostics after their digest commits must make status fail."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(request_payload()), encoding="utf-8")
            run = root / "run"; initialize_run(request, run)
            packet = {"stage": "frame", "request": request_payload(), "inputs": {}, "output_schema": {}, "capabilities": {}}
            with open_locked_run(run) as locked:
                at = locked.events[0].occurred_at
                locked.append(configured(at))
                locked.append(WorkflowEvent("quick-store", at, 3, "quick_attempt_intended", {"stage": "frame", "attempt": 1, "packet": packet}))
                stdout = locked.write_capture("frame", 1, "stdout.bin", b"before")
                stderr = locked.write_capture("frame", 1, "stderr.log", b"diagnostic")
                locked.append(WorkflowEvent("quick-store", at, 4, "quick_attempt_finished", {"stage": "frame", "attempt": 1, "outcome": "failed", "exit_code": 1, "stdout_sha256": stdout, "stderr_sha256": stderr, "result": None, "error": "worker failed"}))
            (run / "tasks" / "task-frame" / "attempts" / "attempt-frame-001" / "stdout.bin").write_bytes(b"after")
            with self.assertRaises(RunCorruptError):
                load_run_status(run)

    def test_replay_rejects_missing_finished_capture(self) -> None:
        """A finished event cannot claim a diagnostic file that was never published."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(request_payload()), encoding="utf-8")
            run = root / "run"; initialize_run(request, run)
            packet = {"stage": "frame", "request": request_payload(), "inputs": {}, "output_schema": {}, "capabilities": {}}
            with open_locked_run(run) as locked:
                at = locked.events[0].occurred_at
                locked.append(configured(at))
                locked.append(WorkflowEvent("quick-store", at, 3, "quick_attempt_intended", {"stage": "frame", "attempt": 1, "packet": packet}))
                stdout = locked.write_capture("frame", 1, "stdout.bin", b"output")
                stderr = locked.write_capture("frame", 1, "stderr.log", b"diagnostic")
                locked.append(WorkflowEvent("quick-store", at, 4, "quick_attempt_finished", {"stage": "frame", "attempt": 1, "outcome": "failed", "exit_code": 1, "stdout_sha256": stdout, "stderr_sha256": stderr, "result": None, "error": "worker failed"}))
            (run / "tasks" / "task-frame" / "attempts" / "attempt-frame-001" / "stderr.log").unlink()
            with self.assertRaises(RunCorruptError):
                load_run_status(run)

    def test_legacy_history_rejects_quick_only_report_projection(self) -> None:
        """A report cache is evidence only for a completed version-two quick run."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(request_payload()), encoding="utf-8")
            run = root / "run"; initialize_run(request, run)
            (run / "report.md").write_text("uncommitted", encoding="utf-8")
            with self.assertRaises(RunCorruptError):
                load_run_status(run)
