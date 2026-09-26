"""Durable bounded research coordinator."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from mathresearch.adapters.base import Adapter, WorkerInput, WorkerOutput
from mathresearch.contracts.validation import ValidationError
from mathresearch.research.broker import run_broker
from mathresearch.research.contracts import (OUTPUT_SCHEMA_VERSION, VALIDATOR_VERSION,
    validate_audit_for_draft, validate_result)
from mathresearch.research.events import ResearchEvent, ResearchSnapshot, canonical_json_bytes
from mathresearch.research.provenance import check_provenance
from mathresearch.research.prompts import build_packet, build_prompt, structural_repair_prompt
from mathresearch.research.provider import (check_provider_observation, create_research_provider,
    count_session_id_markers, parse_provider_observation, provider_configuration)
from mathresearch.research.reporting import render_log, render_report
from mathresearch.research.routing import Decision, assess_latest, next_decision
from mathresearch.research.store import LockedResearchRun, initialize_research, open_research_run
from mathresearch.structured_output import semantic_artifact, validate_payload, validation_issue
from mathresearch.worker_process import execute_worker


Now = Callable[[], datetime]


def _structural_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Return a JSON-path diff, including additions and removals."""
    missing = {"$missing": True}
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if key not in before:
                changes.append({"path": child, "before": missing, "after": after[key]})
            elif key not in after:
                changes.append({"path": child, "before": before[key], "after": missing})
            else:
                changes.extend(_structural_diff(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before):
                changes.append({"path": child, "before": missing, "after": after[index]})
            elif index >= len(after):
                changes.append({"path": child, "before": before[index], "after": missing})
            else:
                changes.extend(_structural_diff(before[index], after[index], child))
        return changes
    if before != after:
        return [{"path": path or "/", "before": before, "after": after}]
    return []


class ProviderFactory(Protocol):
    def __call__(self, request: Any, *, recorded_config: Mapping[str, Any] | None) -> Adapter: ...
FaultHook = Callable[[str, ResearchSnapshot], None]


def initialize(request_path: Path, run_dir: Path) -> ResearchSnapshot:
    """Create a durable research run from an exact request JSON file."""
    return initialize_research(Path(request_path), Path(run_dir))


def _utc(now: Now) -> str:
    value = now()
    if value.tzinfo is None:
        raise ValueError("engine clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _remaining(snapshot: ResearchSnapshot, now: Now) -> int:
    start = datetime.fromisoformat(snapshot.initialized_at.replace("Z", "+00:00"))
    deadline = start.timestamp() + snapshot.request.budgets["max_wall_seconds"]
    return math.floor(deadline - now().timestamp())


def _event(run: LockedResearchRun, kind: str, body: Mapping[str, Any], now: Now,
           *, occurred_at: str | None = None,
           after_event_persisted: Callable[[ResearchSnapshot], None] | None = None) -> ResearchSnapshot:
    item = ResearchEvent.from_json({"schema_version": 4, "record_type": "research_event",
        "sequence": run.snapshot.sequence + 1, "event_type": kind,
        "run_id": run.snapshot.request.run_id, "occurred_at": occurred_at or _utc(now), "body": dict(body)})
    return run.append(item, after_event_persisted=after_event_persisted)


def _decision_body(decision: Decision) -> dict[str, Any]:
    if decision.decision_id is None or decision.details is None:
        raise ValueError("routing decision is missing durable identifiers or details")
    event_kind = decision.kind if decision.kind in {"worker", "tool", "gate", "finish"} else "noop"
    return {"decision_id": decision.decision_id, "kind": event_kind,
            "reason_code": decision.reason_code, "action": decision.action,
            "details": dict(decision.details)}


def _finish_decision(snapshot: ResearchSnapshot, reason: str, status: str,
                     assessment: Mapping[str, Any], *, blockers: list[str] | None = None,
                     decision_id: str | None = None) -> Decision:
    details = {"selected_draft_id": snapshot.latest_draft_id, "audit_id": snapshot.latest_audit_id,
        "question_status": None, "blockers": (blockers or [])[:8],
        "finish_status": status, "round": min(2, snapshot.repairs_started)}
    if decision_id is None:
        decision_id = f"d{len(snapshot.decisions) + 1:04d}"
    return Decision("finish", reason, None, details, assessment=assessment, decision_id=decision_id)


def _assessment_for_stop(snapshot: ResearchSnapshot, reason: str) -> dict[str, Any]:
    if snapshot.latest_draft_id is None:
        result = assess_latest(snapshot)
        result["unresolved"] = [reason]
        return result
    return assess_latest(snapshot)


def _finalize(run: LockedResearchRun, decision: Decision, status: str,
              reason: str, now: Now, fault_hook: FaultHook | None) -> ResearchSnapshot:
    if decision.decision_id is None:
        decision = _finish_decision(run.snapshot, reason, status,
                                    decision.assessment or _assessment_for_stop(run.snapshot, reason))
    recorded = any(item.get("decision_id") == decision.decision_id for item in run.snapshot.decisions)
    if not recorded:
        run.append(ResearchEvent.from_json({"schema_version": 4, "record_type": "research_event",
            "sequence": run.snapshot.sequence + 1, "event_type": "decision_recorded",
            "run_id": run.snapshot.request.run_id, "occurred_at": _utc(now),
            "body": _decision_body(decision)}))
    if fault_hook: fault_hook("before_final_report", run.snapshot)
    assessment = dict(decision.assessment or _assessment_for_stop(run.snapshot, reason))
    finished_at = _utc(now)
    prospective = ResearchSnapshot(**(run.snapshot.__dict__ | {"status": status,
        "final_assessment": assessment, "reason": reason, "finished_at": finished_at}))
    body = {"status": status, "assessment": assessment, "reason": reason,
            "report_markdown": render_report(prospective), "log_markdown": render_log(prospective)}
    snapshot = _event(run, "research_finished", body, now, occurred_at=finished_at,
                      after_event_persisted=(lambda committed: fault_hook(
                          "after_final_event_persisted_before_projection", committed)) if fault_hook else None)
    if fault_hook: fault_hook("after_final_event", snapshot)
    return snapshot


def _open_gate(run: LockedResearchRun, decision: Decision, now: Now,
               fault_hook: FaultHook | None) -> ResearchSnapshot:
    if decision.gate is None: raise ValueError("gate decision is missing its gate payload")
    body = {"gate_id": decision.gate["gate_id"], "kind": decision.gate["kind"],
            "questions": list(decision.gate["questions"]),
            "allowed_response": list(decision.gate["allowed_response"])}
    resume_token = hashlib.sha256(body["gate_id"].encode("utf-8") + canonical_json_bytes(body)).hexdigest()
    run.append(ResearchEvent.from_json({"schema_version": 4, "record_type": "research_event",
        "sequence": run.snapshot.sequence + 1, "event_type": "gate_opened",
        "run_id": run.snapshot.request.run_id, "occurred_at": _utc(now),
        "body": body | {"resume_token": resume_token}}))
    if fault_hook: fault_hook("after_gate_opened", run.snapshot)
    return run.snapshot


def _configuration(adapter: Adapter) -> dict[str, Any]:
    method = getattr(adapter, "configuration_receipt", None)
    if method is not None:
        value = method()
    else:
        value = provider_configuration(adapter)  # type: ignore[arg-type]
    if not isinstance(value, Mapping): raise ValueError("provider returned no configuration receipt")
    config = dict(value)
    config.setdefault("schema_version", OUTPUT_SCHEMA_VERSION)
    config.setdefault("validator_version", VALIDATOR_VERSION)
    return config


def _validate_provider_config(snapshot: ResearchSnapshot, config: Mapping[str, Any],
                              recorded_config: Mapping[str, Any] | None) -> None:
    if config.get("model_requested") != snapshot.request.provider["model"]:
        raise ValueError("provider selected a model different from the immutable request")
    if config.get("effort_requested") != snapshot.request.provider["reasoning_effort"]:
        raise ValueError("provider selected an effort different from the immutable request")
    if recorded_config is not None and any(config.get(key) != value
            for key, value in recorded_config.items() if key != "prompt_version"):
        raise ValueError("provider configuration changed after initial configuration")


def _configure(run: LockedResearchRun, factory: ProviderFactory, now: Now,
               fault_hook: FaultHook | None) -> Adapter:
    adapter = factory(run.snapshot.request, recorded_config=None)
    preflight = getattr(adapter, "preflight", None)
    if preflight is not None: preflight()
    config = _configuration(adapter)
    from mathresearch.research.prompts import PROMPT_VERSION
    config["prompt_version"] = PROMPT_VERSION
    _validate_provider_config(run.snapshot, config, None)
    snapshot = _event(run, "provider_configured", config, now)
    if fault_hook: fault_hook("after_provider_configured", snapshot)
    return adapter


def _scope(action: Mapping[str, Any]) -> str:
    return f"Coordinator-authorized {action['role']} operation with exact validated arguments."


def _tool_packet(snapshot: ResearchSnapshot, action: Mapping[str, Any]) -> dict[str, Any]:
    return {"version": "broker-request-v1", "action_id": action["id"],
            "request": dict(action["payload"]), "capabilities": dict(snapshot.request.capabilities),
            "scope": _scope(action)}


def _tool_result(snapshot: ResearchSnapshot, action: Mapping[str, Any], scratch: Path,
                 remaining: int) -> tuple[WorkerOutput, Mapping[str, Any]]:
    descriptors = snapshot.source_descriptors or {source.id: source.to_json() for source in snapshot.request.sources}
    urls = {descriptor["url"] for descriptor in descriptors.values()
            if descriptor.get("kind") == "url" and isinstance(descriptor.get("url"), str)}
    receipt = run_broker(tool_id=action["id"], request=action["payload"],
        capabilities=snapshot.request.capabilities, descriptors=descriptors,
        authorized_urls=urls, scope=_scope(action), scratch=scratch,
        remaining_seconds=remaining)
    stdout = canonical_json_bytes(receipt)
    return WorkerOutput("succeeded", 0, stdout, b"", receipt, None,
        raw_result=stdout, protocol_status="valid"), receipt


def _telemetry(duration_ms: int, input_bytes: int, output_bytes: int,
               observed: Mapping[str, str | None] | None = None) -> dict[str, Any]:
    observed = observed or {"model": None, "effort": None}
    return {"duration_ms": max(0, duration_ms), "input_bytes": input_bytes,
            "output_bytes": output_bytes, "model_observed": observed.get("model"),
            "effort_observed": observed.get("effort"), "input_tokens": None,
            "output_tokens": None, "reasoning_tokens": None, "cost_usd": None}


def _execute_provider_attempt(run: LockedResearchRun, action: Mapping[str, Any], adapter: Adapter,
                              prompt: str, schema: Mapping[str, Any], scratch_parent: Path,
                              now: Now, monotonic: Callable[[], float], fault_hook: FaultHook | None,
                              *, parent_attempt_id: str | None = None,
                              retry_reason: str | None = None,
                              rejected_payload: Mapping[str, Any] | None = None,
                              validation_errors: Mapping[str, Any] | None = None) -> tuple[WorkerOutput, dict[str, Any], str, int]:
    snapshot = run.snapshot
    attempt_number = sum(1 for item in snapshot.attempts.values()
                         if item["action_id"] == action["id"]) + 1
    attempt_id = f"{action['id']}-a{attempt_number:02d}"
    prompt_bytes, schema_bytes = prompt.encode("utf-8"), canonical_json_bytes(schema)
    input_bytes = len(prompt_bytes) + len(schema_bytes)
    remaining = min(_remaining(snapshot, now), snapshot.request.budgets["per_call_seconds"])
    if snapshot.model_calls_used >= snapshot.request.budgets["max_model_calls"]:
        return WorkerOutput("launch_failed", None, b"", b"", None,
            "provider_attempt_budget_exhausted"), {"model": None, "effort": None}, attempt_id, 0
    if remaining <= 0:
        return WorkerOutput("launch_failed", None, b"", b"", None,
            "deadline_before_launch"), {"model": None, "effort": None}, attempt_id, 0
    if input_bytes > snapshot.request.budgets["max_input_bytes"]:
        return WorkerOutput("launch_failed", None, b"", b"", None,
            "attempt_input_exceeds_max_input_bytes"), {"model": None, "effort": None}, attempt_id, input_bytes
    snapshot = _event(run, "provider_attempt_intended", {
        "attempt_id": attempt_id, "action_id": action["id"],
        "parent_attempt_id": parent_attempt_id,
        "attempt_kind": "initial" if parent_attempt_id is None else "structural_repair",
        "retry_reason": retry_reason,
        "prompt_version": (action["payload"]["prompt_version"] if parent_attempt_id is None
                            else "structural-repair-v4"),
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "repair_errors": ([dict(validation_errors)] if isinstance(validation_errors, Mapping)
                           else list(validation_errors or [])),
        "input_bytes": input_bytes}, now)
    if fault_hook: fault_hook("after_provider_attempt_intent", snapshot)
    before = monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="research-attempt-", dir=str(scratch_parent),
                                          ignore_cleanup_errors=True) as scratch_name:
            raw = execute_worker(adapter, WorkerInput(
                stage=f"{action['role']}:{action.get('branch') or ''}",
                prompt=prompt, output_schema=schema), scratch=Path(scratch_name),
                timeout_seconds=remaining)
    except (OSError, ValueError, TypeError) as exc:
        raw = WorkerOutput("launch_failed", None, b"", b"", None, str(exc)[:4000])
    observed = parse_provider_observation(raw.stderr)
    mismatch = check_provider_observation(snapshot.request, observed)
    output = raw
    validation_errors: list[Mapping[str, Any]] = []
    if mismatch is not None:
        issue = {"path": "$", "category": "provider_configuration_mismatch", "found": None,
            "expected_namespace": None, "available_ids": [], "explanation": mismatch,
            "deterministic_repair_permitted": False, "model_repair_permitted": False}
        validation_errors.append(issue)
        output = WorkerOutput("protocol_error", raw.exit_code, raw.stdout, raw.stderr,
            raw.payload, mismatch, issue, raw.raw_result, "invalid",
            raw.semantic_artifact or semantic_artifact(raw.raw_result or b"", raw.payload))
    elif raw.outcome == "succeeded" and raw.payload is not None:
        packet = json.loads(snapshot.intent_packets[action["id"]])
        result_version = action["payload"]["prompt_version"]

        def validate_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
            checked_result = validate_result(action["role"], value,
                prompt_version=result_version)
            if parent_attempt_id is not None and action["role"] in {"answer", "branch", "synthesize", "revise"}:
                prior_log = list((rejected_payload or {}).get("change_log", []))
                if not checked_result["change_log"] or checked_result["change_log"] == prior_log:
                    raise ValidationError("change_log", "structural repair must record its change explanation")
            if action["role"] == "audit":
                validate_audit_for_draft(value, packet["inputs"]["draft"],
                    prompt_version=result_version)
            if action["role"] in {"answer", "branch", "synthesize", "revise"}:
                issues = check_provenance(value, packet["sources"], packet["tool_results"],
                    prompt_version=result_version)
                if issues: raise ValidationError("provenance", "; ".join(issues))
            return checked_result

        gate = validate_payload(raw.payload, validate_candidate)
        if gate.protocol_status == "invalid":
            issue = gate.issues[0]
            validation_errors.append(issue)
            output = WorkerOutput("protocol_error", raw.exit_code, raw.stdout, raw.stderr,
                raw.payload, f"structured output validation failed: {issue['explanation']}", issue,
                raw.raw_result, "invalid", raw.semantic_artifact or semantic_artifact(raw.raw_result or b"", raw.payload))
        else:
            output = WorkerOutput(raw.outcome, raw.exit_code, raw.stdout, raw.stderr,
                dict(gate.value), raw.error, raw.validation_details, raw.raw_result,
                "valid", raw.semantic_artifact or semantic_artifact(raw.raw_result or b"", raw.payload))
    elif raw.outcome == "protocol_error":
        details = raw.validation_details or {"path": "$", "category": "invalid_json",
            "found": None, "expected_namespace": "one JSON object", "available_ids": [],
            "explanation": raw.error or "provider output could not be parsed",
            "deterministic_repair_permitted": True, "model_repair_permitted": True}
        validation_errors.append(details)
        output = WorkerOutput("protocol_error", raw.exit_code, raw.stdout, raw.stderr,
            raw.payload, raw.error, details, raw.raw_result, "invalid",
            raw.semantic_artifact or semantic_artifact(raw.raw_result or b"", raw.payload))
    combined = " ".join(str(value or "") for value in (
        output.error, output.stderr.decode("utf-8", "replace"),
        output.stdout.decode("utf-8", "replace"))).lower()
    if re.search(r"usage limit|rate.?limit|too many requests|quota exceeded", combined):
        failure_class = "provider_usage_limit"
    elif output.outcome == "protocol_error":
        failure_class = "protocol_error"
    elif output.outcome == "timed_out":
        failure_class = "timeout"
    elif output.outcome not in {"succeeded", "launch_failed"}:
        failure_class = "provider_failure"
    else:
        failure_class = None
    stdout_digest = run.write_attempt_capture(action["id"], attempt_id, "stdout.bin", raw.stdout)
    stderr_digest = run.write_attempt_capture(action["id"], attempt_id, "stderr.log", raw.stderr)
    raw_result = raw.raw_result or b""
    raw_result_digest = run.write_attempt_capture(action["id"], attempt_id, "result.bin", raw_result)
    telemetry = _telemetry(int((monotonic() - before) * 1000), input_bytes,
                           len(raw.stdout) + len(raw.stderr), observed)
    repair_review = None
    if rejected_payload is not None:
        corrected = None if raw.payload is None else dict(raw.payload)
        repair_review = {"rejected_payload": dict(rejected_payload),
                         "corrected_payload": corrected,
                         "validation_errors": dict(validation_errors or {}),
                         "change_explanation": (next(iter(reversed(corrected.get("change_log", []))), None)
                             if corrected and isinstance(corrected.get("change_log"), list) else None)
                             or "Structural correction recorded in the JSON-path diff.",
                         "diff": [] if corrected is None else _structural_diff(rejected_payload, corrected)}
    completed = _event(run, "provider_attempt_finished", {
        "attempt_id": attempt_id, "outcome": output.outcome,
        "exit_code": output.exit_code, "stdout_sha256": stdout_digest,
        "stderr_sha256": stderr_digest, "error": output.error,
        "telemetry": telemetry, "failure_class": failure_class,
        "session_id_marker_count": count_session_id_markers(raw.stderr),
        "repair_review": repair_review,
        "raw_result_sha256": raw_result_digest,
        "protocol_status": output.protocol_status,
        "semantic_available": bool(output.semantic_artifact),
        "semantic_artifact": output.semantic_artifact,
        "validation_errors": validation_errors}, now)
    if fault_hook: fault_hook("after_provider_attempt_finished", completed)
    return output, observed, attempt_id, input_bytes


def _execute_action(run: LockedResearchRun, action: Mapping[str, Any], adapter: Adapter | None,
                    packet: Mapping[str, Any], scratch_parent: Path, remaining: int,
                    now: Now, monotonic: Callable[[], float], fault_hook: FaultHook | None) -> ResearchSnapshot:
    snapshot = run.snapshot
    packet_bytes = canonical_json_bytes(packet)
    if len(packet_bytes) > snapshot.request.budgets["max_input_bytes"]:
        raise ValidationError("max_input_bytes", "intended packet exceeds request limit")
    # Intent is committed before any child can start.
    snapshot = _event(run, "action_intended", {"action_id": action["id"],
        "packet": dict(packet), "packet_sha256": hashlib.sha256(packet_bytes).hexdigest()}, now)
    if fault_hook: fault_hook("after_intent", snapshot)
    remaining = min(_remaining(snapshot, now), snapshot.request.budgets["per_call_seconds"])
    before = monotonic()
    if remaining <= 0:
        output = WorkerOutput("launch_failed", None, b"", b"", None, "deadline_before_launch")
        observed = {"model": None, "effort": None}
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="research-action-", dir=str(scratch_parent),
                                              ignore_cleanup_errors=True) as scratch_name:
                scratch = Path(scratch_name)
                if action["kind"] == "worker":
                    if adapter is None: raise ValueError("worker launch requires a configured provider")
                    prompt = build_prompt(action["role"], packet)
                    output, observed, attempt_id, input_bytes = _execute_provider_attempt(
                        run, action, adapter, prompt, packet["output_schema"], scratch_parent,
                        now, monotonic, fault_hook)
                    attempts_input_bytes = input_bytes
                    if (output.outcome == "protocol_error" and output.error and
                            not (output.validation_details and
                                 output.validation_details.get("model_repair_permitted") is False)):
                        repair_details = output.validation_details or {"path": "$",
                            "category": "protocol_violation", "explanation": output.error,
                            "deterministic_repair_permitted": False,
                            "model_repair_permitted": True}
                        repair_prompt = structural_repair_prompt(prompt,
                            output.payload if isinstance(output.payload, Mapping) else None,
                            repair_details, raw_output=output.raw_result,
                            require_change_log=action["role"] in {"answer", "branch", "synthesize", "revise"})
                        first = output
                        repaired, observed, _, repair_input_bytes = _execute_provider_attempt(
                            run, action, adapter, repair_prompt, packet["output_schema"],
                            scratch_parent, now, monotonic, fault_hook,
                            parent_attempt_id=attempt_id, retry_reason=first.error,
                            rejected_payload=first.payload,
                            validation_errors=repair_details)
                        attempts_input_bytes += repair_input_bytes
                        output = WorkerOutput(repaired.outcome,
                            repaired.exit_code, first.stdout + b"\n[structural-repair]\n" + repaired.stdout,
                            first.stderr + b"\n[structural-repair]\n" + repaired.stderr,
                            repaired.payload if repaired.outcome == "succeeded" else None,
                            repaired.error, repaired.validation_details,
                            repaired.raw_result, repaired.protocol_status,
                            repaired.semantic_artifact or first.semantic_artifact)
                else:
                    output, _ = _tool_result(snapshot, action, scratch, remaining)
                    observed = {"model": None, "effort": None}
        except (OSError, ValueError, TypeError, ValidationError) as exc:
            output = WorkerOutput("protocol_error", None, b"", b"", None, str(exc)[:4000])
            observed = {"model": None, "effort": None}
    duration_ms = int((monotonic() - before) * 1000)
    stdout_digest = run.write_capture(action["id"], "stdout.bin", output.stdout)
    if fault_hook: fault_hook("after_stdout_capture", run.snapshot)
    stderr_digest = run.write_capture(action["id"], "stderr.log", output.stderr)
    if fault_hook: fault_hook("after_stderr_capture", run.snapshot)
    telemetry = _telemetry(duration_ms, locals().get("attempts_input_bytes", len(packet_bytes)),
                           len(output.stdout) + len(output.stderr), observed)
    event_status = output.outcome if output.outcome in {"succeeded", "failed", "timed_out", "cancelled", "launch_failed", "protocol_error"} else "failed"
    finished = _event(run, "action_finished", {"action_id": action["id"],
        "outcome": event_status, "exit_code": output.exit_code,
        "stdout_sha256": stdout_digest, "stderr_sha256": stderr_digest,
        "result": dict(output.payload) if event_status == "succeeded" and output.payload is not None else None,
        "error": output.error if event_status != "succeeded" else None,
        "protocol_status": output.protocol_status,
        "semantic_available": bool(output.semantic_artifact),
        "semantic_artifact": output.semantic_artifact,
        "telemetry": telemetry}, now)
    if fault_hook: fault_hook(f"after_{action.get('role')}_{action.get('branch') or ''}_finished", finished)
    return finished


