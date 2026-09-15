"""Tests for the deterministic Frame worker and safe process boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mathresearch.contracts.frame import build_frame_packet, build_frame_task
from mathresearch.contracts.records import RunRequest
from mathresearch.contracts.run import FrameAttemptIntendedEvent, FrameTaskCreatedEvent
from mathresearch.fake_worker import build_fake_frame_submission
from mathresearch.process_runner import ProcessRunnerError, run_fake_frame_attempt
from mathresearch.run_store import initialize_run, load_run_status, open_locked_run
from tests.helpers import valid_run_request_payload


class FakeFrameProcessTests(unittest.TestCase):
    def _write_packet(self, root: Path) -> Path:
        request = RunRequest.from_json(valid_run_request_payload())
        packet = build_frame_packet(build_frame_task(request), request)
        attempt_dir = root / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"
        attempt_dir.mkdir(parents=True)
        path = attempt_dir / "packet.json"
        path.write_text(json.dumps(packet.to_json()), encoding="utf-8")
        return path

    @staticmethod
    def _run(packet: Path):
        return run_fake_frame_attempt(
            packet,
            attempt=1,
            stdout_path=packet.parent / "stdout.bin",
            stderr_path=packet.parent / "stderr.log",
            run_dir=packet.parents[4],
        )

    def test_nullable_goal_and_context_create_valid_missing_inputs(self) -> None:
        """Unknown request fields must not become invalid non-string frame values."""
        payload = valid_run_request_payload()
        payload["actual_goal"] = None
        payload["context"] = None
        request = RunRequest.from_json(payload)
        submission = build_fake_frame_submission(build_frame_packet(build_frame_task(request), request), attempt=1)
        self.assertEqual(submission.frame["success_criteria"], ())
        self.assertEqual(submission.frame["assumptions"], ())
        self.assertEqual(submission.frame["missing_inputs"], ("actual_goal", "context"))

    def test_each_nullable_request_field_is_valid_in_builder_and_real_child(self) -> None:
        """Each accepted nullable field independently yields a valid deterministic submission."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, goal, context in (("goal", None, "context"), ("context", "goal", None)):
                with self.subTest(name=name):
                    payload = valid_run_request_payload()
                    payload["actual_goal"] = goal
                    payload["context"] = context
                    request = RunRequest.from_json(payload)
                    self.assertIsNotNone(build_fake_frame_submission(build_frame_packet(build_frame_task(request), request), attempt=1))
                    packet = self._write_packet(root / name)
                    packet.write_text(json.dumps(build_frame_packet(build_frame_task(request), request).to_json()), encoding="utf-8")
                    self.assertIsNotNone(self._run(packet).submission)

    def test_real_worker_accepts_each_nullable_request_case(self) -> None:
        """The subprocess protocol covers every valid null combination, not only the builder."""
        for actual_goal, context, missing in ((None, "context", ("actual_goal",)), ("goal", None, ("context",)), (None, None, ("actual_goal", "context"))):
            with self.subTest(actual_goal=actual_goal, context=context), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                payload = valid_run_request_payload()
                payload["actual_goal"] = actual_goal
                payload["context"] = context
                request = RunRequest.from_json(payload)
                packet = build_frame_packet(build_frame_task(request), request)
                packet_path = self._write_packet(root)
                attempt_dir = packet_path.parent
                packet_path.write_text(json.dumps(packet.to_json()), encoding="utf-8")
                result = run_fake_frame_attempt(
                    packet_path,
                    attempt=1,
                    stdout_path=attempt_dir / "stdout.bin",
                    stderr_path=attempt_dir / "stderr.log",
                    run_dir=root,
                )
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.submission.frame["missing_inputs"], missing)  # type: ignore[union-attr]

    def test_real_worker_writes_canonical_capture_files(self) -> None:
        """Raw child bytes belong in the plan-defined attempt artifact names."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = self._write_packet(root)
            result = self._run(packet)
            self.assertEqual(result.exit_code, 0)
            self.assertIsNotNone(result.submission)
            self.assertEqual((packet.parent / "stdout.bin").read_bytes(), result.stdout)
            self.assertEqual((packet.parent / "stderr.log").read_bytes(), result.stderr)

    def test_rejects_collision_or_outside_capture_before_launch(self) -> None:
        """Packet and captures are distinct fixed children of one trusted attempt directory."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = self._write_packet(root)
            outside = root.parent / "outside-capture.bin"
            outside.write_bytes(b"preserve")
            for stdout, stderr in ((packet, packet.parent / "stderr.log"), (packet.parent / "stdout.bin", packet.parent / "stdout.bin"), (outside, packet.parent / "stderr.log")):
                with self.subTest(stdout=stdout, stderr=stderr), patch("mathresearch.process_runner.subprocess.run") as launch:
                    with self.assertRaises(ProcessRunnerError):
                        run_fake_frame_attempt(
                            packet,
                            attempt=1,
                            stdout_path=stdout,
                            stderr_path=stderr,
                            run_dir=root,
                        )
                    launch.assert_not_called()
            self.assertEqual(outside.read_bytes(), b"preserve")

    def test_refuses_a_linked_attempt_ancestor_before_launching(self) -> None:
        """A regular immediate parent cannot hide a linked ancestor traversal."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            actual = root / "actual"
            actual.mkdir()
            linked = root / "linked"
            linked.symlink_to(actual, target_is_directory=True)
            packet = self._write_packet(linked)
            with patch("mathresearch.process_runner.subprocess.run") as launch:
                with self.assertRaises(ProcessRunnerError):
                    run_fake_frame_attempt(
                        packet,
                        attempt=1,
                        stdout_path=packet.parent / "stdout.bin",
                        stderr_path=packet.parent / "stderr.log",
                        run_dir=linked,
                    )
                launch.assert_not_called()

    def test_malformed_completed_output_keeps_structured_process_result(self) -> None:
        """A completed bad worker output remains durable process evidence for Task 4."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("mathresearch.process_runner.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"{bad", b"diag")):
                packet = self._write_packet(root)
                result = self._run(packet)
            self.assertIsNone(result.submission)
            self.assertIsNotNone(result.submission_error)
            self.assertEqual(result.process_outcome(sequence=4, occurred_at=datetime(2026, 9, 14, tzinfo=timezone.utc)).exit_code, 0)
            self.assertEqual((packet.parent / "stdout.bin").read_bytes(), b"{bad")
            self.assertEqual((packet.parent / "stderr.log").read_bytes(), b"diag")

    def test_signed_termination_and_launch_failure_are_not_conflated(self) -> None:
        """Signal termination is persistable; failed creation has no invented outcome."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("mathresearch.process_runner.subprocess.run", return_value=subprocess.CompletedProcess([], -9, b"", b"")):
                result = self._run(self._write_packet(root))
            self.assertEqual(result.process_outcome(sequence=4, occurred_at=datetime(2026, 9, 14, tzinfo=timezone.utc)).exit_code, -9)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("mathresearch.process_runner.subprocess.run", side_effect=FileNotFoundError("missing")):
                with self.assertRaises(ProcessRunnerError):
                    self._run(self._write_packet(root))
            self.assertFalse((root / "tasks" / "task-frame" / "attempts" / "attempt-frame-001" / "stdout.bin").exists())

    def test_timeout_preserves_partial_capture_then_reports_a_runner_failure(self) -> None:
        """A bounded child must leave its visible partial output without inventing an outcome."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = self._write_packet(root)
            timeout = subprocess.TimeoutExpired(["fake"], 1, output=b"partial", stderr=b"slow")
            with patch("mathresearch.process_runner.subprocess.run", side_effect=timeout):
                with self.assertRaisesRegex(ProcessRunnerError, "timed out"):
                    self._run(packet)
            self.assertEqual((packet.parent / "stdout.bin").read_bytes(), b"partial")
            self.assertEqual((packet.parent / "stderr.log").read_bytes(), b"slow")

    def test_rejects_noncanonical_attempt_directory_and_symlink_ancestor_before_launch(self) -> None:
        """Capture boundaries must be actual materialized attempt directories, not arbitrary aliases."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            arbitrary = root / "arbitrary"
            arbitrary.mkdir()
            packet = arbitrary / "packet.json"
            packet.write_text(json.dumps(build_frame_packet(build_frame_task(RunRequest.from_json(valid_run_request_payload())), RunRequest.from_json(valid_run_request_payload())).to_json()), encoding="utf-8")
            with patch("mathresearch.process_runner.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as launch:
                with self.assertRaises(ProcessRunnerError):
                    self._run(packet)
            launch.assert_not_called()

    def test_rejects_canonical_named_attempt_outside_explicit_run_tree_before_launch(self) -> None:
        """An arbitrary matching hierarchy must not gain the supplied run's authority."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = self._write_packet(root / "outside-run")
            with patch("mathresearch.process_runner.subprocess.run") as launch:
                with self.assertRaises(ProcessRunnerError):
                    run_fake_frame_attempt(
                        packet,
                        attempt=1,
                        stdout_path=packet.parent / "stdout.bin",
                        stderr_path=packet.parent / "stderr.log",
                        run_dir=root / "authorized-run",
                    )
            launch.assert_not_called()

            real_packet = self._write_packet(root / "real")
            linked = root / "linked"
            linked.symlink_to(real_packet.parent.parent, target_is_directory=True)
            with patch("mathresearch.process_runner.subprocess.run") as launch:
                with self.assertRaises(ProcessRunnerError):
                    self._run(linked / "attempt-frame-001" / "packet.json")
            launch.assert_not_called()


class FrameCaptureStoreIntegrationTests(unittest.TestCase):
    def test_status_accepts_canonical_child_captures_after_process_outcome(self) -> None:
        """Task 2 checked layout and Task 3 capture names form one resumable run."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request_path = root / "request.json"
            request_path.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
            run_dir = root / "run-local-calculation"
            initialize_run(request_path, run_dir)
            with open_locked_run(run_dir) as locked:
                first = locked.state.initialized_at + timedelta(seconds=1)
                locked.append(FrameTaskCreatedEvent(locked.request.run_id, first, build_frame_task(locked.request), 2))
                locked.append(FrameAttemptIntendedEvent(locked.request.run_id, first + timedelta(seconds=1), "frame", 1, 1, 3))
            attempt = run_dir / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"
            result = run_fake_frame_attempt(
                attempt / "packet.json",
                attempt=1,
                stdout_path=attempt / "stdout.bin",
                stderr_path=attempt / "stderr.log",
                run_dir=run_dir,
            )
            with open_locked_run(run_dir) as locked:
                locked.append(result.process_outcome(sequence=4, occurred_at=first + timedelta(seconds=2)))
            self.assertEqual(load_run_status(run_dir).last_event_sequence, 4)


if __name__ == "__main__":
    unittest.main()
