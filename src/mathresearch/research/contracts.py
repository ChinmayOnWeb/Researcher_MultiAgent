"""Provider-facing strict schemas and semantic validation for research results."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from mathresearch.contracts.validation import (
    ValidationError, require_boolean, require_exact_fields, require_identifier,
    require_nonnegative_integer, require_object, require_string,
)


def obj(properties: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties), "required": list(properties), "additionalProperties": False}


def arr(items: dict[str, Any], max_items: int) -> dict[str, Any]:
    return {"type": "array", "items": items, "maxItems": max_items}


def enum(values: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def text(max_length: int) -> dict[str, Any]:
    return {"type": "string", "maxLength": max_length}


_ID = text(64)
_CITATION = obj({"source_id": _ID, "start": {"type": "integer", "minimum": 0},
                 "end": {"type": "integer", "minimum": 0}, "quote": text(1200)})
_TOOL_ARGUMENTS = {"oneOf": [
    obj({"source_id": _ID}),
    obj({"n": {"type": "integer", "minimum": 0}}),
    obj({"lhs": arr({"type": "integer", "minimum": 0}, 13), "rhs": arr({"type": "integer", "minimum": 0}, 13),
         "lo": {"type": "integer", "minimum": 0}, "hi": {"type": "integer", "minimum": 0}}),
    obj({"lo": {"type": "integer", "minimum": 0}, "hi": {"type": "integer", "minimum": 0},
         "parity": enum(("odd", "even", "all"))}),
]}
_TOOL_REQUEST = obj({"id": _ID, "operation": enum(("fetch_source", "check_integer", "check_polynomial", "search_perfect")),
                     "arguments": _TOOL_ARGUMENTS})
_CLAIM = obj({"id": _ID, "statement": text(4000), "critical": {"type": "boolean"},
              "kind": enum(("definition", "assumption", "source_assertion", "deduction", "model_knowledge", "conjecture")),
              "citations": arr(_CITATION, 4), "step_ids": arr(_ID, 8), "tool_ids": arr(_ID, 4), "depends_on": arr(_ID, 8)})
_STEP = obj({"id": _ID, "statement": text(4000), "justification": text(4000), "depends_on": arr(_ID, 8), "citations": arr(_CITATION, 4)})
_APPROACH = obj({"id": _ID, "description": text(4000), "outcome": enum(("candidate", "rejected", "incomplete")), "reason": text(4000)})
_DRAFT = obj({"answer": text(12000), "question_status": enum(("answered", "open_in_sources", "unresolved", "refuted")),
              "claims": arr(_CLAIM, 12), "proof_steps": arr(_STEP, 24), "approaches": arr(_APPROACH, 3),
              "open_questions": arr(text(4000), 8), "tool_requests": arr(_TOOL_REQUEST, 4), "change_log": arr(text(4000), 8)})
_FRAME = obj({"task_type": enum(("proof", "status", "exploration")), "deliverables": arr(text(4000), 6),
              "subquestions": arr(text(4000), 6), "missing_inputs": arr(text(4000), 4),
              "proposed_checks": arr(_TOOL_REQUEST, 4), "source_needs": arr(text(4000), 4)})
_AUDIT = obj({"checks": arr(obj({"claim_id": _ID, "verdict": enum(("supported", "unsupported", "contradicted", "conditional")),
                                  "reasoning": text(4000), "checked_step_ids": arr(_ID, 24)}), 12),
              "challenges": arr(obj({"claim_id": _ID, "attack": text(4000), "result": text(4000),
                                      "outcome": enum(("survives", "fails", "not_tested")), "tool_ids": arr(_ID, 4)}), 12),
              "missing_evidence": arr(text(4000), 8), "tool_requests": arr(_TOOL_REQUEST, 4),
              "recommended_action": enum(("finish", "revise", "additional_branch", "request_sources"))})


def result_schema(role: str) -> dict[str, Any]:
    """Return a defensive provider schema for one worker role."""
    if role in {"answer", "branch", "synthesize", "revise"}:
        return copy.deepcopy(_DRAFT)
    if role == "frame":
        return copy.deepcopy(_FRAME)
    if role == "audit":
        return copy.deepcopy(_AUDIT)
    raise ValidationError("role", "must be a research worker role")


def _validate_shape(value: Any, schema: Mapping[str, Any], field: str) -> Any:
    if "oneOf" in schema:
        matches: list[Any] = []
        for candidate in schema["oneOf"]:
            try:
                matches.append(_validate_shape(value, candidate, field))
            except ValidationError:
                continue
        if len(matches) != 1:
            raise ValidationError(field, "must match exactly one permitted object shape")
        return matches[0]
    kind = schema["type"]
    if kind == "object":
        data = require_object(value, field)
        expected = set(schema["properties"])
        require_exact_fields(data, field, expected)
        return {key: _validate_shape(data[key], schema["properties"][key], f"{field}.{key}") for key in schema["properties"]}
    if kind == "array":
        if not isinstance(value, list):
            raise ValidationError(field, "must be an array")
        if len(value) > schema["maxItems"]:
            raise ValidationError(field, f"must have at most {schema['maxItems']} items")
        return [_validate_shape(item, schema["items"], f"{field}[{index}]") for index, item in enumerate(value)]
    if kind == "string":
        item = require_string(value, field)
        if "maxLength" in schema and len(item) > schema["maxLength"]:
            raise ValidationError(field, f"must be at most {schema['maxLength']} characters")
        if "enum" in schema and item not in schema["enum"]:
            raise ValidationError(field, f"must be one of {', '.join(schema['enum'])}")
        return item
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(field, "must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValidationError(field, f"must be at least {schema['minimum']}")
        return value
    if kind == "boolean":
        return require_boolean(value, field)
    raise RuntimeError(f"unsupported schema type {kind}")


def _validate_tool_request(request: dict[str, Any], field: str) -> None:
    require_identifier(request["id"], f"{field}.id")
    arguments = request["arguments"]
    operation = request["operation"]
    expected: dict[str, set[str]] = {
        "fetch_source": {"source_id"}, "check_integer": {"n"},
        "check_polynomial": {"lhs", "rhs", "lo", "hi"}, "search_perfect": {"lo", "hi", "parity"},
    }
    require_exact_fields(require_object(arguments, f"{field}.arguments"), f"{field}.arguments", expected[operation])


def _unique_ids(items: list[dict[str, Any]], field: str) -> set[str]:
    ids = [require_identifier(item["id"], f"{field}[{index}].id") for index, item in enumerate(items)]
    if len(ids) != len(set(ids)):
        raise ValidationError(field, "IDs must be unique")
    return set(ids)


def _assert_dag(items: list[dict[str, Any]], field: str) -> None:
    by_id = {item["id"]: item for item in items}
    visiting: set[str] = set(); done: set[str] = set()
    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise ValidationError(field, "dependencies must form a DAG")
        if item_id in done:
            return
        visiting.add(item_id)
        for dependency in by_id[item_id]["depends_on"]:
            if dependency not in by_id:
                raise ValidationError(field, f"unknown dependency '{dependency}'")
            visit(dependency)
        visiting.remove(item_id); done.add(item_id)
    for item_id in by_id:
        visit(item_id)


def _validate_draft(data: dict[str, Any], role: str) -> None:
    if not data["claims"]:
        raise ValidationError("claims", "must contain at least one claim")
    if not any(claim["critical"] for claim in data["claims"]):
        raise ValidationError("claims", "must contain a critical claim")
    claim_ids = _unique_ids(data["claims"], "claims")
    step_ids = _unique_ids(data["proof_steps"], "proof_steps")
    if claim_ids & step_ids:
        raise ValidationError("proof_steps", "claim and proof-step IDs must not overlap")
    _assert_dag(data["claims"], "claims"); _assert_dag(data["proof_steps"], "proof_steps")
    _unique_ids(data["approaches"], "approaches")
    requests = data["tool_requests"]
    _unique_ids(requests, "tool_requests")
    for index, request in enumerate(requests): _validate_tool_request(request, f"tool_requests[{index}]")
    for index, claim in enumerate(data["claims"]):
        prefix = f"claims[{index}]"
        if any(step not in step_ids for step in claim["step_ids"]):
            raise ValidationError(prefix + ".step_ids", "must refer to local proof steps")
        if any(dependency not in claim_ids for dependency in claim["depends_on"]):
            raise ValidationError(prefix + ".depends_on", "must refer to local claims")
        if claim["kind"] == "source_assertion" and not claim["citations"]:
            raise ValidationError(prefix + ".citations", "source assertions require a citation")
        if claim["kind"] == "deduction" and not (claim["step_ids"] or claim["tool_ids"]):
            raise ValidationError(prefix, "deductions require proof steps or tool receipts")
        if claim["kind"] in {"model_knowledge", "conjecture"} and (claim["citations"] or claim["step_ids"] or claim["tool_ids"]):
            raise ValidationError(prefix, "model knowledge and conjectures cannot cite steps or tools")
    if role == "revise":
        if not data["change_log"]:
            raise ValidationError("change_log", "revise results require a change log")
    elif data["change_log"]:
        raise ValidationError("change_log", "is permitted only for revise results")


def validate_audit_for_draft(audit: Mapping[str, Any], draft: Mapping[str, Any]) -> dict[str, Any]:
    """Validate cross-result audit references once the current Draft is available."""
    checked_audit = validate_result("audit", audit)
    checked_draft = validate_result("branch", draft)
    claim_ids = {claim["id"] for claim in checked_draft["claims"]}
    if {check["claim_id"] for check in checked_audit["checks"]} != claim_ids:
        raise ValidationError("checks", "must contain one check for every draft claim")
    if any(challenge["claim_id"] not in claim_ids for challenge in checked_audit["challenges"]):
        raise ValidationError("challenges", "must refer to draft claims")
    critical = {claim["id"] for claim in checked_draft["claims"] if claim["critical"]}
    if not critical <= {challenge["claim_id"] for challenge in checked_audit["challenges"]}:
        raise ValidationError("challenges", "must challenge every critical claim")
    return checked_audit


def validate_action(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the event-level Action record before an engine can launch it."""
    data = require_object(payload, "action")
    require_exact_fields(data, "action", {"id", "kind", "role", "branch", "round", "dependencies", "payload"})
    action_id = require_identifier(data["id"], "action.id")
    kind = _enum_action(data["kind"], "action.kind", {"worker", "tool"})
    role = require_string(data["role"], "action.role")
    branch = data["branch"]
    if branch is not None and branch not in {"a", "b", "c"}:
        raise ValidationError("action.branch", "must be null or one of a, b, c")
    round_number = data["round"]
    if isinstance(round_number, bool) or round_number not in {0, 1, 2}:
        raise ValidationError("action.round", "must be 0, 1, or 2")
    dependencies = data["dependencies"]
    if not isinstance(dependencies, list):
        raise ValidationError("action.dependencies", "must be an array")
    checked_dependencies = [require_identifier(item, f"action.dependencies[{index}]") for index, item in enumerate(dependencies)]
    if len(checked_dependencies) != len(set(checked_dependencies)):
        raise ValidationError("action.dependencies", "must not contain duplicates")
    if kind == "worker":
        if role not in {"answer", "frame", "branch", "synthesize", "audit", "revise"}:
            raise ValidationError("action.role", "must be a worker role")
        worker_payload = require_object(data["payload"], "action.payload")
        require_exact_fields(worker_payload, "action.payload", {"prompt_version"})
        if worker_payload["prompt_version"] != "research-v1":
            raise ValidationError("action.payload.prompt_version", "must equal 'research-v1'")
        checked_payload: dict[str, Any] = {"prompt_version": "research-v1"}
    else:
        if role not in {"fetch_source", "check_integer", "check_polynomial", "search_perfect"}:
            raise ValidationError("action.role", "must be a tool operation")
        checked_payload = _validate_shape(data["payload"], _TOOL_REQUEST, "action.payload")
        _validate_tool_request(checked_payload, "action.payload")
        if checked_payload["operation"] != role:
            raise ValidationError("action.payload.operation", "must equal action.role")
    return {"id": action_id, "kind": kind, "role": role, "branch": branch, "round": round_number,
            "dependencies": checked_dependencies, "payload": checked_payload}


