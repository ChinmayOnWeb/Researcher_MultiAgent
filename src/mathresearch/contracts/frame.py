"""Strict, deterministic contracts for the first (Frame) research task."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from types import MappingProxyType
from typing import Any

from .records import SCHEMA_VERSION, RunRequest
from .validation import (
    ValidationError,
    require_exact_fields,
    require_identifier,
    require_object,
    require_positive_integer,
    require_string,
    require_string_list,
)


_UTC_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_FRAME_OUTPUT_REQUIREMENTS = (
    "framed_question",
    "success_criteria",
    "terms",
    "assumptions",
    "missing_inputs",
    "stakes_assessment",
)


def _parse_utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise ValidationError(field, "must be a UTC timestamp with microseconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValidationError(field, "must be a possible UTC timestamp") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _format_utc_timestamp(value: datetime, field: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValidationError(field, "must be an aware UTC datetime")
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond:06d}Z"
    )


def _require_schema(data: Mapping[str, Any], field: str, expected: set[str], record_type: str) -> None:
    require_exact_fields(data, field, expected)
    if require_positive_integer(data["schema_version"], "schema_version") != SCHEMA_VERSION:
        raise ValidationError("schema_version", f"must equal {SCHEMA_VERSION}")
    if data["record_type"] != record_type:
        raise ValidationError("record_type", f"must equal '{record_type}'")


def _validated_request(value: Any) -> RunRequest:
    if not isinstance(value, RunRequest):
        raise ValidationError("request", "must be a RunRequest")
    return RunRequest.from_json(value.to_json())


def _serialized_string_list(value: Any, field: str) -> list[str]:
    """Validate an in-memory JSON-list value without silently repairing it."""
    if not isinstance(value, (list, tuple)):
        raise ValidationError(field, "must be an array")
    return [require_string(item, f"{field}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True)
class FrameTask:
    """The single deterministic first task for a newly initialized run."""

    task_id: str
    run_id: str
    revision: int
    phase: str
    role: str
    objective: str
    prerequisites: tuple[str, ...]
    allowed_input_ids: tuple[str, ...]
    acceptance_requirements: tuple[str, ...]
    status: str

    @classmethod
    def from_json(cls, payload: Any) -> "FrameTask":
        data = require_object(payload, "frame_task")
        _require_schema(
            data,
            "frame_task",
            {
                "schema_version", "record_type", "task_id", "run_id", "revision", "phase", "role",
                "objective", "prerequisites", "allowed_input_ids", "acceptance_requirements", "status",
            },
            "frame_task",
        )
        if data["phase"] != "frame":
            raise ValidationError("phase", "must equal 'frame'")
        if data["role"] != "framer":
            raise ValidationError("role", "must equal 'framer'")
        if data["status"] != "created":
            raise ValidationError("status", "must equal 'created'")
        return cls(
            task_id=require_identifier(data["task_id"], "task_id"),
            run_id=require_identifier(data["run_id"], "run_id"),
            revision=require_positive_integer(data["revision"], "revision"),
            phase="frame",
            role="framer",
            objective=require_string(data["objective"], "objective"),
            prerequisites=require_string_list(data["prerequisites"], "prerequisites"),
            allowed_input_ids=require_string_list(data["allowed_input_ids"], "allowed_input_ids"),
            acceptance_requirements=require_string_list(
                data["acceptance_requirements"], "acceptance_requirements"
            ),
            status="created",
        )

    def to_json(self) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION, "record_type": "frame_task", "task_id": self.task_id,
            "run_id": self.run_id, "revision": self.revision, "phase": self.phase, "role": self.role,
            "objective": self.objective, "prerequisites": list(self.prerequisites),
            "allowed_input_ids": list(self.allowed_input_ids),
            "acceptance_requirements": list(self.acceptance_requirements), "status": self.status,
        }
        FrameTask.from_json(payload)
        return payload


@dataclass(frozen=True)
class FramePacket:
    """The complete, coordinator-authored input packet for the Frame worker."""

    packet_id: str
    task: FrameTask
    request: RunRequest
    output_requirements: tuple[str, ...]

    @classmethod
    def from_json(cls, payload: Any) -> "FramePacket":
        data = require_object(payload, "frame_packet")
        _require_schema(
            data,
            "frame_packet",
            {"schema_version", "record_type", "packet_id", "task", "request", "output_requirements"},
            "frame_packet",
        )
        task = FrameTask.from_json(data["task"])
        request = RunRequest.from_json(data["request"])
        if task.run_id != request.run_id:
            raise ValidationError("task.run_id", "must match request.run_id")
        requirements = require_string_list(data["output_requirements"], "output_requirements")
        if requirements != _FRAME_OUTPUT_REQUIREMENTS:
            raise ValidationError("output_requirements", "must equal the Frame output requirements")
        return cls(
            packet_id=require_identifier(data["packet_id"], "packet_id"),
            task=task,
            request=request,
            output_requirements=requirements,
        )

    def to_json(self) -> dict[str, Any]:
        if not isinstance(self.task, FrameTask):
            raise ValidationError("task", "must be a FrameTask")
        request = _validated_request(self.request)
        payload = {
            "schema_version": SCHEMA_VERSION, "record_type": "frame_packet", "packet_id": self.packet_id,
            "task": self.task.to_json(), "request": request.to_json(),
            "output_requirements": list(self.output_requirements),
        }
        FramePacket.from_json(payload)
        return payload


@dataclass(frozen=True)
class FrameSubmission:
    """A worker's structured response to one intended Frame attempt."""

    submission_id: str
    run_id: str
    task_id: str
    revision: int
    attempt: int
    submitted_at: datetime
    frame: Mapping[str, Any]

    @classmethod
    def from_json(cls, payload: Any) -> "FrameSubmission":
        data = require_object(payload, "frame_submission")
        _require_schema(
            data,
            "frame_submission",
            {
                "schema_version", "record_type", "submission_id", "run_id", "task_id", "revision",
                "attempt", "submitted_at", "frame",
            },
            "frame_submission",
        )
        frame = require_object(data["frame"], "frame")
        require_exact_fields(frame, "frame", set(_FRAME_OUTPUT_REQUIREMENTS))
        normalized_frame = MappingProxyType({
            "framed_question": require_string(frame["framed_question"], "frame.framed_question"),
            "success_criteria": require_string_list(frame["success_criteria"], "frame.success_criteria"),
            "terms": require_string_list(frame["terms"], "frame.terms"),
            "assumptions": require_string_list(frame["assumptions"], "frame.assumptions"),
            "missing_inputs": require_string_list(frame["missing_inputs"], "frame.missing_inputs"),
            "stakes_assessment": require_string(frame["stakes_assessment"], "frame.stakes_assessment"),
        })
        return cls(
            submission_id=require_identifier(data["submission_id"], "submission_id"),
            run_id=require_identifier(data["run_id"], "run_id"),
            task_id=require_identifier(data["task_id"], "task_id"),
            revision=require_positive_integer(data["revision"], "revision"),
            attempt=require_positive_integer(data["attempt"], "attempt"),
            submitted_at=_parse_utc_timestamp(data["submitted_at"], "submitted_at"),
            frame=normalized_frame,
        )

    def to_json(self) -> dict[str, Any]:
        frame = self.frame
        frame = require_object(frame, "frame")
        require_exact_fields(frame, "frame", set(_FRAME_OUTPUT_REQUIREMENTS))
        payload = {
            "schema_version": SCHEMA_VERSION, "record_type": "frame_submission",
            "submission_id": self.submission_id, "run_id": self.run_id, "task_id": self.task_id,
            "revision": self.revision, "attempt": self.attempt,
            "submitted_at": _format_utc_timestamp(self.submitted_at, "submitted_at"),
            "frame": {
                "framed_question": require_string(frame["framed_question"], "frame.framed_question"),
                "success_criteria": _serialized_string_list(
                    frame["success_criteria"], "frame.success_criteria"
                ),
                "terms": _serialized_string_list(frame["terms"], "frame.terms"),
                "assumptions": _serialized_string_list(frame["assumptions"], "frame.assumptions"),
                "missing_inputs": _serialized_string_list(frame["missing_inputs"], "frame.missing_inputs"),
                "stakes_assessment": require_string(frame["stakes_assessment"], "frame.stakes_assessment"),
            },
        }
        FrameSubmission.from_json(payload)
        return payload


def build_frame_task(request: RunRequest) -> FrameTask:
    """Create the one fixed first task without any ambient coordinator state."""
    request = _validated_request(request)
    return FrameTask(
        task_id="frame", run_id=request.run_id, revision=1, phase="frame", role="framer",
        objective=f"Frame the research question: {request.question}", prerequisites=(),
        allowed_input_ids=("run-request",), acceptance_requirements=_FRAME_OUTPUT_REQUIREMENTS,
        status="created",
    )


def build_frame_packet(task: FrameTask, request: RunRequest) -> FramePacket:
    """Create a fixed complete packet for the matching Frame task and request."""
    if not isinstance(task, FrameTask):
        raise ValidationError("task", "must be a FrameTask")
    task = FrameTask.from_json(task.to_json())
    request = _validated_request(request)
    if task.run_id != request.run_id:
        raise ValidationError("task.run_id", "must match request.run_id")
    return FramePacket("frame-packet", task, request, _FRAME_OUTPUT_REQUIREMENTS)
