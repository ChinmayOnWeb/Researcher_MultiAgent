"""Durable initialization event and state record contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from collections.abc import Iterable
from typing import Any, TypeAlias

from .frame import FrameSubmission, FrameTask, build_frame_task
from .records import SCHEMA_VERSION, RunRequest
from .validation import (
    ValidationError,
    require_exact_fields,
    require_identifier,
    require_nonnegative_integer,
    require_object,
    require_positive_integer,
    require_string,
)


_UTC_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)


def _parse_utc_timestamp(value: Any, field: str) -> datetime:
    """Parse the one supported persisted timestamp format."""
    if not isinstance(value, str) or not _UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise ValidationError(field, "must be a UTC timestamp with microseconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValidationError(field, "must be a possible UTC timestamp") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _format_utc_timestamp(value: datetime, field: str) -> str:
    """Render an aware zero-offset datetime in the persisted wire format."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValidationError(field, "must be an aware UTC datetime")
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond:06d}Z"
    )


def _validated_request(value: Any) -> RunRequest:
    """Revalidate a request before a writer trusts a constructed dataclass."""
    if not isinstance(value, RunRequest):
        raise ValidationError("request", "must be a RunRequest")
    return RunRequest.from_json(value.to_json())


@dataclass(frozen=True)
class RunInitializedEvent:
    """The authoritative first event committed for a durable research run."""

    run_id: str
    occurred_at: datetime
    request: RunRequest
    sequence: int = 1

    @classmethod
    def from_json(cls, payload: Any) -> "RunInitializedEvent":
        """Validate and parse a complete initialization event JSON object."""
        data = require_object(payload, "run_event")
        require_exact_fields(
            data,
            "run_event",
            {
                "schema_version",
                "record_type",
                "sequence",
                "event_type",
                "run_id",
                "occurred_at",
                "request",
            },
        )
        schema_version = require_positive_integer(data["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValidationError("schema_version", f"must equal {SCHEMA_VERSION}")
        if data["record_type"] != "run_event":
            raise ValidationError("record_type", "must equal 'run_event'")
        sequence = require_positive_integer(data["sequence"], "sequence")
        if sequence != 1:
            raise ValidationError("sequence", "must equal 1")
        if data["event_type"] != "run_initialized":
            raise ValidationError("event_type", "must equal 'run_initialized'")
        run_id = require_identifier(data["run_id"], "run_id")
        request = RunRequest.from_json(data["request"])
        if request.run_id != run_id:
            raise ValidationError("run_id", "must match request.run_id")
        return cls(
            run_id=run_id,
            occurred_at=_parse_utc_timestamp(data["occurred_at"], "occurred_at"),
            request=request,
            sequence=sequence,
        )

    def to_json(self) -> dict[str, Any]:
        """Return the exact version-one initialization event JSON representation."""
        sequence = require_positive_integer(self.sequence, "sequence")
        if sequence != 1:
            raise ValidationError("sequence", "must equal 1")
        run_id = require_identifier(self.run_id, "run_id")
        request = _validated_request(self.request)
        if request.run_id != run_id:
            raise ValidationError("run_id", "must match request.run_id")
        return {
            "schema_version": SCHEMA_VERSION,
            "record_type": "run_event",
            "sequence": sequence,
            "event_type": "run_initialized",
            "run_id": run_id,
            "occurred_at": _format_utc_timestamp(self.occurred_at, "occurred_at"),
            "request": request.to_json(),
        }


def _event_data(payload: Any, event_type: str, expected: set[str]) -> Any:
    """Validate common version-one event fields before parsing a specific body."""
    data = require_object(payload, "run_event")
    require_exact_fields(data, "run_event", expected)
    if require_positive_integer(data["schema_version"], "schema_version") != SCHEMA_VERSION:
        raise ValidationError("schema_version", f"must equal {SCHEMA_VERSION}")
    if data["record_type"] != "run_event":
        raise ValidationError("record_type", "must equal 'run_event'")
    if data["event_type"] != event_type:
        raise ValidationError("event_type", f"must equal '{event_type}'")
    return data


@dataclass(frozen=True)
class FrameTaskCreatedEvent:
    """Records creation of the one coordinator-issued Frame task."""

    run_id: str
    occurred_at: datetime
    task: FrameTask
    sequence: int

    @classmethod
    def from_json(cls, payload: Any) -> "FrameTaskCreatedEvent":
        data = _event_data(payload, "frame_task_created", {
            "schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "task",
        })
        task = FrameTask.from_json(data["task"])
        run_id = require_identifier(data["run_id"], "run_id")
        if task.run_id != run_id:
            raise ValidationError("task.run_id", "must match run_id")
        return cls(run_id, _parse_utc_timestamp(data["occurred_at"], "occurred_at"), task,
                   require_positive_integer(data["sequence"], "sequence"))

    def to_json(self) -> dict[str, Any]:
        task = FrameTask.from_json(self.task.to_json()) if isinstance(self.task, FrameTask) else None
        if task is None:
            raise ValidationError("task", "must be a FrameTask")
        run_id = require_identifier(self.run_id, "run_id")
        if task.run_id != run_id:
            raise ValidationError("task.run_id", "must match run_id")
        return {
            "schema_version": SCHEMA_VERSION, "record_type": "run_event",
            "sequence": require_positive_integer(self.sequence, "sequence"),
            "event_type": "frame_task_created", "run_id": run_id,
            "occurred_at": _format_utc_timestamp(self.occurred_at, "occurred_at"), "task": task.to_json(),
        }


@dataclass(frozen=True)
class FrameAttemptIntendedEvent:
    """Records the coordinator's intent to execute one Frame attempt."""

    run_id: str
    occurred_at: datetime
    task_id: str
    revision: int
    attempt: int
    sequence: int

    @classmethod
    def from_json(cls, payload: Any) -> "FrameAttemptIntendedEvent":
        data = _event_data(payload, "frame_attempt_intended", {
            "schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "task_id",
            "revision", "attempt",
        })
        return cls(
            require_identifier(data["run_id"], "run_id"),
            _parse_utc_timestamp(data["occurred_at"], "occurred_at"),
            require_identifier(data["task_id"], "task_id"),
            require_positive_integer(data["revision"], "revision"),
            require_positive_integer(data["attempt"], "attempt"),
            require_positive_integer(data["sequence"], "sequence"),
        )

    def to_json(self) -> dict[str, Any]:
        return _frame_reference_event_json(self, "frame_attempt_intended")


@dataclass(frozen=True)
class FrameProcessOutcomeEvent:
    """Records a completed Frame process attempt and its integer exit code."""

    run_id: str
    occurred_at: datetime
    task_id: str
    revision: int
    attempt: int
    exit_code: int
    sequence: int

    @classmethod
    def from_json(cls, payload: Any) -> "FrameProcessOutcomeEvent":
        data = _event_data(payload, "frame_process_outcome", {
            "schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "task_id",
            "revision", "attempt", "exit_code",
        })
        return cls(
            require_identifier(data["run_id"], "run_id"),
            _parse_utc_timestamp(data["occurred_at"], "occurred_at"),
            require_identifier(data["task_id"], "task_id"),
            require_positive_integer(data["revision"], "revision"),
            require_positive_integer(data["attempt"], "attempt"),
            _require_exit_code(data["exit_code"]),
            require_positive_integer(data["sequence"], "sequence"),
        )

    def to_json(self) -> dict[str, Any]:
        payload = _frame_reference_event_json(self, "frame_process_outcome")
        payload["exit_code"] = _require_exit_code(self.exit_code)
        return payload


@dataclass(frozen=True)
class FrameSubmissionAcceptedEvent:
    """Records coordinator acceptance of a valid successful Frame submission."""

    run_id: str
    occurred_at: datetime
    submission: FrameSubmission
    sequence: int

    @classmethod
    def from_json(cls, payload: Any) -> "FrameSubmissionAcceptedEvent":
        data = _event_data(payload, "frame_submission_accepted", {
            "schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "submission",
        })
        submission = FrameSubmission.from_json(data["submission"])
        run_id = require_identifier(data["run_id"], "run_id")
        if submission.run_id != run_id:
            raise ValidationError("submission.run_id", "must match run_id")
        return cls(run_id, _parse_utc_timestamp(data["occurred_at"], "occurred_at"), submission,
                   require_positive_integer(data["sequence"], "sequence"))

    def to_json(self) -> dict[str, Any]:
        if not isinstance(self.submission, FrameSubmission):
            raise ValidationError("submission", "must be a FrameSubmission")
        submission = FrameSubmission.from_json(self.submission.to_json())
        run_id = require_identifier(self.run_id, "run_id")
        if submission.run_id != run_id:
            raise ValidationError("submission.run_id", "must match run_id")
        return {
            "schema_version": SCHEMA_VERSION, "record_type": "run_event",
            "sequence": require_positive_integer(self.sequence, "sequence"),
            "event_type": "frame_submission_accepted", "run_id": run_id,
            "occurred_at": _format_utc_timestamp(self.occurred_at, "occurred_at"),
            "submission": submission.to_json(),
        }


def _require_exit_code(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("exit_code", "must be an integer")
    return value


def _frame_reference_event_json(event: Any, event_type: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "record_type": "run_event",
        "sequence": require_positive_integer(event.sequence, "sequence"), "event_type": event_type,
        "run_id": require_identifier(event.run_id, "run_id"),
        "occurred_at": _format_utc_timestamp(event.occurred_at, "occurred_at"),
        "task_id": require_identifier(event.task_id, "task_id"),
        "revision": require_positive_integer(event.revision, "revision"),
        "attempt": require_positive_integer(event.attempt, "attempt"),
    }


RunEvent: TypeAlias = (
    RunInitializedEvent
    | FrameTaskCreatedEvent
    | FrameAttemptIntendedEvent
    | FrameProcessOutcomeEvent
    | FrameSubmissionAcceptedEvent
)


def parse_run_event(payload: Any) -> RunEvent:
    """Parse exactly one supported version-one event discriminated by event_type."""
    data = require_object(payload, "run_event")
    event_type = require_string(data.get("event_type"), "event_type")
    parsers = {
        "run_initialized": RunInitializedEvent.from_json,
        "frame_task_created": FrameTaskCreatedEvent.from_json,
        "frame_attempt_intended": FrameAttemptIntendedEvent.from_json,
        "frame_process_outcome": FrameProcessOutcomeEvent.from_json,
        "frame_submission_accepted": FrameSubmissionAcceptedEvent.from_json,
    }
    parser = parsers.get(event_type)
    if parser is None:
        raise ValidationError("event_type", "must be a supported version-one event type")
    return parser(data)


@dataclass(frozen=True)
class RunState:
    """Rebuildable state projection after a run's initialization event."""

    run_id: str
    initialized_at: datetime
    last_event_sequence: int = 1
    status: str = "initialized"
    accepted_submission_count: int = 0

    @classmethod
    def from_json(cls, payload: Any) -> "RunState":
        """Validate and parse a complete initialized-state JSON object."""
        data = require_object(payload, "run_state")
        status = data.get("status")
        expected = {
            "schema_version", "record_type", "run_id", "status", "initialized_at", "last_event_sequence",
        }
        if status == "active":
            expected.add("accepted_submission_count")
        require_exact_fields(data, "run_state", expected)
        schema_version = require_positive_integer(data["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValidationError("schema_version", f"must equal {SCHEMA_VERSION}")
        if data["record_type"] != "run_state":
            raise ValidationError("record_type", "must equal 'run_state'")
        if status not in {"initialized", "active"}:
            raise ValidationError("status", "must equal 'initialized' or 'active'")
        last_event_sequence = require_positive_integer(
            data["last_event_sequence"], "last_event_sequence"
        )
        if status == "initialized" and last_event_sequence != 1:
            raise ValidationError("last_event_sequence", "must equal 1")
        accepted_submission_count = 0
        if status == "active":
            if last_event_sequence == 1:
                raise ValidationError("last_event_sequence", "must exceed 1 for active state")
            accepted_submission_count = require_nonnegative_integer(
                data["accepted_submission_count"], "accepted_submission_count"
            )
            if accepted_submission_count > 1:
                raise ValidationError("accepted_submission_count", "must not exceed 1 for Frame state")
        return cls(
            run_id=require_identifier(data["run_id"], "run_id"),
            initialized_at=_parse_utc_timestamp(data["initialized_at"], "initialized_at"),
            last_event_sequence=last_event_sequence,
            status=status,
            accepted_submission_count=accepted_submission_count,
        )

    def to_json(self) -> dict[str, Any]:
        """Return the exact version-one initialized-state JSON representation."""
        if self.status not in {"initialized", "active"}:
            raise ValidationError("status", "must equal 'initialized' or 'active'")
        last_event_sequence = require_positive_integer(
            self.last_event_sequence, "last_event_sequence"
        )
        if self.status == "initialized" and last_event_sequence != 1:
            raise ValidationError("last_event_sequence", "must equal 1")
        if self.status == "active" and last_event_sequence == 1:
            raise ValidationError("last_event_sequence", "must exceed 1 for active state")
        run_id = require_identifier(self.run_id, "run_id")
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "run_state",
            "run_id": run_id,
            "status": self.status,
            "initialized_at": _format_utc_timestamp(self.initialized_at, "initialized_at"),
            "last_event_sequence": last_event_sequence,
        }
        if self.status == "active":
            accepted_submission_count = require_nonnegative_integer(
                self.accepted_submission_count, "accepted_submission_count"
            )
            if accepted_submission_count > 1:
                raise ValidationError("accepted_submission_count", "must not exceed 1 for Frame state")
            payload["accepted_submission_count"] = accepted_submission_count
        elif self.accepted_submission_count != 0:
            raise ValidationError("accepted_submission_count", "must equal 0 for initialized state")
        return payload


def project_initialization(
    request: RunRequest, initialized_at: datetime
) -> tuple[RunInitializedEvent, RunState]:
    """Create the first authoritative event and its rebuildable state projection."""
    request = _validated_request(request)
    _format_utc_timestamp(initialized_at, "initialized_at")
    event = RunInitializedEvent(
        run_id=request.run_id,
        occurred_at=initialized_at,
        request=request,
    )
    state = RunState(
        run_id=request.run_id,
        initialized_at=initialized_at,
    )
    return event, state


def replay_run_events(events: Iterable[RunEvent]) -> RunState:
    """Purely rebuild the bounded Frame lifecycle from authoritative events.

    This reducer owns no files or processes.  It recognizes only the first task's
    dispatch lifecycle and deliberately has no event that can complete a run.
    """
    initialized: RunInitializedEvent | None = None
    task: FrameTask | None = None
    pending_attempt: int | None = None
    next_attempt = 1
    outcomes: dict[int, int] = {}
    accepted = False
    last_sequence = 0
    last_occurred_at: datetime | None = None

    for candidate in events:
        if not isinstance(
            candidate,
            (
                RunInitializedEvent,
                FrameTaskCreatedEvent,
                FrameAttemptIntendedEvent,
                FrameProcessOutcomeEvent,
                FrameSubmissionAcceptedEvent,
            ),
        ):
            raise ValidationError("run_event", "must be a supported parsed run event")
        event = parse_run_event(candidate.to_json())
        if event.sequence != last_sequence + 1:
            raise ValidationError("sequence", "must be contiguous and start at 1")
        if last_occurred_at is not None and event.occurred_at < last_occurred_at:
            raise ValidationError("occurred_at", "must not precede an earlier event")

        if initialized is None:
            if not isinstance(event, RunInitializedEvent):
                raise ValidationError("event_type", "must begin with 'run_initialized'")
            initialized = event
        else:
            if event.run_id != initialized.run_id:
                raise ValidationError("run_id", "must match initialized run_id")
            if isinstance(event, RunInitializedEvent):
                raise ValidationError("event_type", "cannot initialize a run twice")
            if isinstance(event, FrameTaskCreatedEvent):
                if task is not None:
                    raise ValidationError("event_type", "cannot create Frame task twice")
                if event.task != build_frame_task(initialized.request):
                    raise ValidationError("task", "must equal the deterministic Frame task")
                task = event.task
            elif isinstance(event, FrameAttemptIntendedEvent):
                _require_matching_task_reference(event.task_id, event.revision, task)
                if accepted:
                    raise ValidationError("event_type", "cannot attempt an accepted Frame task")
                if pending_attempt is not None:
                    raise ValidationError("attempt", "cannot intend a new attempt before an outcome")
                if event.attempt != next_attempt:
                    raise ValidationError("attempt", "must be the next Frame attempt")
                pending_attempt = event.attempt
            elif isinstance(event, FrameProcessOutcomeEvent):
                _require_matching_task_reference(event.task_id, event.revision, task)
                if accepted:
                    raise ValidationError("event_type", "cannot record an outcome after acceptance")
                if pending_attempt != event.attempt:
                    raise ValidationError("attempt", "must match the intended Frame attempt")
                outcomes[event.attempt] = event.exit_code
                pending_attempt = None
                next_attempt = event.attempt + 1
            elif isinstance(event, FrameSubmissionAcceptedEvent):
                if task is None:
                    raise ValidationError("event_type", "cannot accept before Frame task creation")
                submission = event.submission
                _require_matching_task_reference(submission.task_id, submission.revision, task)
                if accepted:
                    raise ValidationError("submission_id", "cannot accept Frame submission twice")
                if pending_attempt is not None or submission.attempt != next_attempt - 1:
                    raise ValidationError("attempt", "must be the current completed Frame attempt")
                if outcomes.get(submission.attempt) != 0:
                    raise ValidationError("attempt", "must have a recorded successful process outcome")
                accepted = True
        last_sequence = event.sequence
        last_occurred_at = event.occurred_at

    if initialized is None:
        raise ValidationError("run_event", "must contain an initialization event")
    if task is None:
        return RunState(initialized.run_id, initialized.occurred_at, last_sequence, "initialized")
    return RunState(
        initialized.run_id,
        initialized.occurred_at,
        last_sequence,
        "active",
        1 if accepted else 0,
    )


def _require_matching_task_reference(task_id: str, revision: int, task: FrameTask | None) -> None:
    if task is None:
        raise ValidationError("task_id", "must reference a created Frame task")
    if task_id != task.task_id:
        raise ValidationError("task_id", "must match Frame task")
    if revision != task.revision:
        raise ValidationError("revision", "must match Frame task revision")
