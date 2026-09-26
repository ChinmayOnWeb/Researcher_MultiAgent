"""Provider-facing strict schemas and semantic validation for research results."""

from __future__ import annotations

import copy
import json
import re
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


_ID = text(64) | {"pattern": r"[a-z][a-z0-9-]{2,63}"}
_CITATION = obj({"source_id": _ID, "start": {"type": "integer", "minimum": 0},
                 "end": {"type": "integer", "minimum": 0}, "quote": text(1200)})
# Codex structured outputs reject nested ``oneOf`` schemas but accept the
# equivalent ``anyOf`` form.  Semantic validation below still requires exactly
# one branch to match, so this does not broaden the contract.
_TOOL_ARGUMENTS = {"anyOf": [
    obj({"source_id": _ID}),
    obj({"n": {"type": "integer", "minimum": 1}}),
    obj({"lhs": arr({"type": "integer"}, 13), "rhs": arr({"type": "integer"}, 13),
         "lo": {"type": "integer"}, "hi": {"type": "integer"}}),
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

_BASIS = enum(("question_premise", "additional_assumption", "local_assumption",
               "standard_result", "external_fact", "derivation", "conjecture",
               "unsupported_recollection"))
_CLAIM_V3 = obj({"id": _ID, "statement": text(4000), "critical": {"type": "boolean"},
    "kind": enum(("definition", "assumption", "source_assertion", "deduction", "model_knowledge", "conjecture")),
    "citations": arr(_CITATION, 4), "step_ids": arr(_ID, 8), "tool_ids": arr(_ID, 4),
    "depends_on": arr(_ID, 8), "basis": _BASIS, "basis_reference": text(2000),
    "scope_step_ids": arr(_ID, 24), "discharged_by_step_ids": arr(_ID, 24)})
_DRAFT_V3 = obj({"answer": text(12000), "question_status": enum(("answered", "open_in_sources", "unresolved", "refuted")),
    "claims": arr(_CLAIM_V3, 12), "proof_steps": arr(_STEP, 24), "approaches": arr(_APPROACH, 3),
    "open_questions": arr(text(4000), 8), "tool_requests": arr(_TOOL_REQUEST, 4), "change_log": arr(text(4000), 8)})
_AUDIT_V3 = obj({"checks": arr(obj({"claim_id": _ID, "verdict": enum(("supported", "unsupported", "contradicted", "conditional")),
    "reasoning": text(4000), "checked_step_ids": arr(_ID, 24),
    "basis_verdict": enum(("applicable", "not_applicable", "unsupported", "conditional", "source_attributed", "not_tested")),
    "basis_reasoning": text(4000)}), 12),
    "challenges": _AUDIT["properties"]["challenges"],
    "missing_evidence": _AUDIT["properties"]["missing_evidence"],
    "tool_requests": _AUDIT["properties"]["tool_requests"],
    "recommended_action": _AUDIT["properties"]["recommended_action"]})

OUTPUT_SCHEMA_VERSION = "research-output-v2"
VALIDATOR_VERSION = "research-validator-v5"


def result_schema(role: str, prompt_version: str = "research-v2") -> dict[str, Any]:
    """Return a defensive provider schema for one worker role."""
    if prompt_version not in {"research-v1", "research-v2", "research-v3", "research-v4", "research-v5", "research-v6", "research-v7", "research-v8"}:
        raise ValidationError("prompt_version", "is unsupported")
    if role in {"answer", "branch", "synthesize", "revise"}:
        return copy.deepcopy(_DRAFT_V3 if prompt_version in {"research-v3", "research-v4", "research-v5", "research-v6", "research-v7", "research-v8"} else _DRAFT)
    if role == "frame":
        return copy.deepcopy(_FRAME)
    if role == "audit":
        return copy.deepcopy(_AUDIT_V3 if prompt_version in {"research-v3", "research-v4", "research-v5", "research-v6", "research-v7", "research-v8"} else _AUDIT)
    raise ValidationError("role", "must be a research worker role")


def _validate_shape(value: Any, schema: Mapping[str, Any], field: str) -> Any:
    if "oneOf" in schema or "anyOf" in schema:
        matches: list[Any] = []
        for candidate in schema.get("oneOf", schema.get("anyOf", [])):
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
        missing = sorted(expected - set(data))
        if missing:
            raise ValidationError(f"{field}.{missing[0]}", "required field is missing",
                                  details={"category": "missing_field"})
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValidationError(f"{field}.{unknown[0]}", "field is not in the schema",
                                  details={"category": "unknown_field", "found": unknown[0]})
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
        if "pattern" in schema and re.fullmatch(schema["pattern"], item) is None:
            raise ValidationError(field, "must match the required identifier pattern")
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
    if kind == "null":
        if value is not None:
            raise ValidationError(field, "must be null")
        return None
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
    seen: set[str] = set()
    for index, item_id in enumerate(ids):
        if item_id in seen:
            raise ValidationError(f"{field}[{index}].id", "identifiers must be unique (duplicate identifier)", details={
                "category": "duplicate_id", "bad_reference": item_id,
                "expected_namespace": f"unique {field} IDs", "available_ids": sorted(seen)})
        seen.add(item_id)
    return set(ids)


def _reference_error(path: str, reference: str, namespace: str,
                    available_ids: set[str]) -> ValidationError:
    return ValidationError(path, f"unknown {namespace} reference '{reference}'", details={
        "json_path": path, "bad_reference": reference,
        "expected_namespace": namespace, "available_ids": sorted(available_ids),
    })


def _assert_dag(items: list[dict[str, Any]], field: str, namespace: str) -> None:
    by_id = {item["id"]: item for item in items}
    visiting: set[str] = set(); done: set[str] = set()
    def visit(item_id: str) -> None:
        if item_id in visiting:
            item_index = next(index for index, item in enumerate(items) if item["id"] == item_id)
            raise ValidationError(f"{field}[{item_index}].depends_on", "dependencies must form a DAG (circular dependency)",
                details={"category": "circular_dependency", "bad_reference": item_id,
                         "expected_namespace": namespace, "available_ids": sorted(by_id)})
        if item_id in done:
            return
        visiting.add(item_id)
        item_index = next(index for index, item in enumerate(items) if item["id"] == item_id)
        for dependency_index, dependency in enumerate(by_id[item_id]["depends_on"]):
            if dependency not in by_id:
                raise _reference_error(
                    f"{field}[{item_index}].depends_on[{dependency_index}]",
                    dependency, namespace, set(by_id))
            visit(dependency)
        visiting.remove(item_id); done.add(item_id)
    for item_id in by_id:
        visit(item_id)


def _validate_draft(data: dict[str, Any], role: str, prompt_version: str) -> None:
    if not data["claims"]:
        raise ValidationError("claims", "must contain at least one claim")
    if not any(claim["critical"] for claim in data["claims"]):
        raise ValidationError("claims", "must contain a critical claim")
    claim_ids = _unique_ids(data["claims"], "claims")
    step_ids = _unique_ids(data["proof_steps"], "proof_steps")
    if claim_ids & step_ids:
        raise ValidationError("proof_steps", "claim and proof-step IDs must not overlap")
    _assert_dag(data["claims"], "claims", "claims")
    _assert_dag(data["proof_steps"], "proof_steps", "proof_steps")
    _unique_ids(data["approaches"], "approaches")
    requests = data["tool_requests"]
    _unique_ids(requests, "tool_requests")
    for index, request in enumerate(requests): _validate_tool_request(request, f"tool_requests[{index}]")
    for index, claim in enumerate(data["claims"]):
        prefix = f"claims[{index}]"
        for reference_index, step in enumerate(claim["step_ids"]):
            if step not in step_ids:
                raise _reference_error(prefix + f".step_ids[{reference_index}]", step,
                                       "proof_steps", step_ids)
        for reference_index, dependency in enumerate(claim["depends_on"]):
            if dependency not in claim_ids:
                raise _reference_error(prefix + f".depends_on[{reference_index}]", dependency,
                                       "claims", claim_ids)
        if prompt_version in {"research-v3", "research-v4", "research-v5", "research-v6", "research-v7", "research-v8"}:
            basis = claim["basis"]
            if not claim["basis_reference"]:
                raise ValidationError(prefix + ".basis_reference", "must explain the claimed basis")
            for field in ("scope_step_ids", "discharged_by_step_ids"):
                for ref_index, step_id in enumerate(claim[field]):
                    if step_id not in step_ids:
                        raise _reference_error(f"{prefix}.{field}[{ref_index}]", step_id,
                                               "proof_steps", step_ids)
            if basis == "question_premise" and (claim["scope_step_ids"] or claim["discharged_by_step_ids"]):
                raise ValidationError(prefix + ".basis", "question premises cannot declare local discharge links")
            if basis == "question_premise" and claim["kind"] not in {"assumption", "definition", "source_assertion"}:
                raise ValidationError(prefix + ".basis", "question_premise requires kind=assumption, definition, or source_assertion")
            if basis == "additional_assumption" and claim["kind"] != "assumption":
                raise ValidationError(prefix + ".basis", "additional_assumption requires kind=assumption")
            if basis == "local_assumption":
                if claim["kind"] != "assumption" or not claim["scope_step_ids"] or not claim["discharged_by_step_ids"]:
                    raise ValidationError(prefix + ".basis", "local assumptions require an assumption claim, scope, and discharge steps")
                supported_by = [other for other in data["claims"] if claim["id"] in other["depends_on"]
                                and other["kind"] == "deduction"]
                proof_steps_by_id = {step["id"]: step for step in data["proof_steps"]}
                scope_steps = set(claim["scope_step_ids"])
                def depends_on_scope(step_id: str) -> bool:
                    pending = list(proof_steps_by_id[step_id]["depends_on"])
                    visited: set[str] = set()
                    while pending:
                        dependency = pending.pop()
                        if dependency in scope_steps:
                            return True
                        if dependency not in visited:
                            visited.add(dependency)
                            pending.extend(proof_steps_by_id[dependency]["depends_on"])
                    return step_id in scope_steps
                if any(not depends_on_scope(step_id) for step_id in claim["discharged_by_step_ids"]):
                    raise ValidationError(prefix + ".discharged_by_step_ids",
                        "each discharge step must depend on a proof step in the assumption's scope")
            if basis == "local_assumption" and prompt_version != "research-v8" and not any(
                    set(claim["discharged_by_step_ids"]) <= set(other["step_ids"])
                    for other in supported_by):
                raise ValidationError(prefix + ".discharged_by_step_ids",
                    "must be included in step_ids of a deduction that directly depends on this local assumption")
            elif basis != "local_assumption" and (claim["scope_step_ids"] or claim["discharged_by_step_ids"]):
                raise ValidationError(prefix + ".basis", "only local assumptions may declare scope or discharge steps")
            if basis == "standard_result" and (claim["kind"] != "deduction" or not claim["step_ids"]):
                raise ValidationError(prefix + ".basis", "standard_result requires a deduction with application steps")
            if basis == "external_fact" and (claim["kind"] != "source_assertion" or not claim["citations"]):
                raise ValidationError(prefix + ".basis", "external_fact requires a cited source_assertion")
            if basis == "derivation" and claim["kind"] not in {"deduction", "definition"}:
                raise ValidationError(prefix + ".basis", "derivation requires a deduction or definition claim")
            if basis == "standard_result" and not claim["basis_reference"].strip():
                raise ValidationError(prefix + ".basis_reference", "must name the standard result")
            if basis in {"conjecture", "unsupported_recollection"} and claim["kind"] not in {"model_knowledge", "conjecture"}:
                raise ValidationError(prefix + ".basis", "conjectures and unsupported recollections cannot be relabeled as deductions")
        if claim["kind"] == "source_assertion" and not claim["citations"]:
            raise ValidationError(prefix + ".citations", "source assertions require a citation")
        if claim["kind"] == "deduction" and not (claim["step_ids"] or claim["tool_ids"]):
            raise ValidationError(prefix, "deductions require proof steps or tool receipts")
        if claim["kind"] in {"model_knowledge", "conjecture"} and (claim["citations"] or claim["step_ids"] or claim["tool_ids"]):
            raise ValidationError(prefix, "model knowledge and conjectures cannot cite steps or tools")
    if role == "revise":
        if not data["change_log"]:
            raise ValidationError("change_log", "revise results require a change log")


def validate_audit_for_draft(audit: Mapping[str, Any], draft: Mapping[str, Any], *,
                             prompt_version: str | None = None) -> dict[str, Any]:
    """Validate cross-result audit references once the current Draft is available."""
    version = prompt_version or ("research-v3" if draft.get("claims") and
        all(isinstance(claim, Mapping) and "basis" in claim for claim in draft["claims"]) else "research-v2")
    checked_audit = validate_result("audit", audit, prompt_version=version)
    errors = []
    checked_draft = None
    for producer in ("answer", "branch", "synthesize", "revise"):
        try:
            checked_draft = validate_result(producer, draft, prompt_version=version)
            break
        except ValidationError as exc:
            errors.append(exc)
    if checked_draft is None: raise errors[0]
    claim_ids = {claim["id"] for claim in checked_draft["claims"]}
    if {check["claim_id"] for check in checked_audit["checks"]} != claim_ids:
        raise ValidationError("checks", "must contain one check for every draft claim")
    if any(challenge["claim_id"] not in claim_ids for challenge in checked_audit["challenges"]):
        raise ValidationError("challenges", "must refer to draft claims")
    step_ids = {step["id"] for step in checked_draft["proof_steps"]}
    for index, check in enumerate(checked_audit["checks"]):
        if any(step_id not in step_ids for step_id in check["checked_step_ids"]):
            raise ValidationError(f"checks[{index}].checked_step_ids", "must refer to current draft proof steps")
        if version in {"research-v3", "research-v4", "research-v5", "research-v6", "research-v7", "research-v8"}:
            claim = next(item for item in checked_draft["claims"] if item["id"] == check["claim_id"])
            basis = claim["basis"]
            verdict = check["basis_verdict"]
            if (basis == "local_assumption" and
                    not set(claim["discharged_by_step_ids"]).issubset(set(check["checked_step_ids"]))):
                raise ValidationError(f"checks[{index}].checked_step_ids",
                    "must cover every local-assumption discharge step")
            if basis in {"conjecture", "unsupported_recollection"} and verdict == "applicable":
                raise ValidationError(f"checks[{index}].basis_verdict", "cannot treat conjecture or unsupported recollection as applicable")
            if basis in {"question_premise", "standard_result", "derivation"} and verdict == "source_attributed":
                raise ValidationError(f"checks[{index}].basis_verdict", "source attribution does not validate this mathematical basis")
    return checked_audit


def validate_action(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the event-level Action record before an engine can launch it."""
    data = require_object(payload, "action")
    require_exact_fields(data, "action", {"id", "kind", "role", "branch", "round", "dependencies", "payload"})
    action_id = require_identifier(data["id"], "action.id")
    kind = _enum_action(data["kind"], "action.kind", {"worker", "tool"})
    role = require_string(data["role"], "action.role")
    branch = _nullable_enum(data["branch"], "action.branch", {"a", "b", "c"})
    round_number = _round(data["round"], "action.round")
    dependencies = data["dependencies"]
    if not isinstance(dependencies, list):
        raise ValidationError("action.dependencies", "must be an array")
    if len(dependencies) > 24:
        raise ValidationError("action.dependencies", "must have at most 24 items")
    checked_dependencies = [require_identifier(item, f"action.dependencies[{index}]") for index, item in enumerate(dependencies)]
    if len(checked_dependencies) != len(set(checked_dependencies)):
        raise ValidationError("action.dependencies", "must not contain duplicates")
    if kind == "worker":
        if role not in {"answer", "frame", "branch", "synthesize", "audit", "revise"}:
            raise ValidationError("action.role", "must be a worker role")
        worker_payload = require_object(data["payload"], "action.payload")
        require_exact_fields(worker_payload, "action.payload", {"prompt_version"})
        if worker_payload["prompt_version"] not in {"research-v1", "research-v2", "research-v3", "research-v4", "research-v5", "research-v6", "research-v7", "research-v8"}:
            raise ValidationError("action.payload.prompt_version", "is unsupported")
        checked_payload: dict[str, Any] = {"prompt_version": worker_payload["prompt_version"]}
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


def _nullable_enum(value: Any, field: str, allowed: set[str]) -> str | None:
    if value is None:
        return None
    return _enum_action(value, field, allowed)


def _round(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1, 2}:
        raise ValidationError(field, "must be 0, 1, or 2")
    return value


def validate_decision_details(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate immutable routing metadata without accepting replacement prose."""
    data = require_object(payload, "decision.details")
    require_exact_fields(data, "decision.details", {"selected_draft_id", "audit_id", "question_status", "blockers", "finish_status", "round"})
    nullable_id = lambda value, field: None if value is None else require_identifier(value, field)
    question_status = _nullable_enum(data["question_status"], "decision.details.question_status", {"answered", "open_in_sources", "unresolved", "refuted"})
    finish_status = _nullable_enum(data["finish_status"], "decision.details.finish_status", {"complete", "incomplete", "blocked", "budget_exhausted"})
    blockers = data["blockers"]
    if not isinstance(blockers, list):
        raise ValidationError("decision.details.blockers", "must be an array")
    if len(blockers) > 8:
        raise ValidationError("decision.details.blockers", "must have at most 8 items")
    checked_blockers = [require_string(item, f"decision.details.blockers[{index}]") for index, item in enumerate(blockers)]
    if any(len(item) > 4000 for item in checked_blockers):
        first = next(index for index, item in enumerate(checked_blockers) if len(item) > 4000)
        raise ValidationError(f"decision.details.blockers[{first}]", "must be at most 4000 characters")
    round_number = _round(data["round"], "decision.details.round")
    return {"selected_draft_id": nullable_id(data["selected_draft_id"], "decision.details.selected_draft_id"),
            "audit_id": nullable_id(data["audit_id"], "decision.details.audit_id"),
            "question_status": question_status, "blockers": checked_blockers,
            "finish_status": finish_status, "round": round_number}


def validate_result(role: str, payload: Mapping[str, Any], *,
                    prompt_version: str = "research-v2") -> dict[str, Any]:
    """Validate untrusted worker output, including its internal graph invariants."""
    if not isinstance(payload, Mapping):
        raise ValidationError("result", "must be an object")
    schema = result_schema(role, prompt_version)
    data = _validate_shape(payload, schema, "result")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 65536:
        raise ValidationError("result", "canonical JSON must be at most 65536 UTF-8 bytes")
    if role in {"answer", "branch", "synthesize", "revise"}:
        _validate_draft(data, role, prompt_version)
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
