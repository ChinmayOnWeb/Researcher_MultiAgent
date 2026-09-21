"""Public version-three research commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from typing import Any, Mapping

from mathresearch.adapters.base import WorkerInput
from mathresearch.contracts.research_request import ResearchRequest, SourceInput, build_request_payload
from mathresearch.contracts.validation import ValidationError
from mathresearch.errors import (ExitCode, InvalidInvocationError, RunLockedError,
                                 RunStoreError)
from .engine import answer_research_gate, initialize, run_research
from .events import ResearchSnapshot
from .prompts import PROMPT_VERSION, build_prompt
from .contracts import result_schema, validate_result
from .provider import check_provider_observation, create_research_provider, parse_provider_observation
from mathresearch.worker_process import execute_worker
from .store import load_research_status
from .evaluation import EvaluationStore, load_cases, make_manifest, run_paired_trials


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
    evaluate = commands.add_parser("evaluate", help="prepare or inspect a paired quality evaluation")
    evaluate.add_argument("--cases", required=True, type=Path)
    evaluate.add_argument("--out-dir", required=True, type=Path)
    evaluate.add_argument("--model", required=True)
    evaluate.add_argument("--effort", choices=("high", "medium"), required=True,
                          help="reasoning effort selected on the effort control; frozen per comparison")
    evaluate.add_argument("--case-id", action="append",
                          help="restrict this evaluation to a named case; repeat for a bounded smoke set")
    evaluate.add_argument("--replicates", type=int, default=3,
                          help="paired repetitions per selected case (default: 3)")
    evaluate.add_argument("--live", action="store_true", help="request provider-backed trials")
    evaluate.add_argument("--max-provider-calls", type=int)
    evaluate.add_argument("--max-wall-seconds", type=int)
    evaluate.add_argument("--max-session-usage-percent", type=float,
                          help="maximum percentage-point drop in the 5-hour quota remaining, from the saved start reading")
    evaluate.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _evaluate(arguments: argparse.Namespace) -> int:
    if arguments.live:
        if (arguments.max_provider_calls is None or arguments.max_wall_seconds is None or
                arguments.max_session_usage_percent is None):
            return _invalid("live evaluation requires explicit --max-provider-calls, --max-wall-seconds, and --max-session-usage-percent limits",
                            json_output=arguments.json_output)
        if (arguments.max_provider_calls > 240 or arguments.max_wall_seconds > 7200 or
                arguments.max_session_usage_percent > 10 or arguments.max_provider_calls < 1 or
                arguments.max_wall_seconds < 1 or arguments.max_session_usage_percent <= 0):
            return _invalid("live caps cannot exceed Astra's 240 calls, 7200 seconds, and 10 percentage-point session usage allowance",
                            json_output=arguments.json_output)
    try:
        all_cases, cases_hash, rubric_hash = load_cases(arguments.cases)
        known_case_ids = {case["id"] for case in all_cases}
        requested_case_ids = arguments.case_id
        if requested_case_ids:
            if len(set(requested_case_ids)) != len(requested_case_ids):
                raise ValidationError("case_id", "must not contain duplicates")
            unknown_case_ids = set(requested_case_ids) - known_case_ids
            if unknown_case_ids:
                raise ValidationError("case_id", f"unknown case IDs: {', '.join(sorted(unknown_case_ids))}")
            selected_ids = set(requested_case_ids)
            cases = [case for case in all_cases if case["id"] in selected_ids]
        else:
            cases = all_cases
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[3],
            capture_output=True, text=True, check=False, timeout=10)
        git_sha = git.stdout.strip() if git.returncode == 0 else "unknown"
        manifest = make_manifest(cases=cases, cases_hash=cases_hash, rubric_hash=rubric_hash,
            model=arguments.model, effort=arguments.effort, git_sha=git_sha,
            max_provider_calls=arguments.max_provider_calls if arguments.live else 240,
            max_wall_seconds=arguments.max_wall_seconds if arguments.live else 7200,
            max_session_usage_delta_percent=arguments.max_session_usage_percent if arguments.live else 10,
            replicates=arguments.replicates)
        store = EvaluationStore(arguments.out_dir, manifest)
        run_result = None
        if arguments.live:
            run_result = run_paired_trials(cases, store,
                trial_runner=lambda case, condition, inputs, trial_dir, timeout:
                    _run_evaluation_trial(case, condition, inputs, trial_dir, timeout, manifest),
                usage_checkpoint=lambda case_id, replicate, condition:
                    _prompt_session_usage(case_id, replicate, condition,
                        manifest["caps"]["max_session_usage_delta_percent"]))
        comparison = store.finalize(store.grades(),
            deep_case_ids={case["id"] for case in cases if case["mode"] != "quick"},
            quick_case_ids={case["id"] for case in cases if case["mode"] == "quick"},
            required_replicates=int(manifest["replicates"]))
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        return _invalid(f"evaluation preparation failed: {error}", json_output=arguments.json_output)
    payload = {"comparison_status": comparison["comparison_status"],
               "trial_count": comparison["trial_count"], "grade_count": comparison["grade_count"],
               "manifest_path": str((arguments.out_dir / "manifest.json").resolve()),
               "comparison_path": str((arguments.out_dir / "comparison.json").resolve()),
               "reason": ("live trials stopped: " + str(run_result["stopped_reason"]) if run_result and run_result["stopped_reason"]
                          else "live trial outputs require independent semantic grades" if arguments.live
                          else "offline evaluation initialized; no provider calls were made")}
    if run_result:
        payload["trial_conditions_recorded"] = len(run_result["trial_conditions_recorded"])
        payload["provider_calls_reserved"] = run_result["provider_calls_reserved"]
        payload["wall_seconds_observed"] = run_result["wall_seconds_observed"]
    _emit(payload, arguments.json_output)
    return int(ExitCode.SUCCESS)


def _prompt_session_usage(case_id: str, replicate: int, condition: str,
                          maximum: float = 10.0) -> float | None:
    print(f"Current 5-hour Codex quota remaining percentage before {case_id}/{replicate}/{condition}? "
          f"Enter the remaining percentage (0-100). The evaluator stops after a {maximum:g}-point drop "
          "from its saved starting reading.",
          file=sys.stderr, flush=True)
    try:
        raw = input().strip()
        value = float(raw)
    except (EOFError, ValueError):
        return None
    return value


def _run_evaluation_trial(case: Mapping[str, Any], condition: str,
                          pair_inputs: Mapping[str, Any], trial_dir: Path,
                          timeout_seconds: int, manifest: Mapping[str, Any]) -> dict[str, Any]:
    sources = list(pair_inputs["source_inputs"])
    payload = build_request_payload(run_id=f"eval-{case['id']}-r{pair_inputs['replicate']}-{condition}",
        question=case["question"], objective=case["objective"], mode=case["mode"],
        model=manifest["model"])
    payload["provider"]["reasoning_effort"] = manifest["effort"]
    payload["sources"] = sources
    payload["capabilities"] = {"fetch_sources": False,
        "math_checks": case["mode"] != "quick"}
    payload["budgets"]["max_wall_seconds"] = min(payload["budgets"]["max_wall_seconds"], timeout_seconds)
    payload["budgets"]["per_call_seconds"] = min(180, payload["budgets"]["max_wall_seconds"])
    request = ResearchRequest.from_json(payload)
    if condition == "pipeline":
        run_dir = trial_dir / "run"
        request_file = trial_dir / "request.json"
        request_file.write_text(json.dumps(request.to_json(), ensure_ascii=False), encoding="utf-8")
        initialize(request_file, run_dir)
        snapshot = run_research(run_dir)
        report_path = run_dir / "report.md"
        report = report_path.read_text(encoding="utf-8") if report_path.is_file() else None
        telemetry = list(snapshot.action_telemetry.values())
        observed_models = {item.get("model_observed") for item in telemetry if item.get("model_observed")}
        observed_efforts = {item.get("effort_observed") for item in telemetry if item.get("effort_observed")}
        return {"status": "complete" if snapshot.status == "complete" else "failed",
                "provider_calls": snapshot.model_calls_used, "report": report,
                "cost_usd": None,
                "observed_model": next(iter(observed_models)) if len(observed_models) == 1 else None,
                "observed_effort": next(iter(observed_efforts)) if len(observed_efforts) == 1 else None,
                "input_tokens": None, "output_tokens": None}

    source_map = {item["id"]: SourceInput.from_json(item, field="evaluation.source",
        fetch_sources=False).to_json() for item in sources}
    packet = {"version": PROMPT_VERSION, "role": "answer", "action_id": "baseline-answer",
        "objective": case["objective"], "question": case["question"], "goal": None,
        "context": None, "constraints": [], "audience": "unspecified", "sources": source_map,
        "tool_results": {}, "inputs": {}, "additional_user_input": [],
        "output_schema": result_schema("answer")}
    prompt = build_prompt("answer", packet)
    preflight_started = time.monotonic()
    try:
        adapter = create_research_provider(request)
    except (OSError, ValueError, RuntimeError) as error:
        return {"status": "failed", "provider_calls": 0, "report": None,
                "cost_usd": None, "observed_model": None, "observed_effort": None,
                "error": f"provider preflight failed: {error}"}
    worker_timeout = min(180, int(timeout_seconds - (time.monotonic() - preflight_started)))
    if worker_timeout <= 0:
        return {"status": "failed", "provider_calls": 0, "report": None,
                "cost_usd": None, "observed_model": None, "observed_effort": None,
                "error": "wall-time budget expired during provider preflight"}
    scratch = trial_dir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    output = execute_worker(adapter, WorkerInput("baseline", prompt, result_schema("answer")),
        scratch=scratch, timeout_seconds=worker_timeout)
    observed = parse_provider_observation(output.stderr)
    mismatch = check_provider_observation(request, observed)
    report = None
    status = "failed"
    if output.outcome == "succeeded" and output.payload is not None and mismatch is None:
        try:
            result = validate_result("answer", output.payload)
        except ValidationError as error:
            return {"status": "failed", "provider_calls": 1, "report": None,
                    "cost_usd": None, "observed_model": observed.get("model"),
                    "observed_effort": observed.get("effort"),
                    "input_tokens": None, "output_tokens": None,
                    "error": f"baseline result schema error: {error}"}
        lines = ["# Single-call baseline", "",
            f"Requested model: `{manifest['model']}`; requested effort: `{manifest['effort']}`.",
            "This is one unaudited answer. The paired pipeline received the same question, "
            "source text, and evaluator-supplied check transcripts.", "", "## Inputs", ""]
        for source in sources:
            lines.extend([f"### {source['title']}", "", f"Source ID: `{source['id']}`", ""])
            lines.extend("> " + line for line in source["text"].splitlines())
            lines.append("")
        lines.extend(["## Answer", "", f"Question status: `{result['question_status']}`", ""])
        lines.extend("> " + line for line in result["answer"].splitlines())
        report = "\n".join(lines) + "\n"
        status = "complete"
    if report is not None:
        (trial_dir / "report.md").write_text(report, encoding="utf-8")
    return {"status": status, "provider_calls": 0 if output.outcome == "launch_failed" else 1,
            "report": report,
            "cost_usd": None, "observed_model": observed.get("model"),
            "observed_effort": observed.get("effort"),
            "input_tokens": None, "output_tokens": None,
            "error": mismatch or output.error}


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
    if arguments.research_command == "evaluate":
        return _evaluate(arguments)
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