def run_research(run_dir: Path, *, provider_factory: ProviderFactory | None = None,
                 now: Now | None = None, monotonic: Callable[[], float] = time.monotonic,
                 scratch_parent: Path | None = None, fault_hook: FaultHook | None = None,
                 max_transitions: int = 128) -> ResearchSnapshot:
    """Resume or advance a durable run until it waits, finishes, or blocks."""
    now = now or (lambda: datetime.now(timezone.utc))
    provider_factory = provider_factory or create_research_provider
    scratch_parent = Path(scratch_parent or tempfile.gettempdir())
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with open_research_run(Path(run_dir)) as run:
        adapter: Adapter | None = None
        pending_action_id = run.snapshot.pending_action_id
        pending_action_is_legacy = pending_action_id is not None and run.snapshot.actions[pending_action_id]["kind"] == "worker" and any(
            item.event_type == "action_intended" and item.body["action_id"] == pending_action_id
            and item.schema_version == 3 for item in run.events)
        pending_action_has_attempt_result = pending_action_id is not None and any(
            attempt.get("action_id") == pending_action_id for attempt in run.snapshot.attempts.values())
        if (run.snapshot.status not in {"complete", "incomplete", "blocked", "budget_exhausted"} and
                (run.snapshot.pending_attempt_id is not None or pending_action_is_legacy or
                 pending_action_has_attempt_result)):
            reason = "ambiguous_execution"
            decision = _finish_decision(run.snapshot, reason, "blocked",
                _assessment_for_stop(run.snapshot, reason), blockers=[
                    "A prior action or provider attempt has an unresolved durable execution boundary; it was not relaunched."])
            return _finalize(run, decision, "blocked", reason, now, fault_hook)
        for _ in range(max_transitions):
            decision = next_decision(run.snapshot)
            if decision.kind == "noop" or decision.kind == "await": return run.snapshot
            if decision.kind == "gate":
                run.append(ResearchEvent.from_json({"schema_version": 4, "record_type": "research_event",
                    "sequence": run.snapshot.sequence + 1, "event_type": "decision_recorded",
                    "run_id": run.snapshot.request.run_id, "occurred_at": _utc(now),
                    "body": _decision_body(decision)}))
                if fault_hook: fault_hook("after_gate_decision", run.snapshot)
                return _open_gate(run, decision, now, fault_hook)
            if decision.kind == "finish":
                return _finalize(run, decision, decision.details["finish_status"],
                                 decision.reason_code, now, fault_hook)
            if decision.kind not in {"worker", "tool", "resume"} or decision.action is None:
                raise ValueError(f"unsupported router decision: {decision.kind}")
            action = decision.action
            is_resuming = decision.kind == "resume"
            if _remaining(run.snapshot, now) <= 0:
                return _finalize(run, _finish_decision(run.snapshot, "budget_exhausted", "budget_exhausted",
                    _assessment_for_stop(run.snapshot, "deadline_before_launch")),
                    "budget_exhausted", "deadline_before_launch", now, fault_hook)
            if action["kind"] == "worker" and run.snapshot.provider_config is None:
                try:
                    adapter = _configure(run, provider_factory, now, fault_hook)
                except Exception as exc:
                    reason = "provider_preflight_failed"
                    failed = _finish_decision(run.snapshot, reason, "incomplete",
                        _assessment_for_stop(run.snapshot, reason), blockers=[str(exc)[:4000]])
                    return _finalize(run, failed, "incomplete", reason, now, fault_hook)
                if _remaining(run.snapshot, now) <= 0:
                    reason = "deadline_after_preflight"
                    expired = _finish_decision(run.snapshot, "budget_exhausted", "budget_exhausted",
                        _assessment_for_stop(run.snapshot, reason))
                    return _finalize(run, expired, "budget_exhausted", reason, now, fault_hook)
            elif action["kind"] == "worker" and adapter is None:
                try:
                    adapter = provider_factory(run.snapshot.request,
                                               recorded_config=run.snapshot.provider_config)
                    _validate_provider_config(run.snapshot, _configuration(adapter),
                                               run.snapshot.provider_config)
                except Exception as exc:
                    reason = "provider_unavailable_on_resume"
                    failed = _finish_decision(run.snapshot, reason, "incomplete",
                        _assessment_for_stop(run.snapshot, reason), blockers=[str(exc)[:4000]])
                    return _finalize(run, failed, "incomplete", reason, now, fault_hook)
                preflight = getattr(adapter, "preflight", None)
                if preflight is not None: preflight()
            if not is_resuming:
                run.append(ResearchEvent.from_json({"schema_version": 4, "record_type": "research_event",
                    "sequence": run.snapshot.sequence + 1, "event_type": "decision_recorded",
                    "run_id": run.snapshot.request.run_id, "occurred_at": _utc(now),
                    "body": _decision_body(decision)}))
                if fault_hook: fault_hook("after_decision", run.snapshot)
            action = run.snapshot.actions[action["id"]]
            if action["kind"] == "worker":
                packet = build_packet(run.snapshot.request, run.snapshot, action)
                packet["output_schema"] = packet["output_schema"]
                # Rendering validates the packet before the immutable intent is recorded.
                build_prompt(action["role"], packet)
            else:
                packet = _tool_packet(run.snapshot, action)
            remaining = min(_remaining(run.snapshot, now), run.snapshot.request.budgets["per_call_seconds"])
            if remaining <= 0:
                reason = "deadline_before_intent"
                expired = _finish_decision(run.snapshot, "budget_exhausted", "budget_exhausted",
                    _assessment_for_stop(run.snapshot, reason))
                return _finalize(run, expired, "budget_exhausted", reason, now, fault_hook)
            finished = _execute_action(run, action, adapter, packet, scratch_parent, remaining,
                                       now, monotonic, fault_hook)
            if _remaining(finished, now) <= 0 and finished.status not in {"complete", "incomplete", "blocked", "budget_exhausted"}:
                outcome = finished.outcomes.get(action["id"], {})
                reason = "deadline_before_launch" if outcome.get("error") == "deadline_before_launch" else "deadline_after_action"
                expired = _finish_decision(finished, "budget_exhausted", "budget_exhausted",
                    _assessment_for_stop(finished, reason))
                return _finalize(run, expired, "budget_exhausted", reason, now, fault_hook)
        reason = "transition_limit_reached"
        stalled = _finish_decision(run.snapshot, reason, "blocked", _assessment_for_stop(run.snapshot, reason))
        return _finalize(run, stalled, "blocked", reason, now, fault_hook)
    raise AssertionError("unreachable")


def answer_research_gate(run_dir: Path, response: Mapping[str, Any], *,
                         now: Now | None = None) -> ResearchSnapshot:
    """Durably answer the current human gate, idempotently by response ID."""
    now = now or (lambda: datetime.now(timezone.utc))
    with open_research_run(Path(run_dir)) as run:
        response = dict(response)
        gate_id, response_id = response.get("gate_id"), response.get("response_id")
        prior = run.snapshot.gate_responses.get(gate_id) if isinstance(gate_id, str) else None
        if prior is not None and prior.get("response_id") == response_id:
            if canonical_json_bytes(dict(prior["response"])) != canonical_json_bytes(response):
                raise ValueError("response ID payload conflict")
            return run.snapshot
        gate = run.snapshot.pending_gate
        if gate is None or gate["gate_id"] != gate_id:
            raise ValueError("no matching human gate is open")
        snapshot = _event(run, "gate_answered", {"gate_id": gate_id,
            "response_id": response_id, "response": response}, now)
        if response.get("decision") == "cancel":
            reason = "user_cancelled"
            decision = _finish_decision(snapshot, reason, "incomplete",
                                        _assessment_for_stop(snapshot, reason))
            return _finalize(run, decision, "incomplete", reason, now, None)
        return snapshot
