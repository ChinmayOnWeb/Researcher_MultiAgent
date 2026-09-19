"""Typed capability broker process boundary and durable receipt validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from mathresearch.adapters.base import LaunchSpec, WorkerInput, WorkerOutput
from mathresearch.contracts.validation import (ValidationError, require_exact_fields,
    require_identifier, require_object, require_string)
from mathresearch.research.events import canonical_json_bytes
from mathresearch.research.implementation import IMPLEMENTATION_VERSION
from mathresearch.research.math_checks import perform_math_check, validate_math_arguments
from mathresearch.research.sources import validate_captured_source
from mathresearch.worker_process import execute_worker


_OPERATIONS = {"fetch_source", "check_integer", "check_polynomial", "search_perfect"}


def validate_tool_request(value: Any) -> dict[str, Any]:
    data = require_object(value, "tool request")
    require_exact_fields(data, "tool request", {"id", "operation", "arguments"})
    request_id = require_identifier(data["id"], "tool request.id")
    operation = require_string(data["operation"], "tool request.operation")
    if operation not in _OPERATIONS: raise ValidationError("tool request.operation", "is invalid")
    arguments = require_object(data["arguments"], "tool request.arguments")
    if operation == "fetch_source":
        require_exact_fields(arguments, "tool request.arguments", {"source_id"})
        require_identifier(arguments["source_id"], "tool request.arguments.source_id")
    else:
        arguments = validate_math_arguments(operation, arguments)
    return {"id": request_id, "operation": operation, "arguments": dict(arguments)}


def validate_tool_receipt(value: Any, *, tool_id: str, request: Mapping[str, Any],
                          requested_source: Mapping[str, Any] | None = None,
                          authorized_urls: set[str] | None = None,
                          expected_scope: str | None = None) -> dict[str, Any]:
    data = require_object(value, "tool receipt")
    require_exact_fields(data, "tool receipt", {"tool_id", "request", "status", "result", "error", "scope", "implementation_version"})
    if require_identifier(data["tool_id"], "tool receipt.tool_id") != tool_id:
        raise ValidationError("tool receipt.tool_id", "must match the coordinator action")
    checked_request = validate_tool_request(data["request"])
    if checked_request != validate_tool_request(request):
        raise ValidationError("tool receipt.request", "must match the intended operation")
    status = data["status"]
    if not isinstance(status, str) or status not in {"succeeded", "failed", "denied"}:
        raise ValidationError("tool receipt.status", "is invalid")
    scope = require_string(data["scope"], "tool receipt.scope")
    if len(scope) > 4000: raise ValidationError("tool receipt.scope", "must be at most 4000 characters")
    if expected_scope is not None and scope != expected_scope:
        raise ValidationError("tool receipt.scope", "must match coordinator scope")
    if data["implementation_version"] != IMPLEMENTATION_VERSION:
        raise ValidationError("tool receipt.implementation_version", "is invalid")
    error = data["error"]
    if status == "succeeded":
        if error is not None: raise ValidationError("tool receipt.error", "must be null for success")
        if checked_request["operation"] == "fetch_source":
            if requested_source is None or requested_source.get("kind") != "url":
                raise ValidationError("tool receipt.result", "has no authorized source descriptor")
            result = require_object(data["result"], "tool receipt.result")
            require_exact_fields(result, "tool receipt.result", {"source"})
            if checked_request["arguments"]["source_id"] != requested_source.get("id"):
                raise ValidationError("tool receipt.request", "must use the authorized source")
            source = validate_captured_source(result["source"], requested=requested_source,
                                              authorized_urls=authorized_urls)
            result = {"source": source}
        else:
            result = perform_math_check(checked_request["operation"], checked_request["arguments"])
            if data["result"] != result:
                raise ValidationError("tool receipt.result", "does not match deterministic recomputation")
    else:
        if data["result"] is not None: raise ValidationError("tool receipt.result", "must be null unless succeeded")
        error = require_string(error, "tool receipt.error")
        if not error: raise ValidationError("tool receipt.error", "must be nonempty unless succeeded")
        if len(error) > 4000: raise ValidationError("tool receipt.error", "must be at most 4000 characters")
        result = None
    return {"tool_id": tool_id, "request": checked_request, "status": status, "result": result,
            "error": error, "scope": scope, "implementation_version": IMPLEMENTATION_VERSION}


class BrokerAdapter:
    """Trusted module launcher implementing the existing bounded worker protocol."""

    def __init__(self, envelope: Mapping[str, Any]) -> None:
        self.envelope = dict(envelope)

    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec:
        return LaunchSpec((str(Path(sys.executable).resolve()), "-m", "mathresearch.research.broker_worker"),
                          canonical_json_bytes(self.envelope), Path(os.path.abspath(scratch)), None)

    def decode(self, stdout: bytes, result_bytes: bytes | None) -> Mapping[str, Any]:
        if result_bytes is not None: raise ValueError("broker worker must write its receipt to stdout")
        try:
            text = stdout.decode("utf-8")
            value, end = json.JSONDecoder(object_pairs_hook=_reject_duplicates,
                parse_constant=_reject_constant).raw_decode(text)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("broker output must be strict JSON") from exc
        if text[end:].strip() or not isinstance(value, dict): raise ValueError("broker output must contain one JSON object")
        return value


def run_broker(*, tool_id: str, request: Mapping[str, Any], capabilities: Mapping[str, bool],
               descriptors: Mapping[str, Mapping[str, Any]], authorized_urls: set[str] | None,
               scope: str, scratch: Path, remaining_seconds: int | None = None) -> dict[str, Any]:
    checked = validate_tool_request(request)
    capability = "fetch_sources" if checked["operation"] == "fetch_source" else "math_checks"
    tool_id = require_identifier(tool_id, "tool_id")
    if not isinstance(scope, str) or len(scope) > 4000: raise ValidationError("scope", "must be a string of at most 4000 characters")
    if not capabilities.get(capability, False):
        denied = {"tool_id": tool_id, "request": checked, "status": "denied", "result": None,
                  "error": f"capability_denied:{capability}", "scope": scope,
                  "implementation_version": IMPLEMENTATION_VERSION}
        return validate_tool_receipt(denied, tool_id=tool_id, request=checked)
    if checked["operation"] == "fetch_source":
        descriptor = descriptors.get(checked["arguments"]["source_id"])
        if not isinstance(descriptor, Mapping) or descriptor.get("kind") != "url":
            denied = {"tool_id": tool_id, "request": checked, "status": "denied", "result": None,
                      "error": "source_not_authorized", "scope": scope,
                      "implementation_version": IMPLEMENTATION_VERSION}
            return validate_tool_receipt(denied, tool_id=tool_id, request=checked)
    operation_limit = 15 if checked["operation"] == "fetch_source" else 10
    timeout = min(operation_limit, remaining_seconds) if remaining_seconds is not None else operation_limit
    if timeout <= 0:
        failure = _failed_receipt(tool_id, checked, scope, "operation_deadline_exhausted")
        return validate_tool_receipt(failure, tool_id=tool_id, request=checked)
    envelope = {"schema_version": 1, "record_type": "broker_request", "tool_id": tool_id,
        "request": checked, "scope": scope, "capabilities": dict(capabilities),
        "descriptors": {key: dict(value) for key, value in descriptors.items()},
        "authorized_urls": sorted(authorized_urls or ()), "timeout_seconds": timeout}
    output = execute_worker(BrokerAdapter(envelope), WorkerInput(checked["operation"], "", {}),
                            scratch=Path(scratch), timeout_seconds=timeout)
    if output.outcome != "succeeded" or output.payload is None:
        failure = _failed_receipt(tool_id, checked, scope, output.error or output.outcome)
        return validate_tool_receipt(failure, tool_id=tool_id, request=checked)
    authorized_source = descriptors.get(checked["arguments"].get("source_id")) if checked["operation"] == "fetch_source" else None
    return validate_tool_receipt(output.payload, tool_id=tool_id, request=checked,
                                 requested_source=authorized_source,
                                 expected_scope=scope,
                                 authorized_urls=set(authorized_urls or ()) | {
                                     item.get("url") for item in descriptors.values()
                                     if isinstance(item, Mapping) and isinstance(item.get("url"), str)})


def _failed_receipt(tool_id: str, request: Mapping[str, Any], scope: str, error: str) -> dict[str, Any]:
    return {"tool_id": tool_id, "request": dict(request), "status": "failed", "result": None,
            "error": error[:4000] or "broker_failed", "scope": scope[:4000],
            "implementation_version": IMPLEMENTATION_VERSION}


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")
