"""Coordinator-owned fixed quick workflow over short-lived provider workers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from typing import Any

from .adapters.base import Adapter, WorkerInput, WorkerOutput
from .contracts.quick import QuickState, STAGES, WorkflowEvent, validate_stage_result
from .contracts.records import RunRequest
from .contracts.validation import ValidationError
from .reporting import render_quick_report
from .run_store import LockedRun, open_locked_run
from .worker_process import execute_worker


_CAPABILITIES = {"reasoning": True, "browsing": False, "file_mutation": False, "shell": False, "experiments": False}


def run_quick(run_dir: Path, adapter: Adapter, *, adapter_id: str, executable: Path, model: str | None,
              timeout_seconds: int = 180) -> QuickState:
    """Start or safely resume the four-stage quick graph under one durable lock."""
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValidationError("timeout_seconds", "must be a positive integer")
    with open_locked_run(run_dir) as locked:
        _validate_request(locked.request)
        if not isinstance(locked.state, QuickState):
            if len(locked.events) != 1:
                raise ValidationError("workflow", "unsupported_workflow: initialize a new quick run")
            _preflight(adapter)
            _append_config(locked, adapter_id, executable, model)
        elif locked.state.status in {"complete", "blocked", "budget_exhausted"}:
            _check_configuration(locked, adapter_id, executable, model)
            return locked.state
        else:
            _check_configuration(locked, adapter_id, executable, model)

        while isinstance(locked.state, QuickState) and locked.state.status not in {"complete", "blocked", "budget_exhausted"}:
            stage = locked.state.current_stage
            if stage is None:
                return locked.state
            history = _history(locked)
            finished = history["finished"].get(stage)
            if finished is not None:
                if finished["outcome"] != "succeeded":
                    return _stop(locked, "blocked", f"workflow_blocked: {stage} worker {finished['outcome']}: {finished['error']}")
                # A committed normalized result is authoritative; never decode logs/relaunch.
                _apply_stage_disposition(locked, stage, finished["result"])
                continue
            if stage in history["intended"]:
                return _stop(locked, "blocked", f"workflow_blocked: interrupted {stage} attempt; initialize a new run")
            remaining = _remaining_seconds(locked.request, locked.state)
            if remaining is not None and remaining <= 0:
                return _stop(locked, "budget_exhausted", "budget_exhausted: elapsed time budget reached")
            if locked.state.accepted_submission_count >= locked.request.budgets.max_accepted_submissions:
                return _stop(locked, "budget_exhausted", "budget_exhausted: accepted submission budget reached")
            _preflight(adapter)
            packet = _packet(locked.request, stage, history["accepted"])
            _append(locked, "quick_attempt_intended", {"stage": stage, "attempt": 1, "packet": packet})
            call_timeout = min(timeout_seconds, remaining) if remaining is not None else timeout_seconds
            output = _run_worker(adapter, stage, packet, call_timeout)
            stdout_hash = locked.write_capture(stage, 1, "stdout.bin", output.stdout)
            stderr_hash = locked.write_capture(stage, 1, "stderr.log", output.stderr)
            result, outcome, error = _normalise_output(stage, output, history["accepted"])
            _append(locked, "quick_attempt_finished", {"stage": stage, "attempt": 1, "outcome": outcome,
                "exit_code": output.exit_code, "stdout_sha256": stdout_hash, "stderr_sha256": stderr_hash,
                "result": result, "error": error})
            if outcome != "succeeded":
                return _stop(locked, "blocked", f"workflow_blocked: {stage} worker {outcome}: {error}")
            _apply_stage_disposition(locked, stage, result)
        return locked.state  # pragma: no cover - reducer makes this unreachable


def _run_worker(adapter: Adapter, stage: str, packet: Mapping[str, Any], timeout_seconds: int) -> WorkerOutput:
    task = WorkerInput(stage, _prompt(stage, packet), packet["output_schema"])
    with tempfile.TemporaryDirectory(prefix="mathresearch-quick-") as scratch:
        return execute_worker(adapter, task, scratch=Path(scratch), timeout_seconds=timeout_seconds)


def _preflight(adapter: Adapter) -> None:
    """Confirm provider availability only when configuration or launch is pending."""
    preflight = getattr(adapter, "preflight", None)
    if preflight is None:
        return
    try:
        preflight()
    except (OSError, ValueError, TypeError) as exc:
        raise ValidationError("adapter", f"adapter_unavailable: {exc}") from exc


def _validate_request(request: RunRequest) -> None:
    if request.mode != "quick" or request.stakes != "ordinary" or request.learning_mode:
        raise ValidationError("request", "unsupported_workflow: MVP requires mode=quick, stakes=ordinary, learning_mode=false")
    unsupported = sorted(name for name, enabled in request.capabilities.items() if enabled and name != "reasoning")
    if unsupported:
        raise ValidationError("capabilities", f"unsupported_workflow: unavailable capabilities requested: {', '.join(unsupported)}")


def _append_config(locked: LockedRun, adapter_id: str, executable: Path, model: str | None) -> None:
    if not adapter_id or not isinstance(adapter_id, str): raise ValidationError("adapter", "must be a nonempty string")
    if model is not None and (not isinstance(model, str) or not model): raise ValidationError("model", "must be a nonempty string or null")
    _append(locked, "quick_configured", {"adapter": adapter_id, "executable": str(executable), "model": model,
        "protocol_version": "1", "capabilities": _CAPABILITIES, "stages": list(STAGES)})


def _check_configuration(locked: LockedRun, adapter_id: str, executable: Path, model: str | None) -> None:
    config = next((event.body for event in locked.events if isinstance(event, WorkflowEvent) and event.event_type == "quick_configured"), None)
    if config is None: raise ValidationError("workflow", "unsupported_workflow: quick configuration is missing")
    if config["adapter"] != adapter_id or config["executable"] != str(executable) or config["model"] != model:
        raise ValidationError("configuration", "unsupported_workflow: adapter, executable, or model conflicts with persisted configuration")


def _history(locked: LockedRun) -> dict[str, Any]:
    accepted: dict[str, Mapping[str, Any]] = {}; intended: set[str] = set(); finished: dict[str, Mapping[str, Any]] = {}
    for event in locked.events:
        if not isinstance(event, WorkflowEvent): continue
        if event.event_type == "quick_attempt_intended": intended.add(event.body["stage"])
        elif event.event_type == "quick_attempt_finished": finished[event.body["stage"]] = event.body
        elif event.event_type == "quick_stage_accepted":
            source = finished[event.body["stage"]]; accepted[event.body["stage"]] = source["result"]
    return {"accepted": accepted, "intended": intended, "finished": finished}


def _packet(request: RunRequest, stage: str, accepted: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    inputs = {name: accepted[name] for name in STAGES[:STAGES.index(stage)]}
    return {"stage": stage, "request": request.to_json(), "inputs": inputs, "output_schema": _schema(stage), "capabilities": dict(_CAPABILITIES)}


def _schema(stage: str) -> dict[str, Any]:
    # The durable contracts remain the authority; this is the provider-facing JSON schema.
    properties: dict[str, Any] = {"frame": {"framed_question": {"type": "string"}, "success_criteria": {"type": "array"}, "terms": {"type": "array"}, "assumptions": {"type": "array"}, "missing_inputs": {"type": "array"}, "stakes_assessment": {"type": "string"}},
        "investigate": {"answer": {"type": "string"}, "claims": {"type": "array"}, "alternatives": {"type": "array"}, "limitations": {"type": "array"}},
        "verify": {"checks": {"type": "array"}, "disposition": {"enum": ["pass", "inconclusive", "fail"]}, "limitations": {"type": "array"}},
        "explain": {"summary": {"type": "string"}, "explanation": {"type": "string"}, "conclusion": {"enum": ["supported", "inconclusive"]}, "limitations": {"type": "array"}}}[stage]
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def _prompt(stage: str, packet: Mapping[str, Any]) -> str:
    import json
    return (f"Return exactly one JSON object matching the supplied schema for stage '{stage}'. "
            "You are a bounded worker. You cannot schedule tasks, alter coordinator state, or claim external tools.\n"
            + json.dumps(packet, ensure_ascii=False, separators=(",", ":")))


def _normalise_output(stage: str, output: WorkerOutput, accepted: Mapping[str, Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, str, str | None]:
    if output.outcome != "succeeded" or output.payload is None:
        return None, output.outcome if output.outcome != "succeeded" else "failed", output.error or "provider returned no structured result"
    try:
        return validate_stage_result(stage, output.payload, investigate=accepted.get("investigate"), verify=accepted.get("verify")), "succeeded", None
    except ValidationError as exc:
        return None, "failed", f"adapter_protocol_error: {exc}"


def _apply_stage_disposition(locked: LockedRun, stage: str, result: Mapping[str, Any]) -> QuickState:
    if stage == "frame" and result["missing_inputs"]:
        return _stop(locked, "blocked", "workflow_blocked: Frame requires missing inputs")
    if stage == "frame" and any(word in result["stakes_assessment"].lower() for word in ("escalat", "significant", "high")):
        return _stop(locked, "blocked", "workflow_blocked: Frame requires stakes escalation")
    if stage == "verify" and result["disposition"] == "fail":
        return _stop(locked, "blocked", "workflow_blocked: verification failed")
    _append(locked, "quick_stage_accepted", {"stage": stage, "attempt": 1})
    if stage != "explain": return locked.state  # type: ignore[return-value]
    accepted = _history(locked)["accepted"]
    return _append(locked, "quick_completed", {"report_markdown": render_quick_report(locked.request, accepted)})  # type: ignore[return-value]


def _stop(locked: LockedRun, status: str, reason: str) -> QuickState:
    return _append(locked, "quick_stopped", {"status": status, "reason": reason})  # type: ignore[return-value]


def _append(locked: LockedRun, kind: str, body: Mapping[str, Any]) -> QuickState:
    previous = locked.events[-1].occurred_at
    at = max(datetime.now(timezone.utc), previous + timedelta(microseconds=1))
    return locked.append(WorkflowEvent(locked.request.run_id, at, len(locked.events) + 1, kind, body))  # type: ignore[return-value]


def _remaining_seconds(request: RunRequest, state: QuickState) -> int | None:
    limit = request.budgets.elapsed_time_seconds
    if limit is None: return None
    elapsed = (datetime.now(timezone.utc) - state.initialized_at).total_seconds()
    return max(0, int(limit - elapsed))
