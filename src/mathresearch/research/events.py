"""Strict, pure version-three research event validation and replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from mathresearch.contracts.research_request import ResearchRequest, SourceInput
from mathresearch.contracts.validation import ValidationError, require_exact_fields, require_identifier, require_nonnegative_integer, require_object, require_string
from mathresearch.research.contracts import validate_action, validate_decision_details, validate_result


EVENT_TYPES = frozenset({"research_initialized", "provider_configured", "decision_recorded", "action_intended", "action_finished", "gate_opened", "gate_answered", "research_finished", "provider_attempt_intended", "provider_attempt_finished"})
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


def validate_tool_result(operation: str, value: Any, *, requested_source: Mapping[str, Any] | None = None,
                         requested_arguments: Mapping[str, Any] | None = None,
                         tool_id: str | None = None, request: Mapping[str, Any] | None = None,
                         authorized_urls: set[str] | None = None) -> dict[str, Any]:
    """Validate the durable ToolReceipt against the completed coordinator action."""
    if tool_id is None or request is None:
        raise ValidationError("tool result", "requires coordinator tool ID and request")
    if request.get("operation") != operation:
        raise ValidationError("tool result.request", "operation differs from action")
    from mathresearch.research.broker import validate_tool_receipt
    checked = validate_tool_receipt(value, tool_id=tool_id, request=request,
                                    requested_source=requested_source,
                                    authorized_urls=authorized_urls)
    if len(canonical_json_bytes(checked)) > 65536:
        raise ValidationError("tool result", "canonical JSON must be at most 65536 bytes")
    return checked


def _gate_source_inputs(response: Any, *, gate_id: str, response_id: str,
                        fetch_sources: bool, allowed_response: tuple[str, ...]) -> tuple[SourceInput, ...]:
    """Validate only the gate fields needed to authorize added source descriptors."""
    data = require_object(response, "gate response")
    require_exact_fields(data, "gate response", {"schema_version", "record_type", "gate_id",
                         "response_id", "decision", "text", "sources"})
    if data["schema_version"] != 3 or data["record_type"] != "research_gate_response":
        raise ValidationError("gate response", "must be a version-three research gate response")
    if data["gate_id"] != gate_id or data["response_id"] != response_id:
        raise ValidationError("gate response", "identifiers must match the answered gate event")
    if data["decision"] not in {"supply", "continue_limited", "cancel"} or data["decision"] not in allowed_response:
        raise ValidationError("gate response.decision", "is not accepted by the open gate")
    sources = data["sources"]
    if not isinstance(sources, list) or len(sources) > 6:
        raise ValidationError("gate response.sources", "must be an array with at most 6 entries")
    text = data["text"]
    if text is not None and (not isinstance(text, str) or not text or len(text) > 16000):
        raise ValidationError("gate response.text", "must be null or a 1..16000 character string")
    if data["decision"] != "supply":
        if text is not None or sources:
            raise ValidationError("gate response.sources", "require a supply decision")
        return ()
    if text is None and not sources:
        raise ValidationError("gate response", "supply requires text or sources")
    parsed = tuple(SourceInput.from_json(item, field=f"gate response.sources[{index}]",
                                      fetch_sources=fetch_sources)
                 for index, item in enumerate(sources))
    if len({item.id for item in parsed}) != len(parsed):
        raise ValidationError("gate response.sources", "source IDs must be unique")
    return parsed


@dataclass(frozen=True)
class ResearchEvent:
    sequence: int
    event_type: str
    run_id: str
    occurred_at: str
    body: Mapping[str, Any]
    schema_version: int = 3

    @classmethod
    def from_json(cls, payload: Any) -> "ResearchEvent":
        data = require_object(payload, "research_event")
        require_exact_fields(data, "research_event", {"schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "body"})
        version = data["schema_version"]
        if version not in {3, 4} or data["record_type"] != "research_event":
            raise ValidationError("research_event", "must be a version-three or version-four research event")
        event_type = require_string(data["event_type"], "event_type")
        if event_type not in EVENT_TYPES or (version == 3 and event_type.startswith("provider_attempt_")):
            raise ValidationError("event_type", "is unknown for this event version")
        body = _validate_body(event_type, data["body"])
        return cls(require_nonnegative_integer(data["sequence"], "sequence"), event_type,
                   require_identifier(data["run_id"], "run_id"), _timestamp(data["occurred_at"], "occurred_at"), MappingProxyType(body), version)

    def to_json(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "record_type": "research_event", "sequence": self.sequence,
                "event_type": self.event_type, "run_id": self.run_id, "occurred_at": self.occurred_at,
                "body": dict(self.body)}


def _validate_body(kind: str, payload: Any) -> dict[str, Any]:
    data = require_object(payload, f"{kind}.body")
    if kind == "research_initialized":
        require_exact_fields(data, kind, {"request"}); request = ResearchRequest.from_json(data["request"]); return {"request": request.to_json()}
    if kind == "provider_configured":
        keys = {"executable", "version", "model_requested", "effort_requested", "control_argv", "prompt_version"}; require_exact_fields(data, kind, keys)
        if not isinstance(data["control_argv"], list): raise ValidationError("control_argv", "must be an array")
        checked = {key: require_string(data[key], f"{kind}.{key}") for key in keys if key != "control_argv"} | {"control_argv": [require_string(x, "control_argv[]") for x in data["control_argv"]]}
        if not checked["executable"] or not checked["version"]: raise ValidationError(kind, "executable and version must be nonempty")
        if checked["effort_requested"] not in {"medium", "high"}: raise ValidationError("effort_requested", "must be medium or high")
        if checked["prompt_version"] not in {"research-v1", "research-v2", "research-v3", "research-v4", "research-v5"}: raise ValidationError("prompt_version", "is unsupported")
        return checked
    if kind == "decision_recorded":
        require_exact_fields(data, kind, {"decision_id", "kind", "reason_code", "action", "details"})
        decision_kind = require_string(data["kind"], "decision.kind")
        if decision_kind not in {"worker", "tool", "gate", "finish", "noop"}: raise ValidationError("decision.kind", "is invalid")
        action = None if data["action"] is None else validate_action(data["action"])
        if (decision_kind in {"worker", "tool"}) != (action is not None): raise ValidationError("decision.action", "must match decision kind")
        if action is not None and action["kind"] != decision_kind:
            raise ValidationError("decision.action.kind", "must match decision kind")
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
    if kind == "provider_attempt_intended":
        keys = {"attempt_id", "action_id", "parent_attempt_id", "attempt_kind", "retry_reason", "prompt_version", "prompt_sha256", "schema_sha256", "input_bytes"}
        require_exact_fields(data, kind, keys)
        parent = None if data["parent_attempt_id"] is None else require_identifier(
            data["parent_attempt_id"], "parent_attempt_id")
        attempt_kind = require_string(data["attempt_kind"], "attempt_kind")
        if attempt_kind not in {"initial", "structural_repair"}:
            raise ValidationError("attempt_kind", "is invalid")
        prompt_version = require_string(data["prompt_version"], "prompt_version")
        if prompt_version not in {"research-v1", "research-v2", "research-v3", "research-v4", "research-v5", "structural-repair-v2", "structural-repair-v3"}:
            raise ValidationError("prompt_version", "is invalid")
        return {"attempt_id": require_identifier(data["attempt_id"], "attempt_id"),
                "action_id": require_identifier(data["action_id"], "action_id"),
                "parent_attempt_id": parent, "attempt_kind": attempt_kind,
                "retry_reason": _nullable_string(data["retry_reason"], "retry_reason"),
                "prompt_version": prompt_version,
                "prompt_sha256": _sha(data["prompt_sha256"], "prompt_sha256"),
                "schema_sha256": _sha(data["schema_sha256"], "schema_sha256"),
                "input_bytes": require_nonnegative_integer(data["input_bytes"], "input_bytes")}
    if kind == "provider_attempt_finished":
        keys = {"attempt_id", "outcome", "exit_code", "stdout_sha256", "stderr_sha256", "error", "telemetry", "failure_class", "session_id_marker_count"}
        # repair_review was added within v4; accept earlier v4 journal entries.
        if frozenset(data) not in {frozenset(keys), frozenset(keys | {"repair_review"})}:
            require_exact_fields(data, kind, keys | {"repair_review"})
        outcome = require_string(data["outcome"], "outcome")
        if outcome not in {"succeeded", "failed", "timed_out", "cancelled", "launch_failed", "protocol_error"}:
            raise ValidationError("outcome", "is invalid")
        exit_code = data["exit_code"]
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
            raise ValidationError("exit_code", "must be an integer or null")
        failure_class = _nullable_string(data["failure_class"], "failure_class")
        if failure_class not in {None, "provider_usage_limit", "provider_failure", "timeout", "protocol_error", "other"}:
            raise ValidationError("failure_class", "is invalid")
        review = data.get("repair_review")
        if review is not None:
            review = require_object(review, "repair_review")
            require_exact_fields(review, "repair_review", {"rejected_payload", "corrected_payload", "validation_errors", "change_explanation", "diff"})
            if not isinstance(review["rejected_payload"], Mapping):
                raise ValidationError("repair_review.rejected_payload", "must be an object")
            if review["corrected_payload"] is not None and not isinstance(review["corrected_payload"], Mapping):
                raise ValidationError("repair_review.corrected_payload", "must be an object or null")
            if (not isinstance(review["validation_errors"], Mapping) or
                    not isinstance(review["change_explanation"], str) or not review["change_explanation"] or
                    not isinstance(review["diff"], list)):
                raise ValidationError("repair_review", "must contain validation errors and a diff array")
            for index, change in enumerate(review["diff"]):
                change = require_object(change, f"repair_review.diff[{index}]")
                require_exact_fields(change, f"repair_review.diff[{index}]", {"path", "before", "after"})
                require_string(change["path"], f"repair_review.diff[{index}].path", allow_empty=False)
            try:
                if len(canonical_json_bytes(dict(review))) > 262144:
                    raise ValidationError("repair_review", "must be at most 262144 UTF-8 bytes")
            except (TypeError, ValueError) as exc:
                raise ValidationError("repair_review", "must contain JSON-compatible values") from exc
            review = dict(review)
        return {"attempt_id": require_identifier(data["attempt_id"], "attempt_id"),
                "outcome": outcome, "exit_code": exit_code,
                "stdout_sha256": _sha(data["stdout_sha256"], "stdout_sha256"),
                "stderr_sha256": _sha(data["stderr_sha256"], "stderr_sha256"),
                "error": _nullable_string(data["error"], "error"),
                "telemetry": _telemetry(data["telemetry"]), "failure_class": failure_class,
                "session_id_marker_count": require_nonnegative_integer(data["session_id_marker_count"], "session_id_marker_count"),
                "repair_review": review}
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
    additional_user_input: tuple[Mapping[str, str], ...]
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
    source_descriptors: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    outcomes: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    action_telemetry: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    finished_at: str | None = None
    intended_action_ids: frozenset[str] = frozenset()
    gate_responses: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # Canonical bytes preserve the exact packet attached to each durable intent.
    intent_packets: Mapping[str, bytes] = field(default_factory=dict)
    attempts: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    pending_attempt_id: str | None = None

    def state_json(self) -> dict[str, Any]:
        attempt_count = len(self.attempts) + (1 if self.pending_attempt_id else 0)
        return {"schema_version": 4, "record_type": "research_state", "run_id": self.request.run_id, "initialized_at": self.initialized_at, "sequence": self.sequence, "status": self.status, "pending_action_id": self.pending_action_id, "pending_gate_id": None if self.pending_gate is None else self.pending_gate["gate_id"], "model_calls_used": self.model_calls_used, "tool_calls_used": self.tool_calls_used, "branches_started": self.branches_started, "repairs_started": self.repairs_started, "latest_draft_id": self.latest_draft_id, "latest_audit_id": self.latest_audit_id, "final_assessment": self.final_assessment, "reason": self.reason, "report_path": "report.md" if self.status in TERMINAL else None, "pending_attempt_id": self.pending_attempt_id, "provider_attempt_count": attempt_count, "legacy_action_call_count": max(0, self.model_calls_used - attempt_count), "call_count_basis": "provider_attempt_intents_with_legacy_v3_action_fallback"}


def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ...]) -> ResearchSnapshot:
    if not events: raise ValueError("history requires initialization")
    request: ResearchRequest | None = None; initialized_at = ""; provider_config: Mapping[str, Any] | None = None; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; source_descriptors: dict[str, dict[str, Any]] = {}; source_records: dict[str, Mapping[str, Any]] = {}; tool_results: dict[str, Mapping[str, Any]] = {}; outcomes: dict[str, Mapping[str, Any]] = {}; action_telemetry: dict[str, Mapping[str, Any]] = {}; gate_responses: dict[str, Mapping[str, Any]] = {}; additional_user_input: list[Mapping[str, str]] = []; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; finished_at: str | None = None; gate_ids: set[str] = set(); response_digests: dict[str, str] = {}; attempts: dict[str, Mapping[str, Any]] = {}; attempt_intents: dict[str, Mapping[str, Any]] = {}; pending_attempt: str | None = None; run_id = events[0].run_id; previous_time = ""
    for expected, item in enumerate(events, 1):
        if item.sequence != expected or item.run_id != run_id or (previous_time and item.occurred_at < previous_time): raise ValueError("events must be contiguous and chronological")
        previous_time = item.occurred_at
        if terminal is not None: raise ValueError("event after terminal")
        ambiguous_finish_decision = (item.event_type == "decision_recorded" and
            item.body.get("kind") == "finish" and
            item.body.get("reason_code") == "ambiguous_execution" and
            item.body.get("details", {}).get("finish_status") == "blocked")
        if (pending_attempt is not None and item.event_type not in {
                "provider_attempt_finished", "research_finished"} and
                not ambiguous_finish_decision):
            raise ValueError("only provider attempt completion or an ambiguous terminal stop may follow an attempt intent")
        if item.event_type == "research_initialized":
            if request is not None or expected != 1: raise ValueError("initialization must occur once first")
            request = ResearchRequest.from_json(item.body["request"]); initialized_at = item.occurred_at
            if request.run_id != run_id: raise ValueError("request run_id mismatch")
            source_descriptors = {source.id: source.to_json() for source in request.sources}
            for source in request.sources:
                if source.kind == "text":
                    digest = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
                    source_records[source.id] = MappingProxyType({"id": source.id, "origin": "user_text", "title": source.title,
                        "url": None, "published_at": source.published_at, "captured_at": item.occurred_at,
                        "text": source.text, "sha256": digest, "retrieval_receipt": None})
        elif request is None: raise ValueError("initialization required")
        elif item.event_type == "provider_configured":
            config = item.body
            if provider_config is not None or any(action_id in intended and action["kind"] == "worker" for action_id, action in actions.items()):
                raise ValueError("provider configuration must occur once before the first worker intent")
            if config["model_requested"] != request.provider["model"] or config["effort_requested"] != request.provider["reasoning_effort"]:
                raise ValueError("provider configuration differs from immutable request")
            provider_config = config
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
            if actions[action_id]["kind"] == "worker" and provider_config is None:
                raise ValueError("worker intent requires prior provider configuration")
            if hashlib.sha256(canonical_json_bytes(item.body["packet"])).hexdigest() != item.body["packet_sha256"]: raise ValueError("packet hash mismatch")
            if actions[action_id]["kind"] == "worker":
                packet_tools = item.body["packet"].get("tool_results", {})
                if not isinstance(packet_tools, Mapping):
                    raise ValueError("worker packet tool receipt catalog must be an object")
                for tool_id, receipt in packet_tools.items():
                    committed = tool_results.get(tool_id)
                    if committed is None or canonical_json_bytes(receipt) != canonical_json_bytes(committed):
                        raise ValueError("worker packet contains a receipt not committed before intent")
            intended[action_id] = item.body
        elif item.event_type == "action_finished":
            action_id = item.body["action_id"]
            if pending != action_id or action_id not in intended or pending_attempt is not None: raise ValueError("finish without intent, pending provider attempt, or wrong action")
            action = actions[action_id]
            if (action["kind"] == "worker" and item.body["outcome"] != "launch_failed" and
                    any(event.schema_version >= 4 for event in events if event.event_type == "action_intended" and event.body["action_id"] == action_id) and
                    not any(value["action_id"] == action_id for value in attempt_intents.values())):
                raise ValueError("version-four worker action must have a provider attempt intent")
            outcomes[action_id] = MappingProxyType({"outcome": item.body["outcome"], "exit_code": item.body["exit_code"], "error": item.body["error"]})
            action_telemetry[action_id] = MappingProxyType(dict(item.body["telemetry"]))
            if item.body["outcome"] == "succeeded":
                try:
                    if action["kind"] == "worker":
                        prompt_version = action.get("payload", {}).get("prompt_version", "research-v2")
                        result_version = prompt_version
                        result = validate_result(action["role"], item.body["result"],
                            prompt_version=result_version)
                    else:
                        requested_id = action["payload"]["arguments"].get("source_id")
                        requested_source = source_descriptors.get(requested_id) if isinstance(requested_id, str) else None
                        result = validate_tool_result(action["role"], item.body["result"],
                                                      requested_source=requested_source,
                                                      requested_arguments=action["payload"]["arguments"],
                                                      tool_id=action_id,
                                                      request={"id": action["payload"]["id"], "operation": action["payload"]["operation"], "arguments": action["payload"]["arguments"]},
                                                      authorized_urls={descriptor["url"] for descriptor in source_descriptors.values()
                                                                       if descriptor.get("kind") == "url"})
                except ValidationError as exc:
                    raise ValueError("successful result does not match action") from exc
                results[action_id] = result
                if action["kind"] == "tool":
                    tool_results[action_id] = result
                    if action["role"] == "fetch_source" and result["status"] == "succeeded":
                        captured = result["result"]["source"]
                        source_records[captured["id"]] = MappingProxyType(dict(captured))
            pending = None
        elif item.event_type == "provider_attempt_intended":
            body = item.body
            attempt_id, action_id = body["attempt_id"], body["action_id"]
            action_intent_version = next((event.schema_version for event in events if event.event_type == "action_intended" and event.body["action_id"] == action_id), None)
            if action_intent_version != 4 or pending != action_id or action_id not in intended or actions[action_id]["kind"] != "worker":
                raise ValueError("provider attempt requires a pending version-four worker action")
            if attempt_id in attempt_intents or pending_attempt is not None:
                raise ValueError("duplicate or overlapping provider attempt")
            parent_id = body["parent_attempt_id"]
            if body["attempt_kind"] == "initial":
                if parent_id is not None or any(value["action_id"] == action_id for value in attempt_intents.values()):
                    raise ValueError("initial attempt must be the first attempt for its action")
            elif (parent_id not in attempts or attempts[parent_id]["action_id"] != action_id or
                  attempts[parent_id].get("failure_class") != "protocol_error"):
                raise ValueError("repair attempt must follow a failed attempt for the same action")
            attempt_intents[attempt_id] = body
            pending_attempt = attempt_id
        elif item.event_type == "provider_attempt_finished":
            attempt_id = item.body["attempt_id"]
            if pending_attempt != attempt_id or attempt_id not in attempt_intents:
                raise ValueError("provider attempt finish without matching intent")
            attempts[attempt_id] = MappingProxyType(dict(item.body) | dict(attempt_intents[attempt_id]))
            pending_attempt = None
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
            try:
                additions = _gate_source_inputs(item.body["response"], gate_id=item.body["gate_id"],
                                                response_id=item.body["response_id"],
                                                fetch_sources=request.capabilities["fetch_sources"],
                                                allowed_response=tuple(gate["allowed_response"]))
            except ValidationError as exc:
                raise ValueError("invalid gate source authorization") from exc
            if len(source_descriptors) + len(additions) > 6:
                raise ValueError("source descriptor limit exceeded")
            for source in additions:
                if source.id in source_descriptors:
                    raise ValueError("gate source ID replaces an accepted descriptor")
                source_descriptors[source.id] = source.to_json()
                if source.kind == "text":
                    digest = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
                    source_records[source.id] = MappingProxyType({"id": source.id, "origin": "user_text", "title": source.title,
                        "url": None, "published_at": source.published_at, "captured_at": item.occurred_at,
                        "text": source.text, "sha256": digest, "retrieval_receipt": None})
            text = item.body["response"].get("text") if isinstance(item.body["response"], Mapping) else None
            if text is not None:
                text_source_id = f"gate-text-{item.body['gate_id']}"
                if text_source_id in source_records:
                    raise ValueError("gate text source ID already exists")
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                source_records[text_source_id] = MappingProxyType({"id": text_source_id, "origin": "user_text",
                    "title": f"User response {item.body['gate_id']}", "url": None, "published_at": None,
                    "captured_at": item.occurred_at, "text": text, "sha256": digest, "retrieval_receipt": None})
                additional_user_input.append(MappingProxyType({"gate_id": item.body["gate_id"], "response_id": item.body["response_id"], "text": text}))
            response_digests[response_key] = digest
            gate_responses[item.body["gate_id"]] = MappingProxyType({"response_id": item.body["response_id"],
                "response": MappingProxyType(dict(item.body["response"]))})
            gate = None
        elif item.event_type == "research_finished":
            pending_is_safe_stop = (pending is not None and gate is None and (
                (item.body["status"] == "blocked" and item.body["reason"] == "ambiguous_execution") or
                (item.body["status"] == "budget_exhausted" and pending not in intended)))
            pending_attempt_is_safe_stop = pending_attempt is not None and item.body["status"] == "blocked" and item.body["reason"] == "ambiguous_execution"
            if (pending is not None and not pending_is_safe_stop and not pending_attempt_is_safe_stop) or gate is not None:
                raise ValueError("finish while action or gate pending")
            terminal = item.body
            finished_at = item.occurred_at
    if request is None: raise ValueError("initialization required")
    status = terminal["status"] if terminal else ("awaiting_human" if gate else ("running" if pending else "ready"))
    legacy_worker_ids = {item.body["action_id"] for item in events
                         if item.event_type == "action_intended" and item.schema_version == 3
                         and actions[item.body["action_id"]]["kind"] == "worker"}
    legacy_model = sum(1 for action_id in legacy_worker_ids
                       if not any(value["action_id"] == action_id for value in attempt_intents.values()))
    model = len(attempt_intents) + legacy_model; tools = len(intended) - sum(1 for action_id in intended if actions[action_id]["kind"] == "worker")
    completed = [(action_id, action) for action_id, action in actions.items() if action_id in results]
    draft_ids = [action_id for action_id, action in completed if action["role"] in {"answer", "branch", "synthesize", "revise"}]
    audit_ids = [action_id for action_id, action in completed if action["role"] == "audit"]
    latest_draft = draft_ids[-1] if draft_ids else None; latest_audit = audit_ids[-1] if audit_ids else None
    repair_rounds = {action["round"] for action_id, action in actions.items() if action["round"] > 0 and action_id in results}
    repair_rounds.update(decision["details"]["round"] for decision in decisions if decision["details"]["round"] > 0)
    return ResearchSnapshot(request, initialized_at, len(events), status, provider_config, tuple(decisions), MappingProxyType(actions), MappingProxyType(results), MappingProxyType(source_records), MappingProxyType(tool_results), tuple(additional_user_input), pending, gate, model, tools, sum(1 for a in actions.values() if a["branch"] in {"a", "b", "c"}), len(repair_rounds), latest_draft, latest_audit, None if terminal is None else terminal["assessment"], None if terminal is None else terminal["reason"], MappingProxyType(source_descriptors), MappingProxyType(outcomes), MappingProxyType(action_telemetry), finished_at, frozenset(intended), MappingProxyType(gate_responses), MappingProxyType({action_id: canonical_json_bytes(item["packet"]) for action_id, item in intended.items()}), MappingProxyType(attempts), pending_attempt)
