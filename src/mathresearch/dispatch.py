"""Service-layer orchestration for the deterministic first Frame dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts.frame import build_frame_task
from .contracts.run import (
    FrameAttemptIntendedEvent,
    FrameProcessOutcomeEvent,
    FrameSubmissionAcceptedEvent,
    FrameTaskCreatedEvent,
    RunEvent,
    RunState,
)
from .process_runner import (
    ProcessRunnerError,
    recover_fake_frame_submission,
    run_fake_frame_attempt,
)
from .run_store import STDERR_FILE_NAME, STDOUT_FILE_NAME, LockedRun, open_locked_run


_TASK_ID = "frame"
_REVISION = 1
_ATTEMPT = 1


@dataclass(frozen=True)
class DispatchResult:
    """The durable disposition of one requested fake Frame dispatch."""

    status: str
    state: RunState


def dispatch_fake_frame(
    run_dir: Path, *, timeout_seconds: int | None = None
) -> DispatchResult:
    """Publish and execute the sole Frame attempt without retrying ambiguous intent.

    The run lock remains held across the short local fake process.  Most
    importantly, the intent event is committed and its packet materialized
    before the child is started; a crash after that point leaves a visible,
    deliberately blocked attempt rather than a silently duplicated launch.
    """
    with open_locked_run(run_dir) as locked:
        existing = _frame_history(locked.events)
        if existing.accepted:
            return DispatchResult("already_accepted", locked.state)
        if existing.intent_without_outcome:
            return DispatchResult("blocked_interrupted", locked.state)
        if existing.has_outcome:
            if existing.outcome_exit_code == 0:
                submission = recover_fake_frame_submission(
                    _attempt_directory(locked) / "packet.json",
                    attempt=_ATTEMPT,
                    stdout_path=_attempt_directory(locked) / STDOUT_FILE_NAME,
                    stderr_path=_attempt_directory(locked) / STDERR_FILE_NAME,
                    run_dir=locked.run_dir,
                )
                if submission is not None:
                    locked.append(
                        FrameSubmissionAcceptedEvent(
                            locked.request.run_id,
                            _next_time(locked.events),
                            submission,
                            len(locked.events) + 1,
                        )
                    )
                    return DispatchResult("accepted", locked.state)
            return DispatchResult("already_rejected", locked.state)

        if not existing.task_created:
            locked.append(
                FrameTaskCreatedEvent(
                    locked.request.run_id,
                    _next_time(locked.events),
                    build_frame_task(locked.request),
                    len(locked.events) + 1,
                )
            )
        # Commit intent before discovering or launching any child process.
        locked.append(
            FrameAttemptIntendedEvent(
                locked.request.run_id,
                _next_time(locked.events),
                _TASK_ID,
                _REVISION,
                _ATTEMPT,
                len(locked.events) + 1,
            )
        )
        attempt_dir = _attempt_directory(locked)
        try:
            process = run_fake_frame_attempt(
                attempt_dir / "packet.json",
                attempt=_ATTEMPT,
                stdout_path=attempt_dir / STDOUT_FILE_NAME,
                stderr_path=attempt_dir / STDERR_FILE_NAME,
                run_dir=locked.run_dir,
                timeout_seconds=timeout_seconds,
            )
        except ProcessRunnerError:
            # There is no completed child outcome to invent.  The committed
            # intent is the durable interrupted/blocked recovery boundary.
            raise

        locked.append(
            process.process_outcome(
                sequence=len(locked.events) + 1,
                occurred_at=_next_time(locked.events),
            )
        )
        if process.exit_code != 0 or process.submission is None:
            return DispatchResult("rejected", locked.state)
        locked.append(
            FrameSubmissionAcceptedEvent(
                locked.request.run_id,
                _next_time(locked.events),
                process.submission,
                len(locked.events) + 1,
            )
        )
        return DispatchResult("accepted", locked.state)


@dataclass(frozen=True)
class _FrameHistory:
    task_created: bool
    intent_without_outcome: bool
    has_outcome: bool
    outcome_exit_code: int | None
    accepted: bool


def _frame_history(events: tuple[RunEvent, ...]) -> _FrameHistory:
    """Summarize the one legal Frame lifecycle after store replay validated it."""
    task_created = any(isinstance(event, FrameTaskCreatedEvent) for event in events)
    intended = any(isinstance(event, FrameAttemptIntendedEvent) for event in events)
    outcomes = [event for event in events if isinstance(event, FrameProcessOutcomeEvent)]
    outcome = bool(outcomes)
    accepted = any(isinstance(event, FrameSubmissionAcceptedEvent) for event in events)
    return _FrameHistory(
        task_created,
        intended and not outcome,
        outcome,
        outcomes[-1].exit_code if outcomes else None,
        accepted,
    )


def _attempt_directory(locked: LockedRun) -> Path:
    """Return the sole canonical attempt directory under the locked run root."""
    return locked.run_dir / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"


def _next_time(events: tuple[RunEvent, ...]) -> datetime:
    """Produce a UTC timestamp strictly after the replayed event history."""
    now = datetime.now(timezone.utc)
    previous = events[-1].occurred_at if events else now
    return max(now, previous + timedelta(microseconds=1))
