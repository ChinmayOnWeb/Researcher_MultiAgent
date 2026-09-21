"""Deterministic, source-safe Markdown rendering for research snapshots."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping

from mathresearch.research.events import ResearchSnapshot
from mathresearch.research.routing import _question_status, assess_latest


def _fence(text: str) -> str:
    longest = 0
    run = 0
    for char in text:
        if char == "`": run += 1; longest = max(longest, run)
        else: run = 0
    marker = "`" * max(3, longest + 1)
    return f"{marker}\n{text}\n{marker}"


def _quoted(text: Any) -> str:
    value = str(text)
    return "\n".join("> " + line for line in value.splitlines()) or ">"


def _inline(text: Any) -> str:
    value = str(text).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|")
    return f"`{value}`"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _draft(snapshot: ResearchSnapshot) -> tuple[str | None, Mapping[str, Any] | None]:
    if snapshot.latest_draft_id in snapshot.results:
        return snapshot.latest_draft_id, snapshot.results[snapshot.latest_draft_id]
    candidates = [(action_id, action, snapshot.results[action_id])
                  for action_id, action in snapshot.actions.items()
                  if action_id in snapshot.results and action["role"] in {"answer", "branch", "synthesize", "revise"}]
    if not candidates: return None, None
    candidates.sort(key=lambda item: (item[1].get("round", 0), item[0]))
    for role in ("revise", "synthesize", "answer", "branch"):
        chosen = [item for item in candidates if item[1]["role"] == role]
        if chosen: return chosen[-1][0], chosen[-1][2]
    return None, None


def _assessment(snapshot: ResearchSnapshot, draft: Mapping[str, Any] | None,
                draft_id: str | None) -> Mapping[str, Any]:
    if isinstance(snapshot.final_assessment, Mapping): return snapshot.final_assessment
    if draft is None:
        performed = any(receipt.get("status") == "succeeded" and
                        receipt.get("request", {}).get("operation") != "fetch_source"
                        for receipt in snapshot.tool_results.values())
        return {"answer_status": "unverified", "provenance_status": "valid",
                "semantic_status": "not_audited", "computation_status": "performed" if performed else "not_performed",
                "formal_status": "not_performed", "claim_findings": [],
                "unresolved": [snapshot.reason or "no_draft"]}
    return assess_latest(snapshot)


def render_report(snapshot: ResearchSnapshot) -> str:
    """Render the finalized or prospective terminal snapshot without a model call."""
    request = snapshot.request
    draft_id, draft = _draft(snapshot)
    assessment = _assessment(snapshot, draft, draft_id)
    audit = None
    if snapshot.latest_audit_id in snapshot.results:
        action = snapshot.actions.get(snapshot.latest_audit_id, {})
        if draft_id in action.get("dependencies", []): audit = snapshot.results[snapshot.latest_audit_id]
    lines = ["# Research report", "", "## Original question", "", _fence(request.question), "",
             "## Explicit goal", "", _fence(request.goal if request.goal is not None else "Not specified"), "",
             "## Status", "", f"- Investigation status: **{snapshot.status}**",
             f"- Answer status: **{assessment.get('answer_status', 'unverified')}**",
             f"- Provenance status: **{assessment.get('provenance_status', 'invalid')}**",
             f"- Semantic status: **{assessment.get('semantic_status', 'not_audited')}**",
             f"- Computation status: **{assessment.get('computation_status', 'not_performed')}**", "",
             "## Answer", ""]
    if draft is None:
        lines.extend(["No answer was produced.", "", f"Reason: {_inline(snapshot.reason or 'No completed Draft is available.')}", ""])
    else:
        if request.objective == "prove":
            if assessment.get("answer_status") == "supported_within_scope":
                lines.extend(["Candidate proof reviewed by model; no formal verification was performed.", ""])
            else:
                lines.extend(["Candidate argument remains conditional or unresolved; no formal verification was performed.", ""])
        if assessment.get("provenance_status") == "valid" and _question_status(draft, audit) == "open_in_sources":
            cited_ids = {citation["source_id"] for claim in draft.get("claims", [])
                         if claim.get("critical") and claim.get("kind") == "source_assertion"
                         for citation in claim.get("citations", [])}
            dates = sorted({str(snapshot.sources[source_id].get("published_at")) for source_id in cited_ids
                            if source_id in snapshot.sources and snapshot.sources[source_id].get("published_at")})
            as_of = f" as of {', '.join(dates)}" if dates else ""
            lines.extend([f"The supplied/captured sources describe this as open{as_of}; this is not an exhaustive current-literature claim.", ""])
        lines.extend([_quoted(draft.get("answer", "")), ""])

    lines.extend(["## What was established", ""])
    findings = {item.get("claim_id"): item for item in assessment.get("claim_findings", []) if isinstance(item, Mapping)}
    if draft is None or not draft.get("claims"):
        lines.extend(["No claim-level assessment is available.", ""])
    else:
        for claim in draft["claims"]:
            finding = findings.get(claim["id"], {})
            lines.extend([f"### Claim {_inline(claim['id'])}: {finding.get('status', 'unverified')}", "",
                          _quoted(claim["statement"]), ""])
            if claim.get("kind") == "assumption": lines.extend(["Assumption supplied by the Draft:", ""])
            for citation in claim.get("citations", []):
                source = snapshot.sources.get(citation["source_id"], {})
                lines.extend([f"Citation: {_inline(citation['source_id'])}, character offsets {citation['start']}–{citation['end']}.",
                              f"Source title: {_inline(source.get('title', 'Unknown source'))}.", _quoted(citation["quote"]), ""])
            for step_id in claim.get("step_ids", []):
                step = next((item for item in draft.get("proof_steps", []) if item["id"] == step_id), None)
                if step: lines.extend([f"Checked step {_inline(step_id)}: {_quoted(step['statement'])}", ""])
            if finding.get("reasons"):
                lines.append("Reasons: " + "; ".join(_inline(reason) for reason in finding["reasons"]) + ".")
                lines.append("")

    lines.extend(["## Approaches attempted", ""])
    branches = [(action_id, action, snapshot.results[action_id]) for action_id, action in snapshot.actions.items()
                if action_id in snapshot.results and action.get("role") == "branch"]
    if not branches: lines.extend(["No branch approach was completed.", ""])
    for action_id, action, result in sorted(branches, key=lambda item: item[0]):
        approach_text = "; ".join(item.get("description", "") + (f" — {item.get('reason', '')}" if item.get("reason") else "")
                                    for item in result.get("approaches", [])) or result.get("answer", "")
        label = "targeted_followup" if action.get("branch") == "c" else f"branch_{action.get('branch')}"
        lines.extend([f"### {_inline(action_id)} ({label})", "", _quoted(approach_text), "",
                      "Branches share the requested model and supplied material; branch b had a separate context.", ""])

    lines.extend(["## Critique and revisions", ""])
    if audit is None: lines.extend(["No current audit is available.", ""])
    else:
        for challenge in audit.get("challenges", []):
            lines.extend([f"- Claim {_inline(challenge['claim_id'])}: outcome **{challenge['outcome']}**.",
                          _quoted(challenge["attack"]), _quoted(challenge["result"]), ""])
    if draft and draft.get("change_log"):
        lines.append("Revision log:")
        lines.extend(f"- {_quoted(entry)}" for entry in draft["change_log"])
        lines.append("")

    lines.extend(["## Executed checks", ""])
    if not snapshot.tool_results: lines.extend(["No broker check or source-fetch receipt was recorded.", ""])
    for tool_id, receipt in snapshot.tool_results.items():
        operation = receipt.get("request", {}).get("operation", "unknown")
        lines.extend([f"### Receipt {_inline(tool_id)} — {operation}: {receipt.get('status')}", "",
                      f"Scope: {_quoted(receipt.get('scope', ''))}",
                      f"Input: {_fence(_json(receipt.get('request', {}).get('arguments', {})))}"])
        if receipt.get("status") == "succeeded":
            lines.extend([f"Result: {_fence(_json(receipt.get('result')))}"])
            if operation == "search_perfect": lines.append("This result is limited to the stated finite range; it does not prove global nonexistence.")
            if operation == "check_polynomial" and receipt.get("result", {}).get("coefficient_equal"):
                lines.append("This checks equality of the encoded polynomials; it does not verify that the encoding matches the original question.")
        else:
            lines.append(f"Reason: {_quoted(receipt.get('error', 'No error detail recorded.'))}")
        lines.append("")

    lines.extend(["## Evidence", ""])
    if not snapshot.sources: lines.extend(["No source records were supplied or captured.", ""])
    for source_id, source in snapshot.sources.items():
        lines.extend([f"### {_inline(source.get('title', source_id))}", "",
                      f"- ID: {_inline(source_id)}", f"- Origin: {_inline(source.get('origin', 'unknown'))}",
                      f"- URL: {_inline(source.get('url') or 'none')}",
                      f"- Published: {_inline(source.get('published_at') or 'unknown')}",
                      f"- Captured: {_inline(source.get('captured_at') or 'unknown')}",
                      f"- SHA-256: {_inline(source.get('sha256') or 'unknown')}", ""])

    lines.extend(["## Remaining uncertainty and useful next work", ""])
    limitations = list(draft.get("open_questions", [])) if draft else []
    limitations.extend(assessment.get("unresolved", []))
    limitations.extend(item for decision in snapshot.decisions for item in decision.get("details", {}).get("blockers", []))
    limitations = list(dict.fromkeys(str(item) for item in limitations))
    lines.extend([_quoted(item) for item in limitations] if limitations else ["No additional limitation was recorded."])
    lines.extend(["", "## Run disclosure", "", f"- Requested model: {_inline(request.provider['model'])}",
                  f"- Requested reasoning effort: {_inline(request.provider['reasoning_effort'])}"])
    observed_models = {item.get("model_observed") for item in snapshot.action_telemetry.values() if item.get("model_observed")}
    observed_efforts = {item.get("effort_observed") for item in snapshot.action_telemetry.values() if item.get("effort_observed")}
    lines.append("- Observed models: " + (", ".join(_inline(value) for value in sorted(observed_models)) if observed_models else "unknown"))
    lines.append("- Observed reasoning effort: " + (", ".join(_inline(value) for value in sorted(observed_efforts)) if observed_efforts else "unknown"))
    lines.extend([f"- Model calls: {snapshot.model_calls_used}", f"- Tool calls: {snapshot.tool_calls_used}"])
    elapsed_ms = sum(item.get("duration_ms", 0) for item in snapshot.action_telemetry.values())
    if snapshot.finished_at:
        try:
            start = datetime.fromisoformat(snapshot.initialized_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(snapshot.finished_at.replace("Z", "+00:00"))
            wall = max(0, int((end - start).total_seconds() * 1000))
            lines.append(f"- Wall time: {wall} ms")
        except ValueError: lines.append("- Wall time: unknown (invalid event timestamps)")
    else: lines.append("- Wall time: unknown (terminal time not recorded)")
    lines.extend([f"- Summed child duration: {elapsed_ms} ms", "- Formal verification: not performed"])
    for key, label in (("input_bytes", "Input bytes"), ("output_bytes", "Output bytes")):
        lines.append(f"- {label}: {sum(item.get(key, 0) for item in snapshot.action_telemetry.values())}")
    for key, label in (("input_tokens", "Input tokens"), ("output_tokens", "Output tokens"), ("reasoning_tokens", "Reasoning tokens")):
        values = [item.get(key) for item in snapshot.action_telemetry.values()]
        total = sum(value for value in values if isinstance(value, int)) if any(isinstance(value, int) for value in values) else None
        lines.append(f"- {label}: {total if total is not None else 'unknown'}")
    costs = [item.get("cost_usd") for item in snapshot.action_telemetry.values()]
    cost = sum(value for value in costs if isinstance(value, (int, float))) if costs and all(value is not None for value in costs) else None
    lines.append(f"- Recorded cost: {cost if cost is not None else 'unknown'}")
    return "\n".join(lines).rstrip() + "\n"


def render_log(snapshot: ResearchSnapshot) -> str:
    """Render deterministic action chronology without provider reasoning text."""
    lines = ["# Research log", "", f"Run: {_inline(snapshot.request.run_id)}", ""]
    if not snapshot.decisions: lines.extend(["No routing decision was recorded.", ""])
    for index, decision in enumerate(snapshot.decisions, 1):
        lines.append(f"## Decision {index}: {_inline(decision.get('reason_code', 'unknown'))}")
        lines.append("")
        action = decision.get("action")
        if not isinstance(action, Mapping):
            lines.append(f"Decision kind: {_inline(decision.get('kind', 'unknown'))}")
        else:
            action_id = action["id"]
            outcome = snapshot.outcomes.get(action_id, {})
            telemetry = snapshot.action_telemetry.get(action_id, {})
            lines.extend([f"Action: {_inline(action_id)} ({_inline(action.get('role', 'unknown'))})",
                          "Dependencies: " + (", ".join(_inline(item) for item in action.get("dependencies", [])) or "none"),
                          f"Outcome: {_inline(outcome.get('outcome', 'not recorded'))}",
                          f"Elapsed milliseconds: {telemetry.get('duration_ms', 'unknown')}"])
            if outcome.get("error"): lines.append(f"Error: {_quoted(outcome['error'])}")
        lines.append("")
    lines.extend([f"Terminal status: {_inline(snapshot.status)}", f"Reason: {_inline(snapshot.reason or 'none')}", ""])
    return "\n".join(lines)
