"""Behavioral tests for durable per-run operating-system locks."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

from mathresearch.errors import ExitCode, RunLockedError, RunStoreError
from mathresearch.locking import acquire_run_lock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
PROCESS_TIMEOUT_SECONDS = 5


def read_line_with_timeout(stream: object, timeout: float) -> str:
    """Read one child-process signal without allowing a stalled test to hang."""
    lines: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True)  # type: ignore[union-attr]
    reader.start()
    try:
        return lines.get(timeout=timeout)
    except queue.Empty as exc:
        raise AssertionError("child process did not signal lock acquisition") from exc


LOCK_HOLDER_SCRIPT = """
from pathlib import Path
import sys
from mathresearch.locking import acquire_run_lock

with acquire_run_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.readline()
"""


class RunLockTests(unittest.TestCase):
    def test_rejects_a_second_process_until_the_first_releases_the_lock(self) -> None:
        """Removing nonblocking OS locking would let two writers enter one run."""
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_directory:
            run_dir = Path(temporary_directory) / "run-one"
            run_dir.mkdir()
            environment = os.environ | {"PYTHONPATH": str(SOURCE_ROOT)}
            holder = subprocess.Popen(
                [sys.executable, "-c", LOCK_HOLDER_SCRIPT, str(run_dir)],
                cwd=PROJECT_ROOT,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(
                    read_line_with_timeout(holder.stdout, PROCESS_TIMEOUT_SECONDS),  # type: ignore[arg-type]
                    "locked\n",
                )
                with self.assertRaises(RunLockedError) as raised:
                    with acquire_run_lock(run_dir):
                        self.fail("a contending process acquired the run lock")
                self.assertEqual(raised.exception.code, "run_locked")
                self.assertEqual(raised.exception.exit_code, ExitCode.RUN_LOCKED)

                stdout, stderr = holder.communicate("release\n", timeout=PROCESS_TIMEOUT_SECONDS)
                self.assertEqual(holder.returncode, 0, stderr)
                self.assertEqual(stdout, "")
                with acquire_run_lock(run_dir):
                    pass
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.communicate(timeout=PROCESS_TIMEOUT_SECONDS)

    def test_releases_before_a_sequential_second_acquisition(self) -> None:
        """Leaving a descriptor locked after a normal context exit blocks later work."""
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_directory:
            run_dir = Path(temporary_directory) / "run-one"
            run_dir.mkdir()

            with acquire_run_lock(run_dir):
                pass
            with acquire_run_lock(run_dir):
                pass

    def test_releases_after_an_exception_in_the_protected_work(self) -> None:
        """A writer exception must not strand the run lock for recovery work."""
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_directory:
            run_dir = Path(temporary_directory) / "run-one"
            run_dir.mkdir()

            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with acquire_run_lock(run_dir):
                    raise RuntimeError("interrupted")
            with acquire_run_lock(run_dir):
                pass

    def test_keeps_the_lock_file_after_release(self) -> None:
        """Deleting the sentinel would make file presence look like lock ownership."""
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_directory:
            run_dir = Path(temporary_directory) / "run-one"
            run_dir.mkdir()
            lock_path = run_dir / ".run.lock"

            with acquire_run_lock(run_dir):
                self.assertTrue(lock_path.is_file())
            self.assertTrue(lock_path.is_file())

    def test_allows_independent_run_directories_to_lock_concurrently(self) -> None:
        """Using a shared global lock would serialize unrelated run directories."""
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_directory:
            root = Path(temporary_directory)
            first_run = root / "run-one"
            second_run = root / "run-two"
            first_run.mkdir()
            second_run.mkdir()

            with acquire_run_lock(first_run):
                with acquire_run_lock(second_run):
                    pass

    def test_rejects_unsafe_existing_lock_targets_before_opening_them(self) -> None:
        """Following a link or opening a directory lock target could mutate outside the run."""
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_directory:
            root = Path(temporary_directory)
            for name in ("symlink", "directory"):
                with self.subTest(name=name):
                    run_dir = root / name
                    run_dir.mkdir()
                    lock_path = run_dir / ".run.lock"
                    outside_target = root / f"outside-{name}"
                    if name == "symlink":
                        outside_target.write_bytes(b"")
                        lock_path.symlink_to(outside_target)
                    else:
                        lock_path.mkdir()

                    with self.assertRaises(RunStoreError):
                        with acquire_run_lock(run_dir):
                            self.fail("unsafe lock target was acquired")
                    if name == "symlink":
                        self.assertEqual(outside_target.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
