"""Public version-three research commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

from mathresearch.contracts.research_request import ResearchRequest, build_request_payload
from mathresearch.contracts.validation import ValidationError
from mathresearch.errors import (ExitCode, InvalidInvocationError, RunLockedError,
                                 RunStoreError)
from .engine import answer_research_gate, initialize, run_research
from .events import ResearchSnapshot
from .store import load_research_status


_RESULT_KEYS = ("run_status", "answer_status", "model_calls_used", "tool_calls_used",
                "report_path", "gate_id", "reason")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvalidInvocationError(message)


def add_research_command(commands: Any) -> None:
    parser = commands.add_parser("research", help="create and run bounded research workflows")
    parser.add_argument("research_args", nargs=argparse.REMAINDER)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="mathresearch research", description="Run bounded, durable research workflows.")
    commands = parser.add_subparsers(dest="research_command", required=True)

    init = commands.add_parser("init", help="initialize a research request")
    source = init.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path, help="complete version-three request JSON")
    source.add_argument("--question", help="exact research question")
    init.add_argument("--objective", choices=("answer", "prove", "investigate"))
    init.add_argument("--mode", choices=("quick", "deep", "research"))
    init.add_argument("--run-id")
    init.add_argument("--run-dir", required=True, type=Path)
    init.add_argument("--model")
    init.add_argument("--goal")
    init.add_argument("--context")
    init.add_argument("--constraint", action="append", default=[])
    init.add_argument("--json", action="store_true", dest="json_output")

    for name, help_text in (("run", "advance or resume a research run"),
                            ("status", "show durable research status")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--run-dir", required=True, type=Path)
        sub.add_argument("--json", action="store_true", dest="json_output")
    respond = commands.add_parser("respond", help="answer an open human evidence gate")
    respond.add_argument("--run-dir", required=True, type=Path)
    respond.add_argument("--response", required=True, type=Path, help="version-three gate response JSON")
    respond.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _result(snapshot: ResearchSnapshot, run_dir: Path) -> dict[str, Any]:
    assessment = snapshot.final_assessment
    answer_status = assessment.get("answer_status") if isinstance(assessment, Mapping) else None
    report = run_dir / "report.md"
    return {
        "run_status": snapshot.status,
        "answer_status": answer_status,
        "model_calls_used": snapshot.model_calls_used,
        "tool_calls_used": snapshot.tool_calls_used,
        "report_path": str(report.resolve()) if report.is_file() else None,
        "gate_id": snapshot.pending_gate.get("gate_id") if snapshot.pending_gate else None,
        "reason": snapshot.reason,
    }


def _emit(payload: Mapping[str, Any], json_output: bool, *, stream: Any = None) -> None:
    stream = stream or sys.stdout
    if json_output:
        print(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), file=stream)
        return
    for key, value in payload.items():
        print(f"{key}: {value if value is not None else 'null'}", file=stream)


def _exit_for(snapshot: ResearchSnapshot) -> int:
    if snapshot.status == "awaiting_human":
        return int(ExitCode.AWAITING_HUMAN)
    if snapshot.status == "budget_exhausted":
        return int(ExitCode.BUDGET_EXHAUSTED)
    if snapshot.status == "incomplete" and snapshot.reason == "user_cancelled":
        return int(ExitCode.CANCELLED)
    if snapshot.status in {"blocked", "incomplete"}:
        return int(ExitCode.BLOCKED)
    return int(ExitCode.SUCCESS)


def _invalid(message: str, *, json_output: bool) -> int:
    payload = {key: None for key in _RESULT_KEYS}
    payload["reason"] = message
    _emit(payload, json_output, stream=sys.stderr)
    return int(ExitCode.INVALID_INVOCATION)


def _store_error(error: RunStoreError, *, run_dir: Path, json_output: bool) -> int:
    payload = {key: None for key in _RESULT_KEYS}
    payload["run_status"] = "locked" if isinstance(error, RunLockedError) else "blocked"
    payload["report_path"] = str((run_dir / "report.md").resolve()) if (run_dir / "report.md").is_file() else None
    payload["reason"] = f"{error.code}: {error}"
    _emit(payload, json_output, stream=sys.stderr)
    return int(error.exit_code)


def _request_from_args(arguments: argparse.Namespace) -> dict[str, Any]:
    flags = (arguments.objective, arguments.mode, arguments.run_id, arguments.model)
    if arguments.request is not None:
        if any(value is not None for value in flags) or arguments.goal is not None or arguments.context is not None or arguments.constraint:
            raise InvalidInvocationError("--request cannot be combined with question-building options")
        try:
            return ResearchRequest.from_json(json.loads(arguments.request.read_text(encoding="utf-8"))).to_json()
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise InvalidInvocationError(f"invalid research request: {error}") from error
    missing = [name for name in ("objective", "mode", "run_id", "model") if getattr(arguments, name) is None]
    if missing:
        raise InvalidInvocationError("question form requires --" + ", --".join(missing))
    payload = build_request_payload(run_id=arguments.run_id, question=arguments.question,
        objective=arguments.objective, mode=arguments.mode, model=arguments.model,
        goal=arguments.goal, context=arguments.context, constraints=arguments.constraint)
    return ResearchRequest.from_json(payload).to_json()


def _initialize(arguments: argparse.Namespace) -> int:
    try:
        payload = _request_from_args(arguments)
        with tempfile.TemporaryDirectory(prefix="mathresearch-request-") as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            snapshot = initialize(request_path, arguments.run_dir)
    except InvalidInvocationError as error:
        return _invalid(str(error), json_output=arguments.json_output)
    except RunStoreError as error:
        return _store_error(error, run_dir=arguments.run_dir, json_output=arguments.json_output)
    except OSError as error:
        return _store_error(RunStoreError(f"research storage error: {error}"),
                            run_dir=arguments.run_dir, json_output=arguments.json_output)
    result = _result(snapshot, arguments.run_dir)
    if not arguments.json_output:
        _emit({"mode": snapshot.request.mode, "objective": snapshot.request.objective,
               "capabilities": dict(snapshot.request.capabilities)}, False, stream=sys.stderr)
    _emit(result, arguments.json_output)
    return int(ExitCode.SUCCESS)


def _run_state(snapshot: ResearchSnapshot, run_dir: Path, *, json_output: bool,
               before_decision_count: int = 0) -> int:
    payload = _result(snapshot, run_dir)
    if not json_output:
        for decision in snapshot.decisions[before_decision_count:]:
            action = decision.get("action") or {}
            print(f"research: {decision.get('reason_code')} {action.get('role', '')} {action.get('id', '')}".rstrip(), file=sys.stderr)
    _emit(payload, json_output)
    return _exit_for(snapshot)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except InvalidInvocationError as error:
        return _invalid(str(error), json_output="--json" in (argv or sys.argv[1:]))
    if arguments.research_command == "init":
        return _initialize(arguments)
    response: Mapping[str, Any] | None = None
    if arguments.research_command == "respond":
        try:
            decoded = json.loads(arguments.response.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return _invalid(f"invalid response JSON: {error}", json_output=arguments.json_output)
        if not isinstance(decoded, Mapping):
            return _invalid("gate response must be a JSON object", json_output=arguments.json_output)
        response = decoded
    try:
        if arguments.research_command == "status":
            snapshot = load_research_status(arguments.run_dir)
            return _run_state(snapshot, arguments.run_dir, json_output=arguments.json_output)
        if arguments.research_command == "run":
            prior = load_research_status(arguments.run_dir)
            snapshot = run_research(arguments.run_dir)
            return _run_state(snapshot, arguments.run_dir, json_output=arguments.json_output,
                               before_decision_count=len(prior.decisions))
        assert response is not None
        snapshot = answer_research_gate(arguments.run_dir, response)
        if snapshot.status not in {"complete", "incomplete", "blocked", "budget_exhausted"}:
            snapshot = run_research(arguments.run_dir)
        return _run_state(snapshot, arguments.run_dir, json_output=arguments.json_output)
    except InvalidInvocationError as error:
        return _invalid(str(error), json_output=arguments.json_output)
    except RunStoreError as error:
        return _store_error(error, run_dir=arguments.run_dir, json_output=arguments.json_output)
    except OSError as error:
        return _store_error(RunStoreError(f"research storage error: {error}"),
                            run_dir=arguments.run_dir, json_output=arguments.json_output)
    except ValidationError as error:
        return _invalid(str(error), json_output=arguments.json_output)
    except KeyboardInterrupt:
        payload = {key: None for key in _RESULT_KEYS}
        payload["run_status"] = "incomplete"
        payload["reason"] = "operation interrupted"
        _emit(payload, arguments.json_output, stream=sys.stderr)
        return int(ExitCode.CANCELLED)
