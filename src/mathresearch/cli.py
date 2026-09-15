"""Public command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .adapters.codex import CodexAdapter
from .adapters.discovery import discover_built_in_adapters
from .adapters.base import Adapter
from .contracts.quick import QuickState
from .contracts.run import RunState
from .contracts.validation import ValidationError
from .dispatch import DispatchResult, dispatch_fake_frame
from .errors import ExitCode, InvalidInvocationError, RunStoreError
from .process_runner import ProcessRunnerError
from .quick_workflow import run_quick
from .run_store import initialize_run, load_run_status


INVALID_INVOCATION_MESSAGE = (
    "invalid command-line arguments; run 'mathresearch --help' for usage"
)


class AdapterUnavailableError(RuntimeError):
    """A requested provider cannot satisfy the quick MVP's capability boundary."""


def resolve_quick_provider(
    adapter_id: str, model: str | None
) -> tuple[Adapter, str, Path, str | None]:
    """Resolve the one public quick provider without invoking it during parsing.

    Discovery deliberately distinguishes an executable on ``PATH`` from a
    provider that can enforce the MVP's no-shell capability profile.
    """
    if adapter_id != "codex":
        raise ValidationError("adapter", f"unsupported_workflow: unsupported adapter '{adapter_id}'")
    availability = next(
        (item for item in discover_built_in_adapters() if item.adapter_id == adapter_id),
        None,
    )
    if availability is None or not availability.available or availability.executable is None:
        reason = availability.reason if availability is not None else "adapter is not installed"
        raise AdapterUnavailableError(reason or "adapter is not installed")
    executable = Path(availability.executable)
    return CodexAdapter(executable, model=model), adapter_id, executable, model


class CliArgumentParser(argparse.ArgumentParser):
    """Argument parser that leaves error formatting to the CLI boundary."""

    def error(self, message: str) -> None:
        raise InvalidInvocationError(message)


def build_parser() -> argparse.ArgumentParser:
    """Create the parser without probing any external agent installation."""
    parser = CliArgumentParser(
        prog="mathresearch",
        description="Coordinate durable, multi-agent research runs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", required=True
    )
    doctor_parser = commands.add_parser(
        "doctor", help="inspect installed agent CLI adapters"
    )
    doctor_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="emit JSON"
    )
    init_parser = commands.add_parser(
        "init", help="durably initialize a research run from a request"
    )
    init_parser.add_argument(
        "--request", required=True, type=Path, help="path to the request JSON"
    )
    init_parser.add_argument(
        "--run-dir", required=True, type=Path, help="destination directory for the run"
    )
    init_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="emit JSON"
    )
    status_parser = commands.add_parser(
        "status", help="replay and report a durable research run"
    )
    status_parser.add_argument(
        "--run-dir", required=True, type=Path, help="directory containing the run"
    )
    status_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="emit JSON"
    )
    dispatch_parser = commands.add_parser(
        "dispatch", help="execute the deterministic local Frame worker"
    )
    dispatch_parser.add_argument(
        "--run-dir", required=True, type=Path, help="directory containing the run"
    )
    dispatch_parser.add_argument(
        "--adapter", required=True, help="execution adapter (only 'fake' is available)"
    )
    dispatch_parser.add_argument(
        "--timeout-seconds", type=_positive_timeout_seconds,
        help="positive execution timeout in seconds"
    )
    dispatch_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="emit JSON"
    )
    run_parser = commands.add_parser(
        "run", help="start or resume the fixed four-stage quick research workflow"
    )
    run_parser.add_argument(
        "--run-dir", required=True, type=Path, help="directory containing the run"
    )
    run_parser.add_argument(
        "--adapter", required=True, help="quick workflow provider (only 'codex')"
    )
    run_parser.add_argument(
        "--model", help="optional provider-specific model selection"
    )
    run_parser.add_argument(
        "--timeout-seconds", type=_positive_timeout_seconds, default=180,
        help="positive per-stage timeout in seconds (default: 180)",
    )
    run_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="emit JSON"
    )
    return parser


