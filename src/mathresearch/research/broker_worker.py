"""Trusted child entry point for typed math and exact-URL broker operations."""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping

from mathresearch.contracts.validation import ValidationError, require_exact_fields, require_identifier, require_object, require_string
from mathresearch.research.broker import IMPLEMENTATION_VERSION, validate_tool_request
from mathresearch.research.math_checks import perform_math_check
from mathresearch.research.sources import SourceFetchError, fetch_source


def handle_request(value: Any) -> dict[str, Any]:
    envelope = require_object(value, "broker request")
    require_exact_fields(envelope, "broker request", {"schema_version", "record_type", "tool_id", "request",
        "scope", "capabilities", "descriptors", "authorized_urls", "timeout_seconds"})
    if envelope["schema_version"] != 1 or envelope["record_type"] != "broker_request":
        raise ValidationError("broker request", "unsupported version or record type")
    tool_id = require_identifier(envelope["tool_id"], "tool_id")
    request = validate_tool_request(envelope["request"])
    scope = require_string(envelope["scope"], "scope")
    if len(scope) > 4000: raise ValidationError("scope", "must be at most 4000 characters")
    capabilities = require_object(envelope["capabilities"], "capabilities")
    require_exact_fields(capabilities, "capabilities", {"fetch_sources", "math_checks"})
    if any(not isinstance(capabilities[key], bool) for key in capabilities):
        raise ValidationError("capabilities", "must contain booleans")
    descriptors = require_object(envelope["descriptors"], "descriptors")
    urls = envelope["authorized_urls"]
    if not isinstance(urls, list) or any(not isinstance(item, str) for item in urls):
        raise ValidationError("authorized_urls", "must be an array of strings")
    timeout = envelope["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValidationError("timeout_seconds", "must be positive")
    capability = "fetch_sources" if request["operation"] == "fetch_source" else "math_checks"
    status, result, error = "succeeded", None, None
    if not capabilities[capability]:
        status, error = "denied", f"capability_denied:{capability}"
    else:
        try:
            if request["operation"] == "fetch_source":
                result = fetch_source(request["arguments"]["source_id"], descriptors,
                    authorized_urls=set(urls), timeout_seconds=timeout)["source"]
                result = {"source": result}
            else:
                result = perform_math_check(request["operation"], request["arguments"])
        except SourceFetchError as exc:
            status, error = "failed", exc.reason
        except (ValidationError, OSError, TimeoutError) as exc:
            status, error = "failed", str(exc) or "broker_operation_failed"
    return {"tool_id": tool_id, "request": request, "status": status, "result": result,
            "error": error, "scope": scope, "implementation_version": IMPLEMENTATION_VERSION}


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main() -> int:
    raw = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        print("broker input exceeds 1 MiB", file=sys.stderr)
        return 2
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
        receipt = handle_request(value)
        sys.stdout.buffer.write(json.dumps(receipt, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8"))
        return 0
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        print(f"broker protocol error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
