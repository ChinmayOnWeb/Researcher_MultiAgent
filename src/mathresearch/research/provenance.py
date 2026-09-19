"""Mechanical citation and receipt provenance checks; no truth or entailment claims."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from mathresearch.contracts.validation import ValidationError
from mathresearch.research.contracts import validate_audit_for_draft, validate_result


def _validated_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    errors = []
    for role in ("answer", "branch", "synthesize", "revise"):
        try:
            return validate_result(role, draft)
        except ValidationError as exc:
            errors.append(exc)
    raise errors[0]


def check_provenance(draft: Mapping[str, Any], sources: Mapping[str, Any],
                     tool_results: Mapping[str, Any], *,
                     audit: Mapping[str, Any] | None = None) -> list[str]:
    """Return deterministic contract issues for unknown or mismatched evidence references.

    Passing means IDs, offsets, quotes, hashes, and receipt status are mechanically
    consistent. It does not establish source truth or semantic entailment.
    """
    issues: list[str] = []
    try:
        checked = _validated_draft(draft)
    except (ValidationError, TypeError, KeyError):
        return ["invalid_draft"]
    checked_audit = None
    if audit is not None:
        try: checked_audit = validate_audit_for_draft(audit, checked)
        except (ValidationError, TypeError, KeyError): issues.append("invalid_audit")
    if not isinstance(sources, Mapping) or not isinstance(tool_results, Mapping):
        return ["invalid_evidence_catalog"]
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
                if tool_id not in valid_tools:
                    issues.append(f"unknown_successful_tool:challenge:{challenge['claim_id']}:{tool_id}")
    return issues
