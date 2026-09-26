"""Mechanical citation and receipt provenance checks; no truth or entailment claims."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from mathresearch.contracts.validation import ValidationError
from mathresearch.research.contracts import validate_audit_for_draft, validate_result


def _validated_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    errors = []
    version = ("research-v3" if isinstance(draft, Mapping) and isinstance(draft.get("claims"), list)
               and draft["claims"] and all(isinstance(claim, Mapping) and "basis" in claim
                                           for claim in draft["claims"]) else "research-v2")
    for role in ("answer", "branch", "synthesize", "revise"):
        try:
            return validate_result(role, draft, prompt_version=version)
        except ValidationError as exc:
            errors.append(exc)
    raise errors[0]


def _validated_catalog(sources: Mapping[str, Any], tool_results: Mapping[str, Any]
                       ) -> tuple[dict[str, Mapping[str, Any]], set[str], list[str]]:
    issues: list[str] = []
    checked_sources: dict[str, Mapping[str, Any]] = {}
    for source_id, source in sources.items():
        if not isinstance(source_id, str) or not isinstance(source, Mapping) or source.get("id") != source_id:
            issues.append(f"invalid_source_record:{source_id}")
            continue
        if source.get("kind") == "text":
            text_input = source.get("text")
            if not isinstance(text_input, str) or source.get("url") is not None:
                issues.append(f"invalid_source_record:{source_id}")
            else:
                checked_sources[source_id] = {"id": source_id, "text": text_input}
            continue
        if source.get("kind") == "url" and source.get("text") is None:
            continue
        text = source.get("text")
        digest = source.get("sha256")
        if not isinstance(text, str) or not isinstance(digest, str):
            issues.append(f"invalid_source_record:{source_id}")
            continue
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            issues.append(f"source_hash_mismatch:{source_id}")
            continue
        checked_sources[source_id] = source
    valid_tools: set[str] = set()
    authorized_urls = {str(source.get("url")) for source in checked_sources.values()
                       if isinstance(source.get("url"), str)}
    for source in checked_sources.values():
        retrieval = source.get("retrieval_receipt")
        if isinstance(retrieval, Mapping):
            for key in ("requested_url", "final_url"):
                if isinstance(retrieval.get(key), str): authorized_urls.add(retrieval[key])
    for tool_id, receipt in tool_results.items():
        try:
            from mathresearch.research.broker import validate_tool_receipt
            if not isinstance(receipt, Mapping): raise ValidationError("tool receipt", "must be an object")
            requested_source = None
            if receipt.get("request", {}).get("operation") == "fetch_source":
                source_id = receipt["request"]["arguments"].get("source_id")
                candidate = checked_sources.get(source_id)
                retrieval = candidate.get("retrieval_receipt") if candidate else None
                if candidate and isinstance(retrieval, Mapping):
                    requested_source = {"id": source_id, "kind": "url", "title": candidate.get("title"),
                        "url": retrieval.get("requested_url"), "published_at": candidate.get("published_at")}
            checked_receipt = validate_tool_receipt(receipt, tool_id=tool_id,
                request=receipt.get("request"), requested_source=requested_source,
                authorized_urls=authorized_urls)
            if checked_receipt["status"] == "succeeded": valid_tools.add(tool_id)
        except (ValidationError, TypeError, KeyError, AttributeError, ImportError):
            issues.append(f"invalid_tool_receipt:{tool_id}")
    return checked_sources, valid_tools, issues


def check_provenance(draft: Mapping[str, Any], sources: Mapping[str, Any],
                     tool_results: Mapping[str, Any], *,
                     audit: Mapping[str, Any] | None = None,
                     audit_sources: Mapping[str, Any] | None = None,
                     audit_tool_results: Mapping[str, Any] | None = None) -> list[str]:
    """Return deterministic contract issues for unknown or mismatched evidence references.

    Passing means IDs, offsets, quotes, hashes, and receipt status are mechanically
    consistent. It does not establish source truth or semantic entailment.
    """
    issues: list[str] = []
    version = ("research-v3" if isinstance(draft, Mapping) and isinstance(draft.get("claims"), list)
               and draft["claims"] and isinstance(draft["claims"][0], Mapping)
               and "basis" in draft["claims"][0] else "research-v2")
    errors = []
    checked = None
    for producer in ("answer", "branch", "synthesize", "revise"):
        try:
            checked = validate_result(producer, draft, prompt_version=version)
            break
        except ValidationError as exc:
            errors.append(exc)
    if checked is None:
        return ["invalid_draft"]
    checked_audit = None
    if audit is not None:
        try:
            audit_version = version
            checked_audit = validate_audit_for_draft(audit, checked, prompt_version=audit_version)
        except (ValidationError, TypeError, KeyError): issues.append("invalid_audit")
    if not isinstance(sources, Mapping) or not isinstance(tool_results, Mapping):
        return ["invalid_evidence_catalog"]
    checked_sources, valid_tools, catalog_issues = _validated_catalog(sources, tool_results)
    issues.extend(catalog_issues)
    audit_valid_tools = valid_tools
    if audit_tool_results is not None:
        checked_audit_sources = sources if audit_sources is None else audit_sources
        if not isinstance(audit_tool_results, Mapping) or not isinstance(checked_audit_sources, Mapping):
            issues.append("invalid_audit_evidence_catalog")
            audit_valid_tools = set()
        else:
            _, audit_valid_tools, audit_issues = _validated_catalog(checked_audit_sources, audit_tool_results)
            issues.extend(audit_issues)
    for claim in checked["claims"]:
        for citation in claim["citations"]:
            source_id = citation["source_id"]
            source = checked_sources.get(source_id)
            if source is None:
                issues.append(f"unknown_source:{claim['id']}:{source_id}")
                continue
            start, end, quote = citation["start"], citation["end"], citation["quote"]
            text = source["text"]
            if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
                issues.append(f"invalid_citation_offsets:{claim['id']}:{source_id}")
            elif not 0 <= start < end <= len(text) or text[start:end] != quote:
                issues.append(f"citation_quote_mismatch:{claim['id']}:{source_id}")
        for tool_id in claim["tool_ids"]:
            if tool_id not in valid_tools:
                issues.append(f"unknown_successful_tool:{claim['id']}:{tool_id}")
    if checked_audit is not None:
        for challenge in checked_audit["challenges"]:
            for tool_id in challenge["tool_ids"]:
                if tool_id not in audit_valid_tools:
                    issues.append(f"unknown_successful_tool:challenge:{challenge['claim_id']}:{tool_id}")
    return issues


def assess(draft: Mapping[str, Any], sources: Mapping[str, Any],
           tool_results: Mapping[str, Any], *, audit: Mapping[str, Any] | None = None,
           audit_sources: Mapping[str, Any] | None = None,
           audit_tool_results: Mapping[str, Any] | None = None,
           run_tool_results: Mapping[str, Any] | None = None,
           objective: str = "investigate", question: str = "", goal: str = "") -> dict[str, Any]:
    """Derive a qualified, deterministic assessment from validated records.

    Semantic entailment remains model-reviewed; this function only combines the
    audit labels with mechanical evidence integrity and dependency status.
    """
    version = ("research-v3" if isinstance(draft, Mapping) and isinstance(draft.get("claims"), list)
               and draft["claims"] and isinstance(draft["claims"][0], Mapping)
               and "basis" in draft["claims"][0] else "research-v2")
    errors = []
    checked = None
    for role in ("answer", "branch", "synthesize", "revise"):
        try:
            checked = validate_result(role, draft, prompt_version=version)
            break
        except ValidationError as exc:
            errors.append(exc)
    if checked is None:
        raise errors[0]
    issues = check_provenance(checked, sources, tool_results, audit=audit,
                              audit_sources=audit_sources, audit_tool_results=audit_tool_results)
    if any(issue in {"invalid_draft", "invalid_audit", "invalid_evidence_catalog", "invalid_audit_evidence_catalog"}
           for issue in issues):
        return {"answer_status": "unverified", "provenance_status": "invalid",
            "semantic_status": "issues_found", "computation_status": "not_performed",
            "formal_status": "not_performed", "claim_findings": [
                {"claim_id": claim["id"], "status": "unverified", "reasons": issues}
                for claim in checked["claims"]], "unresolved": list(dict.fromkeys(issues))}
    checked_audit = None
    if audit is not None and "invalid_audit" not in issues:
        audit_version = ("research-v3" if version == "research-v3" and isinstance(audit, Mapping)
            and audit.get("checks") and isinstance(audit["checks"][0], Mapping)
            and "basis_verdict" in audit["checks"][0] else "research-v2")
        checked_audit = validate_audit_for_draft(audit, checked, prompt_version=audit_version)
    math_succeeded = False
    observed_tools = tool_results if run_tool_results is None else run_tool_results
    if isinstance(observed_tools, Mapping):
        for tool_id, receipt in observed_tools.items():
            try:
                from mathresearch.research.broker import validate_tool_receipt
                if isinstance(receipt, Mapping):
                    verified = validate_tool_receipt(receipt, tool_id=tool_id,
                                                     request=receipt.get("request"))
                    math_succeeded |= verified["status"] == "succeeded" and verified["request"]["operation"] != "fetch_source"
            except (ValidationError, TypeError, KeyError, AttributeError):
                continue
    computation = "performed" if math_succeeded else "not_performed"
    findings: list[dict[str, Any]] = []
    failed_tools = ([f"tool_{tool_id}_{receipt['status']}" for tool_id, receipt in observed_tools.items()
                    if isinstance(receipt, Mapping) and receipt.get("status") in {"failed", "denied"}]
                    if isinstance(observed_tools, Mapping) else [])
    failed_tools = list(dict.fromkeys(failed_tools))
    provenance_invalid = bool(issues)
    checks = {} if checked_audit is None else {item["claim_id"]: item for item in checked_audit["checks"]}
    challenges: dict[str, list[dict[str, Any]]] = {}
    if checked_audit is not None:
        for item in checked_audit["challenges"]:
            challenges.setdefault(item["claim_id"], []).append(item)
    steps = {item["id"]: item for item in checked["proof_steps"]}
    claim_by_id = {item["id"]: item for item in checked["claims"]}
    memo: dict[str, str] = {}

    def step_closure(step_ids: list[str]) -> set[str]:
        found: set[str] = set()
        pending = list(step_ids)
        while pending:
            step_id = pending.pop()
            if step_id in found:
                continue
            found.add(step_id)
            pending.extend(steps[step_id]["depends_on"])
        return found

    claim_issues: dict[str, list[str]] = {claim["id"]: [] for claim in checked["claims"]}
    for issue in issues:
        parts = issue.split(":")
        candidate = next((part for part in parts[1:] if part in claim_issues), None)
        if candidate is None and any(issue.startswith(prefix) for prefix in ("source_hash_mismatch:", "invalid_source_record:", "invalid_tool_receipt:")):
            candidate = next((claim["id"] for claim in checked["claims"]
                if any(citation["source_id"] in issue for citation in claim["citations"]) or
                   any(tool_id in issue for tool_id in claim["tool_ids"])), None)
        if candidate is None:
            for claim_id in claim_issues:
                claim_issues[claim_id].append(issue)
        else:
            claim_issues[candidate].append(issue)
    for claim in checked["claims"]:
        if any(claim_issues[dep] for dep in claim["depends_on"]):
            claim_issues[claim["id"]].extend(f"dependency_{dep}_provenance_invalid"
                for dep in claim["depends_on"] if claim_issues[dep])

    def status_for(claim_id: str, visiting: set[str] | None = None) -> str:
        if claim_id in memo: return memo[claim_id]
        claim = claim_by_id[claim_id]
        if claim_issues[claim_id]: result = "unverified"
        elif checked_audit is None: result = "unverified"
        else:
            check = checks[claim_id]
            related = challenges.get(claim_id, [])
            contradicted = check["verdict"] == "contradicted" or any(c["outcome"] == "fails" and c["tool_ids"] for c in related)
            if contradicted: result = "contradicted"
            elif claim["critical"] and any(c["outcome"] == "not_tested" for c in related): result = "unverified"
            elif checked_audit is not None and "basis" in claim and "basis_verdict" in check:
                basis = claim["basis"]
                basis_verdict = check["basis_verdict"]
                if basis in {"conjecture", "unsupported_recollection"}: result = "unverified"
                elif basis == "additional_assumption": result = "conditional"
                elif basis == "local_assumption":
                    dependents = [other for other in checked["claims"] if claim_id in other["depends_on"] and other["kind"] == "deduction"]
                    discharged = bool(dependents) and all(checks[other["id"]]["verdict"] == "supported" and
                        checks[other["id"]]["basis_verdict"] == "applicable" and
                        set(claim["discharged_by_step_ids"]) <= set(checks[other["id"]]["checked_step_ids"])
                        for other in dependents)
                    result = "discharged_local_assumption" if discharged else "conditional"
                elif basis == "question_premise":
                    reference = claim["basis_reference"].strip()
                    result = "accepted_premise" if reference and reference in (question + " " + goal) and basis_verdict == "applicable" else "unverified"
                elif basis == "external_fact": result = "source_attributed" if basis_verdict == "source_attributed" else "unverified"
                elif basis == "standard_result" and (basis_verdict != "applicable" or check["verdict"] != "supported"):
                    result = "unverified"
                elif basis in {"standard_result", "derivation"} and basis_verdict == "applicable" and check["verdict"] == "supported":
                    result = "model_reviewed_derivation"
                elif basis_verdict == "conditional" or check["verdict"] == "conditional": result = "conditional"
                else: result = "unverified"
            elif claim_issues[claim_id]: result = "unverified"
            elif claim["kind"] in {"model_knowledge", "conjecture"}: result = "unverified"
            elif check["verdict"] == "conditional" or claim["kind"] == "assumption": result = "conditional"
            elif check["verdict"] != "supported": result = "unverified"
            elif claim["kind"] == "source_assertion": result = "source_supported"
            elif claim["kind"] == "deduction":
                result = "model_reviewed_derivation"
                for dep in claim["depends_on"]:
                    dep_status = status_for(dep, visiting)
                    if dep_status == "contradicted": result = "contradicted"
                    elif dep_status in {"conditional", "unverified"} and result != "contradicted": result = dep_status
            else: result = "model_reviewed_derivation"
        memo[claim_id] = result
        return result

    for claim in checked["claims"]:
        reasons: list[str] = []
        if checked_audit is None: reasons.append("not_audited")
        else:
            check = checks[claim["id"]]
            if check["verdict"] != "supported": reasons.append(f"audit_{check['verdict']}")
            if any(ch["outcome"] == "not_tested" for ch in challenges.get(claim["id"], [])): reasons.append("challenge_not_tested")
            if any(ch["outcome"] == "fails" for ch in challenges.get(claim["id"], [])): reasons.append("counterexample_challenge_failed")
            for dep in claim["depends_on"]:
                if status_for(dep) in {"conditional", "unverified", "contradicted"}: reasons.append(f"dependency_{dep}_{status_for(dep)}")
        reasons.extend(claim_issues[claim["id"]])
        basis = claim.get("basis")
        findings.append({"claim_id": claim["id"], "status": status_for(claim["id"]), "reasons": reasons,
                         "basis": basis, "basis_reference": claim.get("basis_reference"),
                         "truth_status": ("not_established" if basis == "external_fact" else "reviewed"),
                         "evidence_status": ("source_attributed" if basis == "external_fact" and status_for(claim["id"]) == "source_attributed" else None)})
    critical_statuses = [memo[c["id"]] for c in checked["claims"] if c["critical"]]
    unresolved: list[str] = []
    unresolved.extend(failed_tools)
    if checked_audit is None: unresolved.append("not_audited")
    else:
        unresolved.extend(checked_audit["missing_evidence"])
        challenged = {challenge["claim_id"] for challenge in checked_audit["challenges"]}
        if any(claim["critical"] and claim["id"] not in challenged for claim in checked["claims"]): unresolved.append("critical_claim_missing_challenge")
        if any(claim["critical"] and any(challenge["claim_id"] == claim["id"] and challenge["outcome"] == "not_tested" for challenge in checked_audit["challenges"]) for claim in checked["claims"]): unresolved.append("critical_challenge_not_tested")
        checks_by_claim = {item["claim_id"]: item for item in checked_audit["checks"]}
        if objective == "prove" and any(claim["critical"] and claim["kind"] == "deduction" and
            not step_closure(claim["step_ids"]) <= set(checks_by_claim[claim["id"]]["checked_step_ids"])
            for claim in checked["claims"]): unresolved.append("critical_proof_steps_not_covered")
    if "contradicted" in critical_statuses: answer_status = "refuted"
    elif checked_audit is None: answer_status = "unverified"
    elif unresolved or "unverified" in critical_statuses: answer_status = "inconclusive"
    elif "conditional" in critical_statuses: answer_status = "conditional"
    else: answer_status = "supported_within_scope"
    semantic = "not_audited" if checked_audit is None else ("issues_found" if unresolved or answer_status in {"inconclusive", "refuted"} or any(item["status"] in {"unverified", "contradicted"} for item in findings) else "model_reviewed")
    return {"answer_status": answer_status, "provenance_status": "invalid" if provenance_invalid else "valid",
            "semantic_status": semantic, "computation_status": computation,
            "formal_status": "not_performed", "claim_findings": findings,
            "unresolved": list(dict.fromkeys(unresolved))}
