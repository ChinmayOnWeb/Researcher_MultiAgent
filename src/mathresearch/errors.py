"""Shared error types and stable command exit codes."""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path
from typing import ClassVar


class ExitCode(IntEnum):
    SUCCESS = 0
    AWAITING_HUMAN = 10
    BLOCKED = 11
    BUDGET_EXHAUSTED = 12
    INVALID_INVOCATION = 20
    CANCELLED = 21
    RUN_LOCKED = 22
    RUN_STORE_ERROR = 23


class InvalidInvocationError(ValueError):
    """Raised when command-line arguments cannot be accepted."""


class RunStoreError(RuntimeError):
    """Raised when durable run storage cannot complete an operation."""

    code: ClassVar[str] = "run_store_error"
    exit_code: ClassVar[ExitCode] = ExitCode.RUN_STORE_ERROR


class RunLockedError(RunStoreError):
    """Raised when another process currently holds a run's OS lock."""

    code: ClassVar[str] = "run_locked"
    exit_code: ClassVar[ExitCode] = ExitCode.RUN_LOCKED

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        super().__init__(f"run is locked: {run_dir}")


class RunNotFoundError(RunStoreError):
    """Raised when status is requested for a run directory that does not exist."""

    code: ClassVar[str] = "run_not_found"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        super().__init__(f"run not found: {run_dir}")


class RunUninitializedError(RunStoreError):
    """Raised when a run has no committed initialization event yet."""

    code: ClassVar[str] = "run_uninitialized"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        super().__init__(f"run is uninitialized: {run_dir}")


class RunCorruptError(RunStoreError):
    """Raised when durable run evidence cannot be safely replayed."""

    code: ClassVar[str] = "run_corrupt"

    def __init__(self, run_dir: Path, reason: str) -> None:
        self.run_dir = run_dir
        self.reason = reason
        super().__init__(f"run is corrupt: {run_dir}: {reason}")
