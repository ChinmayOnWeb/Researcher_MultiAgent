"""Strict records and reducer for the fixed four-stage quick workflow."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .run import RunInitializedEvent, _format_utc_timestamp, _parse_utc_timestamp
from .validation import (ValidationError, require_exact_fields, require_identifier,
                         require_nonnegative_integer, require_object,
                         require_optional_string, require_positive_integer,
                         require_string, require_string_list)

WORKFLOW_SCHEMA_VERSION = 2
STAGES = ("frame", "investigate", "verify", "explain")
_OUTCOMES = frozenset(("succeeded", "failed", "timed_out", "cancelled", "launch_failed"))
_TERMINAL = frozenset(("blocked", "budget_exhausted", "complete"))


def _json_value(value: Any, field: str) -> Any:
    """Copy JSON-like values while rejecting non-string mapping keys."""
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValidationError(field, "must be finite JSON")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{field}[]") for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValidationError(field, "must have string keys")
        return {key: _json_value(item, f"{field}.{key}") for key, item in value.items()}
    raise ValidationError(field, "must be JSON-compatible")


def _stage(value: Any, field: str = "stage") -> str:
    result = require_string(value, field)
    if result not in STAGES:
        raise ValidationError(field, "must be one of frame, investigate, verify, explain")
    return result


def _sha(value: Any, field: str) -> str:
    result = require_string(value, field)
    if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
        raise ValidationError(field, "must be a lowercase SHA-256 hex digest")
    return result


def _validate_packet(value: Any) -> dict[str, Any]:
    data = require_object(value, "body.packet")
    require_exact_fields(data, "body.packet", {"stage", "request", "inputs", "output_schema", "capabilities"})
    _stage(data["stage"], "body.packet.stage")
    for field in ("request", "inputs", "output_schema", "capabilities"):
        require_object(data[field], f"body.packet.{field}")
    return _json_value(data, "body.packet")


def _validate_packet_context(
    packet: Mapping[str, Any],
    *,
    stage: str,
    request: RunInitializedEvent,
    accepted: Mapping[str, Mapping[str, Any]],
) -> None:
    """Bind a durable worker packet to the initialized request and fixed graph."""
    if packet["request"] != request.request.to_json():
        raise ValidationError("body.packet.request", "must exactly match the initialized request")
    prerequisite_count = STAGES.index(stage)
    expected_inputs = {name: accepted[name] for name in STAGES[:prerequisite_count]}
    if packet["inputs"] != expected_inputs:
        raise ValidationError("body.packet.inputs", "must exactly match accepted prerequisite payloads")


def _validate_frame(value: Any) -> dict[str, Any]:
    data = require_object(value, "result")
    require_exact_fields(data, "result", {"framed_question", "success_criteria", "terms", "assumptions", "missing_inputs", "stakes_assessment"})
    require_string(data["framed_question"], "result.framed_question")
    for name in ("success_criteria", "terms", "assumptions", "missing_inputs"):
        require_string_list(data[name], f"result.{name}")
    require_string(data["stakes_assessment"], "result.stakes_assessment")
    return _json_value(data, "result")


def _validate_investigate(value: Any) -> dict[str, Any]:
    data = require_object(value, "result")
    require_exact_fields(data, "result", {"answer", "claims", "alternatives", "limitations"})
    require_string(data["answer"], "result.answer")
    claims = data["claims"]
    if not isinstance(claims, list): raise ValidationError("result.claims", "must be an array")
    ids: set[str] = set()
    for index, claim in enumerate(claims):
        claim_data = require_object(claim, f"result.claims[{index}]")
        require_exact_fields(claim_data, f"result.claims[{index}]", {"id", "statement", "basis", "support"})
        claim_id = require_string(claim_data["id"], f"result.claims[{index}].id")
        if claim_id in ids: raise ValidationError("result.claims", "must have unique claim ids")
        ids.add(claim_id)
        require_string(claim_data["statement"], f"result.claims[{index}].statement")
        if require_string(claim_data["basis"], f"result.claims[{index}].basis") not in {"supplied", "derived", "inferred", "unknown"}:
            raise ValidationError(f"result.claims[{index}].basis", "must be a supported basis")
        require_string(claim_data["support"], f"result.claims[{index}].support")
    require_string_list(data["alternatives"], "result.alternatives")
    require_string_list(data["limitations"], "result.limitations")
    return _json_value(data, "result")


def _validate_verify(value: Any, claims: set[str] | None = None) -> dict[str, Any]:
    data = require_object(value, "result")
    require_exact_fields(data, "result", {"checks", "disposition", "limitations"})
    checks = data["checks"]
    if not isinstance(checks, list): raise ValidationError("result.checks", "must be an array")
    seen: set[str] = set(); verdicts: list[str] = []
    for index, check in enumerate(checks):
        check_data = require_object(check, f"result.checks[{index}]")
        require_exact_fields(check_data, f"result.checks[{index}]", {"claim_id", "verdict", "reasoning"})
        claim_id = require_string(check_data["claim_id"], f"result.checks[{index}].claim_id")
        if claim_id in seen: raise ValidationError("result.checks", "must have one check per claim")
        seen.add(claim_id)
        verdict = require_string(check_data["verdict"], f"result.checks[{index}].verdict")
        if verdict not in {"supported", "unsupported", "contradicted"}: raise ValidationError(f"result.checks[{index}].verdict", "must be supported, unsupported, or contradicted")
        verdicts.append(verdict); require_string(check_data["reasoning"], f"result.checks[{index}].reasoning")
    if claims is not None and seen != claims: raise ValidationError("result.checks", "must check every investigative claim exactly once")
    disposition = require_string(data["disposition"], "result.disposition")
    if disposition not in {"pass", "inconclusive", "fail"}: raise ValidationError("result.disposition", "must be pass, inconclusive, or fail")
    if "contradicted" in verdicts and disposition != "fail": raise ValidationError("result.disposition", "must be fail when a claim is contradicted")
    if "unsupported" in verdicts and disposition == "pass": raise ValidationError("result.disposition", "cannot be pass with unsupported claim")
    require_string_list(data["limitations"], "result.limitations")
    return _json_value(data, "result")


def _validate_explain(value: Any, disposition: str | None = None) -> dict[str, Any]:
    data = require_object(value, "result")
    require_exact_fields(data, "result", {"summary", "explanation", "conclusion", "limitations"})
    require_string(data["summary"], "result.summary"); require_string(data["explanation"], "result.explanation")
    conclusion = require_string(data["conclusion"], "result.conclusion")
    if conclusion not in {"supported", "inconclusive"}: raise ValidationError("result.conclusion", "must be supported or inconclusive")
    if disposition == "inconclusive" and conclusion == "supported": raise ValidationError("result.conclusion", "cannot be supported after inconclusive verification")
    require_string_list(data["limitations"], "result.limitations")
    return _json_value(data, "result")


def validate_stage_result(stage: str, value: Any, *, investigate: Mapping[str, Any] | None = None, verify: Mapping[str, Any] | None = None) -> dict[str, Any]:
    stage = _stage(stage)
    if stage == "frame": return _validate_frame(value)
    if stage == "investigate": return _validate_investigate(value)
    if stage == "verify":
        claims = {str(item["id"]) for item in investigate.get("claims", [])} if investigate else None
        return _validate_verify(value, claims)
    return _validate_explain(value, str(verify.get("disposition")) if verify else None)


@dataclass(frozen=True)
class WorkflowEvent:
    run_id: str
    occurred_at: datetime
    sequence: int
    event_type: str
    body: Mapping[str, Any]

    @classmethod
    def from_json(cls, payload: Any) -> "WorkflowEvent":
        data = require_object(payload, "workflow_event")
        require_exact_fields(data, "workflow_event", {"schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "body"})
        if require_positive_integer(data["schema_version"], "schema_version") != WORKFLOW_SCHEMA_VERSION: raise ValidationError("schema_version", "must equal 2")
        if data["record_type"] != "workflow_event": raise ValidationError("record_type", "must equal 'workflow_event'")
        event = cls(require_identifier(data["run_id"], "run_id"), _parse_utc_timestamp(data["occurred_at"], "occurred_at"), require_positive_integer(data["sequence"], "sequence"), require_string(data["event_type"], "event_type"), _validate_event_body(data["event_type"], data["body"]))
        return event

    def to_json(self) -> dict[str, Any]:
        return WorkflowEvent.from_json({"schema_version": 2, "record_type": "workflow_event", "sequence": self.sequence, "event_type": self.event_type, "run_id": self.run_id, "occurred_at": _format_utc_timestamp(self.occurred_at, "occurred_at"), "body": self.body})._to_json()

    def _to_json(self) -> dict[str, Any]:
        return {"schema_version": 2, "record_type": "workflow_event", "sequence": self.sequence, "event_type": self.event_type, "run_id": self.run_id, "occurred_at": _format_utc_timestamp(self.occurred_at, "occurred_at"), "body": _json_value(self.body, "body")}


def _validate_event_body(event_type: Any, value: Any) -> dict[str, Any]:
    kind = require_string(event_type, "event_type"); data = require_object(value, "body")
    if kind == "quick_configured":
        require_exact_fields(data, "body", {"adapter", "executable", "model", "protocol_version", "capabilities", "stages"})
        require_string(data["adapter"], "body.adapter"); require_string(data["executable"], "body.executable"); require_optional_string(data["model"], "body.model"); require_string(data["protocol_version"], "body.protocol_version")
        caps = require_object(data["capabilities"], "body.capabilities")
        if not all(isinstance(key, str) and isinstance(item, bool) for key, item in caps.items()): raise ValidationError("body.capabilities", "must map string names to booleans")
        if tuple(require_string_list(data["stages"], "body.stages")) != STAGES: raise ValidationError("body.stages", "must be the fixed ordered stages")
    elif kind == "quick_attempt_intended":
        require_exact_fields(data, "body", {"stage", "attempt", "packet"}); _stage(data["stage"]); 
        if require_positive_integer(data["attempt"], "body.attempt") != 1: raise ValidationError("body.attempt", "must equal 1")
        packet = _validate_packet(data["packet"])
        if packet["stage"] != data["stage"]: raise ValidationError("body.packet.stage", "must match body.stage")
    elif kind == "quick_attempt_finished":
        require_exact_fields(data, "body", {"stage", "attempt", "outcome", "exit_code", "stdout_sha256", "stderr_sha256", "result", "error"}); _stage(data["stage"])
        if require_positive_integer(data["attempt"], "body.attempt") != 1: raise ValidationError("body.attempt", "must equal 1")
        if require_string(data["outcome"], "body.outcome") not in _OUTCOMES: raise ValidationError("body.outcome", "must be a supported worker outcome")
        if data["exit_code"] is not None and (isinstance(data["exit_code"], bool) or not isinstance(data["exit_code"], int)): raise ValidationError("body.exit_code", "must be an integer or null")
        _sha(data["stdout_sha256"], "body.stdout_sha256"); _sha(data["stderr_sha256"], "body.stderr_sha256"); require_optional_string(data["error"], "body.error")
        if data["outcome"] == "succeeded":
            if data["exit_code"] != 0 or data["result"] is None: raise ValidationError("body", "successful outcome requires zero exit and result")
            validate_stage_result(data["stage"], data["result"])
        elif data["result"] is not None: raise ValidationError("body.result", "must be null unless outcome succeeded")
    elif kind == "quick_stage_accepted":
        require_exact_fields(data, "body", {"stage", "attempt"}); _stage(data["stage"])
        if require_positive_integer(data["attempt"], "body.attempt") != 1: raise ValidationError("body.attempt", "must equal 1")
    elif kind == "quick_stopped":
        require_exact_fields(data, "body", {"status", "reason"}); status = require_string(data["status"], "body.status")
        if status not in {"blocked", "budget_exhausted"}: raise ValidationError("body.status", "must be blocked or budget_exhausted")
        require_string(data["reason"], "body.reason")
    elif kind == "quick_completed":
        require_exact_fields(data, "body", {"report_markdown"}); require_string(data["report_markdown"], "body.report_markdown")
    else: raise ValidationError("event_type", "must be a supported quick event type")
    return _json_value(data, "body")


@dataclass(frozen=True)
class QuickState:
    run_id: str; initialized_at: datetime; status: str; last_event_sequence: int; accepted_submission_count: int; current_stage: str | None; reason: str | None; report_path: str | None
    @classmethod
    def from_json(cls, payload: Any) -> "QuickState":
        data = require_object(payload, "quick_state")
        require_exact_fields(data, "quick_state", {"schema_version", "record_type", "run_id", "initialized_at", "status", "last_event_sequence", "accepted_submission_count", "current_stage", "reason", "report_path"})
        if require_positive_integer(data["schema_version"], "schema_version") != 2: raise ValidationError("schema_version", "must equal 2")
        if data["record_type"] != "quick_state": raise ValidationError("record_type", "must equal 'quick_state'")
        status = require_string(data["status"], "status")
        if status not in {"initialized", "configured", "active", "blocked", "budget_exhausted", "complete"}: raise ValidationError("status", "must be a supported quick status")
        current = data["current_stage"]
        if current is not None: _stage(current, "current_stage")
        return cls(require_identifier(data["run_id"], "run_id"), _parse_utc_timestamp(data["initialized_at"], "initialized_at"), status, require_positive_integer(data["last_event_sequence"], "last_event_sequence"), require_nonnegative_integer(data["accepted_submission_count"], "accepted_submission_count"), current, require_optional_string(data["reason"], "reason"), require_optional_string(data["report_path"], "report_path"))
    def to_json(self) -> dict[str, Any]:
        return QuickState.from_json({"schema_version": 2, "record_type": "quick_state", "run_id": self.run_id, "initialized_at": _format_utc_timestamp(self.initialized_at, "initialized_at"), "status": self.status, "last_event_sequence": self.last_event_sequence, "accepted_submission_count": self.accepted_submission_count, "current_stage": self.current_stage, "reason": self.reason, "report_path": self.report_path})._to_json()
    def _to_json(self) -> dict[str, Any]:
        return {"schema_version": 2, "record_type": "quick_state", "run_id": self.run_id, "initialized_at": _format_utc_timestamp(self.initialized_at, "initialized_at"), "status": self.status, "last_event_sequence": self.last_event_sequence, "accepted_submission_count": self.accepted_submission_count, "current_stage": self.current_stage, "reason": self.reason, "report_path": self.report_path}


def replay_quick_events(events: Iterable[RunInitializedEvent | WorkflowEvent]) -> QuickState:
    initial: RunInitializedEvent | None = None; configured = False; accepted: dict[str, Mapping[str, Any]] = {}; pending: str | None = None; finished: dict[str, Mapping[str, Any]] = {}; terminal: tuple[str, str | None, str | None] | None = None; last_seq = 0; last_at: datetime | None = None
    for raw in events:
        event = RunInitializedEvent.from_json(raw.to_json()) if isinstance(raw, RunInitializedEvent) else WorkflowEvent.from_json(raw.to_json()) if isinstance(raw, WorkflowEvent) else None
        if event is None: raise ValidationError("run_event", "must be initialization or workflow event")
        if event.sequence != last_seq + 1: raise ValidationError("sequence", "must be contiguous and start at 1")
        if last_at and event.occurred_at < last_at: raise ValidationError("occurred_at", "must not precede earlier event")
        if initial is None:
            if not isinstance(event, RunInitializedEvent): raise ValidationError("event_type", "must begin with run_initialized")
            initial = event
        else:
            if event.run_id != initial.run_id: raise ValidationError("run_id", "must match initialized run_id")
            if not isinstance(event, WorkflowEvent): raise ValidationError("event_type", "cannot initialize twice")
            if terminal: raise ValidationError("event_type", "cannot follow terminal quick event")
            if event.event_type == "quick_configured":
                if configured or pending or accepted or finished: raise ValidationError("event_type", "configuration must directly follow initialization")
                configured = True
            elif not configured: raise ValidationError("event_type", "quick workflow must be configured first")
            elif event.event_type == "quick_attempt_intended":
                stage = event.body["stage"]
                if pending or stage in finished or stage in accepted or STAGES[len(accepted)] != stage: raise ValidationError("stage", "must be next unaccepted quick stage")
                _validate_packet_context(event.body["packet"], stage=stage, request=initial, accepted=accepted)
                pending = stage
            elif event.event_type == "quick_attempt_finished":
                stage = event.body["stage"]
                if pending != stage: raise ValidationError("stage", "must finish the intended stage")
                if event.body["outcome"] == "succeeded":
                    investigate = accepted.get("investigate"); verify = accepted.get("verify")
                    validate_stage_result(stage, event.body["result"], investigate=investigate, verify=verify)
                finished[stage] = event.body; pending = None
            elif event.event_type == "quick_stage_accepted":
                stage = event.body["stage"]; finish = finished.get(stage)
                if finish is None or finish["outcome"] != "succeeded" or stage in accepted or STAGES[len(accepted)] != stage: raise ValidationError("stage", "must accept the next successfully finished stage")
                accepted[stage] = finish["result"]
            elif event.event_type == "quick_stopped":
                terminal = (event.body["status"], event.body["reason"], None)
            elif event.event_type == "quick_completed":
                if pending or len(accepted) != 4 or accepted["verify"]["disposition"] == "fail": raise ValidationError("event_type", "cannot complete before all eligible acceptances")
                terminal = ("complete", None, event.body["report_markdown"])
            else: raise ValidationError("event_type", "must be a supported quick event type")
        last_seq = event.sequence; last_at = event.occurred_at
    if initial is None: raise ValidationError("run_event", "must contain initialization")
    if terminal: status, reason, report = terminal
    elif not configured: status, reason, report = "initialized", None, None
    elif pending: status, reason, report = "active", None, None
    elif accepted: status, reason, report = "active", None, None
    else: status, reason, report = "configured", None, None
    current = None if terminal or not configured else (pending or STAGES[len(accepted)] if len(accepted) < 4 else None)
    return QuickState(initial.run_id, initial.occurred_at, status, last_seq, len(accepted), current, reason, "report.md" if report is not None else None)
