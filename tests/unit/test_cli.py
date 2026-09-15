"""Behavioral tests for the public command-line entry point."""

from __future__ import annotations

import os
from pathlib import Path
import json
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from io import StringIO
from typing import Iterator
import uuid

from mathresearch import cli
from mathresearch.dispatch import DispatchResult
from mathresearch.errors import ExitCode
from mathresearch.process_runner import ProcessRunnerError
from mathresearch.run_store import load_run_status, open_locked_run
from tests.helpers import valid_run_request_payload

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"


@contextmanager
def _workspace_temporary_directory() -> Iterator[Path]:
    """Create a test directory with inherited workspace permissions on Windows."""
    directory = PROJECT_ROOT / f".cli-test-{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class CliTests(unittest.TestCase):
    def _run_cli(self, *arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Invoke the public module entry point in a fresh interpreter."""
        child_environment = os.environ | {"PYTHONPATH": str(SOURCE_ROOT)}
        if environment is not None:
            child_environment.update(environment)
        return subprocess.run(
            [sys.executable, "-m", "mathresearch", *arguments],
            cwd=PROJECT_ROOT,
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_command_returns_a_structured_invalid_invocation_error(self) -> None:
        """A host invoking the coordinator without an action must receive an error."""
        environment = os.environ | {"PYTHONPATH": str(SOURCE_ROOT)}

        result = subprocess.run(
            [sys.executable, "-m", "mathresearch"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 20)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "code": "invalid_invocation",
                "message": "invalid command-line arguments; run 'mathresearch --help' for usage",
            },
        )

    def test_help_is_available_without_an_agent_cli(self) -> None:
        """Removing provider CLIs must not prevent users discovering commands."""
        environment = os.environ | {"PYTHONPATH": str(SOURCE_ROOT)}

        result = subprocess.run(
            [sys.executable, "-m", "mathresearch", "--help"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mathresearch", result.stdout)
        self.assertIn("doctor", result.stdout)

    def test_unknown_command_returns_a_structured_invalid_invocation_error(self) -> None:
        """A typo must remain machine-readable for hosts that call this CLI."""
        environment = os.environ | {"PYTHONPATH": str(SOURCE_ROOT)}

        result = subprocess.run(
            [sys.executable, "-m", "mathresearch", "does-not-exist"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 20)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "code": "invalid_invocation",
                "message": "invalid command-line arguments; run 'mathresearch --help' for usage",
            },
        )

    def test_doctor_json_reports_missing_built_in_adapters(self) -> None:
        """Hosts must see unavailable adapters instead of an unusable CLI failure."""
        environment = os.environ | {"PATH": "", "PYTHONPATH": str(SOURCE_ROOT)}

        result = subprocess.run(
            [sys.executable, "-m", "mathresearch", "doctor", "--json"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "adapters": [
                    {"available": False, "id": "claude"},
                    {"available": False, "id": "codex"},
                ]
            },
        )

    def test_init_and_status_json_survive_a_fresh_process_restart(self) -> None:
        """The public commands must initialize and replay a run without agent execution."""
        with _workspace_temporary_directory() as root:
            request_path = root / "request.json"
            request_path.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
            run_dir = root / "run"

            initialized = self._run_cli(
                "init",
                "--request",
                str(request_path),
                "--run-dir",
                str(run_dir),
                "--json",
                environment={"PATH": ""},
            )

            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertEqual(initialized.stderr, "")
            initialized_payload = json.loads(initialized.stdout)
            self.assertEqual(initialized_payload["run_id"], "run-local-calculation")
            self.assertEqual(initialized_payload["status"], "initialized")
            self.assertEqual(initialized_payload["last_event_sequence"], 1)

            (run_dir / "state.json").unlink()
            status = self._run_cli(
                "status",
                "--run-dir",
                str(run_dir),
                "--json",
                environment={"PATH": ""},
            )

            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout), initialized_payload)
            self.assertEqual(
                json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
                initialized_payload,
            )

    def test_init_and_status_have_readable_outputs(self) -> None:
        """Direct users must receive a concise summary when JSON is not requested."""
        with _workspace_temporary_directory() as root:
            request_path = root / "request.json"
            request_path.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
            run_dir = root / "run"

            initialized = self._run_cli(
                "init", "--request", str(request_path), "--run-dir", str(run_dir)
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertIn("run-local-calculation", initialized.stdout)
            self.assertIn("initialized", initialized.stdout)

            status = self._run_cli("status", "--run-dir", str(run_dir))
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("run-local-calculation", status.stdout)
            self.assertIn("initialized", status.stdout)

    def test_dispatch_fake_completes_frame_and_a_repeat_is_idempotent(self) -> None:
        """The public dispatch command must expose the durable fake lifecycle."""
        with _workspace_temporary_directory() as root:
            request_path = root / "request.json"
            request_path.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
            run_dir = root / "run"
            initialized = self._run_cli("init", "--request", str(request_path), "--run-dir", str(run_dir))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            dispatched = self._run_cli(
                "dispatch", "--run-dir", str(run_dir), "--adapter", "fake", "--timeout-seconds", "5", "--json"
            )
            self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
            self.assertEqual(json.loads(dispatched.stdout)["dispatch_status"], "accepted")
            self.assertEqual(json.loads(dispatched.stdout)["state"]["accepted_submission_count"], 1)
            attempt = run_dir / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"
            self.assertTrue((attempt / "packet.json").is_file())
            self.assertTrue((attempt / "stdout.bin").is_file())
            self.assertTrue((attempt / "stderr.log").is_file())

            repeated = self._run_cli("dispatch", "--run-dir", str(run_dir), "--adapter", "fake", "--json")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(json.loads(repeated.stdout)["dispatch_status"], "already_accepted")
            self.assertEqual(load_run_status(run_dir).accepted_submission_count, 1)

    def test_dispatch_rejected_and_interrupted_results_are_user_visible(self) -> None:
        """A child rejection and crash-window block must not be reported as successful acceptance."""
        state = cli.RunState("run-local-calculation", datetime(2026, 1, 1, tzinfo=timezone.utc))
        with patch.object(cli, "dispatch_fake_frame", return_value=DispatchResult("rejected", state)):
            stderr = StringIO()
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["dispatch", "--run-dir", "run", "--adapter", "fake", "--json"])
        self.assertEqual(result, int(ExitCode.BLOCKED))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue()), {"code": "dispatch_rejected", "message": "fake Frame dispatch was rejected"})

    def test_dispatch_forwards_validated_timeout_to_the_fake_service(self) -> None:
        """Dropping the CLI timeout would leave callers unable to bound the child process."""
        state = cli.RunState("run-local-calculation", datetime(2026, 1, 1, tzinfo=timezone.utc))
        with patch.object(cli, "dispatch_fake_frame", return_value=DispatchResult("accepted", state)) as dispatched:
            with redirect_stdout(StringIO()):
                result = cli.main(["dispatch", "--run-dir", "run", "--adapter", "fake", "--timeout-seconds", "7", "--json"])
        self.assertEqual(result, 0)
        dispatched.assert_called_once_with(Path("run"), timeout_seconds=7)

    def test_dispatch_runner_failure_is_structured_instead_of_a_traceback(self) -> None:
        """A launch or timeout failure leaves durable intent but must be readable to a CLI caller."""
        stderr = StringIO()
        with patch.object(cli, "dispatch_fake_frame", side_effect=ProcessRunnerError("worker timed out")):
            with redirect_stderr(stderr):
                result = cli.main(["dispatch", "--run-dir", "run", "--adapter", "fake", "--json"])
        self.assertEqual(result, int(ExitCode.BLOCKED))
        self.assertEqual(json.loads(stderr.getvalue()), {"code": "dispatch_failed", "message": "worker timed out"})

    def test_dispatch_rejects_unsupported_adapter_missing_run_and_invalid_timeout(self) -> None:
        """Only the local fake adapter and a positive integer timeout are currently accepted."""
        with _workspace_temporary_directory() as root:
            missing = root / "missing"
            unsupported = self._run_cli("dispatch", "--run-dir", str(missing), "--adapter", "codex", "--json")
            self.assertEqual(unsupported.returncode, int(ExitCode.INVALID_INVOCATION))
            self.assertEqual(json.loads(unsupported.stderr)["code"], "unsupported_adapter")

            absent = self._run_cli("dispatch", "--run-dir", str(missing), "--adapter", "fake", "--json")
            self.assertEqual(absent.returncode, int(ExitCode.RUN_STORE_ERROR))
            self.assertEqual(json.loads(absent.stderr)["code"], "run_not_found")

            invalid_timeout = self._run_cli("dispatch", "--run-dir", str(missing), "--adapter", "fake", "--timeout-seconds", "0", "--json")
            self.assertEqual(invalid_timeout.returncode, int(ExitCode.INVALID_INVOCATION))
            self.assertEqual(json.loads(invalid_timeout.stderr)["code"], "invalid_invocation")

    def test_status_run_store_error_is_structured_in_json_mode(self) -> None:
        """Typed storage failures must be machine-readable and use their declared exit code."""
        with _workspace_temporary_directory() as root:
            run_dir = root / "missing"
            result = self._run_cli("status", "--run-dir", str(run_dir), "--json")

            self.assertEqual(result.returncode, int(ExitCode.RUN_STORE_ERROR))
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                json.loads(result.stderr),
                {"code": "run_not_found", "message": f"run not found: {run_dir}"},
            )

    def test_status_run_store_error_is_readable_without_json_mode(self) -> None:
        """Human-facing storage failures should avoid a Python traceback."""
        with _workspace_temporary_directory() as root:
            run_dir = root / "missing"
            result = self._run_cli("status", "--run-dir", str(run_dir))

            self.assertEqual(result.returncode, int(ExitCode.RUN_STORE_ERROR))
            self.assertEqual(result.stdout, "")
            self.assertIn("run_not_found", result.stderr)
            self.assertIn(f"run not found: {run_dir}", result.stderr)

    def test_keyboard_interrupt_returns_cancellation_exit_code(self) -> None:
        """An interrupted storage operation must be a controlled cancellation."""
        stderr = StringIO()
        stdout = StringIO()
        with patch.object(cli, "load_run_status", side_effect=KeyboardInterrupt):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["status", "--run-dir", "ignored", "--json"])

        self.assertEqual(result, int(ExitCode.CANCELLED))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"code": "cancelled", "message": "operation cancelled"},
        )


if __name__ == "__main__":
    unittest.main()
