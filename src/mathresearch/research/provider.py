"""Explicit Codex configuration and provider-header observations for research runs."""

from __future__ import annotations

import re
import shutil
from typing import Any, Mapping

from mathresearch.adapters.codex import CodexAdapter
from mathresearch.adapters.base import Adapter
from mathresearch.contracts.research_request import ResearchRequest


def create_research_provider(request: ResearchRequest, *,
                             recorded_config: Mapping[str, Any] | None = None) -> Adapter:
    """Resolve and preflight Codex using the immutable requested model and effort."""
    if recorded_config is not None:
        if (recorded_config.get("model_requested") != request.provider["model"] or
                recorded_config.get("effort_requested") != request.provider["reasoning_effort"]):
            raise ValueError("recorded provider configuration disagrees with the immutable request")
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("Codex executable is unavailable")
    adapter = CodexAdapter(executable, model=request.provider["model"],
                           reasoning_effort=request.provider["reasoning_effort"])
    adapter.preflight()
    return adapter


def provider_configuration(adapter: CodexAdapter) -> dict[str, Any]:
    """Build the exact durable provider_configured event body."""
    return adapter.configuration_receipt()


def check_provider_observation(request: ResearchRequest, observed: dict[str, str | None]) -> str | None:
    """Return a protocol/configuration failure for an observed mismatch; unknowns stay unknown."""
    expected_model = request.provider["model"]
    expected_effort = request.provider["reasoning_effort"]
    if observed.get("model") is not None and observed["model"] != expected_model:
        return "observed_model_mismatch"
    if observed.get("effort") is not None and observed["effort"] != expected_effort:
        return "observed_effort_mismatch"
    return None


def parse_provider_observation(stderr: bytes | str) -> dict[str, str | None]:
    """Read only Codex metadata before its first user header; echoed prompt text is ignored."""
    if isinstance(stderr, bytes):
        try:
            text = stderr.decode("utf-8")
        except UnicodeDecodeError:
            return {"model": None, "effort": None}
    elif isinstance(stderr, str):
        text = stderr
    else:
        return {"model": None, "effort": None}
    header = text.splitlines()
    try:
        user_index = header.index("user")
        header = header[:user_index]
    except ValueError:
        return {"model": None, "effort": None}
    values: dict[str, list[str]] = {"model": [], "effort": []}
    for line in header:
        match = re.fullmatch(r"\s*model:\s*(\S+)\s*", line)
        if match:
            values["model"].append(match.group(1))
        match = re.fullmatch(r"\s*reasoning effort:\s*(\S+)\s*", line)
        if match:
            values["effort"].append(match.group(1))
    return {key: items[0] if items and len(set(items)) == 1 else None
            for key, items in values.items()}
