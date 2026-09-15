"""Provider-neutral boundary for one short-lived worker process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class WorkerInput:
    stage: str
    prompt: str
    output_schema: Mapping[str, Any]


@dataclass(frozen=True)
class LaunchSpec:
    argv: tuple[str, ...]
    stdin: bytes
    cwd: Path
    result_file: Path | None


@dataclass(frozen=True)
class WorkerOutput:
    outcome: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    payload: Mapping[str, Any] | None
    error: str | None


class Adapter(Protocol):
    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec: ...

    def decode(self, stdout: bytes, result_bytes: bytes | None) -> Mapping[str, Any]: ...
