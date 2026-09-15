"""Codex CLI adapter for the locally verified 0.154.0 noninteractive interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from .base import LaunchSpec, WorkerInput


class CodexAdapter:
    """Use a fresh, ephemeral Codex process with a dedicated structured result file.

    The quick profile disables every locally verified native tool route that
    could execute commands or reach external systems, and ignores ambient
    config and policy files for every worker process.
    """

    protocol_version = "codex-exec-0.154.0"
    capabilities: Mapping[str, bool] = {
        "web_search": False,
        "file_mutation": False,
        "external_mcp_config": False,
        "shell_execution": False,
    }
    _DISABLED_FEATURES = ("shell_tool", "browser_use", "computer_use", "apps")

    def __init__(self, executable: Path, model: str | None = None) -> None:
        self.executable = Path(executable)
        self.model = model
        self._preflight_done = False

    def preflight(self) -> None:
        """Confirm that the installed CLI exposes every native disable control.

        This check never submits a prompt.  It checks the feature inventory and
        asks the parser to accept the complete noninteractive control set before
        a coordinator records any worker intent.
        """
        if self._preflight_done:
            return
        inventory = self._run_preflight(
            (str(self.executable), *self._disable_arguments(), "features", "list")
        )
        states = {
            feature: re.search(
                rf"^{re.escape(feature)}\s+\S+\s+(true|false)\s*$",
                inventory.stdout,
                flags=re.MULTILINE,
            )
            for feature in self._DISABLED_FEATURES
        }
        missing = [feature for feature, state in states.items() if state is None]
        if missing:
            raise ValueError(
                "Codex cannot enforce the quick MVP disabled-tool profile; "
                f"feature inventory is missing: {', '.join(missing)}"
            )
        enabled = [
            feature
            for feature, state in states.items()
            if state is not None and state.group(1) != "false"
        ]
        if enabled:
            raise ValueError(
                "Codex cannot enforce the quick MVP disabled-tool profile; "
                f"features must be disabled: {', '.join(enabled)}"
            )
        self._run_preflight(
            tuple([str(self.executable), *self._control_arguments(), "exec", "--ignore-user-config", "--ignore-rules", "--help"])
        )
        self._preflight_done = True

    def _run_preflight(self, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Codex capability preflight failed: {exc}") from exc
        if result.returncode != 0:
            raise ValueError(
                "Codex cannot enforce the quick MVP disabled-tool profile: "
                f"preflight command exited {result.returncode}: {result.stderr.strip()}"
            )
        return result

    @classmethod
    def _disable_arguments(cls) -> tuple[str, ...]:
        arguments: list[str] = []
        for feature in cls._DISABLED_FEATURES:
            arguments.extend(("--disable", feature))
        return tuple(arguments)

    @classmethod
    def _control_arguments(cls) -> tuple[str, ...]:
        arguments = ["--strict-config", *cls._disable_arguments()]
        arguments.extend(("--ask-for-approval", "never", "--sandbox", "read-only"))
        return tuple(arguments)

    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec:
        root = Path(os.path.abspath(scratch))
        schema_path = root / "output-schema.json"
        result_path = root / "result.json"
        with schema_path.open("x", encoding="utf-8") as schema_file:
            schema_file.write(json.dumps(task.output_schema, sort_keys=True, separators=(",", ":"), allow_nan=False))
        argv: list[str] = [
            str(self.executable), *self._control_arguments(), "exec", "--skip-git-repo-check", "--ephemeral",
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
