"""Strict validation primitives for untrusted JSON-compatible values."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
CAPABILITY_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")


class ValidationError(ValueError):
    """Identifies an invalid input field without accepting partial data."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    """Require a JSON object with string keys."""
    if not isinstance(value, Mapping):
        raise ValidationError(field, "must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValidationError(field, "must have string keys")
    return value


def require_exact_fields(
    value: Mapping[str, Any], field: str, expected: set[str]
) -> None:
    """Reject missing and unknown fields so schema evolution is explicit."""
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ValidationError(field, f"missing required field '{missing[0]}'")
    if unknown:
        raise ValidationError(field, f"unknown field '{unknown[0]}'")


def require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    """Require a JSON string, optionally rejecting empty values."""
    if not isinstance(value, str):
        raise ValidationError(field, "must be a string")
    if not allow_empty and not value:
        raise ValidationError(field, "must not be empty")
    return value


def require_optional_string(value: Any, field: str) -> str | None:
    """Require either a nonempty string or an explicit JSON null."""
    if value is None:
        return None
    return require_string(value, field)


def require_identifier(value: Any, field: str) -> str:
    """Require a stable opaque identifier, never a filesystem path."""
    identifier = require_string(value, field)
    if not ID_PATTERN.fullmatch(identifier):
        raise ValidationError(field, "must be a lowercase opaque identifier")
    return identifier


def require_capability_name(value: Any, field: str) -> str:
    """Require a stable lower-snake-case capability declaration key."""
    name = require_string(value, field)
    if not CAPABILITY_NAME_PATTERN.fullmatch(name):
        raise ValidationError(field, "must be a lowercase capability name")
    return name


def require_boolean(value: Any, field: str) -> bool:
    """Require an actual JSON boolean."""
    if not isinstance(value, bool):
        raise ValidationError(field, "must be a boolean")
    return value


def require_positive_integer(value: Any, field: str) -> int:
    """Require an integer greater than zero, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(field, "must be a positive integer")
    return value


def require_nonnegative_integer(value: Any, field: str) -> int:
    """Require an integer at least zero, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(field, "must be a nonnegative integer")
    return value


def require_string_list(value: Any, field: str) -> tuple[str, ...]:
    """Require a JSON array of nonempty strings."""
    if not isinstance(value, list):
        raise ValidationError(field, "must be an array")
    return tuple(require_string(item, f"{field}[{index}]") for index, item in enumerate(value))
