"""Pure ordered routing and qualified finish decisions for research snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
from typing import Any, Mapping

from mathresearch.research.events import ResearchSnapshot, TERMINAL
from mathresearch.research.provenance import assess


@dataclass(frozen=True)
class Decision:
    kind: str
    reason_code: str
    action: Mapping[str, Any] | None = None
    details: Mapping[str, Any] | None = None
    gate: Mapping[str, Any] | None = None
    assessment: Mapping[str, Any] | None = None
    decision_id: str | None = None


def _results(snapshot: ResearchSnapshot, role: str) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    pairs = [(action, snapshot.results[action_id]) for action_id, action in snapshot.actions.items()
             if action_id in snapshot.results and action.get("role") == role]
    return sorted(pairs, key=lambda pair: (pair[0].get("round", 0), pair[0]["id"]))


def _latest(snapshot: ResearchSnapshot, role: str) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    values = _results(snapshot, role)
    return values[-1] if values else None


def assess_latest(snapshot: ResearchSnapshot) -> dict[str, Any]:
    selected = _latest(snapshot, "revise") or _latest(snapshot, "synthesize") or _latest(snapshot, "answer") or _latest(snapshot, "branch")
    if selected is None:
        return {"answer_status": "unverified", "provenance_status": "valid", "semantic_status": "not_audited",
                "computation_status": "performed" if any(r.get("status") == "succeeded" for r in snapshot.tool_results.values()) else "not_performed",
                "formal_status": "not_performed", "claim_findings": [], "unresolved": ["no_draft"]}
    draft_action, draft = selected
    audit_pair = _latest(snapshot, "audit")
    audit = None
    audit_sources: Mapping[str, Any] | None = None
    audit_tool_results: Mapping[str, Any] | None = None
    if audit_pair and draft_action["id"] in audit_pair[0].get("dependencies", []):
        audit = audit_pair[1]
        try:
            audit_packet = json.loads(snapshot.intent_packets[audit_pair[0]["id"]])
            audit_sources = audit_packet["sources"]
            audit_tool_results = audit_packet["tool_results"]
        except (KeyError, TypeError, ValueError):
            audit_sources = {}
            audit_tool_results = {}
    try:
        draft_packet = json.loads(snapshot.intent_packets[draft_action["id"]])
        visible_sources = draft_packet["sources"]
        visible_tool_results = draft_packet["tool_results"]
    except (KeyError, TypeError, ValueError):
        visible_sources = {}
        visible_tool_results = {}
    return assess(draft, visible_sources, visible_tool_results, audit=audit,
                  audit_sources=audit_sources, audit_tool_results=audit_tool_results,
                  run_tool_results=snapshot.tool_results,
                  objective=snapshot.request.objective)


def _details(snapshot: ResearchSnapshot, *, selected: str | None = None,
             audit_id: str | None = None, question_status: str | None = None,
             blockers: list[str] | None = None, finish_status: str | None = None,
             round_number: int = 0) -> dict[str, Any]:
    return {"selected_draft_id": selected, "audit_id": audit_id,
            "question_status": question_status, "blockers": (blockers or [])[:8],
            "finish_status": finish_status, "round": min(2, round_number)}


def _decision_id(snapshot: ResearchSnapshot) -> str:
    return f"d{len(snapshot.decisions) + 1:04d}"


def _action_id(snapshot: ResearchSnapshot) -> str:
    return f"a{len(snapshot.actions) + 1:04d}"


def _worker(snapshot: ResearchSnapshot, role: str, reason: str, *, branch: str | None = None,
            round_number: int = 0, dependencies: list[str] | None = None,
            selected: str | None = None, audit_id: str | None = None,
            blockers: list[str] | None = None) -> Decision:
    inherited = [blocker for decision in snapshot.decisions
                 for blocker in decision.get("details", {}).get("blockers", [])]
    combined = list(dict.fromkeys(inherited + (blockers or [])))
    if snapshot.model_calls_used >= snapshot.request.budgets["max_model_calls"]:
        return _finish(snapshot, "model_call_budget_exhausted", "budget_exhausted",
                       selected=selected, audit_id=audit_id, assessment=assess_latest(snapshot),
                       blockers=combined + ["model call budget exhausted"])
    action = {"id": _action_id(snapshot), "kind": "worker", "role": role, "branch": branch,
              "round": min(2, round_number), "dependencies": dependencies or [],
              "payload": {"prompt_version": "research-v1"}}
    return Decision("worker", reason, action,
                    _details(snapshot, selected=selected, audit_id=audit_id,
                             blockers=combined, round_number=round_number))


def _tool(snapshot: ResearchSnapshot, request: Mapping[str, Any], reason: str,
          *, round_number: int = 0, dependencies: list[str] | None = None,
          selected: str | None = None, audit_id: str | None = None) -> Decision:
    if snapshot.tool_calls_used >= snapshot.request.budgets["max_tool_calls"]:
        return _finish(snapshot, "tool_call_budget_exhausted", "complete", selected=selected,
                       audit_id=audit_id, assessment=assess_latest(snapshot),
                       blockers=["tool call budget exhausted"])
    args = json.loads(json.dumps(request["arguments"], sort_keys=True, separators=(",", ":")))
    operation = request["operation"]
    payload = {"id": request["id"], "operation": operation, "arguments": args}
    action = {"id": _action_id(snapshot), "kind": "tool", "role": operation, "branch": None,
              "round": min(2, round_number), "dependencies": dependencies or [], "payload": payload}
    return Decision("tool", reason, action,
                    _details(snapshot, selected=selected, audit_id=audit_id,
                             round_number=round_number))


def _finish(snapshot: ResearchSnapshot, reason: str, status: str, *, selected: str | None = None,
            audit_id: str | None = None, assessment: Mapping[str, Any] | None = None,
            blockers: list[str] | None = None, question_status: str | None = None) -> Decision:
    return Decision("finish", reason, None,
                    _details(snapshot, selected=selected, audit_id=audit_id, question_status=question_status,
                             blockers=blockers, finish_status=status), assessment=assessment)


def _gate(snapshot: ResearchSnapshot, kind: str, reason: str, questions: list[str], allowed: list[str],
          *, round_number: int = 0) -> Decision:
    gate_id = f"g{len([d for d in snapshot.decisions if d.get('kind') == 'gate']) + 1:04d}"
    gate = {"gate_id": gate_id, "kind": kind, "questions": questions[:4], "allowed_response": allowed}
    return Decision("gate", reason, None, _details(snapshot, round_number=round_number), gate=gate)


def _tool_fingerprint(operation: str, arguments: Mapping[str, Any]) -> str:
    raw = json.dumps({"operation": operation, "arguments": arguments}, sort_keys=True,
                     separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _question_status(draft: Mapping[str, Any], audit: Mapping[str, Any] | None) -> str:
    status = draft.get("question_status")
    if status != "open_in_sources": return status
    if audit is None: return "unresolved"
    checks = {item["claim_id"]: item for item in audit.get("checks", [])}
    for claim in draft.get("claims", []):
        if claim.get("critical") and claim.get("kind") == "source_assertion" and claim.get("citations"):
            reasoning = checks.get(claim["id"], {}).get("reasoning", "").lower()
            if any(word in reasoning for word in ("open", "status", "unsolved", "unresolved", "conjecture")):
                return "open_in_sources"
    return "unresolved"


def _next_decision(snapshot: ResearchSnapshot) -> Decision:
    """Return the next bounded action from a validated snapshot, without side effects."""
    request = snapshot.request
    details = _details(snapshot)
    if snapshot.status in TERMINAL:
        return Decision("noop", "terminal_noop", details=details, assessment=snapshot.final_assessment)
    if snapshot.pending_action_id:
        if snapshot.pending_action_id in snapshot.intended_action_ids:
            return _finish(snapshot, "ambiguous_execution", "blocked", blockers=["pending action has unknown completion"])
        action = snapshot.actions.get(snapshot.pending_action_id)
        previous = next((item for item in reversed(snapshot.decisions)
                         if item.get("action", {}).get("id") == snapshot.pending_action_id), None)
        if action is not None and previous is not None:
            return Decision("resume", previous["reason_code"], action,
                            previous["details"], decision_id=previous["decision_id"])
        return _finish(snapshot, "ambiguous_execution", "blocked", blockers=["pending decision lacks a recoverable action"])
    if snapshot.pending_gate:
        return Decision("await", "human_input_needed", details=details, gate=snapshot.pending_gate)
    if any(action_id not in snapshot.results and action_id != snapshot.pending_action_id
           for action_id in snapshot.actions):
        return _finish(snapshot, "action_failed", "incomplete", assessment=assess_latest(snapshot),
                       blockers=["a completed action has no validated result"])

    completed = [a for aid, a in snapshot.actions.items() if aid in snapshot.results]
    successful = {a["id"] for a in completed}
    draft_pair = _latest(snapshot, "revise") or _latest(snapshot, "synthesize") or _latest(snapshot, "answer")
    audit_pair = _latest(snapshot, "audit")
    frame_pair = _latest(snapshot, "frame")
    if request.mode == "quick":
        if draft_pair is None:
            return _worker(snapshot, "answer", "quick_answer")
        evaluation = assess_latest(snapshot)
        return _finish(snapshot, "quick_unreviewed", "complete", selected=draft_pair[0]["id"],
                       assessment=evaluation, question_status=_question_status(draft_pair[1], None))

    if frame_pair is None:
        return _worker(snapshot, "frame", "frame_request")
    frame_action, frame = frame_pair
    if request.objective == "prove" and frame.get("task_type") != "proof":
        mismatch_answered = any(d.get("reason_code") == "intent_mismatch" for d in snapshot.decisions)
        if not mismatch_answered:
            return _gate(snapshot, "intent_mismatch", "intent_mismatch",
                         ["The frame selected a different task type. Continue with the original prove objective or cancel."],
                         ["continue_limited", "cancel"])
    if frame.get("missing_inputs") and not any(d.get("reason_code") == "missing_inputs" for d in snapshot.decisions):
        return _gate(snapshot, "missing_inputs", "missing_inputs", list(frame["missing_inputs"]),
                     ["supply", "continue_limited", "cancel"])
    captured = set(snapshot.sources)
    for action_id, result in snapshot.results.items():
        action = snapshot.actions[action_id]
        if action.get("role") == "fetch_source" and result.get("status") == "succeeded" and isinstance(result.get("result"), Mapping):
            source = result["result"].get("source")
            if isinstance(source, Mapping): captured.add(source.get("id"))
    descriptors = snapshot.source_descriptors or {source.id: source.to_json() for source in request.sources}
    initial_blockers: list[str] = []
    for source_id, source in descriptors.items():
        if source.get("kind") == "url" and source_id not in captured:
            prior = any(a.get("role") == "fetch_source" and a.get("payload", {}).get("arguments", {}).get("source_id") == source_id for a in snapshot.actions.values())
            if not prior and request.capabilities["fetch_sources"]:
                if snapshot.tool_calls_used < request.budgets["max_tool_calls"]:
                    return _tool(snapshot, {"id": f"fetch-{source_id}", "operation": "fetch_source", "arguments": {"source_id": source_id}}, "acquire_source", dependencies=[frame_action["id"]])
                initial_blockers.append(f"tool_budget_prevented_fetch:{source_id}")

    already = set()
    for action in completed:
        if action["kind"] == "tool" and action["role"] != "fetch_source":
            already.add(_tool_fingerprint(action["role"], action["payload"]["arguments"]))
    denied_initial_checks = list(initial_blockers)
    if request.capabilities["math_checks"]:
        for proposed in frame.get("proposed_checks", []):
            if proposed["operation"] == "fetch_source":
                continue
            fp = _tool_fingerprint(proposed["operation"], proposed["arguments"])
            if fp not in already:
                if snapshot.tool_calls_used < request.budgets["max_tool_calls"]:
                    return _tool(snapshot, proposed, "execute_frame_check", dependencies=[frame_action["id"]])
                denied_initial_checks.append("tool_budget_prevented_frame_check")
    if frame.get("source_needs") and not any(d.get("reason_code") == "request_evidence" for d in snapshot.decisions):
        return _gate(snapshot, "request_evidence", "request_evidence", list(frame["source_needs"]),
                     ["supply", "continue_limited", "cancel"])
    if frame.get("proposed_checks") and not request.capabilities["math_checks"]:
        denied_initial_checks.append("frame_requested_math_check_without_permission")
    if any(item.get("operation") == "fetch_source" for item in frame.get("proposed_checks", [])):
        denied_initial_checks.append("frame_source_fetch_proposal_ignored")

    branch_a = next((a for a in completed if a.get("role") == "branch" and a.get("branch") == "a"), None)
    branch_b = next((a for a in completed if a.get("role") == "branch" and a.get("branch") == "b"), None)
    branch_c = next((a for a in completed if a.get("role") == "branch" and a.get("branch") == "c"), None)
    if branch_a is None: return _worker(snapshot, "branch", "initial_approach", branch="a", dependencies=[frame_action["id"]], blockers=denied_initial_checks)
    if branch_b is None:
        if sum(1 for a in completed if a.get("role") == "branch") >= request.budgets["max_branches"]:
            return _finish(snapshot, "branch_budget_exhausted", "incomplete", assessment=assess_latest(snapshot),
                           blockers=["branch cap prevents the required independent approach"])
        return _worker(snapshot, "branch", "independent_approach", branch="b", dependencies=[frame_action["id"]])
    synthesis = _latest(snapshot, "synthesize")
    if synthesis is None or not {branch_a["id"], branch_b["id"]} <= set(synthesis[0].get("dependencies", [])):
        deps = [branch_a["id"], branch_b["id"]] + ([branch_c["id"]] if branch_c else [])
        return _worker(snapshot, "synthesize", "compare_approaches", dependencies=deps,
                       round_number=branch_c["round"] if branch_c else 0)
    current_action, current_draft = synthesis
    if _latest(snapshot, "revise") and _latest(snapshot, "revise")[0].get("round", 0) >= synthesis[0].get("round", 0):
        current_action, current_draft = _latest(snapshot, "revise")
    audit_pair = _latest(snapshot, "audit")
    if audit_pair is None or current_action["id"] not in audit_pair[0].get("dependencies", []):
        return _worker(snapshot, "audit", "challenge_claims", dependencies=[current_action["id"]],
                       selected=current_action["id"], round_number=current_action["round"])
    audit_action, audit = audit_pair
    assessment = assess(current_draft, snapshot.sources, snapshot.tool_results, audit=audit, objective=request.objective)
    existing = set()
    for action in completed:
        if action["kind"] == "tool": existing.add(_tool_fingerprint(action["role"], action["payload"]["arguments"]))
    for receipt in snapshot.tool_results.values():
        if isinstance(receipt, Mapping) and isinstance(receipt.get("request"), Mapping):
            req = receipt["request"]
            if receipt.get("status") in {"succeeded", "failed", "denied"}:
                existing.add(_tool_fingerprint(req.get("operation"), req.get("arguments", {})))
    blockers = [issue for issue in assessment["unresolved"]]
    blockers.extend(f"claim_{item['claim_id']}_{item['status']}" for item in assessment["claim_findings"] if item["status"] in {"unverified", "conditional", "contradicted"})
    if assessment["answer_status"] in {"supported_within_scope", "conditional"} and not blockers:
        return _finish(snapshot, "assessment_satisfied", "complete", selected=current_action["id"], audit_id=audit_action["id"], assessment=assessment, question_status=_question_status(current_draft, audit))

    max_repairs = request.budgets["max_repairs"]
    round_number = max(audit_action["round"] + 1,
                       max((action["round"] for action in completed if action["round"] > audit_action["round"]), default=0))
    can_repair = snapshot.repairs_started < max_repairs
    audit_requests = audit.get("tool_requests", [])
    calls_left = request.budgets["max_model_calls"] - snapshot.model_calls_used
    if can_repair and calls_left >= 2 and request.capabilities["math_checks"]:
        for proposed in audit_requests:
            if proposed["operation"] == "fetch_source":
                authorized_ids = {source_id for source_id, source in descriptors.items() if source.get("kind") == "url"}
                if proposed["arguments"].get("source_id") not in authorized_ids:
                    blockers.append("audit_requested_unapproved_source")
                    continue
            fp = _tool_fingerprint(proposed["operation"], proposed["arguments"])
            if fp not in existing:
                if snapshot.tool_calls_used < request.budgets["max_tool_calls"]:
                    return _tool(snapshot, proposed, "test_audit_objection", round_number=round_number,
                                 dependencies=[audit_action["id"]], selected=current_action["id"], audit_id=audit_action["id"])
                blockers.append("tool_budget_prevented_audit_check")
    if can_repair and audit_requests and not request.capabilities["math_checks"]:
        blockers.append("audit_requested_math_check_without_permission")
    if can_repair and audit.get("recommended_action") == "request_sources" and not any(d.get("reason_code") == "request_evidence" for d in snapshot.decisions):
        return _gate(snapshot, "request_evidence", "request_evidence", audit.get("missing_evidence") or ["Supply a relevant source or continue with a qualified result."], ["supply", "continue_limited", "cancel"], round_number=round_number)
    branch_count = sum(1 for a in completed if a.get("role") == "branch")
    if can_repair and calls_left >= 3 and request.mode == "research" and audit.get("recommended_action") == "additional_branch" and branch_count == 2 and request.budgets["max_branches"] >= 3:
        return _worker(snapshot, "branch", "targeted_extra_branch", branch="c", round_number=round_number,
                       dependencies=[audit_action["id"]], selected=current_action["id"], audit_id=audit_action["id"], blockers=audit.get("missing_evidence", []))
    if can_repair and calls_left >= 2:
        return _worker(snapshot, "revise", "repair_argument", round_number=round_number,
                       dependencies=[current_action["id"], audit_action["id"]], selected=current_action["id"],
                       audit_id=audit_action["id"], blockers=blockers)
    finish_reason = "investigation_exhausted"
    finish_status = "budget_exhausted" if can_repair and calls_left < 2 else "complete"
    return _finish(snapshot, finish_reason, finish_status, selected=current_action["id"],
                   audit_id=audit_action["id"], assessment=assessment, blockers=blockers,
                   question_status=_question_status(current_draft, audit))


def next_decision(snapshot: ResearchSnapshot) -> Decision:
    """Return a stable, monotonically identified decision without side effects."""
    decision = _next_decision(snapshot)
    return decision if decision.decision_id is not None else replace(decision, decision_id=_decision_id(snapshot))
