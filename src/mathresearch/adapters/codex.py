"""Codex CLI adapter for the locally verified 0.154.0 noninteractive interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .base import LaunchSpec, WorkerInput


class CodexAdapter:
    """Use a fresh, ephemeral Codex process with a dedicated structured result file.

    This adapter retains the locally verified argv protocol, but is deliberately
    unavailable to the quick-research MVP.  Codex 0.154.0 can restrict writes,
    web search, configured MCP, and rules, but it cannot natively disable shell
    execution.  A reasoning-only profile must not claim that a read-only shell
    is no shell at all.
    """

    protocol_version = "codex-exec-0.154.0"
    capabilities: Mapping[str, bool] = {
        "web_search": False,
        "file_mutation": False,
        "external_mcp_config": False,
        "shell_execution": True,
    }

    def __init__(self, executable: Path, model: str | None = None) -> None:
        self.executable = Path(executable)
        self.model = model

    def preflight(self) -> None:
        """Reject the unsupported reasoning-only MVP capability profile."""
        raise ValueError(
            "Codex 0.154.0 cannot enforce disabled shell execution; "
            "the reasoning-only MVP provider profile is unavailable"
        )

    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec:
        root = Path(os.path.abspath(scratch))
        schema_path = root / "output-schema.json"
        result_path = root / "result.json"
        with schema_path.open("x", encoding="utf-8") as schema_file:
            schema_file.write(json.dumps(task.output_schema, sort_keys=True, separators=(",", ":"), allow_nan=False))
        argv: list[str] = [
            str(self.executable), "--ask-for-approval", "never", "--sandbox", "read-only",
            "exec", "--skip-git-repo-check", "--ephemeral",
            "--ignore-user-config", "--ignore-rules",
        ]
        if self.model is not None:
            argv.extend(("--model", self.model))
        argv.extend(("--output-schema", str(schema_path), "--output-last-message", str(result_path), "-"))
        return LaunchSpec(tuple(argv), task.prompt.encode("utf-8"), root, result_path)

    def decode(self, stdout: bytes, result_bytes: bytes | None) -> Mapping[str, Any]:
        if result_bytes is None:
            raise ValueError("Codex did not produce a dedicated final result")
        try:
            text = result_bytes.decode("utf-8")
            decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
            value, end = decoder.raw_decode(text)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Codex final result is not strict JSON") from exc
        if text[end:].strip() or not isinstance(value, dict):
            raise ValueError("Codex final result must be one JSON object")
        return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")