def _enum_action(value: Any, field: str, allowed: set[str]) -> str:
    item = require_string(value, field)
    if item not in allowed:
        raise ValidationError(field, f"must be one of {', '.join(sorted(allowed))}")
    return item


def validate_decision_details(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate immutable routing metadata without accepting replacement prose."""
    data = require_object(payload, "decision.details")
    require_exact_fields(data, "decision.details", {"selected_draft_id", "audit_id", "question_status", "blockers", "finish_status", "round"})
    nullable_id = lambda value, field: None if value is None else require_identifier(value, field)
    question_status = data["question_status"]
    if question_status is not None and question_status not in {"answered", "open_in_sources", "unresolved", "refuted"}:
        raise ValidationError("decision.details.question_status", "is invalid")
    finish_status = data["finish_status"]
    if finish_status is not None and finish_status not in {"complete", "incomplete", "blocked", "budget_exhausted"}:
        raise ValidationError("decision.details.finish_status", "is invalid")
    blockers = data["blockers"]
    if not isinstance(blockers, list):
        raise ValidationError("decision.details.blockers", "must be an array")
    checked_blockers = [require_string(item, f"decision.details.blockers[{index}]") for index, item in enumerate(blockers)]
    round_number = data["round"]
    if isinstance(round_number, bool) or round_number not in {0, 1, 2}:
        raise ValidationError("decision.details.round", "must be 0, 1, or 2")
    return {"selected_draft_id": nullable_id(data["selected_draft_id"], "decision.details.selected_draft_id"),
            "audit_id": nullable_id(data["audit_id"], "decision.details.audit_id"),
            "question_status": question_status, "blockers": checked_blockers,
            "finish_status": finish_status, "round": round_number}


def validate_result(role: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate untrusted worker output, including its internal graph invariants."""
    if not isinstance(payload, Mapping):
        raise ValidationError("result", "must be an object")
    schema = result_schema(role)
    data = _validate_shape(payload, schema, "result")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 65536:
        raise ValidationError("result", "canonical JSON must be at most 65536 UTF-8 bytes")
    if role in {"answer", "branch", "synthesize", "revise"}:
        _validate_draft(data, role)
    elif role == "frame":
        if not data["deliverables"] or not data["subquestions"]:
            raise ValidationError("result", "Frame needs deliverables and subquestions")
        _unique_ids(data["proposed_checks"], "proposed_checks")
        for index, request in enumerate(data["proposed_checks"]): _validate_tool_request(request, f"proposed_checks[{index}]")
    else:
        _unique_ids(data["tool_requests"], "tool_requests")
        for index, request in enumerate(data["tool_requests"]): _validate_tool_request(request, f"tool_requests[{index}]")
        if not data["challenges"]:
            raise ValidationError("challenges", "must contain at least one challenge")
    return data
