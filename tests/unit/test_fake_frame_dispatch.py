"""Integration coverage for durable fake Frame dispatch orchestration."""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mathresearch.contracts.frame import build_frame_task
from mathresearch.contracts.run import (
    FrameAttemptIntendedEvent,
    FrameSubmissionAcceptedEvent,
    FrameTaskCreatedEvent,
)
from mathresearch.dispatch import dispatch_fake_frame
from mathresearch.process_runner import ProcessResult
from mathresearch.run_store import LockedRun, initialize_run, load_run_status, open_locked_run
from tests.helpers import valid_run_request_payload


class FakeFrameDispatchTests(unittest.TestCase):
    def _initialized_run(self, root: Path) -> Path:
        request = root / "request.json"
        request.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
        run_dir = root / "run-local-calculation"
        initialize_run(request, run_dir)
        return run_dir

    def test_dispatch_accepts_one_frame_and_is_idempotent(self) -> None:
        """One call records the whole Frame lifecycle; a later call launches nothing."""
        with tempfile.TemporaryDirectory() as temp:
            run_dir = self._initialized_run(Path(temp))
            first = dispatch_fake_frame(run_dir)
            self.assertEqual(first.status, "accepted")
            self.assertEqual(first.state.status, "active")
            self.assertEqual(first.state.accepted_submission_count, 1)
            self.assertEqual(first.state.last_event_sequence, 5)
            attempt = run_dir / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"
            self.assertTrue((attempt / "packet.json").is_file())
            self.assertTrue((attempt / "stdout.bin").is_file())
            self.assertTrue((attempt / "stderr.log").is_file())
            with patch("mathresearch.dispatch.run_fake_frame_attempt") as launch:
                duplicate = dispatch_fake_frame(run_dir)
            launch.assert_not_called()
            self.assertEqual(duplicate.status, "already_accepted")
            self.assertEqual(duplicate.state.last_event_sequence, 5)
            self.assertEqual(load_run_status(run_dir).accepted_submission_count, 1)

    def test_intent_only_history_is_blocked_without_relaunch(self) -> None:
        """A crash after durable intent is never silently retried by a later dispatch."""
        with tempfile.TemporaryDirectory() as temp:
            run_dir = self._initialized_run(Path(temp))
            with open_locked_run(run_dir) as locked:
                created = locked.state.initialized_at + timedelta(microseconds=1)
                locked.append(FrameTaskCreatedEvent(locked.request.run_id, created, build_frame_task(locked.request), 2))
                locked.append(FrameAttemptIntendedEvent(locked.request.run_id, created + timedelta(microseconds=1), "frame", 1, 1, 3))
            with patch("mathresearch.dispatch.run_fake_frame_attempt") as launch:
                result = dispatch_fake_frame(run_dir)
            launch.assert_not_called()
            self.assertEqual(result.status, "blocked_interrupted")
            self.assertEqual(result.state.last_event_sequence, 3)

    def test_successful_outcome_crash_recovers_acceptance_without_relaunch(self) -> None:
        """A retry accepts a captured successful submission after the acceptance crash window."""
        with tempfile.TemporaryDirectory() as temp:
            run_dir = self._initialized_run(Path(temp))
            original_append = LockedRun.append

            def crash_before_acceptance(locked: LockedRun, candidate: object):
                if isinstance(candidate, FrameSubmissionAcceptedEvent):
                    raise RuntimeError("simulated coordinator crash")
                return original_append(locked, candidate)  # type: ignore[arg-type]

            with patch.object(LockedRun, "append", new=crash_before_acceptance):
                with self.assertRaisesRegex(RuntimeError, "simulated coordinator crash"):
                    dispatch_fake_frame(run_dir)

            with patch("mathresearch.dispatch.run_fake_frame_attempt") as launch:
                recovered = dispatch_fake_frame(run_dir)
            launch.assert_not_called()
            self.assertEqual(recovered.status, "accepted")
            self.assertEqual(recovered.state.accepted_submission_count, 1)
            self.assertEqual(recovered.state.last_event_sequence, 5)
            self.assertEqual(
                json.loads((run_dir / "events" / "000005.json").read_text(encoding="utf-8"))["event_type"],
                "frame_submission_accepted",
            )
            with patch("mathresearch.dispatch.run_fake_frame_attempt") as launch:
                duplicate = dispatch_fake_frame(run_dir)
            launch.assert_not_called()
            self.assertEqual(duplicate.status, "already_accepted")
            self.assertEqual(duplicate.state.last_event_sequence, 5)

    def test_malformed_zero_exit_output_persists_outcome_without_acceptance(self) -> None:
        """A completed malformed worker result is inspectable and not accepted."""
        with tempfile.TemporaryDirectory() as temp:
            run_dir = self._initialized_run(Path(temp))
            malformed = ProcessResult("run-local-calculation", "frame", 1, 1, 0, b"{bad", b"diagnostic", None, "bad JSON")
            with patch("mathresearch.dispatch.run_fake_frame_attempt", return_value=malformed):
                result = dispatch_fake_frame(run_dir)
            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.state.last_event_sequence, 4)
            self.assertEqual(result.state.accepted_submission_count, 0)
            events = sorted((run_dir / "events").glob("*.json"))
            self.assertEqual(json.loads(events[-1].read_text(encoding="utf-8"))["event_type"], "frame_process_outcome")

    def test_failed_and_negative_process_results_are_persisted_without_acceptance(self) -> None:
        """Every completed non-success result gets its signed durable process outcome."""
        for exit_code in (2, -9):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temp:
                run_dir = self._initialized_run(Path(temp))
                failed = ProcessResult("run-local-calculation", "frame", 1, 1, exit_code, b"", b"failed", None)
                with patch("mathresearch.dispatch.run_fake_frame_attempt", return_value=failed):
                    result = dispatch_fake_frame(run_dir)
                self.assertEqual(result.status, "rejected")
                self.assertEqual(result.state.last_event_sequence, 4)
                outcome = json.loads((run_dir / "events" / "000004.json").read_text(encoding="utf-8"))
                self.assertEqual(outcome["exit_code"], exit_code)
