"""Safe process boundary for a real provider worker."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import stat
import subprocess
import threading
from typing import Any, Mapping

from .adapters.base import Adapter, LaunchSpec, WorkerInput, WorkerOutput
from .locking import _is_link_or_reparse_point


MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 1 * 1024 * 1024


def execute_worker(adapter: Adapter, task: WorkerInput, *, scratch: Path, timeout_seconds: int) -> WorkerOutput:
    """Run one provider with argv execution, bounded diagnostics, and hard timeout.

    This function owns no run-state authority.  It only returns raw diagnostics
    and a parsed provider payload for the coordinator to validate and persist.
    """
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        return _launch_failure("timeout_seconds must be a positive integer")
    root = Path(os.path.abspath(scratch))
    try:
        _require_safe_directory_chain(root)
        preflight = getattr(adapter, "preflight", None)
        if preflight is not None:
            preflight()
        spec = adapter.prepare(task, root)
        _validate_spec(spec, root)
    except (OSError, ValueError, TypeError) as exc:
        return _launch_failure(str(exc))
    try:
        process = _start(spec)
    except OSError as exc:
        return _launch_failure(f"could not launch provider: {exc}")
    job = _WindowsJob(process) if os.name == "nt" else None
    stdout_reader = _BoundedReader(process.stdout)
    stderr_reader = _BoundedReader(process.stderr)
    stdout_reader.start(); stderr_reader.start()
    stdin_writer = _StdinWriter(process.stdin, spec.stdin)
    stdin_writer.start()
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except KeyboardInterrupt:
        teardown_ok = _terminate_tree(process, job)
        _close_stdin(process)
        stdin_writer.join(timeout=1)
        stdout_reader.join(timeout=2); stderr_reader.join(timeout=2)
        if teardown_ok:
            _close_streams(process)
        else:
            raise RuntimeError("provider interruption cleanup could not be confirmed")
        raise
    except subprocess.TimeoutExpired:
        teardown_ok = _terminate_tree(process, job)
        _close_stdin(process)
        stdin_writer.join(timeout=1)
        stdout_reader.join(); stderr_reader.join()
        _close_streams(process)
        if not teardown_ok:
            return WorkerOutput("cancelled", None, stdout_reader.data, stderr_reader.data, None, "provider timeout cleanup could not be confirmed")
        return WorkerOutput("timed_out", None, stdout_reader.data, stderr_reader.data, None, "provider timed out")
    except OSError as exc:
        _terminate_tree(process, job)
        stdout_reader.join(); stderr_reader.join()
        _close_streams(process)
        return WorkerOutput("launch_failed", None, stdout_reader.data, stderr_reader.data, None, f"provider I/O failed: {exc}")
    finally:
        if job is not None:
            job.close()
    stdout_reader.join(); stderr_reader.join()
    stdin_writer.join(timeout=1)
    _close_streams(process)
    if stdin_writer.error is not None and exit_code == 0:
        return WorkerOutput("failed", exit_code, stdout_reader.data, stderr_reader.data, None, f"provider I/O failed: {stdin_writer.error}")
    if exit_code != 0:
        return WorkerOutput("failed", exit_code, stdout_reader.data, stderr_reader.data, None, "provider exited unsuccessfully")
    try:
        result_bytes = _read_result(spec.result_file, root)
        payload = adapter.decode(stdout_reader.data, result_bytes)
        if not isinstance(payload, Mapping):
            raise ValueError("provider decoded a non-object result")
    except (OSError, ValueError, TypeError) as exc:
        return WorkerOutput("failed", exit_code, stdout_reader.data, stderr_reader.data, None, f"adapter protocol error: {exc}")
    return WorkerOutput("succeeded", exit_code, stdout_reader.data, stderr_reader.data, dict(payload), None)


def _launch_failure(message: str) -> WorkerOutput:
    return WorkerOutput("launch_failed", None, b"", b"", None, message)


def _validate_spec(spec: LaunchSpec, root: Path) -> None:
    if not spec.argv or any(not isinstance(part, str) or not part for part in spec.argv):
        raise ValueError("launch argv must be a non-empty string tuple")
    if Path(os.path.abspath(spec.cwd)) != root:
        raise ValueError("provider cwd must be the supplied scratch directory")
    if spec.result_file is not None:
        target = Path(os.path.abspath(spec.result_file))
        if target.parent != root:
            raise ValueError("provider result file must be directly inside scratch")
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("provider result file already exists in scratch")


def _start(spec: LaunchSpec) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "cwd": str(spec.cwd), "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(spec.argv, **kwargs)


def _read_result(result_file: Path | None, root: Path) -> bytes | None:
    if result_file is None:
        return None
    path = Path(os.path.abspath(result_file))
    if path.parent != root:
        raise ValueError("provider result file escapes scratch")
    expected = path.lstat()
    _require_safe_regular_file(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("provider result file is unsafe")
        observed = path.lstat()
        if (
            _is_link_or_reparse_point(observed)
            or observed.st_dev != expected.st_dev
            or observed.st_ino != expected.st_ino
            or metadata.st_dev != expected.st_dev
            or metadata.st_ino != expected.st_ino
        ):
            raise ValueError("provider result file changed while being opened")
        if metadata.st_size > MAX_RESULT_BYTES:
            raise ValueError("provider result exceeds 1 MiB")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise ValueError("provider result changed while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("provider result changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _require_safe_directory_chain(path: Path) -> None:
    current = path
    while True:
        metadata = current.lstat()
        if _is_link_or_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("scratch directory is unsafe")
        if current == current.parent:
            return
        current = current.parent


def _require_safe_regular_file(path: Path) -> None:
    metadata = path.lstat()
    if _is_link_or_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("provider result file is unsafe")


class _BoundedReader(threading.Thread):
    def __init__(self, stream: Any) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.data = b""

    def run(self) -> None:
        chunks: list[bytes] = []
        retained = 0
        while True:
            chunk = self.stream.read(64 * 1024)
            if not chunk:
                break
            if retained < MAX_CAPTURE_BYTES:
                kept = chunk[: MAX_CAPTURE_BYTES - retained]
                chunks.append(kept)
                retained += len(kept)
        self.data = b"".join(chunks)


class _StdinWriter(threading.Thread):
    """Deliver input off the timeout-owning thread while captures are drained."""
    def __init__(self, stream: Any, data: bytes) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.data = data
        self.error: OSError | None = None

    def run(self) -> None:
        try:
            if self.stream is not None:
                self.stream.write(self.data)
                self.stream.close()
        except OSError as exc:
            self.error = exc


def _close_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _close_stdin(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass


def _terminate_tree(process: subprocess.Popen[bytes], job: "_WindowsJob | None") -> bool:
    try:
        if os.name == "nt":
            if job is not None and job.confirmed:
                job.terminate()
            else:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=10)
        else:
            os.killpg(process.pid, 15)
        process.wait(timeout=10)
        return not (os.name == "nt" and (job is None or not job.confirmed))
    except (OSError, subprocess.TimeoutExpired):
        return False


class _WindowsJob:
    """Best-effort Windows Job Object, killed on explicit timeout and close."""
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.handle: int | None = None
        self.failure_reason: str | None = None
        if os.name != "nt":
            return
        self.kernel32 = _windows_job_api()
        handle = self.kernel32.CreateJobObjectW(None, None)
        if not handle:
            self.failure_reason = f"CreateJobObjectW failed: {ctypes.get_last_error()}"
            return
        self.handle = handle
        if not self.kernel32.AssignProcessToJobObject(handle, process._handle):
            self.failure_reason = f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
            self.close()

    @property
    def confirmed(self) -> bool:
        return self.handle is not None and self.failure_reason is None

    def terminate(self) -> None:
        if self.handle is not None:
            self.kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle is not None:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def _windows_job_api() -> Any:
    """Load Job Object APIs with pointer-safe ctypes declarations."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    kernel32.TerminateJobObject.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32
