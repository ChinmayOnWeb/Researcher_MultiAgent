"""Strict version-three request records for the bounded research workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

from .validation import (
    ValidationError, require_boolean, require_exact_fields, require_identifier,
    require_nonnegative_integer, require_object, require_positive_integer,
    require_string,
)


SCHEMA_VERSION = 3
_PROFILES = {
    "quick": (1, 0, 0, 1, 180),
    "deep": (7, 6, 1, 2, 900),
    "research": (11, 10, 2, 3, 1800),
}
_CAPABILITIES = {"fetch_sources", "math_checks"}


def _enum(value: Any, field: str, allowed: set[str]) -> str:
    item = require_string(value, field)
    if item not in allowed:
        raise ValidationError(field, f"must be one of {', '.join(sorted(allowed))}")
    return item


def _limited_text(value: Any, field: str, maximum: int, *, nullable: bool = False,
                  empty: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = require_string(value, field, allow_empty=empty)
    if len(text) > maximum:
        raise ValidationError(field, f"must be at most {maximum} characters")
    return text


def _utc_timestamp(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = require_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(field, "must be a UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValidationError(field, "must be a UTC timestamp")
    return text


def _https_url(value: Any, field: str) -> str:
    url = require_string(value, field)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError(field, "must be an HTTPS URL")
    return url


@dataclass(frozen=True)
class SourceInput:
    id: str
    kind: str
    title: str
    text: str | None
    url: str | None
    published_at: str | None

    @classmethod
    def from_json(cls, payload: Any, *, field: str, fetch_sources: bool) -> "SourceInput":
        data = require_object(payload, field)
        require_exact_fields(data, field, {"id", "kind", "title", "text", "url", "published_at"})
        source_id = require_identifier(data["id"], f"{field}.id")
        if source_id == "request-context" or source_id.startswith(("gate-text-", "agent-")):
            raise ValidationError(f"{field}.id", "is reserved")
        kind = _enum(data["kind"], f"{field}.kind", {"text", "url"})
        title = _limited_text(data["title"], f"{field}.title", 4000)
        published_at = _utc_timestamp(data["published_at"], f"{field}.published_at")
        if kind == "text":
            text = _limited_text(data["text"], f"{field}.text", 32768)
            if data["url"] is not None:
                raise ValidationError(f"{field}.url", "must be null for text sources")
            return cls(source_id, kind, title, text, None, published_at)
        if data["text"] is not None:
            raise ValidationError(f"{field}.text", "must be null for URL sources")
        if not fetch_sources:
            raise ValidationError(field, "URL sources require fetch_sources capability")
        return cls(source_id, kind, title, None, _https_url(data["url"], f"{field}.url"), published_at)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "title": self.title, "text": self.text,
                "url": self.url, "published_at": self.published_at}


@dataclass(frozen=True)
class ResearchRequest:
    run_id: str
    question: str
    goal: str | None
    context: str | None
    constraints: tuple[str, ...]
    audience: str
    objective: str
    mode: str
    stakes: str
    learning_mode: bool
    provider: Mapping[str, str]
    capabilities: Mapping[str, bool]
    budgets: Mapping[str, int]
    sources: tuple[SourceInput, ...]

    @classmethod
    def from_json(cls, payload: Any) -> "ResearchRequest":
        data = require_object(payload, "research_request")
        expected = {"schema_version", "record_type", "run_id", "question", "goal", "context",
                    "constraints", "audience", "objective", "mode", "stakes", "learning_mode",
                    "provider", "capabilities", "budgets", "sources"}
        require_exact_fields(data, "research_request", expected)
        if require_positive_integer(data["schema_version"], "schema_version") != SCHEMA_VERSION:
            raise ValidationError("schema_version", "must equal 3")
        if data["record_type"] != "research_request":
            raise ValidationError("record_type", "must equal 'research_request'")
        mode = _enum(data["mode"], "mode", set(_PROFILES))
        stakes = _enum(data["stakes"], "stakes", {"ordinary", "significant", "high"})
        learning_mode = require_boolean(data["learning_mode"], "learning_mode")
        if stakes != "ordinary" or learning_mode:
            raise ValidationError("unsupported_workflow", "only ordinary nonlearning research is supported")
        provider_data = require_object(data["provider"], "provider")
        require_exact_fields(provider_data, "provider", {"adapter", "model", "reasoning_effort"})
        if provider_data["adapter"] != "codex":
            raise ValidationError("provider.adapter", "must equal 'codex'")
        provider = MappingProxyType({"adapter": "codex",
            "model": _limited_text(provider_data["model"], "provider.model", 100),
            "reasoning_effort": _enum(provider_data["reasoning_effort"], "provider.reasoning_effort", {"medium", "high"})})
        capability_data = require_object(data["capabilities"], "capabilities")
        require_exact_fields(capability_data, "capabilities", _CAPABILITIES)
        capabilities = MappingProxyType({key: require_boolean(capability_data[key], f"capabilities.{key}") for key in sorted(_CAPABILITIES)})
        budgets = _parse_budgets(data["budgets"], mode)
        if mode == "quick" and any(capabilities.values()):
            raise ValidationError("capabilities", "Quick does not permit broker capabilities; select Deep or Research")
        constraints_data = data["constraints"]
        if not isinstance(constraints_data, list) or len(constraints_data) > 20:
            raise ValidationError("constraints", "must be an array with at most 20 entries")
        constraints = tuple(_limited_text(item, f"constraints[{index}]", 1000) for index, item in enumerate(constraints_data))
        sources_data = data["sources"]
        if not isinstance(sources_data, list) or len(sources_data) > 6:
            raise ValidationError("sources", "must be an array with at most 6 entries")
        sources = tuple(SourceInput.from_json(item, field=f"sources[{index}]", fetch_sources=capabilities["fetch_sources"])
                        for index, item in enumerate(sources_data))
        if len({source.id for source in sources}) != len(sources):
            raise ValidationError("sources", "source IDs must be unique")
        inline_bytes = sum(len(source.text.encode("utf-8")) for source in sources if source.text is not None)
        context = _limited_text(data["context"], "context", 16000, nullable=True, empty=True)
        if context is not None:
            inline_bytes += len(context.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
        if inline_bytes > 65536:
            raise ValidationError("sources", "combined normalized source text exceeds 65536 UTF-8 bytes")
        return cls(require_identifier(data["run_id"], "run_id"), _limited_text(data["question"], "question", 12000),
                   _limited_text(data["goal"], "goal", 4000, nullable=True), context, constraints,
                   _limited_text(data["audience"], "audience", 100), _enum(data["objective"], "objective", {"answer", "prove", "investigate"}),
                   mode, stakes, learning_mode, provider, capabilities, MappingProxyType(budgets), sources)

    def to_json(self) -> dict[str, Any]:
        return {"schema_version": 3, "record_type": "research_request", "run_id": self.run_id,
                "question": self.question, "goal": self.goal, "context": self.context,
                "constraints": list(self.constraints), "audience": self.audience, "objective": self.objective,
                "mode": self.mode, "stakes": self.stakes, "learning_mode": self.learning_mode,
                "provider": dict(self.provider), "capabilities": dict(self.capabilities),
                "budgets": dict(self.budgets), "sources": [source.to_json() for source in self.sources]}


def _parse_budgets(payload: Any, mode: str) -> dict[str, int]:
    data = require_object(payload, "budgets")
    expected = {"max_model_calls", "max_tool_calls", "max_repairs", "max_branches", "max_wall_seconds", "per_call_seconds", "max_input_bytes"}
    require_exact_fields(data, "budgets", expected)
    caps = _PROFILES[mode]
    parsed = {
        "max_model_calls": require_positive_integer(data["max_model_calls"], "budgets.max_model_calls"),
        "max_tool_calls": require_nonnegative_integer(data["max_tool_calls"], "budgets.max_tool_calls"),
        "max_repairs": require_nonnegative_integer(data["max_repairs"], "budgets.max_repairs"),
        "max_branches": require_positive_integer(data["max_branches"], "budgets.max_branches"),
        "max_wall_seconds": require_positive_integer(data["max_wall_seconds"], "budgets.max_wall_seconds"),
        "per_call_seconds": require_positive_integer(data["per_call_seconds"], "budgets.per_call_seconds"),
        "max_input_bytes": require_positive_integer(data["max_input_bytes"], "budgets.max_input_bytes"),
    }
    for key, cap in zip(("max_model_calls", "max_tool_calls", "max_repairs", "max_branches", "max_wall_seconds"), caps):
        if parsed[key] > cap:
            raise ValidationError(f"budgets.{key}", f"must not exceed {cap} for {mode}")
    if parsed["per_call_seconds"] > parsed["max_wall_seconds"]:
        raise ValidationError("budgets.per_call_seconds", "must not exceed max_wall_seconds")
    if parsed["max_input_bytes"] > 131072:
        raise ValidationError("budgets.max_input_bytes", "must not exceed 131072")
    return parsed


def build_request_payload(*, run_id: str, question: str, objective: str, mode: str, model: str,
                          goal: str | None = None, context: str | None = None,
                          constraints: Sequence[str] = ()) -> dict[str, Any]:
    """Build explicit CLI defaults without changing any user supplied string."""
    if mode not in _PROFILES:
        raise ValidationError("mode", "must be one of deep, quick, research")
    calls, tools, repairs, branches, wall = _PROFILES[mode]
    return {"schema_version": 3, "record_type": "research_request", "run_id": run_id,
            "question": question, "goal": goal, "context": context, "constraints": list(constraints),
            "audience": "unspecified", "objective": objective, "mode": mode, "stakes": "ordinary",
            "learning_mode": False, "provider": {"adapter": "codex", "model": model,
            "reasoning_effort": "medium" if mode == "quick" else "high"},
            "capabilities": {"fetch_sources": False, "math_checks": False},
            "budgets": {"max_model_calls": calls, "max_tool_calls": tools, "max_repairs": repairs,
            "max_branches": branches, "max_wall_seconds": wall, "per_call_seconds": 180,
            "max_input_bytes": 131072}, "sources": []}
