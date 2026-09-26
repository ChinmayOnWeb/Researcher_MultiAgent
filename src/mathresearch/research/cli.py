"""Public research commands for durable request versions three and four."""

from __future__ import annotations

import argparse
import difflib
import hashlib
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
from .prompts import PROMPT_VERSION, build_prompt, structural_repair_prompt
from .contracts import result_schema, validate_result
from .provider import (check_provider_observation, count_session_id_markers,
    create_research_provider, parse_provider_observation)
from mathresearch.worker_process import execute_worker
from .store import load_research_status
from .evaluation import (EvaluationStore, load_cases, make_manifest, run_paired_trials,
                         write_json, _read_json)
from mathresearch.structured_output import semantic_artifact, validate_payload, validation_issue


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
    source.add_argument("--request", type=Path, help="complete version-three or version-four request JSON")
    source.add_argument("--question", help="exact research question")
    init.add_argument("--objective", choices=("answer", "prove", "investigate"))
    init.add_argument("--mode", choices=("quick", "deep", "research"))
    init.add_argument("--execution-policy", choices=("fixed", "sequential_review", "adaptive"),
                      default="fixed")
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
    evaluate.add_argument("--model", default="gpt-5.6-terra")
    evaluate.add_argument("--effort", choices=("high", "medium"), default="medium",
                          help="reasoning effort selected on the effort control; frozen per comparison")
    evaluate.add_argument("--case-id", action="append",
                          help="restrict this evaluation to a named case; repeat for a bounded smoke set")
    evaluate.add_argument("--condition", choices=("paired", "repair-paired", "architecture", "baseline", "baseline_repair",
        "sequential_review", "pipeline", "adaptive"), default="paired",
                          help="run strict paired evaluation, repair-enabled baseline versus pipeline, or one condition")
    evaluate.add_argument("--replicates", type=int, default=3,
                          help="paired repetitions per selected case (default: 3)")
    evaluate.add_argument("--live", action="store_true", help="request provider-backed trials")
    evaluate.add_argument("--dry-run-manifest", action="store_true",
                          help="freeze schedule and worst-case resource projection without provider calls")
    evaluate.add_argument("--max-provider-calls", type=int)
    evaluate.add_argument("--max-wall-seconds", type=int)
    evaluate.add_argument("--max-session-usage-percent", type=float,
                          help="maximum percentage-point drop in the 5-hour quota remaining, from the saved start reading")
    evaluate.add_argument("--prepare-grading-packets", action="store_true",
                          help="freeze condition-blind packets for existing trial outputs")
    evaluate.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _promote_live_authorization(manifest_path: Path, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Record an explicit live resume of a previously dry-run manifest."""
    if manifest.get("execution_authorization") != "dry_run_only":
        return manifest
    promoted = dict(manifest)
    promoted["execution_authorization"] = "live_explicit"
    write_json(manifest_path, promoted)
    return promoted


def _evaluate(arguments: argparse.Namespace) -> int:
    if arguments.live:
        if arguments.max_provider_calls is None or arguments.max_wall_seconds is None:
            return _invalid("live evaluation requires explicit --max-provider-calls and --max-wall-seconds limits",
                            json_output=arguments.json_output)
        if arguments.max_provider_calls < 1 or arguments.max_wall_seconds < 1:
            return _invalid("live caps must be positive explicit values",
                            json_output=arguments.json_output)
    if arguments.dry_run_manifest and arguments.live:
        return _invalid("--dry-run-manifest cannot be combined with --live",
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
        out_manifest_path = arguments.out_dir / "manifest.json"
        saved_manifest = _read_json(out_manifest_path) if out_manifest_path.exists() else None
        quick_cases = [case for case in cases if case["mode"] == "quick"]
        if arguments.condition in {"repair-paired", "baseline_repair", "sequential_review", "adaptive"} and quick_cases:
            # A mixed corpus can resume an arm that its saved per-case schedule
            # excludes for Quick cases. New schedules still reject unsupported arms.
            scheduled_by_case = (saved_manifest or {}).get("conditions_by_case", {})
            quick_is_excluded = bool(saved_manifest) and all(
                arguments.condition not in scheduled_by_case.get(case["id"],
                    saved_manifest.get("conditions", ())) for case in quick_cases)
            eligible_deep_cases = [case for case in cases if case["mode"] != "quick" and
                arguments.condition in scheduled_by_case.get(case["id"],
                    (saved_manifest or {}).get("conditions", ()))]
            if not quick_is_excluded or not eligible_deep_cases:
                raise ValidationError("condition", "this comparison requires Deep or Research cases; Quick supports only the fixed single-answer workflow")
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[3],
            capture_output=True, text=True, check=False, timeout=10)
        git_sha = git.stdout.strip() if git.returncode == 0 else "unknown"
        requested_conditions = (("baseline_repair", "pipeline") if arguments.condition == "repair-paired"
            else ("baseline", "sequential_review", "pipeline") if arguments.condition == "architecture"
            else ("baseline", "pipeline") if arguments.condition == "paired"
            else (arguments.condition,))
        conditions_by_case = None
        if arguments.condition == "architecture" and any(case["mode"] == "quick" for case in cases):
            conditions_by_case = {case["id"]: ("baseline", "pipeline")
                if case["mode"] == "quick" else requested_conditions for case in cases}
        if out_manifest_path.exists():
            manifest = saved_manifest
            requested_conditions = tuple(manifest.get("conditions", ()))
            if arguments.condition == "repair-paired" and not {"baseline_repair", "pipeline"}.issubset(requested_conditions):
                raise ValidationError("condition", "repair-paired is not in the saved schedule")
            if arguments.condition == "architecture" and not {"baseline", "sequential_review", "pipeline"}.issubset(requested_conditions):
                raise ValidationError("condition", "architecture comparison is not in the saved schedule")
            if arguments.condition not in {"paired", "repair-paired", "architecture"} and arguments.condition not in requested_conditions:
                raise ValidationError("condition", "selected condition is not in the saved schedule")
            if arguments.condition not in {"paired", "repair-paired", "architecture"}:
                scheduled_by_case = manifest.get("conditions_by_case", {})
                eligible_cases = [case for case in cases if arguments.condition in
                    scheduled_by_case.get(case["id"], requested_conditions)]
                if not eligible_cases:
                    raise ValidationError("condition", "selected condition is not scheduled for any selected case")
            if (manifest.get("cases_hash") != cases_hash or manifest.get("rubric_hash") != rubric_hash or
                    manifest.get("case_ids") != [case["id"] for case in cases]):
                raise ValidationError("manifest", "saved corpus or rubric differs from current inputs")
            if manifest.get("model") != arguments.model or manifest.get("effort") != arguments.effort:
                raise ValidationError("manifest", "saved model or effort differs from the requested run")
            if manifest.get("replicates") != arguments.replicates:
                raise ValidationError("manifest", "replicate count differs from the saved schedule")
            caps = manifest["caps"]
            if arguments.live and (arguments.max_provider_calls != caps["max_provider_calls"] or
                    arguments.max_wall_seconds != caps["max_wall_seconds"]):
                raise ValidationError("caps", "live caps must match the saved manifest when resuming")
            if arguments.live and arguments.max_session_usage_percent is not None and \
                    arguments.max_session_usage_percent != caps["max_session_usage_delta_percent"]:
                raise ValidationError("caps", "session usage allowance must match the saved manifest when resuming")
        else:
            caps = {"max_provider_calls": arguments.max_provider_calls if arguments.max_provider_calls is not None else 1,
                    "max_wall_seconds": arguments.max_wall_seconds if arguments.max_wall_seconds is not None else 1,
                    "max_session_usage_delta_percent": (
                        arguments.max_session_usage_percent
                        if arguments.max_session_usage_percent is not None else 10)}
            manifest = make_manifest(cases=cases, cases_hash=cases_hash, rubric_hash=rubric_hash,
                model=arguments.model, effort=arguments.effort, git_sha=git_sha,
                max_provider_calls=caps["max_provider_calls"],
                max_wall_seconds=caps["max_wall_seconds"],
                max_session_usage_delta_percent=caps["max_session_usage_delta_percent"],
                replicates=arguments.replicates, conditions=requested_conditions,
                conditions_by_case=conditions_by_case)
            if arguments.dry_run_manifest:
                projection = manifest["resource_projection"]
                if (arguments.max_provider_calls is not None and
                        arguments.max_provider_calls < projection["provider_calls_worst_case"]):
                    raise ValidationError("max_provider_calls", "dry-run cap is below the projected worst case")
                if (arguments.max_wall_seconds is not None and
                        arguments.max_wall_seconds < projection["wall_seconds_worst_case"]):
                    raise ValidationError("max_wall_seconds", "dry-run cap is below the projected worst case")
                manifest["caps"]["max_provider_calls"] = (arguments.max_provider_calls
                    if arguments.max_provider_calls is not None else projection["provider_calls_worst_case"])
                manifest["caps"]["max_wall_seconds"] = (arguments.max_wall_seconds
                    if arguments.max_wall_seconds is not None else projection["wall_seconds_worst_case"])
                manifest["execution_authorization"] = "dry_run_only"
            elif arguments.live:
                manifest["execution_authorization"] = "live_explicit"
        if arguments.live and manifest.get("execution_authorization") == "dry_run_only":
            manifest = _promote_live_authorization(out_manifest_path, manifest)
        store = EvaluationStore(arguments.out_dir, manifest)
        run_result = None
        if arguments.live:
            selected_conditions = None if arguments.condition in {"paired", "repair-paired", "architecture"} else {arguments.condition}
            run_result = run_paired_trials(cases, store,
                trial_runner=lambda case, condition, inputs, trial_dir, timeout:
                    _run_evaluation_trial(case, condition, inputs, trial_dir, timeout, manifest),
                usage_checkpoint=None, selected_case_ids=set(requested_case_ids) if requested_case_ids else None,
                selected_conditions=selected_conditions)
        comparison = store.finalize(store.grades(),
            deep_case_ids={case["id"] for case in cases if case["mode"] != "quick"},
            quick_case_ids={case["id"] for case in cases if case["mode"] == "quick"},
            required_replicates=int(manifest["replicates"]))
        grading_packets = None
        if arguments.prepare_grading_packets:
            rubric_text = (arguments.cases / "rubric.md").read_text(encoding="utf-8")
            grading_packets = store.prepare_grading_packets(cases, rubric_text)
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        return _invalid(f"evaluation preparation failed: {error}", json_output=arguments.json_output)
    payload = {"comparison_status": comparison["comparison_status"],
               "trial_count": comparison["trial_count"], "grade_count": comparison["grade_count"],
               "manifest_path": str((arguments.out_dir / "manifest.json").resolve()),
               "comparison_path": str((arguments.out_dir / "comparison.json").resolve()),
               "reason": ("live trials stopped: " + str(run_result["stopped_reason"]) if run_result and run_result["stopped_reason"]
                          else "live trial outputs require independent semantic grades" if arguments.live
                          else "dry-run manifest prepared; no provider calls were made" if arguments.dry_run_manifest
                          else "offline evaluation initialized; no provider calls were made"),
               "session_usage_monitoring": "disabled_by_user" if arguments.live else "not_applicable"}
    if arguments.dry_run_manifest:
        payload["resource_projection"] = manifest["resource_projection"]
    if grading_packets is not None:
        payload["grading_packets"] = grading_packets
    if run_result:
        payload["trial_conditions_recorded"] = len(run_result["trial_conditions_recorded"])
        payload["provider_calls_reserved"] = run_result["provider_calls_reserved"]
        payload["wall_seconds_observed"] = run_result["wall_seconds_observed"]
    _emit(payload, arguments.json_output)
    if run_result and run_result["stopped_reason"]:
        reason = run_result["stopped_reason"]
        return int(ExitCode.CANCELLED if reason == "user_cancelled" else
                   ExitCode.BUDGET_EXHAUSTED if reason in {"session_usage_cap_reached", "wall_time_cap_reached"}
                   else ExitCode.BLOCKED)
    return int(ExitCode.SUCCESS)


def _prompt_session_usage(case_id: str, replicate: int, condition: str,
                          maximum: float = 10.0) -> float | None:
    print(f"Current 5-hour Codex quota remaining percentage before {case_id}/{replicate}/{condition}? "
          f"Enter the remaining percentage (0-100). The evaluator stops after a {maximum:g}-point drop "
          "from its saved starting reading. Read the current dashboard; do not reuse an earlier reading. "
          "Enter blank to stop. This is a manual checkpoint; monitor usage during the trial too.",
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
    payload = build_request_payload(run_id=(
        f"eval-{case['id']}-r{pair_inputs['replicate']}-{condition.replace('_', '-')}"),
        question=case["question"], objective=case["objective"], mode=case["mode"],
        model=manifest["model"], execution_policy={
            "sequential_review": "sequential_review", "adaptive": "adaptive"}.get(condition, "fixed"))
    payload["provider"]["reasoning_effort"] = manifest["effort"]
    if condition in {"pipeline", "sequential_review", "adaptive"}:
        payload["budgets"]["max_repairs"] = manifest["retry_policy"][condition][
            "structural_retries_by_mode"][case["mode"]]
    payload["sources"] = sources
    capability_entry = manifest.get("capability_policy", {}).get(case["id"], {})
    payload["capabilities"] = capability_entry.get("conditions", {}).get(condition,
        case.get("capabilities", {"fetch_sources": False,
            "math_checks": bool(case.get("checks"))}))
    if not payload["capabilities"]["math_checks"]:
        payload["constraints"] = list(payload.get("constraints", [])) + [
            "Do not propose computational checks; return an empty proposed_checks list."]
    payload["budgets"]["max_wall_seconds"] = min(payload["budgets"]["max_wall_seconds"], timeout_seconds)
    payload["budgets"]["per_call_seconds"] = min(180, payload["budgets"]["max_wall_seconds"])
    request = ResearchRequest.from_json(payload)
    if condition in {"pipeline", "sequential_review", "adaptive"}:
        run_dir = trial_dir / "run"
        request_file = trial_dir / "request.json"
        request_file.write_text(json.dumps(request.to_json(), ensure_ascii=False), encoding="utf-8")
        initialize(request_file, run_dir)
        worker_tmp = trial_dir / "worker-tmp"
        worker_tmp.mkdir(parents=True, exist_ok=True)
        snapshot = run_research(run_dir, scratch_parent=worker_tmp)
        # Smoke evaluations are noninteractive. Continue only through gates
        # that explicitly allow a limited, qualified run; never supply sources
        # or turn missing evidence into verification.
        gate_responses = 0
        while snapshot.status == "awaiting_human" and snapshot.pending_gate is not None:
            gate = snapshot.pending_gate
            if "continue_limited" not in gate.get("allowed_response", []):
                break
            gate_responses += 1
            if gate_responses > request.budgets["max_model_calls"]:
                break
            response = {"schema_version": 3, "record_type": "research_gate_response",
                        "gate_id": gate["gate_id"],
                        "response_id": f"smoke-continue-{gate['gate_id']}",
                        "decision": "continue_limited", "text": None, "sources": []}
            snapshot = answer_research_gate(run_dir, response)
            snapshot = run_research(run_dir, scratch_parent=worker_tmp)
        report_path = run_dir / "report.md"
        report = report_path.read_text(encoding="utf-8") if report_path.is_file() else None
        telemetry = [item for action_id, item in snapshot.action_telemetry.items()
                     if snapshot.actions[action_id]["kind"] == "worker"]
        observed_models = {item.get("model_observed") for item in telemetry}
        observed_efforts = {item.get("effort_observed") for item in telemetry}
        errors = [str(item["error"]) for item in snapshot.outcomes.values() if item.get("error")]
        protocol_invalid = any(item.get("outcome") == "protocol_error"
                               for item in snapshot.outcomes.values())
        semantic_action = next(((action_id, item) for action_id, item in reversed(
            list(snapshot.outcomes.items())) if item.get("semantic_artifact")), (None, {}))
        semantic_text = semantic_action[1].get("semantic_artifact")
        semantic_attempt = next((item for item in reversed(list(snapshot.attempts.values()))
            if item.get("action_id") == semantic_action[0] and
            item.get("semantic_artifact") == semantic_text), {})
        return {"status": "complete" if snapshot.status == "complete" else "failed",
                "provider_calls": snapshot.model_calls_used, "report": report,
                "tool_calls_used": snapshot.tool_calls_used,
                "artifact_sha256": semantic_attempt.get("raw_result_sha256"),
                "semantic_availability": "available" if semantic_text else "unavailable",
                "semantic_artifact": semantic_text,
                "protocol_validity": ("valid" if snapshot.status == "complete" else
                    "invalid" if protocol_invalid else "unavailable"),
                "final_status": (snapshot.final_assessment.get("answer_status")
                    if isinstance(snapshot.final_assessment, Mapping) else snapshot.status),
                "cost_usd": None,
                "error": "; ".join(errors) or (snapshot.reason if snapshot.status != "complete" else None),
                "observed_model": next(iter(observed_models)) if len(observed_models) == 1 else None,
                "observed_effort": next(iter(observed_efforts)) if len(observed_efforts) == 1 else None,
                "input_tokens": None, "output_tokens": None,
                "failure_class": ("provider_usage_limit" if any(
                    marker in ("; ".join(errors)).lower() for marker in
                    ("usage limit", "rate limit", "quota exceeded", "too many requests"))
                    else None),
                "observed_session_markers": (None if snapshot.pending_attempt_id else
                    sum(item.get("session_id_marker_count", 0) for item in snapshot.attempts.values()))}

    source_map = {item["id"]: SourceInput.from_json(item, field="evaluation.source",
        fetch_sources=False).to_json() for item in sources}
    packet = {"version": PROMPT_VERSION, "role": "answer", "action_id": "baseline-answer",
        "objective": case["objective"], "question": case["question"], "goal": None,
        "context": None, "constraints": [], "audience": "unspecified", "sources": source_map,
        "tool_results": {}, "inputs": {}, "additional_user_input": [],
        "output_schema": result_schema("answer", PROMPT_VERSION)}
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
    output = execute_worker(adapter, WorkerInput("baseline", prompt, result_schema("answer", PROMPT_VERSION)),
        scratch=scratch, timeout_seconds=worker_timeout)
    (trial_dir / "stdout.bin").write_bytes(output.stdout)
    (trial_dir / "stderr.log").write_bytes(output.stderr)
    (trial_dir / "provider-result.bin").write_bytes(output.raw_result or b"")
    initial_output = output
    write_json(trial_dir / "provider-result.json", {
        "outcome": output.outcome, "exit_code": output.exit_code,
        "error": output.error, "payload": output.payload})
    observed = parse_provider_observation(output.stderr)
    mismatch = check_provider_observation(request, observed)
    provider_calls = 0 if output.outcome == "launch_failed" else 1
    report = None
    status = "failed"
    result = None
    validation_errors: list[Mapping[str, Any]] = []
    if mismatch is not None:
        validation_errors = [{"path": "$", "category": "provider_configuration_mismatch",
            "found": None, "expected_namespace": None, "available_ids": [],
            "explanation": mismatch, "deterministic_repair_permitted": False,
            "model_repair_permitted": False}]
    elif output.outcome == "protocol_error":
        validation_errors = [output.validation_details or {"path": "$",
            "category": "invalid_json", "found": None,
            "expected_namespace": "one JSON object", "available_ids": [],
            "explanation": output.error or "invalid structured output",
            "deterministic_repair_permitted": False, "model_repair_permitted": True}]
    elif output.outcome == "succeeded" and output.payload is not None:
        gate = validate_payload(output.payload, lambda value: validate_result(
            "answer", value, prompt_version=PROMPT_VERSION))
        if gate.protocol_status == "valid": result = gate.value
        else: validation_errors = list(gate.issues)

    if (result is None and validation_errors and condition == "baseline_repair" and
            validation_errors[0].get("model_repair_permitted") is not False):
        rejected_output = output
        repair_prompt = structural_repair_prompt(prompt,
            output.payload if isinstance(output.payload, Mapping) else None,
            validation_errors[0], raw_output=output.raw_result,
            require_change_log=True)
        remaining = int(timeout_seconds - (time.monotonic() - preflight_started))
        if remaining > 0:
            repair_scratch = trial_dir / "repair-scratch"
            repair_scratch.mkdir(parents=True, exist_ok=True)
            repaired = execute_worker(adapter, WorkerInput(
                "baseline-structural-repair", repair_prompt, result_schema("answer", PROMPT_VERSION)),
                scratch=repair_scratch, timeout_seconds=min(180, remaining))
            if repaired.outcome != "launch_failed": provider_calls += 1
            (trial_dir / "repair.stdout.bin").write_bytes(repaired.stdout)
            (trial_dir / "repair.stderr.log").write_bytes(repaired.stderr)
            (trial_dir / "provider-result-repair.bin").write_bytes(repaired.raw_result or b"")
            write_json(trial_dir / "provider-result-repair.json", {
                "outcome": repaired.outcome, "exit_code": repaired.exit_code,
                "error": repaired.error, "payload": repaired.payload})
            before_text = (json.dumps(rejected_output.payload, ensure_ascii=False,
                indent=2, sort_keys=True).splitlines() if isinstance(rejected_output.payload, Mapping)
                else (rejected_output.raw_result or b"").decode("utf-8", "replace").splitlines())
            after_text = json.dumps(repaired.payload, ensure_ascii=False, indent=2,
                sort_keys=True).splitlines() if repaired.payload is not None else []
            (trial_dir / "repair-review.diff").write_text("\n".join(difflib.unified_diff(
                before_text, after_text, fromfile="rejected-payload", tofile="corrected-payload",
                lineterm="")) + "\n", encoding="utf-8")
            output = repaired
            observed = parse_provider_observation(repaired.stderr)
            mismatch = check_provider_observation(request, observed)
            validation_errors = []
            if mismatch is not None:
                validation_errors = [{"path": "$", "category": "provider_configuration_mismatch",
                    "found": None, "expected_namespace": None, "available_ids": [],
                    "explanation": mismatch, "deterministic_repair_permitted": False,
                    "model_repair_permitted": False}]
            elif repaired.outcome == "protocol_error":
                validation_errors = [repaired.validation_details or {"path": "$",
                    "category": "invalid_json", "found": None,
                    "expected_namespace": "one JSON object", "available_ids": [],
                    "explanation": repaired.error or "invalid repaired output",
                    "deterministic_repair_permitted": False, "model_repair_permitted": True}]
            elif repaired.outcome == "succeeded" and repaired.payload is not None:
                def validate_repair(value: Mapping[str, Any]) -> dict[str, Any]:
                    checked = validate_result("answer", value, prompt_version=PROMPT_VERSION)
                    old_change_log = (rejected_output.payload.get("change_log", [])
                        if isinstance(rejected_output.payload, Mapping) else [])
                    if not checked["change_log"] or checked["change_log"] == old_change_log:
                        raise ValidationError("change_log", "structural repair must record its change explanation")
                    return checked
                gate = validate_payload(repaired.payload, validate_repair)
                if gate.protocol_status == "valid": result = gate.value
                else: validation_errors = list(gate.issues)

    if result is None:
        review_payload = (output.payload if isinstance(output.payload, Mapping)
                          else initial_output.payload)
        semantic_source = output if output.semantic_artifact else initial_output
        combined_error = "; ".join(value for value in (
            "; ".join(str(issue.get("explanation", "")) for issue in validation_errors),
            mismatch, output.error) if value)
        error_lower = combined_error.lower()
        failure_class = ("provider_usage_limit" if any(marker in error_lower for marker in
            ("usage limit", "rate limit", "quota exceeded", "too many requests"))
            else "schema_rejection" if validation_errors or output.outcome == "protocol_error"
            else "provider_failure")
        raw_bytes = semantic_source.raw_result or b""
        return {"status": "failed", "provider_calls": provider_calls, "report": None,
                "cost_usd": None, "observed_model": observed.get("model"),
                "observed_effort": observed.get("effort"), "input_tokens": None,
                "output_tokens": None, "provider_outcome": output.outcome,
                "provider_exit_code": output.exit_code,
                "observed_session_markers": count_session_id_markers(initial_output.stderr) +
                    (count_session_id_markers(output.stderr) if output is not initial_output else 0),
                "artifact_sha256": hashlib.sha256(raw_bytes).hexdigest()
                    if semantic_source.semantic_artifact else None,
                "protocol_validity": "invalid" if failure_class == "schema_rejection" else "unavailable",
                "semantic_availability": "available" if semantic_source.semantic_artifact else "unavailable",
                "semantic_artifact": semantic_source.semantic_artifact,
                "failure_class": failure_class,
                "final_status": review_payload.get("question_status")
                    if isinstance(review_payload, Mapping) else None,
                "error": combined_error or "baseline returned no valid result"}
        lines = ["# " + ("Repair-enabled baseline" if condition == "baseline_repair" else "Single-call baseline"), "",
            f"Requested model: `{manifest['model']}`; requested effort: `{manifest['effort']}`.",
            "This is one unaudited answer. The paired pipeline received the same question, "
            "source text, and evaluator-supplied check transcripts.", "", "## Inputs", ""]
        for source in sources:
            lines.extend([f"### {source['title']}", "", f"Source ID: `{source['id']}`", ""])
            lines.extend("> " + line for line in source["text"].splitlines())
            lines.append("")
        lines.extend(["## Answer", "", f"Question status: `{result['question_status']}`", ""])
        lines.extend("> " + line for line in result["answer"].splitlines())
        lines.extend(["", "## Structured draft", "", "```json",
                      json.dumps(result, ensure_ascii=False, indent=2), "```"])
        report = "\n".join(lines) + "\n"
        status = "complete"
    if report is not None:
        (trial_dir / "report.md").write_text(report, encoding="utf-8")
    semantic_source = output if output.semantic_artifact else initial_output
    raw_bytes = semantic_source.raw_result or b""
    return {"status": status, "provider_calls": provider_calls,
            "tool_calls_used": 0,
            "report": report,
            "artifact_sha256": hashlib.sha256(raw_bytes).hexdigest()
                if semantic_source.semantic_artifact else None,
            "protocol_validity": "valid" if status == "complete" else
                "invalid" if output.outcome == "protocol_error" or mismatch is not None else "unavailable",
            "semantic_availability": "available" if semantic_source.semantic_artifact else "unavailable",
            "semantic_artifact": semantic_source.semantic_artifact,
            "final_status": (output.payload.get("question_status")
                             if isinstance(output.payload, Mapping) else None),
            "failure_class": ("provider_usage_limit" if any(marker in
                " ".join((str(output.error or ""), output.stderr.decode("utf-8", "replace"))).lower()
                for marker in ("usage limit", "rate limit", "quota exceeded", "too many requests"))
                else None),
            "observed_session_markers": count_session_id_markers(output.stderr),
            "cost_usd": None, "observed_model": observed.get("model"),
            "observed_effort": observed.get("effort"),
            "input_tokens": None, "output_tokens": None,
            "provider_outcome": output.outcome, "provider_exit_code": output.exit_code,
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
        if any(value is not None for value in flags) or arguments.goal is not None or arguments.context is not None or arguments.constraint or arguments.execution_policy != "fixed":
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
        goal=arguments.goal, context=arguments.context, constraints=arguments.constraint,
        execution_policy=arguments.execution_policy)
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
