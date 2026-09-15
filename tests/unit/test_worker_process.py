from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from mathresearch.adapters.base import LaunchSpec, WorkerInput
from mathresearch.worker_process import MAX_CAPTURE_BYTES, _windows_job_api, execute_worker


class _StubAdapter:
    def __init__(self, script: Path, *, result_name: str | None = "result.json") -> None:
        self.script = script
        self.result_name = result_name

    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec:
        result = scratch / self.result_name if self.result_name else None
        return LaunchSpec((sys.executable, str(self.script)), task.prompt.encode(), scratch, result)

    def decode(self, stdout: bytes, result_bytes: bytes | None):
        raw = result_bytes if result_bytes is not None else stdout
        return json.loads(raw.decode("utf-8"))


class ExecuteWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.script = self.root / "child.py"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def task(self) -> WorkerInput:
        return WorkerInput("frame", "hello from stdin", {"type": "object"})

    def write_child(self, source: str) -> None:
        self.script.write_text(source, encoding="utf-8")

    def test_returns_payload_from_dedicated_result_file(self) -> None:
        self.write_child(
            "import pathlib, sys\n"
            "assert sys.stdin.buffer.read() == b'hello from stdin'\n"
            "pathlib.Path('result.json').write_text('{\\\"ok\\\":true}')\n"
            "print('diagnostic')\n"
        )
        output = execute_worker(_StubAdapter(self.script), self.task(), scratch=self.scratch, timeout_seconds=5)
        self.assertEqual(output.outcome, "succeeded")
        self.assertEqual(output.payload, {"ok": True})
        self.assertEqual(output.stdout, b"diagnostic\r\n" if sys.platform == "win32" else b"diagnostic\n")

    def test_invalid_result_protocol_is_failed_and_keeps_diagnostics(self) -> None:
        self.write_child("import pathlib; pathlib.Path('result.json').write_text('not-json'); print('not-json')\n")
        output = execute_worker(_StubAdapter(self.script), self.task(), scratch=self.scratch, timeout_seconds=5)
        self.assertEqual(output.outcome, "failed")
        self.assertIsNone(output.payload)
        self.assertEqual(output.stdout.strip(), b"not-json")
        self.assertIn("protocol", output.error or "")

    def test_nonzero_exit_does_not_decode_result(self) -> None:
        self.write_child("import pathlib, sys; pathlib.Path('result.json').write_text('{\\\"ok\\\":true}'); sys.exit(7)\n")
        output = execute_worker(_StubAdapter(self.script), self.task(), scratch=self.scratch, timeout_seconds=5)
        self.assertEqual(output.outcome, "failed")
        self.assertEqual(output.exit_code, 7)
        self.assertIsNone(output.payload)

    def test_timeout_is_reported(self) -> None:
        self.write_child("import time; print('started', flush=True); time.sleep(30)\n")
        output = execute_worker(_StubAdapter(self.script), self.task(), scratch=self.scratch, timeout_seconds=1)
        self.assertEqual(output.outcome, "timed_out")
        self.assertIsNone(output.payload)
        self.assertIn(b"started", output.stdout)

    def test_timeout_covers_a_large_prompt_when_child_never_reads_stdin(self) -> None:
        self.write_child("import time; time.sleep(30)\n")
        started = time.monotonic()
        output = execute_worker(
            _StubAdapter(self.script),
            WorkerInput("frame", "x" * (16 * 1024 * 1024), {"type": "object"}),
            scratch=self.scratch,
            timeout_seconds=1,
        )
        self.assertEqual(output.outcome, "timed_out")
        self.assertLess(time.monotonic() - started, 8)

    def test_timeout_kills_a_spawned_descendant(self) -> None:
        marker = self.root / "orphaned-child.txt"
        self.write_child(
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {repr('import pathlib,time; time.sleep(2); pathlib.Path(' + repr(str(marker)) + ').write_text(\"orphan\")')}])\n"
            "time.sleep(30)\n"
        )
        output = execute_worker(_StubAdapter(self.script), self.task(), scratch=self.scratch, timeout_seconds=1)
        self.assertEqual(output.outcome, "timed_out")
        time.sleep(3)
        self.assertFalse(marker.exists(), "timeout left a provider descendant alive")

    def test_diagnostic_captures_are_bounded_while_child_is_drained(self) -> None:
        self.write_child("import sys; sys.stdout.buffer.write(b'x' * (9 * 1024 * 1024))\n")
        output = execute_worker(_StubAdapter(self.script, result_name=None), self.task(), scratch=self.scratch, timeout_seconds=10)
        self.assertEqual(output.outcome, "failed")
        self.assertEqual(len(output.stdout), MAX_CAPTURE_BYTES)

    def test_rejects_result_file_outside_scratch(self) -> None:
        self.write_child("print('never runs')\n")
        adapter = _StubAdapter(self.script, result_name="../result.json")
        output = execute_worker(adapter, self.task(), scratch=self.scratch, timeout_seconds=5)
        self.assertEqual(output.outcome, "launch_failed")
        self.assertIn("scratch", output.error or "")

    def test_rejects_a_dangling_result_link_before_launch(self) -> None:
        link = self.scratch / "result.json"
        try:
            os.symlink(self.root / "outside.json", link)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {exc}")
        self.write_child("raise AssertionError('child must not launch')\n")
        output = execute_worker(_StubAdapter(self.script), self.task(), scratch=self.scratch, timeout_seconds=5)
        self.assertEqual(output.outcome, "launch_failed")
        self.assertIn("already exists", output.error or "")

    def test_windows_job_ffi_uses_pointer_safe_signatures(self) -> None:
        class Function:
            argtypes = None
            restype = None

        class Kernel32:
            CreateJobObjectW = Function()
            AssignProcessToJobObject = Function()
            TerminateJobObject = Function()
            CloseHandle = Function()

        kernel32 = Kernel32()
        with patch("mathresearch.worker_process.ctypes.WinDLL", return_value=kernel32):
            configured = _windows_job_api()
        self.assertIs(configured, kernel32)
        self.assertEqual(kernel32.CreateJobObjectW.argtypes, (ctypes.c_void_p, ctypes.c_wchar_p))
        self.assertIs(kernel32.CreateJobObjectW.restype, ctypes.c_void_p)
        self.assertEqual(kernel32.AssignProcessToJobObject.argtypes, (ctypes.c_void_p, ctypes.c_void_p))
