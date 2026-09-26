"""Shared, meaning-preserving handling of provider structured output.

This module deliberately does not repair missing IDs, references, evidence, or
proof steps.  It only finds one unambiguous JSON object and records validation
failures in a stable machine-readable form.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class ParsedOutput:
    value: Mapping[str, Any]
    normalized_text: str
    normalization: tuple[str, ...]


@dataclass(frozen=True)
class ValidationOutcome:
    protocol_status: str
    value: Any | None
    issues: tuple[dict[str, Any], ...]


def parse_json_object(raw: bytes | str) -> ParsedOutput:
    """Parse one object, allowing only unambiguous transport-format cleanup."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig")
        had_bom = raw.startswith(b"\xef\xbb\xbf")
    elif isinstance(raw, str):
        text = raw.removeprefix("\ufeff")
        had_bom = raw.startswith("\ufeff")
    else:
        raise TypeError("structured output must be UTF-8 bytes or text")
    candidate = text.strip()
    repairs: list[str] = []
    if had_bom:
        repairs.append("removed_utf8_bom")
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            first = lines[0].strip().lower()
            if first in {"```", "```json"}:
                candidate = "\n".join(lines[1:-1]).strip()
                repairs.append("removed_markdown_fence")

    # A JSON array is never an acceptable root object. Without this check,
    # scanning for nested braces could mistake its first element for the
    # provider's complete result.
    if candidate.startswith("["):
        try:
            decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys,
                                       parse_constant=_reject_constant)
            root, end = decoder.raw_decode(candidate)
        except (json.JSONDecodeError, ValueError):
            root = None
        else:
            if isinstance(root, list) and not candidate[end:].strip():
                raise ValueError("structured output root must be a JSON object")
    elif candidate.startswith("{"):
        try:
            decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys,
                                       parse_constant=_reject_constant)
            root, end = decoder.raw_decode(candidate)
        except ValueError as error:
            if not isinstance(error, json.JSONDecodeError):
                raise
        else:
            if isinstance(root, dict) and not candidate[end:].strip():
                return ParsedOutput(root, candidate[:end], tuple(repairs))

    decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys,
                               parse_constant=_reject_constant)
    roots: list[tuple[int, int, Any]] = []
    parse_failures: list[ValueError] = []
    for match in re.finditer(r"[\[{]", candidate):
        try:
            value, end = decoder.raw_decode(candidate, match.start())
        except ValueError as error:
            parse_failures.append(error)
            continue
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            roots.append((match.start(), end, value))
    # Nested object candidates are part of their enclosing JSON object. Keep
    # only outermost parseable objects so prose may safely surround one value.
    outermost = [item for item in roots if not any(
        other[0] < item[0] and item[1] <= other[1] for other in roots
    )]
    if len(outermost) != 1:
        if not outermost:
            if parse_failures:
                raise parse_failures[0]
            raise ValueError("no valid JSON object found")
        raise ValueError("more than one unambiguous JSON object found")
    start, end, value = outermost[0]
    if candidate[:start].strip() or candidate[end:].strip():
        repairs.append("extracted_single_json_object_from_prose")
    if not isinstance(value, dict):
        raise ValueError("structured output must be one JSON object")
    return ParsedOutput(value, candidate[start:end], tuple(repairs))


def semantic_artifact(raw: bytes | str, parsed: Mapping[str, Any] | None = None) -> str | None:
    """Recover answer text for inspection without implying protocol validity."""
    if parsed is not None:
        for key in ("answer", "conclusion", "summary", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:12000]
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = text.removeprefix("\ufeff").strip()
    # Recover a well-formed JSON string value for an answer even when another
    # part of the surrounding object is malformed. Never synthesize content.
    match = re.search(r'"(?:answer|conclusion|summary|text)"\s*:\s*("(?:\\.|[^"\\])*")', text, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()[:12000]
    if text and not text.lstrip().startswith(("{", "[")):
        return text[:12000]
    return None


def validation_issue(error: BaseException) -> dict[str, Any]:
    """Normalize contract errors into actionable, serializable diagnostics."""
    field = getattr(error, "field", "$")
    message = getattr(error, "message", str(error))
    details = getattr(error, "details", {})
    issue: dict[str, Any] = {
        "path": details.get("json_path", field),
        "category": details.get("category", _category(message, details)),
        "found": details.get("bad_reference", details.get("found")),
        "expected_namespace": details.get("expected_namespace"),
        "available_ids": details.get("available_ids", []),
        "explanation": message,
        "deterministic_repair_permitted": False,
        "model_repair_permitted": True,
    }
    return issue


def validate_payload(value: Any, validator: Any) -> ValidationOutcome:
    """Run a domain contract through the shared protocol-classification gate."""
    try:
        return ValidationOutcome("valid", validator(value), ())
    except Exception as error:
        # Contract validators raise ValidationError; preserve unexpected errors
        # rather than disguising implementation faults as model formatting.
        from mathresearch.contracts.validation import ValidationError
        if not isinstance(error, ValidationError):
            raise
        return ValidationOutcome("invalid", None, (validation_issue(error),))


def _category(message: str, details: Mapping[str, Any]) -> str:
    if "bad_reference" in details or "unknown" in message and "reference" in message:
        return "unknown_reference"
    if "unique" in message or "duplicate" in message:
        return "duplicate_id"
    if "DAG" in message or "cycle" in message:
        return "circular_dependency"
    if "missing required" in message or "required field is missing" in message:
        return "missing_field"
    if "unknown field" in message or "unexpected" in message:
        return "unknown_field"
    return "schema_violation"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")