def _positive_timeout_seconds(value: str) -> int:
    """Parse the deliberately narrow whole-second worker timeout."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except InvalidInvocationError as error:
        print(
            json.dumps(
                {"code": "invalid_invocation", "message": INVALID_INVOCATION_MESSAGE},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return int(ExitCode.INVALID_INVOCATION)
    if arguments.command == "doctor":
        payload = {
            "adapters": [adapter.to_json() for adapter in discover_built_in_adapters()]
        }
        if arguments.json_output:
            print(json.dumps(payload, sort_keys=True))
        else:
            for adapter in payload["adapters"]:
                availability = "available" if adapter["available"] else "unavailable"
                print(f"{adapter['id']}: {availability}")
        return int(ExitCode.SUCCESS)

    try:
        if arguments.command == "init":
            state = initialize_run(arguments.request, arguments.run_dir)
        elif arguments.command == "status":
            state = load_run_status(arguments.run_dir)
        elif arguments.command == "dispatch":
            if arguments.adapter != "fake":
                return _report_error(
                    code="unsupported_adapter",
                    message=f"adapter is not available in this milestone: {arguments.adapter}",
                    exit_code=ExitCode.INVALID_INVOCATION,
                    json_output=arguments.json_output,
                )
            dispatch = dispatch_fake_frame(
                arguments.run_dir, timeout_seconds=arguments.timeout_seconds
            )
        else:
            adapter, adapter_id, executable, model = resolve_quick_provider(
                arguments.adapter, arguments.model
            )
            quick_state = run_quick(
                arguments.run_dir,
                adapter,
                adapter_id=adapter_id,
                executable=executable,
                model=model,
                timeout_seconds=arguments.timeout_seconds,
            )
    except KeyboardInterrupt:
        return _report_error(
            code="cancelled",
            message="operation cancelled",
            exit_code=ExitCode.CANCELLED,
            json_output=arguments.json_output,
        )
    except AdapterUnavailableError as error:
        return _report_error(
            code="adapter_unavailable",
            message=str(error),
            exit_code=ExitCode.BLOCKED,
            json_output=arguments.json_output,
        )
    except RunStoreError as error:
        return _report_error(
            code=error.code,
            message=str(error),
            exit_code=error.exit_code,
            json_output=arguments.json_output,
        )
    except ProcessRunnerError as error:
        return _report_error(
            code="dispatch_failed",
            message=str(error),
            exit_code=ExitCode.BLOCKED,
            json_output=arguments.json_output,
        )
    except ValidationError as error:
        code, exit_code = _workflow_validation_disposition(error)
        return _report_error(
            code=code,
            message=str(error),
            exit_code=exit_code,
            json_output=arguments.json_output,
        )

    if arguments.command == "dispatch":
        return _report_dispatch(dispatch, json_output=arguments.json_output)
    if arguments.command == "run":
        return _report_quick_run(quick_state, arguments.run_dir, json_output=arguments.json_output)

    _report_state(state, json_output=arguments.json_output)
    return int(ExitCode.SUCCESS)


def _report_state(state: RunState, *, json_output: bool) -> None:
    """Render one successful run operation in machine or human form."""
    payload = state.to_json()
    if json_output:
        print(json.dumps(payload, sort_keys=True))
        return
    print(f"run_id: {payload['run_id']}")
    print(f"status: {payload['status']}")
    print(f"initialized_at: {payload['initialized_at']}")
    print(f"last_event_sequence: {payload['last_event_sequence']}")


def _workflow_validation_disposition(error: ValidationError) -> tuple[str, ExitCode]:
    """Map explicit quick-workflow validation markers to stable CLI errors."""
    if error.message.startswith("unsupported_workflow:"):
        return "unsupported_workflow", ExitCode.INVALID_INVOCATION
    if error.message.startswith("adapter_unavailable:"):
        return "adapter_unavailable", ExitCode.BLOCKED
    return RunStoreError.code, RunStoreError.exit_code


def _report_quick_run(
    state: QuickState, run_dir: Path, *, json_output: bool
) -> int:
    """Render terminal quick state without presenting a blocked workflow as success."""
    if state.status == "complete":
        report_path = str((run_dir / (state.report_path or "report.md")).resolve())
        payload = {
            "run_status": state.status,
            "accepted_submission_count": state.accepted_submission_count,
            "report_path": report_path,
        }
        if json_output:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"run_status: {payload['run_status']}")
            print(f"accepted_submission_count: {payload['accepted_submission_count']}")
            print(f"report_path: {payload['report_path']}")
        return int(ExitCode.SUCCESS)

    if state.status == "budget_exhausted":
        code, exit_code = "budget_exhausted", ExitCode.BUDGET_EXHAUSTED
    elif state.reason is not None and (
        "adapter_protocol_error:" in state.reason
        or "adapter protocol error:" in state.reason
    ):
        code, exit_code = "adapter_protocol_error", ExitCode.BLOCKED
    else:
        code, exit_code = "workflow_blocked", ExitCode.BLOCKED
    return _report_error(
        code=code,
        message=state.reason or f"quick workflow ended with status {state.status}",
        exit_code=exit_code,
        json_output=json_output,
    )


def _report_dispatch(result: DispatchResult, *, json_output: bool) -> int:
    """Render the durable disposition rather than implying every dispatch accepted work."""
    rejected = {"rejected", "already_rejected"}
    blocked = {"blocked_interrupted"}
    if result.status in rejected | blocked:
        code = "dispatch_rejected" if result.status in rejected else "dispatch_blocked"
        message = (
            "fake Frame dispatch was rejected"
            if result.status in rejected
            else "fake Frame dispatch is blocked by an interrupted attempt"
        )
        return _report_error(
            code=code,
            message=message,
            exit_code=ExitCode.BLOCKED,
            json_output=json_output,
        )
    payload = {"dispatch_status": result.status, "state": result.state.to_json()}
    if json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"dispatch_status: {result.status}")
        _report_state(result.state, json_output=False)
    return int(ExitCode.SUCCESS)


def _report_error(
    *, code: str, message: str, exit_code: ExitCode, json_output: bool
) -> int:
    """Render a stable command error and return its process exit code."""
    if json_output:
        print(json.dumps({"code": code, "message": message}, sort_keys=True), file=sys.stderr)
    else:
        print(f"{code}: {message}", file=sys.stderr)
    return int(exit_code)
