"""Coordinator-owned, versioned record definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .validation import (
    ValidationError,
    require_boolean,
    require_capability_name,
    require_exact_fields,
    require_identifier,
    require_nonnegative_integer,
    require_object,
    require_optional_string,
    require_positive_integer,
    require_string,
    require_string_list,
)


SCHEMA_VERSION = 1
MODES = frozenset({"quick", "deep", "research"})
STAKES = frozenset({"ordinary", "significant", "high"})


def _require_enum(value: Any, field: str, allowed: frozenset[str]) -> str:
    item = require_string(value, field)
    if item not in allowed:
        raise ValidationError(field, f"must be one of {', '.join(sorted(allowed))}")
    return item


@dataclass(frozen=True)
class RunBudgets:
    """Local limits applied by a coordinator before launching workers."""

    max_accepted_submissions: int
    max_revision_cycles: int
    elapsed_time_seconds: int | None

    @classmethod
    def from_json(cls, payload: Any) -> "RunBudgets":
        data = require_object(payload, "budgets")
        require_exact_fields(
            data,
            "budgets",
            {
                "max_accepted_submissions",
                "max_revision_cycles",
                "elapsed_time_seconds",
            },
        )
        elapsed = data["elapsed_time_seconds"]
        if elapsed is not None:
            elapsed = require_positive_integer(elapsed, "budgets.elapsed_time_seconds")
        return cls(
            max_accepted_submissions=require_positive_integer(
                data["max_accepted_submissions"], "budgets.max_accepted_submissions"
            ),
            max_revision_cycles=require_nonnegative_integer(
                data["max_revision_cycles"], "budgets.max_revision_cycles"
            ),
            elapsed_time_seconds=elapsed,
        )

    def to_json(self) -> dict[str, int | None]:
        return {
            "max_accepted_submissions": self.max_accepted_submissions,
            "max_revision_cycles": self.max_revision_cycles,
            "elapsed_time_seconds": self.elapsed_time_seconds,
        }


@dataclass(frozen=True)
class RunRequest:
    """The user-supplied, unmodified intent for one research run."""

    run_id: str
    question: str
    actual_goal: str | None
    context: str | None
    constraints: tuple[str, ...]
    audience_level: str
    mode: str
    stakes: str
    learning_mode: bool
    capabilities: Mapping[str, bool]
    budgets: RunBudgets

    @classmethod
    def from_json(cls, payload: Any) -> "RunRequest":
        data = require_object(payload, "run_request")
        require_exact_fields(
            data,
            "run_request",
            {
                "schema_version",
                "record_type",
                "run_id",
                "question",
                "actual_goal",
                "context",
                "constraints",
                "audience_level",
                "mode",
                "stakes",
                "learning_mode",
                "capabilities",
                "budgets",
            },
        )
        schema_version = require_positive_integer(data["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValidationError("schema_version", f"must equal {SCHEMA_VERSION}")
        if data["record_type"] != "run_request":
            raise ValidationError("record_type", "must equal 'run_request'")
        capabilities_data = require_object(data["capabilities"], "capabilities")
        capabilities = MappingProxyType({
            require_capability_name(key, f"capabilities key '{key}'"): require_boolean(
                value, f"capabilities.{key}"
            )
            for key, value in capabilities_data.items()
        })
        return cls(
            run_id=require_identifier(data["run_id"], "run_id"),
            question=require_string(data["question"], "question"),
            actual_goal=require_optional_string(data["actual_goal"], "actual_goal"),
            context=require_optional_string(data["context"], "context"),
            constraints=require_string_list(data["constraints"], "constraints"),
            audience_level=require_string(data["audience_level"], "audience_level"),
            mode=_require_enum(data["mode"], "mode", MODES),
            stakes=_require_enum(data["stakes"], "stakes", STAKES),
            learning_mode=require_boolean(data["learning_mode"], "learning_mode"),
            capabilities=capabilities,
            budgets=RunBudgets.from_json(data["budgets"]),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "record_type": "run_request",
            "run_id": self.run_id,
            "question": self.question,
            "actual_goal": self.actual_goal,
            "context": self.context,
            "constraints": list(self.constraints),
            "audience_level": self.audience_level,
            "mode": self.mode,
            "stakes": self.stakes,
            "learning_mode": self.learning_mode,
            "capabilities": dict(self.capabilities),
            "budgets": self.budgets.to_json(),
        }
