"""Process boundary for executing a Frame worker and preserving child capture bytes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any

from .contracts.frame import FramePacket, FrameSubmission
from .contracts.run import FrameProcessOutcomeEvent
from .contracts.validation import ValidationError
from .locking import _is_link_or_reparse_point
from .run_store import PACKET_FILE_NAME, STDERR_FILE_NAME, STDOUT_FILE_NAME


class ProcessRunnerError(RuntimeError):
    """Raised when a worker process or its local capture boundary is unsafe."""


@dataclass(frozen=True)
class ProcessResult:
    """Raw child capture plus the one validated submission, when execution succeeded."""

    run_id: str
    task_id: str
    revision: int
    attempt: int
    exit_code: int
    stdout: bytes
    stderr: bytes
    submission: FrameSubmission | None
    submission_error: str | None = None

    def process_outcome(self, *, sequence: int, occurred_at: datetime) -> FrameProcessOutcomeEvent:
        """Build the exact event Task 4 can append after process capture is durable."""
        event = FrameProcessOutcomeEvent(
            self.run_id,
            occurred_at,
            self.task_id,
            self.revision,
            self.attempt,
            self.exit_code,
            sequence,
        )
        return FrameProcessOutcomeEvent.from_json(event.to_json())


def run_fake_frame_attempt(
    packet_path: Path,
    *,
    attempt: int,
    stdout_path: Path,
    stderr_path: Path,
    run_dir: Path,
    timeout_seconds: int | None = None,
) -> ProcessResult:
    """Execute the deterministic child worker and persist its raw captures safely."""
    packet_path, stdout_path, stderr_path = _require_attempt_layout(
        packet_path,
        attempt,
        stdout_path,
        stderr_path,
        run_dir,
    )
    packet = _load_safe_packet(packet_path)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "mathresearch.fake_worker", "--packet", str(packet_path), "--attempt", str(attempt)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        _atomic_write_capture(stdout_path, stdout)
        _atomic_write_capture(stderr_path, stderr)
        raise ProcessRunnerError("fake Frame worker timed out") from exc
    except OSError as exc:
        raise ProcessRunnerError("could not launch fake Frame worker") from exc
    _atomic_write_capture(stdout_path, completed.stdout)
    _atomic_write_capture(stderr_path, completed.stderr)
    submission, submission_error = _parse_successful_submission(completed.returncode, completed.stdout, packet, attempt)
    return ProcessResult(
        run_id=packet.task.run_id,
        task_id=packet.task.task_id,
        revision=packet.task.revision,
        attempt=attempt,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        submission=submission,
        submission_error=submission_error,
    )


def recover_fake_frame_submission(
    packet_path: Path,
    *,
    attempt: int,
    stdout_path: Path,
    stderr_path: Path,
    run_dir: Path,
) -> FrameSubmission | None:
    """Revalidate the captured result of a durably completed successful attempt.

    This performs no child launch and does not rewrite any capture.  It is used
    only when the outcome event is already committed but acceptance was
    interrupted before it could be published.
    """
    packet_path, stdout_path, _ = _require_attempt_layout(
        packet_path,
        attempt,
        stdout_path,
        stderr_path,
        run_dir,
    )
    packet = _load_safe_packet(packet_path)
    _require_safe_input_file(stdout_path)
    try:
        stdout = stdout_path.read_bytes()
    except OSError as exc:
        raise ProcessRunnerError(f"could not read process capture: {stdout_path}") from exc
    submission, _ = _parse_successful_submission(0, stdout, packet, attempt)
    return submission


def _load_safe_packet(path: Path) -> FramePacket:
    _require_safe_input_file(path)
    try:
        with path.open("r", encoding="utf-8") as packet_file:
            payload = json.load(packet_file, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
        return FramePacket.from_json(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise ProcessRunnerError(f"invalid Frame packet: {path}") from exc


def _parse_successful_submission(
    exit_code: int,
    stdout: bytes,
    packet: FramePacket,
    attempt: int,
) -> tuple[FrameSubmission | None, str | None]:
    if exit_code != 0:
        return None, None
    try:
        text = stdout.decode("utf-8")
        decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
        payload, index = decoder.raw_decode(text)
        if text[index:].strip():
            raise ValueError("worker stdout contains more than one JSON value")
        submission = FrameSubmission.from_json(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        return None, "successful worker emitted an invalid Frame submission"
    if (
        submission.run_id != packet.task.run_id
        or submission.task_id != packet.task.task_id
        or submission.revision != packet.task.revision
        or submission.attempt != attempt
    ):
        return None, "worker submission does not match the materialized Frame packet"
    return submission, None


def _require_attempt_layout(
    packet_path: Path,
    attempt: int,
    stdout_path: Path,
    stderr_path: Path,
    run_dir: Path,
) -> tuple[Path, Path, Path]:
    """Require fixed artifacts under the supplied non-linked materialized run tree."""
    packet = _absolute_path(packet_path)
    stdout = _absolute_path(stdout_path)
    stderr = _absolute_path(stderr_path)
    run_root = _absolute_path(run_dir)
    attempt_dir = packet.parent
    if packet.name != PACKET_FILE_NAME:
        raise ProcessRunnerError("Frame packet must be named packet.json")
    expected_attempt_dir = (
        run_root
        / "tasks"
        / "task-frame"
        / "attempts"
        / f"attempt-frame-{attempt:03d}"
    )
    if attempt_dir != expected_attempt_dir:
        raise ProcessRunnerError("Frame packet must be in the supplied run's canonical attempt directory")
    if stdout != attempt_dir / STDOUT_FILE_NAME or stderr != attempt_dir / STDERR_FILE_NAME:
        raise ProcessRunnerError("Frame captures must be fixed distinct attempt artifacts")
    if len({packet, stdout, stderr}) != 3:
        raise ProcessRunnerError("Frame packet and captures must be distinct")
    _require_safe_directory_chain(attempt_dir)
    _require_safe_capture_target(stdout)
    _require_safe_capture_target(stderr)
    return packet, stdout, stderr


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _require_safe_directory_chain(directory: Path) -> None:
    """Refuse a linked/reparse ancestor before using it as the capture boundary."""
    current = directory
    while True:
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ProcessRunnerError(f"could not inspect capture directory: {current}") from exc
        if _is_link_or_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ProcessRunnerError(f"unsafe capture directory: {current}")
        if current == current.parent:
            return
        current = current.parent


def _require_safe_input_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProcessRunnerError(f"could not inspect Frame packet: {path}") from exc
    if _is_link_or_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ProcessRunnerError(f"unsafe Frame packet: {path}")


def _require_safe_capture_target(path: Path) -> None:
    try:
        parent_metadata = path.parent.lstat()
    except OSError as exc:
        raise ProcessRunnerError(f"could not inspect capture directory: {path.parent}") from exc
    if _is_link_or_reparse_point(parent_metadata) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ProcessRunnerError(f"unsafe capture directory: {path.parent}")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProcessRunnerError(f"could not inspect capture target: {path}") from exc
    if _is_link_or_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ProcessRunnerError(f"unsafe capture target: {path}")


def _atomic_write_capture(target: Path, contents: bytes) -> None:
    _require_safe_capture_target(target)
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as temporary_file:
            descriptor = None
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, target)
    except OSError as exc:
        raise ProcessRunnerError(f"could not write process capture: {target}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate key: {key}")
        payload[key] = value
    return payload


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")
