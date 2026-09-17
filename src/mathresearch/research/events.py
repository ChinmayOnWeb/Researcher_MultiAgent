"""Strict, pure version-three research event validation and replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from mathresearch.contracts.research_request import ResearchRequest
from mathresearch.contracts.validation import ValidationError, require_exact_fields, require_identifier, require_nonnegative_integer, require_object, require_string
from mathresearch.research.contracts import validate_action, validate_decision_details, validate_result


EVENT_TYPES = frozenset({"research_initialized", "provider_configured", "decision_recorded", "action_intended", "action_finished", "gate_opened", "gate_answered", "research_finished"})
TERMINAL = frozenset({"complete", "incomplete", "blocked", "budget_exhausted"})


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-compatible") from exc


def _timestamp(value: Any, field: str) -> str:
    text = require_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(field, "must be a UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(field, "must be an offset-aware timestamp")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(value: Any, field: str) -> str:
    text = require_string(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValidationError(field, "must be a lowercase SHA-256 hex digest")
    return text


def _nullable_string(value: Any, field: str) -> str | None:
    return None if value is None else require_string(value, field)


def _telemetry(value: Any) -> dict[str, Any]:
    data = require_object(value, "telemetry")
    keys = {"duration_ms", "input_bytes", "output_bytes", "model_observed", "effort_observed", "input_tokens", "output_tokens", "reasoning_tokens", "cost_usd"}
    require_exact_fields(data, "telemetry", keys)
    checked = {key: require_nonnegative_integer(data[key], f"telemetry.{key}") for key in ("duration_ms", "input_bytes", "output_bytes")}
    for key in ("model_observed", "effort_observed", "cost_usd"):
        checked[key] = _nullable_string(data[key], f"telemetry.{key}")
    for key in ("input_tokens", "output_tokens", "reasoning_tokens"):
        checked[key] = None if data[key] is None else require_nonnegative_integer(data[key], f"telemetry.{key}")
    return checked


def validate_tool_result(operation: str, value: Any) -> dict[str, Any]:
    """Accept only the currently durable tool shape; Task 6 owns semantics."""
    data = require_object(value, "tool result")
    if operation != "fetch_source":
        raise ValidationError("tool result", "operation result schema is not available before Task 6")
    require_exact_fields(data, "tool result", {"source"})
    source = require_object(data["source"], "tool result.source")
    if "id" not in source:
        raise ValidationError("tool result.source", "missing required field 'id'")
    require_identifier(source["id"], "tool result.source.id")
    checked = {key: value for key, value in source.items()}
    if len(canonical_json_bytes({"source": checked})) > 65536:
        raise ValidationError("tool result", "canonical JSON must be at most 65536 bytes")
    return {"source": checked}


@dataclass(frozen=True)
class ResearchEvent:
    sequence: int
    event_type: str
    run_id: str
    occurred_at: str
    body: Mapping[str, Any]

    @classmethod
    def from_json(cls, payload: Any) -> "ResearchEvent":
        data = require_object(payload, "research_event")
        require_exact_fields(data, "research_event", {"schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "body"})
        if data["schema_version"] != 3 or data["record_type"] != "research_event":
            raise ValidationError("research_event", "must be a version-three research event")
        event_type = require_string(data["event_type"], "event_type")
        if event_type not in EVENT_TYPES: raise ValidationError("event_type", "is unknown")
        body = _validate_body(event_type, data["body"])
        return cls(require_nonnegative_integer(data["sequence"], "sequence"), event_type,
                   require_identifier(data["run_id"], "run_id"), _timestamp(data["occurred_at"], "occurred_at"), MappingProxyType(body))

    def to_json(self) -> dict[str, Any]:
        return {"schema_version": 3, "record_type": "research_event", "sequence": self.sequence,
                "event_type": self.event_type, "run_id": self.run_id, "occurred_at": self.occurred_at,
                "body": dict(self.body)}


def _validate_body(kind: str, payload: Any) -> dict[str, Any]:
    data = require_object(payload, f"{kind}.body")
    if kind == "research_initialized":
        require_exact_fields(data, kind, {"request"}); request = ResearchRequest.from_json(data["request"]); return {"request": request.to_json()}
    if kind == "provider_configured":
        keys = {"executable", "version", "model_requested", "effort_requested", "control_argv", "prompt_version"}; require_exact_fields(data, kind, keys)
        if not isinstance(data["control_argv"], list): raise ValidationError("control_argv", "must be an array")
        return {key: require_string(data[key], f"{kind}.{key}") for key in keys if key != "control_argv"} | {"control_argv": [require_string(x, "control_argv[]") for x in data["control_argv"]]}
    if kind == "decision_recorded":
        require_exact_fields(data, kind, {"decision_id", "kind", "reason_code", "action", "details"})
        decision_kind = require_string(data["kind"], "decision.kind")
        if decision_kind not in {"worker", "tool", "gate", "finish", "noop"}: raise ValidationError("decision.kind", "is invalid")
        action = None if data["action"] is None else validate_action(data["action"])
        if (decision_kind in {"worker", "tool"}) != (action is not None): raise ValidationError("decision.action", "must match decision kind")
        return {"decision_id": require_identifier(data["decision_id"], "decision_id"), "kind": decision_kind, "reason_code": require_string(data["reason_code"], "reason_code"), "action": action, "details": validate_decision_details(data["details"])}
    if kind == "action_intended":
        require_exact_fields(data, kind, {"action_id", "packet", "packet_sha256"})
        packet = require_object(data["packet"], "packet")
        return {"action_id": require_identifier(data["action_id"], "action_id"), "packet": dict(packet), "packet_sha256": _sha(data["packet_sha256"], "packet_sha256")}
    if kind == "action_finished":
        keys = {"action_id", "outcome", "exit_code", "stdout_sha256", "stderr_sha256", "result", "error", "telemetry"}; require_exact_fields(data, kind, keys)
        outcome = require_string(data["outcome"], "outcome")
        if outcome not in {"succeeded", "failed", "timed_out", "cancelled", "launch_failed", "protocol_error"}: raise ValidationError("outcome", "is invalid")
        exit_code = data["exit_code"]
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)): raise ValidationError("exit_code", "must be an integer or null")
        result = data["result"]; error = _nullable_string(data["error"], "error")
        if outcome == "succeeded":
            if exit_code != 0 or result is None or error is not None: raise ValidationError("action_finished", "success requires exit code zero, result, and null error")
        elif result is not None: raise ValidationError("result", "must be null for a non-success outcome")
        return {"action_id": require_identifier(data["action_id"], "action_id"), "outcome": outcome, "exit_code": exit_code, "stdout_sha256": _sha(data["stdout_sha256"], "stdout_sha256"), "stderr_sha256": _sha(data["stderr_sha256"], "stderr_sha256"), "result": result, "error": error, "telemetry": _telemetry(data["telemetry"])}
    if kind == "gate_opened":
        require_exact_fields(data, kind, {"gate_id", "kind", "questions", "allowed_response", "resume_token"})
        questions, allowed = data["questions"], data["allowed_response"]
        if not isinstance(questions, list) or not 1 <= len(questions) <= 4: raise ValidationError("questions", "must contain one to four strings")
        if not isinstance(allowed, list) or not allowed: raise ValidationError("allowed_response", "must be a nonempty array")
        return {"gate_id": require_identifier(data["gate_id"], "gate_id"), "kind": require_string(data["kind"], "gate.kind"), "questions": [require_string(x, "questions[]") for x in questions], "allowed_response": [require_string(x, "allowed_response[]") for x in allowed], "resume_token": _sha(data["resume_token"], "resume_token")}
    if kind == "gate_answered":
        require_exact_fields(data, kind, {"gate_id", "response_id", "response"})
        return {"gate_id": require_identifier(data["gate_id"], "gate_id"), "response_id": require_identifier(data["response_id"], "response_id"), "response": data["response"]}
    keys = {"status", "assessment", "reason", "report_markdown", "log_markdown"}; require_exact_fields(data, kind, keys)
    status = require_string(data["status"], "status")
    if status not in TERMINAL: raise ValidationError("status", "must be terminal")
    return {"status": status, "assessment": data["assessment"], "reason": require_string(data["reason"], "reason"), "report_markdown": require_string(data["report_markdown"], "report_markdown", allow_empty=True), "log_markdown": require_string(data["log_markdown"], "log_markdown", allow_empty=True)}


@dataclass(frozen=True)
class ResearchSnapshot:
    request: ResearchRequest
    initialized_at: str
    sequence: int
    status: str
    provider_config: Mapping[str, Any] | None
    decisions: tuple[Mapping[str, Any], ...]
    actions: Mapping[str, Mapping[str, Any]]
    results: Mapping[str, Any]
    sources: Mapping[str, Any]
    tool_results: Mapping[str, Any]
    pending_action_id: str | None
    pending_gate: Mapping[str, Any] | None
    model_calls_used: int
    tool_calls_used: int
    branches_started: int
    repairs_started: int
    latest_draft_id: str | None
    latest_audit_id: str | None
    final_assessment: Any
    reason: str | None

    def state_json(self) -> dict[str, Any]:
        return {"schema_version": 3, "record_type": "research_state", "run_id": self.request.run_id, "initialized_at": self.initialized_at, "sequence": self.sequence, "status": self.status, "pending_action_id": self.pending_action_id, "pending_gate_id": None if self.pending_gate is None else self.pending_gate["gate_id"], "model_calls_used": self.model_calls_used, "tool_calls_used": self.tool_calls_used, "branches_started": self.branches_started, "repairs_started": self.repairs_started, "latest_draft_id": self.latest_draft_id, "latest_audit_id": self.latest_audit_id, "final_assessment": self.final_assessment, "reason": self.reason, "report_path": "report.md" if self.status in TERMINAL else None}


def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ...]) -> ResearchSnapshot:
    if not events: raise ValueError("history requires initialization")
    request: ResearchRequest | None = None; initialized_at = ""; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; gate_ids: set[str] = set(); response_digests: dict[str, str] = {}; run_id = events[0].run_id; previous_time = ""
    for expected, item in enumerate(events, 1):
        if item.sequence != expected or item.run_id != run_id or (previous_time and item.occurred_at < previous_time): raise ValueError("events must be contiguous and chronological")
        previous_time = item.occurred_at
        if terminal is not None: raise ValueError("event after terminal")
        if item.event_type == "research_initialized":
            if request is not None or expected != 1: raise ValueError("initialization must occur once first")
            request = ResearchRequest.from_json(item.body["request"]); initialized_at = item.occurred_at
            if request.run_id != run_id: raise ValueError("request run_id mismatch")
        elif request is None: raise ValueError("initialization required")
        elif item.event_type == "decision_recorded":
            action = item.body["action"]
            if item.body["kind"] == "noop": raise ValueError("noop decisions are not persisted")
            if action is not None:
                action_id = action["id"]
                if action_id in actions or pending is not None: raise ValueError("duplicate or overlapping action")
                if any(dep not in results for dep in action["dependencies"]): raise ValueError("action dependency is unfinished")
                actions[action_id] = action; pending = action_id
            decisions.append(item.body)
        elif item.event_type == "action_intended":
            action_id = item.body["action_id"]
            if pending != action_id or action_id in intended: raise ValueError("intent without matching decision")
            if hashlib.sha256(canonical_json_bytes(item.body["packet"])).hexdigest() != item.body["packet_sha256"]: raise ValueError("packet hash mismatch")
            intended[action_id] = item.body
        elif item.event_type == "action_finished":
            action_id = item.body["action_id"]
            if pending != action_id or action_id not in intended: raise ValueError("finish without intent or wrong action")
            action = actions[action_id]
            if item.body["outcome"] == "succeeded":
                try:
                    result = (validate_result(action["role"], item.body["result"])
                              if action["kind"] == "worker" else validate_tool_result(action["role"], item.body["result"]))
                except ValidationError as exc:
                    raise ValueError("successful result does not match action") from exc
                results[action_id] = result
            pending = None
        elif item.event_type == "gate_opened":
            if gate is not None or item.body["gate_id"] in gate_ids: raise ValueError("duplicate gate")
            gate = item.body
            gate_ids.add(item.body["gate_id"])
        elif item.event_type == "gate_answered":
            digest = hashlib.sha256(canonical_json_bytes(item.body["response"])).hexdigest()
            response_key = f"{item.body['gate_id']}\0{item.body['response_id']}"
            prior = response_digests.get(response_key)
            if prior is not None:
                if prior != digest: raise ValueError("response ID payload conflict")
                continue
            if gate is None or gate["gate_id"] != item.body["gate_id"]: raise ValueError("unknown or closed gate")
            response_digests[response_key] = digest
            gate = None
        elif item.event_type == "research_finished":
            if pending is not None: raise ValueError("finish while action pending")
            terminal = item.body
    if request is None: raise ValueError("initialization required")
    status = terminal["status"] if terminal else ("awaiting_human" if gate else ("running" if pending else "ready"))
    model = sum(1 for action_id in intended if actions[action_id]["kind"] == "worker"); tools = len(intended) - model
    return ResearchSnapshot(request, initialized_at, len(events), status, None, tuple(decisions), MappingProxyType(actions), MappingProxyType(results), MappingProxyType({}), MappingProxyType({}), pending, gate, model, tools, sum(1 for a in actions.values() if a["branch"] in {"a", "b", "c"}), 0, None, None, None if terminal is None else terminal["assessment"], None if terminal is None else terminal["reason"])
