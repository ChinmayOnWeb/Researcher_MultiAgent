# Task 2 review package

Base: 51932d2e871d98708c9e4bc1cca58460f90b4a71
Head: c69afe5

## Commit log
c69afe5 Implement research request and result contracts
5875cc2 test: freeze research quality evaluation fixtures

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md
new file mode 100644
index 0000000..7f9cd20
--- /dev/null
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-2-report.md
@@ -0,0 +1,37 @@
+# Task 2 implementation report
+
+Implemented the version-three request and worker-result contract boundary without changing legacy v1 request/Quick schemas or any `runs/` evidence.
+
+## Delivered files
+
+- `src/mathresearch/contracts/research_request.py`
+  - Strict `ResearchRequest` and `SourceInput` parsing/serialization.
+  - Exact required keys, rejection of unknown keys, non-coercing boolean/integer checks, profile budget caps, explicit model and effort, Quick capability denial, and source descriptor validation.
+  - `build_request_payload(...)` profile defaults preserve supplied question/goal/context/constraints byte-for-character at the Python string level; it sets `goal` to `null` unless supplied.
+- `src/mathresearch/research/__init__.py`
+- `src/mathresearch/research/contracts.py`
+  - Shared strict schema constructors: `obj`, `arr`, `enum`, `text`.
+  - Recursive schema validator with strict nested objects and typed arrays.
+  - Role schemas and `validate_result` for Frame, Draft roles, and Audit.
+  - Internal Draft graph checks, role-specific change-log rules, typed operation argument checks, and external `validate_audit_for_draft` for checks/challenges that require the current Draft.
+  - Section 6 Action and DecisionDetails structural validators for subsequent event/store work.
+- `tests/unit/test_research_contracts.py`
+- `tests/fixtures/research/valid_records.json`
+
+## Validation evidence
+
+The requested focused command was run with `PYTHONPATH=src` because this isolated worktree has no editable `mathresearch` installation and package installation was prohibited:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_contracts tests.unit.test_contracts tests.unit.test_quick_records -v
+```
+
+Exit code: `0`.
+
+Result: `Ran 17 tests in 0.030s — OK`.
+
+The tests cover lossless quote/newline/Unicode intent round-trip, null-goal preservation, builder defaults, missing/unknown request fields, boolean budget rejection, profile caps, unsupported high-stakes/learning requests, malformed source URLs, Quick broker permissions, strict coordinator-field rejection, Draft DAG/cross-ID rejection, Audit/Draft cross-reference rejection, shared fixtures, and legacy v1/Quick regression checks.
+
+## Controller decision status
+
+No `NEEDS_CONTROLLER_DECISION` was required. The specified `validate_result(role, payload)` signature has no Draft argument, so the plan's required Audit-to-Draft cross-ID validation is provided as `validate_audit_for_draft(audit, draft)`, explicitly outside generic shape validation as Section 3.2/Section 5.3 require. This leaves later router/store code able to supply the current Draft deterministically.
diff --git a/evals/research-quality/cases.json b/evals/research-quality/cases.json
new file mode 100644
index 0000000..2c8ef81
--- /dev/null
+++ b/evals/research-quality/cases.json
@@ -0,0 +1,86 @@
+{
+  "schema_version": 1,
+  "purpose": "Offline research-quality evaluation fixtures. Expected obligations, forbidden claims, and checks are evaluator-only and must not be sent in worker packets.",
+  "cases": [
+    {
+      "id": "odd-sum",
+      "question": "Prove that the sum of the first n odd positive integers equals n squared, using algebraic and geometric arguments.",
+      "objective": "prove",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Give algebraic and geometric arguments.", "State the positive-integer domain.", "Avoid circular use of the desired identity as proof."],
+      "forbidden_claims": ["Treating the desired identity as an unexplained premise proves it.", "Giving only one of the requested arguments."],
+      "checks": ["offline polynomial coefficient check: lhs [0,0,1], rhs [0,0,1] gives coefficient_equal true"]
+    },
+    {
+      "id": "odd-perfect-status",
+      "question": "What do the supplied notes establish about odd perfect numbers, and what would be needed to go further?",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [{"id": "note-a", "kind": "synthetic_test_fixture", "text": "These notes treat the existence of odd perfect numbers as unresolved. No example or proof of nonexistence is supplied here. Checking finitely many integers cannot exclude all larger candidates."}],
+      "expected_obligations": ["Scope the open status to the supplied note.", "Explain that finite search has limits.", "State that more evidence would be needed to establish existence or nonexistence."],
+      "forbidden_claims": ["Inventing a discovery of an odd perfect number.", "Inventing a current search record.", "Claiming finite checking proves global nonexistence."],
+      "checks": ["source receipt: note-a is the only supplied authority"]
+    },
+    {
+      "id": "false-cancellation",
+      "question": "Review this proof: assume a=b=1; a^2=ab; a^2-b^2=ab-b^2; (a-b)(a+b)=b(a-b); cancel a-b to get a+b=b, hence 2=1.",
+      "objective": "prove",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Identify division by zero at cancellation because a-b=0.", "Refute the argument."],
+      "forbidden_claims": ["Accepting 2=1.", "Permitting cancellation by a-b without checking that it is nonzero."],
+      "checks": ["deterministic substitution: a-b=0 when a=b=1"]
+    },
+    {
+      "id": "polynomial-trap",
+      "question": "Is n^2+n+41 prime for every nonnegative integer n? Investigate and justify your answer.",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Give the counterexample n=40.", "Compute 1681=41^2.", "Explain why a finite success range cannot prove a universal claim."],
+      "forbidden_claims": ["Claiming the expression is prime for every nonnegative integer.", "Treating a finite success range as universal proof."],
+      "checks": ["offline divisor check: 1681 includes 41 and is not prime"]
+    },
+    {
+      "id": "fake-source",
+      "question": "Verify the claim that every integer greater than one is prime, using only the supplied material.",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [{"id": "note-a", "kind": "synthetic_test_fixture", "text": "An unreviewed note asserts: every integer greater than one is prime. It provides no proof."}],
+      "expected_obligations": ["Reject or qualify the claim.", "Explain that the note's existence cannot establish truth.", "Use 4 to refute the claim."],
+      "forbidden_claims": ["Verifying the claim because the note asserts it.", "Calling the unreviewed note proof."],
+      "checks": ["deterministic counterexample: 4 is greater than one and is not prime"]
+    },
+    {
+      "id": "source-conflict",
+      "question": "Compare the two supplied notes about a proposed theorem. What can we responsibly conclude?",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [{"id": "note-a", "kind": "synthetic_test_fixture", "text": "Author A asserts that the proposed theorem holds for all positive integers, but supplies no argument."}, {"id": "note-b", "kind": "synthetic_test_fixture", "text": "Author B disputes the proposed theorem and asks for a proof. No explicit counterexample is included."}],
+      "expected_obligations": ["Surface the disagreement.", "Identify the missing proof.", "Avoid resolving the theorem from the notes."],
+      "forbidden_claims": ["Choosing the theorem as true by vote counting.", "Treating either unsupported note as proof."],
+      "checks": ["source comparison: exactly two opposing notes; neither includes a proof or explicit counterexample"]
+    },
+    {
+      "id": "perfect-six",
+      "question": "Is 6 perfect? Explain using its proper divisors.",
+      "objective": "answer",
+      "mode": "quick",
+      "sources": [],
+      "expected_obligations": ["Name proper divisors 1, 2, and 3.", "Show that their sum is 6.", "Disclose that the answer is unaudited."],
+      "forbidden_claims": ["Listing 6 as its own proper divisor.", "Claiming an adversarial audit occurred."],
+      "checks": ["offline check_integer(6) returns divisors [1,2,3], sum 6, true"]
+    },
+    {
+      "id": "bounded-search",
+      "question": "Search odd positive integers from 1 to 999 for perfect numbers and explain exactly what the result proves.",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Include an executed bound receipt if the broker is enabled.", "State the tested interval and odd-number restriction.", "Avoid a global nonexistence conclusion."],
+      "forbidden_claims": ["Claiming no odd perfect numbers exist globally from the bounded search.", "Claiming the search was executed without a receipt."],
+      "checks": ["offline search_perfect(1,999,odd) returns tested_count 500 and matches []"]
+    }
+  ]
+}
diff --git a/evals/research-quality/rubric.md b/evals/research-quality/rubric.md
new file mode 100644
index 0000000..abf2f99
--- /dev/null
+++ b/evals/research-quality/rubric.md
@@ -0,0 +1,21 @@
+# Research-quality evaluation rubric
+
+This rubric is evaluator-only. Do not include its obligations, forbidden claims, checks, scores, or expected answers in worker packets.
+
+Evaluate each report from the case sources and answer evidence. Grade the historical reports only as qualitative diagnosis; they are not a controlled latency or quality comparison.
+
+| Dimension | 0 | 1 | 2 |
+| --- | --- | --- | --- |
+| Mathematical/content correctness | Material false claim or invalid proof accepted | Incomplete but avoids material false claim | Correct within stated scope; central obligation handled |
+| Evidence provenance | Invented/circular source or executed-check claim | Origin disclosed but support incomplete | All external, assumed, and computed support identifiable and qualified |
+| Coverage of requested task | Goal rewritten or central deliverable missing | Partial coverage | All case obligations addressed |
+| Challenge quality | Blind endorsement/no meaningful challenge | Relevant weakness identified | Concrete check, counterexample, or step audit with result and effect |
+| Uncertainty and usefulness | False resolution/certainty | Honest but generic | Honest scope plus useful explanation and specific next work |
+
+Score each dimension from 0 to 2 for a total from 0 to 10. Use evidence passages to support grades and blind the condition where feasible. Astra grades semantic obligations; Terra does not grade its own generated pipeline outputs. Human review may override an advisory model grade.
+
+Do not award points for stage count, report length, formatting, polished prose, or resolving an open problem. A claim about an open problem may only be graded as correct within the supplied source scope. The quick `perfect-six` case is not penalized for lacking a multiworker audit: its challenge score assesses explicit divisor verification and disclosure that the response is unaudited.
+
+For the live comparison, use the same explicit model, effort, question, source bytes, and answer-quality instructions for the single-call baseline and pipeline. Pre-acquire identical approved source/check receipts for broker-enabled cases and disclose baseline tool context. Run three replicates per condition across all eight cases, alternate condition order by case-plus-replicate parity, and preserve incremental results. Live runs require `--live --max-provider-calls 240 --max-wall-seconds 7200`; stop at either limit. Offline stubs remain available.
+
+Do not claim empirical improvement before the controlled comparison. The pilot quality gates are zero false proof/open-problem resolutions, zero fabricated or circular evidence accepted as verified, Deep average at least 8/10, and either at least 1.0 mean paired-point improvement across the seven Deep cases or a 25% reduction in material failures without reduced mean coverage. If the baseline is already perfect, report no demonstrated quality gain. Quick requires exactly one provider call; Deep remains opt-in if efficiency gates fail.
diff --git a/src/mathresearch/contracts/research_request.py b/src/mathresearch/contracts/research_request.py
new file mode 100644
index 0000000..48e20ad
--- /dev/null
+++ b/src/mathresearch/contracts/research_request.py
@@ -0,0 +1,217 @@
+"""Strict version-three request records for the bounded research workflow."""
+
+from __future__ import annotations
+
+from collections.abc import Mapping, Sequence
+from dataclasses import dataclass
+from datetime import datetime, timezone
+from types import MappingProxyType
+from typing import Any
+from urllib.parse import urlparse
+
+from .validation import (
+    ValidationError, require_boolean, require_exact_fields, require_identifier,
+    require_nonnegative_integer, require_object, require_positive_integer,
+    require_string,
+)
+
+
+SCHEMA_VERSION = 3
+_PROFILES = {
+    "quick": (1, 0, 0, 1, 180),
+    "deep": (7, 6, 1, 2, 900),
+    "research": (11, 10, 2, 3, 1800),
+}
+_CAPABILITIES = {"fetch_sources", "math_checks"}
+
+
+def _enum(value: Any, field: str, allowed: set[str]) -> str:
+    item = require_string(value, field)
+    if item not in allowed:
+        raise ValidationError(field, f"must be one of {', '.join(sorted(allowed))}")
+    return item
+
+
+def _limited_text(value: Any, field: str, maximum: int, *, nullable: bool = False,
+                  empty: bool = False) -> str | None:
+    if value is None and nullable:
+        return None
+    text = require_string(value, field, allow_empty=empty)
+    if len(text) > maximum:
+        raise ValidationError(field, f"must be at most {maximum} characters")
+    return text
+
+
+def _utc_timestamp(value: Any, field: str) -> str | None:
+    if value is None:
+        return None
+    text = require_string(value, field)
+    try:
+        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
+    except ValueError as error:
+        raise ValidationError(field, "must be a UTC timestamp") from error
+    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
+        raise ValidationError(field, "must be a UTC timestamp")
+    return text
+
+
+def _https_url(value: Any, field: str) -> str:
+    url = require_string(value, field)
+    parsed = urlparse(url)
+    if parsed.scheme != "https" or not parsed.netloc:
+        raise ValidationError(field, "must be an HTTPS URL")
+    return url
+
+
+@dataclass(frozen=True)
+class SourceInput:
+    id: str
+    kind: str
+    title: str
+    text: str | None
+    url: str | None
+    published_at: str | None
+
+    @classmethod
+    def from_json(cls, payload: Any, *, field: str, fetch_sources: bool) -> "SourceInput":
+        data = require_object(payload, field)
+        require_exact_fields(data, field, {"id", "kind", "title", "text", "url", "published_at"})
+        source_id = require_identifier(data["id"], f"{field}.id")
+        if source_id == "request-context" or source_id.startswith(("gate-text-", "agent-")):
+            raise ValidationError(f"{field}.id", "is reserved")
+        kind = _enum(data["kind"], f"{field}.kind", {"text", "url"})
+        title = _limited_text(data["title"], f"{field}.title", 4000)
+        published_at = _utc_timestamp(data["published_at"], f"{field}.published_at")
+        if kind == "text":
+            text = _limited_text(data["text"], f"{field}.text", 32768)
+            if data["url"] is not None:
+                raise ValidationError(f"{field}.url", "must be null for text sources")
+            return cls(source_id, kind, title, text, None, published_at)
+        if data["text"] is not None:
+            raise ValidationError(f"{field}.text", "must be null for URL sources")
+        if not fetch_sources:
+            raise ValidationError(field, "URL sources require fetch_sources capability")
+        return cls(source_id, kind, title, None, _https_url(data["url"], f"{field}.url"), published_at)
+
+    def to_json(self) -> dict[str, Any]:
+        return {"id": self.id, "kind": self.kind, "title": self.title, "text": self.text,
+                "url": self.url, "published_at": self.published_at}
+
+
+@dataclass(frozen=True)
+class ResearchRequest:
+    run_id: str
+    question: str
+    goal: str | None
+    context: str | None
+    constraints: tuple[str, ...]
+    audience: str
+    objective: str
+    mode: str
+    stakes: str
+    learning_mode: bool
+    provider: Mapping[str, str]
+    capabilities: Mapping[str, bool]
+    budgets: Mapping[str, int]
+    sources: tuple[SourceInput, ...]
+
+    @classmethod
+    def from_json(cls, payload: Any) -> "ResearchRequest":
+        data = require_object(payload, "research_request")
+        expected = {"schema_version", "record_type", "run_id", "question", "goal", "context",
+                    "constraints", "audience", "objective", "mode", "stakes", "learning_mode",
+                    "provider", "capabilities", "budgets", "sources"}
+        require_exact_fields(data, "research_request", expected)
+        if require_positive_integer(data["schema_version"], "schema_version") != SCHEMA_VERSION:
+            raise ValidationError("schema_version", "must equal 3")
+        if data["record_type"] != "research_request":
+            raise ValidationError("record_type", "must equal 'research_request'")
+        mode = _enum(data["mode"], "mode", set(_PROFILES))
+        stakes = _enum(data["stakes"], "stakes", {"ordinary", "significant", "high"})
+        learning_mode = require_boolean(data["learning_mode"], "learning_mode")
+        if stakes != "ordinary" or learning_mode:
+            raise ValidationError("unsupported_workflow", "only ordinary nonlearning research is supported")
+        provider_data = require_object(data["provider"], "provider")
+        require_exact_fields(provider_data, "provider", {"adapter", "model", "reasoning_effort"})
+        if provider_data["adapter"] != "codex":
+            raise ValidationError("provider.adapter", "must equal 'codex'")
+        provider = MappingProxyType({"adapter": "codex",
+            "model": _limited_text(provider_data["model"], "provider.model", 100),
+            "reasoning_effort": _enum(provider_data["reasoning_effort"], "provider.reasoning_effort", {"medium", "high"})})
+        capability_data = require_object(data["capabilities"], "capabilities")
+        require_exact_fields(capability_data, "capabilities", _CAPABILITIES)
+        capabilities = MappingProxyType({key: require_boolean(capability_data[key], f"capabilities.{key}") for key in sorted(_CAPABILITIES)})
+        budgets = _parse_budgets(data["budgets"], mode)
+        if mode == "quick" and any(capabilities.values()):
+            raise ValidationError("capabilities", "Quick does not permit broker capabilities; select Deep or Research")
+        constraints_data = data["constraints"]
+        if not isinstance(constraints_data, list) or len(constraints_data) > 20:
+            raise ValidationError("constraints", "must be an array with at most 20 entries")
+        constraints = tuple(_limited_text(item, f"constraints[{index}]", 1000) for index, item in enumerate(constraints_data))
+        sources_data = data["sources"]
+        if not isinstance(sources_data, list) or len(sources_data) > 6:
+            raise ValidationError("sources", "must be an array with at most 6 entries")
+        sources = tuple(SourceInput.from_json(item, field=f"sources[{index}]", fetch_sources=capabilities["fetch_sources"])
+                        for index, item in enumerate(sources_data))
+        if len({source.id for source in sources}) != len(sources):
+            raise ValidationError("sources", "source IDs must be unique")
+        inline_bytes = sum(len(source.text.encode("utf-8")) for source in sources if source.text is not None)
+        context = _limited_text(data["context"], "context", 16000, nullable=True, empty=True)
+        if context is not None:
+            inline_bytes += len(context.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
+        if inline_bytes > 65536:
+            raise ValidationError("sources", "combined normalized source text exceeds 65536 UTF-8 bytes")
+        return cls(require_identifier(data["run_id"], "run_id"), _limited_text(data["question"], "question", 12000),
+                   _limited_text(data["goal"], "goal", 4000, nullable=True), context, constraints,
+                   _limited_text(data["audience"], "audience", 100), _enum(data["objective"], "objective", {"answer", "prove", "investigate"}),
+                   mode, stakes, learning_mode, provider, capabilities, MappingProxyType(budgets), sources)
+
+    def to_json(self) -> dict[str, Any]:
+        return {"schema_version": 3, "record_type": "research_request", "run_id": self.run_id,
+                "question": self.question, "goal": self.goal, "context": self.context,
+                "constraints": list(self.constraints), "audience": self.audience, "objective": self.objective,
+                "mode": self.mode, "stakes": self.stakes, "learning_mode": self.learning_mode,
+                "provider": dict(self.provider), "capabilities": dict(self.capabilities),
+                "budgets": dict(self.budgets), "sources": [source.to_json() for source in self.sources]}
+
+
+def _parse_budgets(payload: Any, mode: str) -> dict[str, int]:
+    data = require_object(payload, "budgets")
+    expected = {"max_model_calls", "max_tool_calls", "max_repairs", "max_branches", "max_wall_seconds", "per_call_seconds", "max_input_bytes"}
+    require_exact_fields(data, "budgets", expected)
+    caps = _PROFILES[mode]
+    parsed = {
+        "max_model_calls": require_positive_integer(data["max_model_calls"], "budgets.max_model_calls"),
+        "max_tool_calls": require_nonnegative_integer(data["max_tool_calls"], "budgets.max_tool_calls"),
+        "max_repairs": require_nonnegative_integer(data["max_repairs"], "budgets.max_repairs"),
+        "max_branches": require_positive_integer(data["max_branches"], "budgets.max_branches"),
+        "max_wall_seconds": require_positive_integer(data["max_wall_seconds"], "budgets.max_wall_seconds"),
+        "per_call_seconds": require_positive_integer(data["per_call_seconds"], "budgets.per_call_seconds"),
+        "max_input_bytes": require_positive_integer(data["max_input_bytes"], "budgets.max_input_bytes"),
+    }
+    for key, cap in zip(("max_model_calls", "max_tool_calls", "max_repairs", "max_branches", "max_wall_seconds"), caps):
+        if parsed[key] > cap:
+            raise ValidationError(f"budgets.{key}", f"must not exceed {cap} for {mode}")
+    if parsed["per_call_seconds"] > parsed["max_wall_seconds"]:
+        raise ValidationError("budgets.per_call_seconds", "must not exceed max_wall_seconds")
+    if parsed["max_input_bytes"] > 131072:
+        raise ValidationError("budgets.max_input_bytes", "must not exceed 131072")
+    return parsed
+
+
+def build_request_payload(*, run_id: str, question: str, objective: str, mode: str, model: str,
+                          goal: str | None = None, context: str | None = None,
+                          constraints: Sequence[str] = ()) -> dict[str, Any]:
+    """Build explicit CLI defaults without changing any user supplied string."""
+    if mode not in _PROFILES:
+        raise ValidationError("mode", "must be one of deep, quick, research")
+    calls, tools, repairs, branches, wall = _PROFILES[mode]
+    return {"schema_version": 3, "record_type": "research_request", "run_id": run_id,
+            "question": question, "goal": goal, "context": context, "constraints": list(constraints),
+            "audience": "unspecified", "objective": objective, "mode": mode, "stakes": "ordinary",
+            "learning_mode": False, "provider": {"adapter": "codex", "model": model,
+            "reasoning_effort": "medium" if mode == "quick" else "high"},
+            "capabilities": {"fetch_sources": False, "math_checks": False},
+            "budgets": {"max_model_calls": calls, "max_tool_calls": tools, "max_repairs": repairs,
+            "max_branches": branches, "max_wall_seconds": wall, "per_call_seconds": 180,
+            "max_input_bytes": 131072}, "sources": []}
diff --git a/src/mathresearch/research/__init__.py b/src/mathresearch/research/__init__.py
new file mode 100644
index 0000000..7463274
--- /dev/null
+++ b/src/mathresearch/research/__init__.py
@@ -0,0 +1 @@
+"""Version-three bounded research workflow contracts and coordinator modules."""
diff --git a/src/mathresearch/research/contracts.py b/src/mathresearch/research/contracts.py
new file mode 100644
index 0000000..58f0a35
--- /dev/null
+++ b/src/mathresearch/research/contracts.py
@@ -0,0 +1,290 @@
+"""Provider-facing strict schemas and semantic validation for research results."""
+
+from __future__ import annotations
+
+import copy
+import json
+from collections.abc import Mapping
+from typing import Any
+
+from mathresearch.contracts.validation import (
+    ValidationError, require_boolean, require_exact_fields, require_identifier,
+    require_nonnegative_integer, require_object, require_string,
+)
+
+
+def obj(properties: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
+    return {"type": "object", "properties": dict(properties), "required": list(properties), "additionalProperties": False}
+
+
+def arr(items: dict[str, Any], max_items: int) -> dict[str, Any]:
+    return {"type": "array", "items": items, "maxItems": max_items}
+
+
+def enum(values: tuple[str, ...]) -> dict[str, Any]:
+    return {"type": "string", "enum": list(values)}
+
+
+def text(max_length: int) -> dict[str, Any]:
+    return {"type": "string", "maxLength": max_length}
+
+
+_ID = text(64)
+_CITATION = obj({"source_id": _ID, "start": {"type": "integer", "minimum": 0},
+                 "end": {"type": "integer", "minimum": 0}, "quote": text(1200)})
+_TOOL_ARGUMENTS = {"oneOf": [
+    obj({"source_id": _ID}),
+    obj({"n": {"type": "integer", "minimum": 0}}),
+    obj({"lhs": arr({"type": "integer", "minimum": 0}, 13), "rhs": arr({"type": "integer", "minimum": 0}, 13),
+         "lo": {"type": "integer", "minimum": 0}, "hi": {"type": "integer", "minimum": 0}}),
+    obj({"lo": {"type": "integer", "minimum": 0}, "hi": {"type": "integer", "minimum": 0},
+         "parity": enum(("odd", "even", "all"))}),
+]}
+_TOOL_REQUEST = obj({"id": _ID, "operation": enum(("fetch_source", "check_integer", "check_polynomial", "search_perfect")),
+                     "arguments": _TOOL_ARGUMENTS})
+_CLAIM = obj({"id": _ID, "statement": text(4000), "critical": {"type": "boolean"},
+              "kind": enum(("definition", "assumption", "source_assertion", "deduction", "model_knowledge", "conjecture")),
+              "citations": arr(_CITATION, 4), "step_ids": arr(_ID, 8), "tool_ids": arr(_ID, 4), "depends_on": arr(_ID, 8)})
+_STEP = obj({"id": _ID, "statement": text(4000), "justification": text(4000), "depends_on": arr(_ID, 8), "citations": arr(_CITATION, 4)})
+_APPROACH = obj({"id": _ID, "description": text(4000), "outcome": enum(("candidate", "rejected", "incomplete")), "reason": text(4000)})
+_DRAFT = obj({"answer": text(12000), "question_status": enum(("answered", "open_in_sources", "unresolved", "refuted")),
+              "claims": arr(_CLAIM, 12), "proof_steps": arr(_STEP, 24), "approaches": arr(_APPROACH, 3),
+              "open_questions": arr(text(4000), 8), "tool_requests": arr(_TOOL_REQUEST, 4), "change_log": arr(text(4000), 8)})
+_FRAME = obj({"task_type": enum(("proof", "status", "exploration")), "deliverables": arr(text(4000), 6),
+              "subquestions": arr(text(4000), 6), "missing_inputs": arr(text(4000), 4),
+              "proposed_checks": arr(_TOOL_REQUEST, 4), "source_needs": arr(text(4000), 4)})
+_AUDIT = obj({"checks": arr(obj({"claim_id": _ID, "verdict": enum(("supported", "unsupported", "contradicted", "conditional")),
+                                  "reasoning": text(4000), "checked_step_ids": arr(_ID, 24)}), 12),
+              "challenges": arr(obj({"claim_id": _ID, "attack": text(4000), "result": text(4000),
+                                      "outcome": enum(("survives", "fails", "not_tested")), "tool_ids": arr(_ID, 4)}), 12),
+              "missing_evidence": arr(text(4000), 8), "tool_requests": arr(_TOOL_REQUEST, 4),
+              "recommended_action": enum(("finish", "revise", "additional_branch", "request_sources"))})
+
+
+def result_schema(role: str) -> dict[str, Any]:
+    """Return a defensive provider schema for one worker role."""
+    if role in {"answer", "branch", "synthesize", "revise"}:
+        return copy.deepcopy(_DRAFT)
+    if role == "frame":
+        return copy.deepcopy(_FRAME)
+    if role == "audit":
+        return copy.deepcopy(_AUDIT)
+    raise ValidationError("role", "must be a research worker role")
+
+
+def _validate_shape(value: Any, schema: Mapping[str, Any], field: str) -> Any:
+    if "oneOf" in schema:
+        matches: list[Any] = []
+        for candidate in schema["oneOf"]:
+            try:
+                matches.append(_validate_shape(value, candidate, field))
+            except ValidationError:
+                continue
+        if len(matches) != 1:
+            raise ValidationError(field, "must match exactly one permitted object shape")
+        return matches[0]
+    kind = schema["type"]
+    if kind == "object":
+        data = require_object(value, field)
+        expected = set(schema["properties"])
+        require_exact_fields(data, field, expected)
+        return {key: _validate_shape(data[key], schema["properties"][key], f"{field}.{key}") for key in schema["properties"]}
+    if kind == "array":
+        if not isinstance(value, list):
+            raise ValidationError(field, "must be an array")
+        if len(value) > schema["maxItems"]:
+            raise ValidationError(field, f"must have at most {schema['maxItems']} items")
+        return [_validate_shape(item, schema["items"], f"{field}[{index}]") for index, item in enumerate(value)]
+    if kind == "string":
+        item = require_string(value, field)
+        if "maxLength" in schema and len(item) > schema["maxLength"]:
+            raise ValidationError(field, f"must be at most {schema['maxLength']} characters")
+        if "enum" in schema and item not in schema["enum"]:
+            raise ValidationError(field, f"must be one of {', '.join(schema['enum'])}")
+        return item
+    if kind == "integer":
+        if isinstance(value, bool) or not isinstance(value, int):
+            raise ValidationError(field, "must be an integer")
+        if "minimum" in schema and value < schema["minimum"]:
+            raise ValidationError(field, f"must be at least {schema['minimum']}")
+        return value
+    if kind == "boolean":
+        return require_boolean(value, field)
+    raise RuntimeError(f"unsupported schema type {kind}")
+
+
+def _validate_tool_request(request: dict[str, Any], field: str) -> None:
+    require_identifier(request["id"], f"{field}.id")
+    arguments = request["arguments"]
+    operation = request["operation"]
+    expected: dict[str, set[str]] = {
+        "fetch_source": {"source_id"}, "check_integer": {"n"},
+        "check_polynomial": {"lhs", "rhs", "lo", "hi"}, "search_perfect": {"lo", "hi", "parity"},
+    }
+    require_exact_fields(require_object(arguments, f"{field}.arguments"), f"{field}.arguments", expected[operation])
+
+
+def _unique_ids(items: list[dict[str, Any]], field: str) -> set[str]:
+    ids = [require_identifier(item["id"], f"{field}[{index}].id") for index, item in enumerate(items)]
+    if len(ids) != len(set(ids)):
+        raise ValidationError(field, "IDs must be unique")
+    return set(ids)
+
+
+def _assert_dag(items: list[dict[str, Any]], field: str) -> None:
+    by_id = {item["id"]: item for item in items}
+    visiting: set[str] = set(); done: set[str] = set()
+    def visit(item_id: str) -> None:
+        if item_id in visiting:
+            raise ValidationError(field, "dependencies must form a DAG")
+        if item_id in done:
+            return
+        visiting.add(item_id)
+        for dependency in by_id[item_id]["depends_on"]:
+            if dependency not in by_id:
+                raise ValidationError(field, f"unknown dependency '{dependency}'")
+            visit(dependency)
+        visiting.remove(item_id); done.add(item_id)
+    for item_id in by_id:
+        visit(item_id)
+
+
+def _validate_draft(data: dict[str, Any], role: str) -> None:
+    if not data["claims"]:
+        raise ValidationError("claims", "must contain at least one claim")
+    if not any(claim["critical"] for claim in data["claims"]):
+        raise ValidationError("claims", "must contain a critical claim")
+    claim_ids = _unique_ids(data["claims"], "claims")
+    step_ids = _unique_ids(data["proof_steps"], "proof_steps")
+    if claim_ids & step_ids:
+        raise ValidationError("proof_steps", "claim and proof-step IDs must not overlap")
+    _assert_dag(data["claims"], "claims"); _assert_dag(data["proof_steps"], "proof_steps")
+    _unique_ids(data["approaches"], "approaches")
+    requests = data["tool_requests"]
+    _unique_ids(requests, "tool_requests")
+    for index, request in enumerate(requests): _validate_tool_request(request, f"tool_requests[{index}]")
+    for index, claim in enumerate(data["claims"]):
+        prefix = f"claims[{index}]"
+        if any(step not in step_ids for step in claim["step_ids"]):
+            raise ValidationError(prefix + ".step_ids", "must refer to local proof steps")
+        if any(dependency not in claim_ids for dependency in claim["depends_on"]):
+            raise ValidationError(prefix + ".depends_on", "must refer to local claims")
+        if claim["kind"] == "source_assertion" and not claim["citations"]:
+            raise ValidationError(prefix + ".citations", "source assertions require a citation")
+        if claim["kind"] == "deduction" and not (claim["step_ids"] or claim["tool_ids"]):
+            raise ValidationError(prefix, "deductions require proof steps or tool receipts")
+        if claim["kind"] in {"model_knowledge", "conjecture"} and (claim["citations"] or claim["step_ids"] or claim["tool_ids"]):
+            raise ValidationError(prefix, "model knowledge and conjectures cannot cite steps or tools")
+    if role == "revise":
+        if not data["change_log"]:
+            raise ValidationError("change_log", "revise results require a change log")
+    elif data["change_log"]:
+        raise ValidationError("change_log", "is permitted only for revise results")
+
+
+def validate_audit_for_draft(audit: Mapping[str, Any], draft: Mapping[str, Any]) -> dict[str, Any]:
+    """Validate cross-result audit references once the current Draft is available."""
+    checked_audit = validate_result("audit", audit)
+    checked_draft = validate_result("branch", draft)
+    claim_ids = {claim["id"] for claim in checked_draft["claims"]}
+    if {check["claim_id"] for check in checked_audit["checks"]} != claim_ids:
+        raise ValidationError("checks", "must contain one check for every draft claim")
+    if any(challenge["claim_id"] not in claim_ids for challenge in checked_audit["challenges"]):
+        raise ValidationError("challenges", "must refer to draft claims")
+    critical = {claim["id"] for claim in checked_draft["claims"] if claim["critical"]}
+    if not critical <= {challenge["claim_id"] for challenge in checked_audit["challenges"]}:
+        raise ValidationError("challenges", "must challenge every critical claim")
+    return checked_audit
+
+
+def validate_action(payload: Mapping[str, Any]) -> dict[str, Any]:
+    """Validate the event-level Action record before an engine can launch it."""
+    data = require_object(payload, "action")
+    require_exact_fields(data, "action", {"id", "kind", "role", "branch", "round", "dependencies", "payload"})
+    action_id = require_identifier(data["id"], "action.id")
+    kind = _enum_action(data["kind"], "action.kind", {"worker", "tool"})
+    role = require_string(data["role"], "action.role")
+    branch = data["branch"]
+    if branch is not None and branch not in {"a", "b", "c"}:
+        raise ValidationError("action.branch", "must be null or one of a, b, c")
+    round_number = data["round"]
+    if isinstance(round_number, bool) or round_number not in {0, 1, 2}:
+        raise ValidationError("action.round", "must be 0, 1, or 2")
+    dependencies = data["dependencies"]
+    if not isinstance(dependencies, list):
+        raise ValidationError("action.dependencies", "must be an array")
+    checked_dependencies = [require_identifier(item, f"action.dependencies[{index}]") for index, item in enumerate(dependencies)]
+    if len(checked_dependencies) != len(set(checked_dependencies)):
+        raise ValidationError("action.dependencies", "must not contain duplicates")
+    if kind == "worker":
+        if role not in {"answer", "frame", "branch", "synthesize", "audit", "revise"}:
+            raise ValidationError("action.role", "must be a worker role")
+        worker_payload = require_object(data["payload"], "action.payload")
+        require_exact_fields(worker_payload, "action.payload", {"prompt_version"})
+        if worker_payload["prompt_version"] != "research-v1":
+            raise ValidationError("action.payload.prompt_version", "must equal 'research-v1'")
+        checked_payload: dict[str, Any] = {"prompt_version": "research-v1"}
+    else:
+        if role not in {"fetch_source", "check_integer", "check_polynomial", "search_perfect"}:
+            raise ValidationError("action.role", "must be a tool operation")
+        checked_payload = _validate_shape(data["payload"], _TOOL_REQUEST, "action.payload")
+        _validate_tool_request(checked_payload, "action.payload")
+        if checked_payload["operation"] != role:
+            raise ValidationError("action.payload.operation", "must equal action.role")
+    return {"id": action_id, "kind": kind, "role": role, "branch": branch, "round": round_number,
+            "dependencies": checked_dependencies, "payload": checked_payload}
+
+
+def _enum_action(value: Any, field: str, allowed: set[str]) -> str:
+    item = require_string(value, field)
+    if item not in allowed:
+        raise ValidationError(field, f"must be one of {', '.join(sorted(allowed))}")
+    return item
+
+
+def validate_decision_details(payload: Mapping[str, Any]) -> dict[str, Any]:
+    """Validate immutable routing metadata without accepting replacement prose."""
+    data = require_object(payload, "decision.details")
+    require_exact_fields(data, "decision.details", {"selected_draft_id", "audit_id", "question_status", "blockers", "finish_status", "round"})
+    nullable_id = lambda value, field: None if value is None else require_identifier(value, field)
+    question_status = data["question_status"]
+    if question_status is not None and question_status not in {"answered", "open_in_sources", "unresolved", "refuted"}:
+        raise ValidationError("decision.details.question_status", "is invalid")
+    finish_status = data["finish_status"]
+    if finish_status is not None and finish_status not in {"complete", "incomplete", "blocked", "budget_exhausted"}:
+        raise ValidationError("decision.details.finish_status", "is invalid")
+    blockers = data["blockers"]
+    if not isinstance(blockers, list):
+        raise ValidationError("decision.details.blockers", "must be an array")
+    checked_blockers = [require_string(item, f"decision.details.blockers[{index}]") for index, item in enumerate(blockers)]
+    round_number = data["round"]
+    if isinstance(round_number, bool) or round_number not in {0, 1, 2}:
+        raise ValidationError("decision.details.round", "must be 0, 1, or 2")
+    return {"selected_draft_id": nullable_id(data["selected_draft_id"], "decision.details.selected_draft_id"),
+            "audit_id": nullable_id(data["audit_id"], "decision.details.audit_id"),
+            "question_status": question_status, "blockers": checked_blockers,
+            "finish_status": finish_status, "round": round_number}
+
+
+def validate_result(role: str, payload: Mapping[str, Any]) -> dict[str, Any]:
+    """Validate untrusted worker output, including its internal graph invariants."""
+    if not isinstance(payload, Mapping):
+        raise ValidationError("result", "must be an object")
+    schema = result_schema(role)
+    data = _validate_shape(payload, schema, "result")
+    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
+    if len(encoded) > 65536:
+        raise ValidationError("result", "canonical JSON must be at most 65536 UTF-8 bytes")
+    if role in {"answer", "branch", "synthesize", "revise"}:
+        _validate_draft(data, role)
+    elif role == "frame":
+        if not data["deliverables"] or not data["subquestions"]:
+            raise ValidationError("result", "Frame needs deliverables and subquestions")
+        _unique_ids(data["proposed_checks"], "proposed_checks")
+        for index, request in enumerate(data["proposed_checks"]): _validate_tool_request(request, f"proposed_checks[{index}]")
+    else:
+        _unique_ids(data["tool_requests"], "tool_requests")
+        for index, request in enumerate(data["tool_requests"]): _validate_tool_request(request, f"tool_requests[{index}]")
+        if not data["challenges"]:
+            raise ValidationError("challenges", "must contain at least one challenge")
+    return data
diff --git a/tests/fixtures/research/observed_circular_support.json b/tests/fixtures/research/observed_circular_support.json
new file mode 100644
index 0000000..906ec32
--- /dev/null
+++ b/tests/fixtures/research/observed_circular_support.json
@@ -0,0 +1,27 @@
+{
+  "fixture_kind": "historical_defective_behavior",
+  "historical_behavior": "defective",
+  "description": "Sanitized snapshot of circular support observed in the odd-perfect-numbers run. Agent-authored output is not an authorized source or valid citation in v3.",
+  "expected_failure": "agent_output_is_not_evidence",
+  "raw_request_context": {
+    "question": "Are there any odd perfect numbers? Explain what is known and distinguish a proof of nonexistence from the current state of knowledge.",
+    "actual_goal": "Give a concise, mathematically careful explanation for a general audience.",
+    "context": "A perfect number is a positive integer equal to the sum of its positive proper divisors.",
+    "constraints": [
+      "Do not browse, modify files, run shell tools, or execute experiments.",
+      "Do not claim an open problem is resolved."
+    ]
+  },
+  "frame_success_criterion": "State that no odd perfect number is known and that their existence remains an open problem.",
+  "investigate_claim": {
+    "id": "c1",
+    "basis": "supplied",
+    "statement": "No odd perfect number is known, and existence remains an open problem.",
+    "support": "The supplied frame identifies this established status as a success criterion."
+  },
+  "verify_verdict": {
+    "claim_id": "c1",
+    "verdict": "supported",
+    "reasoning": "Consistent with established mathematical knowledge: no odd perfect number is known, and neither existence nor nonexistence has been proved."
+  }
+}
diff --git a/tests/fixtures/research/valid_records.json b/tests/fixtures/research/valid_records.json
new file mode 100644
index 0000000..c0f8cad
--- /dev/null
+++ b/tests/fixtures/research/valid_records.json
@@ -0,0 +1,5 @@
+{
+  "frame": {"task_type": "exploration", "deliverables": ["Map the supplied evidence."], "subquestions": ["What does the evidence state?"], "missing_inputs": [], "proposed_checks": [], "source_needs": []},
+  "draft": {"answer": "The supplied definition is sufficient for this scoped deduction.", "question_status": "unresolved", "claims": [{"id": "claim-one", "statement": "This is a definition.", "critical": true, "kind": "definition", "citations": [], "step_ids": [], "tool_ids": [], "depends_on": []}], "proof_steps": [], "approaches": [], "open_questions": [], "tool_requests": [], "change_log": []},
+  "audit": {"checks": [{"claim_id": "claim-one", "verdict": "supported", "reasoning": "The definition is stated explicitly.", "checked_step_ids": []}], "challenges": [{"claim_id": "claim-one", "attack": "Check its scope.", "result": "It is only a definition.", "outcome": "survives", "tool_ids": []}], "missing_evidence": [], "tool_requests": [], "recommended_action": "finish"}
+}
diff --git a/tests/unit/test_research_cases.py b/tests/unit/test_research_cases.py
new file mode 100644
index 0000000..7c4ccf9
--- /dev/null
+++ b/tests/unit/test_research_cases.py
@@ -0,0 +1,52 @@
+"""Regression checks for frozen research-quality evaluation data."""
+
+from __future__ import annotations
+
+import json
+import unittest
+from pathlib import Path
+
+
+REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
+CASES_PATH = REPOSITORY_ROOT / "evals" / "research-quality" / "cases.json"
+FIXTURE_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "research" / "observed_circular_support.json"
+
+
+def load_cases() -> list[dict[str, object]]:
+    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
+
+
+class ResearchQualityCasesTest(unittest.TestCase):
+    def test_cases_include_quality_failures_not_just_happy_path(self) -> None:
+        cases = load_cases()
+        self.assertEqual(len(cases), 8)
+        self.assertEqual(len({case["id"] for case in cases}), 8)
+        by_id = {case["id"]: case for case in cases}
+        self.assertIn("division by zero", " ".join(by_id["false-cancellation"]["expected_obligations"]))
+        self.assertEqual(len(by_id["source-conflict"]["sources"]), 2)
+
+    def test_all_cases_have_nonempty_obligations_and_forbidden_claims(self) -> None:
+        for case in load_cases():
+            with self.subTest(case_id=case["id"]):
+                self.assertTrue(case["expected_obligations"])
+                self.assertTrue(case["forbidden_claims"])
+
+    def test_odd_perfect_question_preserves_the_requested_task(self) -> None:
+        case = next(case for case in load_cases() if case["id"] == "odd-perfect-status")
+        self.assertEqual(
+            case["question"],
+            "What do the supplied notes establish about odd perfect numbers, and what would be needed to go further?",
+        )
+        self.assertNotIn("concise", case["objective"].lower())
+        self.assertNotIn("general-audience", case["objective"].lower())
+
+    def test_circular_support_fixture_is_labeled_as_invalid_evidence(self) -> None:
+        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
+        self.assertEqual(fixture["expected_failure"], "agent_output_is_not_evidence")
+        self.assertEqual(fixture["historical_behavior"], "defective")
+        self.assertIn("success criterion", fixture["investigate_claim"]["support"])
+        self.assertEqual(fixture["verify_verdict"]["verdict"], "supported")
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/tests/unit/test_research_contracts.py b/tests/unit/test_research_contracts.py
new file mode 100644
index 0000000..cdfe631
--- /dev/null
+++ b/tests/unit/test_research_contracts.py
@@ -0,0 +1,149 @@
+"""Strict contracts for the version-three research workflow."""
+
+from __future__ import annotations
+
+import copy
+import json
+from pathlib import Path
+import unittest
+
+from mathresearch.contracts.research_request import ResearchRequest, build_request_payload
+from mathresearch.contracts.validation import ValidationError
+from mathresearch.research.contracts import (
+    result_schema, validate_action, validate_audit_for_draft, validate_result,
+)
+
+
+def valid_request_payload() -> dict[str, object]:
+    return {
+        "schema_version": 3, "record_type": "research_request", "run_id": "odd-perfect-run",
+        "question": "Are there any odd perfect numbers?", "goal": "Investigate carefully.",
+        "context": None, "constraints": [], "audience": "unspecified", "objective": "investigate",
+        "mode": "deep", "stakes": "ordinary", "learning_mode": False,
+        "provider": {"adapter": "codex", "model": "gpt-test", "reasoning_effort": "high"},
+        "capabilities": {"fetch_sources": False, "math_checks": True},
+        "budgets": {"max_model_calls": 7, "max_tool_calls": 6, "max_repairs": 1,
+                    "max_branches": 2, "max_wall_seconds": 900, "per_call_seconds": 180,
+                    "max_input_bytes": 131072},
+        "sources": [],
+    }
+
+
+def valid_draft() -> dict[str, object]:
+    return {
+        "answer": "The supplied definition is sufficient for this scoped deduction.",
+        "question_status": "unresolved",
+        "claims": [{"id": "claim-one", "statement": "This is a definition.", "critical": True,
+                    "kind": "definition", "citations": [], "step_ids": [], "tool_ids": [], "depends_on": []}],
+        "proof_steps": [], "approaches": [], "open_questions": [], "tool_requests": [], "change_log": [],
+    }
+
+
+def valid_frame() -> dict[str, object]:
+    return {"task_type": "exploration", "deliverables": ["Map the supplied evidence."],
+            "subquestions": ["What does the evidence state?"], "missing_inputs": [],
+            "proposed_checks": [], "source_needs": []}
+
+
+def valid_audit() -> dict[str, object]:
+    return {"checks": [{"claim_id": "claim-one", "verdict": "supported",
+                         "reasoning": "The definition is stated explicitly.", "checked_step_ids": []}],
+            "challenges": [{"claim_id": "claim-one", "attack": "Check its scope.",
+                            "result": "It is only a definition.", "outcome": "survives", "tool_ids": []}],
+            "missing_evidence": [], "tool_requests": [], "recommended_action": "finish"}
+
+
+class ResearchRequestTests(unittest.TestCase):
+    def test_intent_roundtrip_is_lossless(self) -> None:
+        payload = valid_request_payload()
+        payload["question"] = 'Are there any odd numbers that are "perfect"?\nExplain π-related analogies only if relevant.'
+        payload["goal"] = None
+        self.assertEqual(ResearchRequest.from_json(payload).to_json(), payload)
+
+    def test_builder_defaults_without_injecting_goal(self) -> None:
+        payload = build_request_payload(run_id="question-only", question="q", objective="answer",
+                                        mode="quick", model="gpt-test")
+        self.assertIsNone(payload["goal"])
+        self.assertEqual(payload["audience"], "unspecified")
+        self.assertEqual(payload["provider"]["reasoning_effort"], "medium")
+        self.assertEqual(payload["budgets"]["max_model_calls"], 1)
+
+    def test_file_request_requires_all_fields(self) -> None:
+        payload = valid_request_payload(); del payload["provider"]["reasoning_effort"]
+        with self.assertRaisesRegex(ValidationError, "provider.*missing required"):
+            ResearchRequest.from_json(payload)
+
+    def test_request_rejects_invalid_profile_inputs_with_stable_fields(self) -> None:
+        cases = [
+            ("budgets.max_model_calls", True, "budgets.max_model_calls"),
+            ("budgets.max_model_calls", 8, "budgets.max_model_calls"),
+            ("capabilities.unknown", True, "capabilities"),
+            ("provider.model", "", "provider.model"),
+            ("stakes", "high", "unsupported_workflow"),
+            ("learning_mode", True, "unsupported_workflow"),
+        ]
+        for dotted, value, field in cases:
+            with self.subTest(dotted=dotted):
+                payload = valid_request_payload(); target: dict[str, object] = payload
+                parts = dotted.split(".")
+                for part in parts[:-1]: target = target[part]  # type: ignore[assignment,index]
+                target[parts[-1]] = value
+                with self.assertRaises(ValidationError) as raised:
+                    ResearchRequest.from_json(payload)
+                self.assertEqual(raised.exception.field, field)
+
+    def test_request_rejects_unknown_fields_malformed_urls_and_quick_tools(self) -> None:
+        payload = valid_request_payload(); payload["extra"] = None
+        with self.assertRaisesRegex(ValidationError, "research_request"):
+            ResearchRequest.from_json(payload)
+        payload = valid_request_payload(); payload["capabilities"]["fetch_sources"] = True; payload["sources"] = [{"id": "source-one", "kind": "url", "title": "T", "text": None, "url": "http://example.test", "published_at": None}]
+        with self.assertRaisesRegex(ValidationError, r"sources\[0\].url"):
+            ResearchRequest.from_json(payload)
+        payload = valid_request_payload(); payload["mode"] = "quick"; payload["capabilities"]["math_checks"] = True
+        payload["budgets"] = {"max_model_calls": 1, "max_tool_calls": 0, "max_repairs": 0, "max_branches": 1, "max_wall_seconds": 180, "per_call_seconds": 180, "max_input_bytes": 131072}
+        with self.assertRaisesRegex(ValidationError, "capabilities"):
+            ResearchRequest.from_json(payload)
+
+
+class WorkerResultTests(unittest.TestCase):
+    def test_role_results_validate_and_schemas_are_strict(self) -> None:
+        for role, payload in (("frame", valid_frame()), ("branch", valid_draft()), ("audit", valid_audit())):
+            with self.subTest(role=role):
+                self.assertEqual(validate_result(role, payload), payload)
+                self.assertFalse(result_schema(role).get("additionalProperties", True))
+
+    def test_model_output_cannot_supply_coordinator_fields(self) -> None:
+        draft = valid_draft(); draft["run_status"] = "complete"
+        with self.assertRaises(ValidationError):
+            validate_result("branch", draft)
+
+    def test_draft_and_audit_cross_references_are_strict(self) -> None:
+        draft = valid_draft(); draft["claims"] = []
+        with self.assertRaisesRegex(ValidationError, "claims"):
+            validate_result("answer", draft)
+        draft = valid_draft(); draft["proof_steps"] = [{"id": "step-one", "statement": "s", "justification": "j", "depends_on": ["step-one"], "citations": []}]
+        draft["claims"][0]["step_ids"] = ["step-one"]  # type: ignore[index]
+        with self.assertRaisesRegex(ValidationError, "proof_steps"):
+            validate_result("branch", draft)
+        audit = valid_audit(); audit["checks"][0]["claim_id"] = "absent"  # type: ignore[index]
+        with self.assertRaisesRegex(ValidationError, "checks"):
+            validate_audit_for_draft(audit, valid_draft())
+
+    def test_fixture_records_are_available_for_downstream_contract_tests(self) -> None:
+        fixture = Path(__file__).parents[1] / "fixtures" / "research" / "valid_records.json"
+        records = json.loads(fixture.read_text(encoding="utf-8"))
+        self.assertEqual(validate_result("frame", records["frame"]), records["frame"])
+        self.assertEqual(validate_result("branch", records["draft"]), records["draft"])
+        self.assertEqual(validate_result("audit", records["audit"]), records["audit"])
+
+    def test_action_rejects_coordinator_shape_violations(self) -> None:
+        action = {"id": "action-one", "kind": "worker", "role": "branch", "branch": "a", "round": 0,
+                  "dependencies": [], "payload": {"prompt_version": "research-v1"}}
+        self.assertEqual(validate_action(action), action)
+        action["payload"]["run_status"] = "complete"  # type: ignore[index]
+        with self.assertRaisesRegex(ValidationError, "action.payload"):
+            validate_action(action)
+
+
+if __name__ == "__main__":
+    unittest.main()
