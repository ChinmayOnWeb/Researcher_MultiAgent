"""Paired research-quality evaluation records and aggregation.

This module deliberately separates trial execution from grading. Process
completion is never treated as a semantic grade, and unknown provider cost
remains unknown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import re
import secrets
import statistics
import time
from typing import Any

from mathresearch.contracts.validation import ValidationError
from mathresearch.locking import acquire_run_lock
from mathresearch.research.math_checks import perform_math_check, validate_math_arguments


DIMENSIONS = ("correctness", "provenance", "coverage", "challenge", "uncertainty")
CONDITIONS = ("baseline", "pipeline")
VALID_CONDITIONS = (*CONDITIONS, "baseline_repair", "sequential_review", "adaptive")
BASELINE_PREFLIGHT_WORST_SECONDS = 30
CASE_FIELDS = {"id", "question", "objective", "mode", "sources",
               "expected_obligations", "forbidden_claims", "checks"}
CASE_OPTIONAL_FIELDS = {"capabilities", "evidence_policy"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def classify_trial_failure(raw: Mapping[str, Any]) -> str | None:
    explicit = raw.get("failure_class")
    if explicit in {"schema_rejection", "provider_usage_limit", "provider_failure",
                    "timeout", "permission_failure", "other"}:
        return explicit
    message = str(raw.get("error") or "").lower()
    outcome = str(raw.get("provider_outcome") or "").lower()
    if "schema error" in message or "structural validation failed" in message:
        return "schema_rejection"
    if re.search(r"usage limit|rate.?limit|too many requests|quota exceeded", message):
        return "provider_usage_limit"
    if outcome in {"timed_out", "timeout"} or "timed out" in message:
        return "timeout"
    if "permission" in message or "access is denied" in message:
        return "permission_failure"
    if outcome in {"failed", "launch_failed", "cancelled"} or message:
        return "provider_failure"
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(str(path), f"cannot read strict JSON: {error}") from error


def _report_semantic_material(report: str) -> dict[str, Any] | None:
    """Project a research report to answer content without workflow/status metadata."""
    # Keep current answer/check evidence only; revision history and uncertainty
    # summaries may describe superseded drafts rather than the final result.
    names = ("Answer", "Critique and revisions", "Executed checks")
    sections: dict[str, str] = {}
    for name in names:
        match = re.search(rf"(?ms)^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", report)
        if match:
            sections[name] = match.group(1).strip()
    answer = sections.get("Answer", "")
    if not answer or "No answer was produced" in answer:
        return None
    # These phrases are inserted by the report renderer, not part of the model's
    # answer. Remove the whole preamble before any captured-output fallback.
    answer = re.sub(r"(?m)^(?:Candidate proof reviewed by model; no formal verification was performed\.|"
                    r"Candidate argument remains conditional or unresolved; no formal verification was performed\.|"
                    r"The supplied/captured sources describe this as open[^\n]*\.)\s*\n*", "", answer)
    answer = re.sub(r"(?m)^\s*(?:[-*]\s*)?Question status:\s*[^\n]*\n*", "", answer)
    answer = re.sub(r"(?m)^> ?", "", answer).strip()
    supporting = []
    for name in names:
        if name == "Answer" or not sections.get(name):
            continue
        body = sections[name]
        if name == "Critique and revisions":
            # Preserve the substantive attack and result text, removing the
            # renderer's claim IDs, outcome labels, and superseded revision log.
            body = re.split(r"(?m)^Revision log:\s*$", body)[0]
            body = re.sub(r"(?m)^- Claim `[^`]+`: outcome \*\*[^*]+\*\*\.\s*$", "", body)
            body = re.sub(r"(?m)^Reasons?:\s*.*$", "", body)
            body = re.sub(r"(?m)^No current audit is available\.?\s*$", "", body)
            body = re.sub(r"(?m)^> ?", "", body)
        else:
            # Receipt IDs and operation status are workflow metadata. Keep scope,
            # arguments, results, and failure reasons as substantive evidence.
            body = re.sub(r"(?m)^### Receipt .*?$", "", body)
            body = re.sub(r"(?m)^### [^\n]*$", "", body)
            body = re.sub(r"(?m)^-?(?:Status|Outcome):\s*.*$", "", body)
            body = re.sub(r"(?m)^No broker check or source-fetch receipt was recorded\.?\s*$", "", body)
        if body.strip():
            supporting.append(body.strip())
    return {"answer": answer.strip(), "supporting_work": "\n\n".join(supporting)}


def _payload_semantic_material(payload: Any) -> dict[str, Any] | None:
    """Keep answer-bearing fields from a captured model result; omit workflow hints."""
    if isinstance(payload, Mapping) and isinstance(payload.get("payload"), Mapping):
        payload = payload["payload"]
    if not isinstance(payload, Mapping) or not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        return None
    # Some older adapters wrapped the response JSON inside the answer string.
    for _ in range(2):
        try:
            nested = json.loads(payload["answer"])
        except (TypeError, json.JSONDecodeError):
            break
        if not isinstance(nested, Mapping) or not isinstance(nested.get("answer"), str):
            break
        payload = nested
    blocks = [payload["answer"].strip()]
    fields = (("Claims", "claims"), ("Proof", "proof_steps"),
              ("Evidence", "citations"), ("Evidence", "evidence"),
              ("Limitations", "open_questions"))
    for heading, field in fields:
        entries = payload.get(field)
        if entries is None or entries == []:
            continue
        blocks.append(heading + ":\n" + json.dumps(entries, ensure_ascii=False, sort_keys=True))
    approaches = payload.get("approaches")
    if isinstance(approaches, list) and approaches:
        checks = [{"description": entry.get("description"), "reason": entry.get("reason")}
                  for entry in approaches if isinstance(entry, Mapping)]
        if checks:
            blocks.append("Reasoning checks:\n" + json.dumps(checks, ensure_ascii=False, sort_keys=True))
    return {"answer": blocks[0], "supporting_work": "\n\n".join(blocks[1:])}


def _captured_answer_material(trial_dir: Path, trial: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Find answer-bearing artifacts when report finalization failed, with hashes."""
    candidates: list[tuple[tuple[int, int, int], str, dict[str, Any], str]] = []
    paths = list(trial_dir.rglob("attempts/**/stdout.bin"))
    paths.extend(path for path in trial_dir.glob("provider-result*.json") if path.is_file())
    paths.extend(path for path in trial_dir.rglob("stdout.bin") if path not in paths)
    for path in paths:
        try:
            raw = path.read_bytes()
            if path.suffix == ".json":
                value = json.loads(raw.decode("utf-8"))
                value = value.get("payload") if isinstance(value, Mapping) else None
            else:
                value = json.loads(raw.decode("utf-8"))
            material = _payload_semantic_material(value)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if material is not None:
            relative = path.relative_to(trial_dir).as_posix()
            attempt = re.search(r"actions/a(\d+)/attempts/a\d+-a(\d+)/stdout\.bin$", relative)
            action = re.search(r"actions/a(\d+)/stdout\.bin$", relative)
            if attempt:
                order = (3, int(attempt.group(1)), int(attempt.group(2)))
            elif action:
                order = (2, int(action.group(1)), 0)
            elif path.name.startswith("provider-result"):
                order = (1, 0, 0)
            else:
                order = (0, 0, 0)
            candidates.append((order, relative, material, sha256(raw)))
    if candidates:
        _, _, material, artifact_hash = max(candidates, key=lambda item: item[0])
    report = trial.get("report")
    if isinstance(report, str):
        report_material = _report_semantic_material(report)
        if report_material is not None and not candidates:
            return report_material, []
        if report_material is not None and candidates:
            # Captured model output is the graded answer. Reports are generated
            # summaries; retain only current audit/check evidence, never its answer.
            parts = [part for part in (material.get("supporting_work", ""),
                                      report_material.get("supporting_work", "")) if part]
            material = {"answer": material["answer"], "supporting_work": "\n\n".join(parts)}
            report_hash = trial.get("report_sha256") or sha256(report.encode("utf-8"))
            return material, list(dict.fromkeys(value for value in (artifact_hash, report_hash)
                                                if value != trial.get("artifact_sha256")))
    if candidates:
        return material, [artifact_hash]
    return None, []


def _captured_output_hashes(trial_dir: Path) -> set[str]:
    """Return hashes for persisted provider captures usable as grading support."""
    paths = list(trial_dir.rglob("stdout.bin"))
    paths.extend(path for path in trial_dir.glob("provider-result*.json") if path.is_file())
    paths.extend(path for path in trial_dir.rglob("report.md") if path.is_file())
    hashes: set[str] = set()
    for path in paths:
        try:
            hashes.add(sha256(path.read_bytes()))
        except OSError:
            continue
    trial_path = trial_dir / "trial.json"
    try:
        trial = _read_json(trial_path)
        report = trial.get("report")
        report_hash = trial.get("report_sha256")
        if isinstance(report, str) and isinstance(report_hash, str) and sha256(report.encode("utf-8")) == report_hash:
            hashes.add(report_hash)
    except (OSError, ValidationError, AttributeError):
        pass
    return hashes


def load_cases(directory: Path) -> tuple[list[dict[str, Any]], str, str]:
    """Read and freeze cases/rubric, keeping grader-only fields in the evaluator."""
    root = Path(directory)
    cases_doc = _read_json(root / "cases.json")
    if not isinstance(cases_doc, dict) or set(cases_doc) != {"schema_version", "purpose", "cases"}:
        raise ValidationError("cases", "must contain schema_version, purpose, and cases")
    if cases_doc["schema_version"] != 1 or not isinstance(cases_doc["cases"], list):
        raise ValidationError("cases", "unsupported schema or cases is not an array")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(cases_doc["cases"]):
        field = f"cases[{index}]"
        if (not isinstance(raw, dict) or not CASE_FIELDS.issubset(raw) or
                set(raw) - CASE_FIELDS - CASE_OPTIONAL_FIELDS):
            raise ValidationError(field, "has unknown or missing fields")
        case_id = raw["id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case_id):
            raise ValidationError(f"{field}.id", "must be a lowercase hyphenated identifier")
        if case_id in seen:
            raise ValidationError(f"{field}.id", "must be unique")
        seen.add(case_id)
        if not isinstance(raw["question"], str) or not raw["question"]:
            raise ValidationError(f"{field}.question", "must be nonempty text")
        if raw["objective"] not in {"answer", "prove", "investigate"}:
            raise ValidationError(f"{field}.objective", "is invalid")
        if raw["mode"] not in {"quick", "deep", "research"}:
            raise ValidationError(f"{field}.mode", "is invalid")
        capabilities = raw.get("capabilities", {"fetch_sources": False,
            "math_checks": bool(raw["checks"])})
        if (not isinstance(capabilities, dict) or
                set(capabilities) != {"fetch_sources", "math_checks"} or
                any(not isinstance(value, bool) for value in capabilities.values())):
            raise ValidationError(f"{field}.capabilities", "must explicitly contain fetch_sources and math_checks booleans")
        if raw["mode"] == "quick" and any(capabilities.values()):
            raise ValidationError(f"{field}.capabilities", "Quick cases cannot use broker capabilities")
        if raw.get("evidence_policy", "receipt_assisted") not in {"receipt_assisted", "autonomous"}:
            raise ValidationError(f"{field}.evidence_policy", "must be receipt_assisted or autonomous")
        for key in ("sources", "expected_obligations", "forbidden_claims", "checks"):
            if not isinstance(raw[key], list):
                raise ValidationError(f"{field}.{key}", "must be an array")
        if not all(isinstance(item, str) and item for key in ("expected_obligations", "forbidden_claims") for item in raw[key]):
            raise ValidationError(field, "obligations and forbidden claims must be nonempty strings")
        if not raw["forbidden_claims"]:
            raise ValidationError(f"{field}.forbidden_claims", "must contain at least one failure condition")
        for source_index, source in enumerate(raw["sources"]):
            if not isinstance(source, dict) or set(source) != {"id", "kind", "text"}:
                raise ValidationError(f"{field}.sources[{source_index}]", "must contain id, kind, and text")
            if not all(isinstance(source[key], str) and source[key] for key in ("id", "kind", "text")):
                raise ValidationError(f"{field}.sources[{source_index}]", "values must be nonempty strings")
        for check_index, check in enumerate(raw["checks"]):
            check_field = f"{field}.checks[{check_index}]"
            if not isinstance(check, dict) or set(check) != {"operation", "arguments", "scope"}:
                raise ValidationError(check_field, "must contain operation, arguments, and scope")
            if check["operation"] not in {"check_integer", "check_polynomial", "search_perfect"}:
                raise ValidationError(f"{check_field}.operation", "is not an allowed math operation")
            if not isinstance(check["scope"], str) or not check["scope"].strip():
                raise ValidationError(f"{check_field}.scope", "must be nonempty text")
            validate_math_arguments(check["operation"], check["arguments"])
        cases.append(json.loads(canonical_bytes(raw)))
    if not cases:
        raise ValidationError("cases", "must not be empty")
    rubric_path = root / "rubric.md"
    try:
        rubric = rubric_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValidationError("rubric", f"cannot read rubric: {error}") from error
    if not rubric.strip():
        raise ValidationError("rubric", "must not be empty")
    return cases, sha256(canonical_bytes(cases)), sha256(rubric.encode("utf-8"))


def worker_case(case: Mapping[str, Any], *, source_inputs: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Project only worker-authorized fields; never leak grader rubric data."""
    if not CASE_FIELDS.issubset(case) or set(case) - CASE_FIELDS - CASE_OPTIONAL_FIELDS:
        raise ValidationError("case", "has unknown or missing fields")
    sources = source_inputs if source_inputs is not None else case["sources"]
    return {"question": case["question"], "objective": case["objective"],
            "mode": case["mode"], "sources": json.loads(canonical_bytes(list(sources)))}


def make_manifest(*, cases: Sequence[Mapping[str, Any]], cases_hash: str,
                  rubric_hash: str, model: str, effort: str, git_sha: str,
                  max_provider_calls: int, max_wall_seconds: int,
                  max_session_usage_delta_percent: float = 10.0,
                  replicates: int = 3,
                  conditions: Sequence[str] = CONDITIONS,
                  conditions_by_case: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    """Create immutable comparison identity including deterministic paired ordering."""
    if not model or effort not in {"medium", "high"}:
        raise ValidationError("provider", "requires an explicit model and medium/high effort")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise ValidationError("replicates", "must be a positive integer")
    if isinstance(max_provider_calls, bool) or not isinstance(max_provider_calls, int) or max_provider_calls < 1:
        raise ValidationError("max_provider_calls", "must be a positive integer")
    if isinstance(max_wall_seconds, bool) or not isinstance(max_wall_seconds, int) or max_wall_seconds < 1:
        raise ValidationError("max_wall_seconds", "must be a positive integer")
    if (isinstance(max_session_usage_delta_percent, bool) or
            not isinstance(max_session_usage_delta_percent, (int, float)) or
            not math.isfinite(max_session_usage_delta_percent) or
            not 0 < max_session_usage_delta_percent <= 10):
        raise ValidationError("max_session_usage_delta_percent", "must be a percentage-point allowance in (0,10]")
    conditions = tuple(conditions)
    if not conditions or len(set(conditions)) != len(conditions) or any(c not in VALID_CONDITIONS for c in conditions):
        raise ValidationError("conditions", "must contain unique supported evaluation conditions")
    if conditions_by_case is not None and set(conditions_by_case) - {str(case["id"]) for case in cases}:
        raise ValidationError("conditions_by_case", "contains a case outside the frozen corpus")
    case_conditions = {str(case["id"]): tuple((conditions_by_case or {}).get(str(case["id"]), conditions))
                       for case in cases}
    for case_id, scheduled_conditions in case_conditions.items():
        if (not scheduled_conditions or len(set(scheduled_conditions)) != len(scheduled_conditions) or
                set(scheduled_conditions) - set(conditions)):
            raise ValidationError(f"conditions_by_case.{case_id}", "must be a nonempty unique subset of conditions")
    case_modes = {str(case["id"]): case["mode"] for case in cases}
    for case_id, scheduled_conditions in case_conditions.items():
        if case_modes[case_id] == "quick" and set(scheduled_conditions) - {"baseline", "pipeline"}:
            raise ValidationError(f"conditions_by_case.{case_id}",
                                  "Quick cases support only baseline and pipeline conditions")
    order = []
    order_seed = 0
    for case_index, case in enumerate(cases):
        for replicate in range(1, replicates + 1):
            pair_position = case_index * replicates + replicate - 1
            rotation = (pair_position + order_seed) % len(conditions)
            case_schedule = case_conditions[str(case["id"])]
            case_rotation = pair_position % len(case_schedule)
            scheduled = list(case_schedule[case_rotation:] + case_schedule[:case_rotation])
            order.append({"case_id": case["id"], "case_position": case_index,
                          "pair_position": pair_position, "replicate": replicate,
                          "conditions": scheduled})
    source_hashes = {str(case["id"]): sha256(canonical_bytes(case.get("sources", []))) for case in cases}
    projected_calls: dict[str, int] = {}
    projected_wall: dict[str, int] = {}
    mode_wall = {"quick": 180, "deep": 900, "research": 1800}
    for condition in conditions:
        scheduled_cases = [case for case in cases if condition in case_conditions[str(case["id"])] ]
        projected_calls[condition] = sum(
            retry_policy_cap for case in cases for retry_policy_cap in [
                (2 if condition == "baseline_repair" else 1 if condition == "baseline" else
                 {"quick": 1, "deep": 8, "research": 12}[case["mode"]]) * replicates]
            if condition in case_conditions[str(case["id"])])
        projected_wall[condition] = sum(
            ((390 if condition == "baseline_repair" else 210) if condition in
                {"baseline", "baseline_repair"} else mode_wall[case["mode"]]) * replicates
            for case in scheduled_cases)
    comparison_condition = next((condition for condition in ("pipeline", "adaptive", "sequential_review")
                                 if condition in conditions), None)
    return {"schema_version": 2, "record_type": "research_evaluation_manifest",
            "cases_hash": cases_hash, "rubric_hash": rubric_hash, "case_ids": [case["id"] for case in cases],
            "source_hashes": source_hashes,
            "model": model, "effort": effort, "git_sha": git_sha,
            "code_schema_version": 2,
            "order_seed": order_seed,
            "caps": {"max_provider_calls": max_provider_calls, "max_wall_seconds": max_wall_seconds,
                     "max_session_usage_delta_percent": float(max_session_usage_delta_percent)},
            "replicates": replicates, "conditions": list(conditions),
            "conditions_by_case": {case_id: list(value) for case_id, value in case_conditions.items()},
            "comparison_condition": comparison_condition,
            "ordering_rule": "global_case_order_then_replicate; rotate condition order by (pair_position + order_seed) modulo condition count",
            "capability_policy": {str(case["id"]): {
                "mode": case["mode"], "evidence_policy": case.get("evidence_policy", "receipt_assisted"),
                "declared": case.get("capabilities", {"fetch_sources": False,
                    "math_checks": bool(case.get("checks"))}),
                "conditions": {condition: ({
                    "fetch_sources": bool(case.get("capabilities", {}).get("fetch_sources", False)),
                    "math_checks": bool(case.get("capabilities", {}).get("math_checks", bool(case.get("checks"))))}
                    if condition in {"pipeline", "sequential_review", "adaptive"} and
                       case.get("evidence_policy", "receipt_assisted") == "autonomous"
                    else {"fetch_sources": False, "math_checks": False})
                    for condition in case_conditions[str(case["id"])]}} for case in cases},
            "retry_policy": {condition: {
                "structural_retries_by_mode": {
                    mode: (1 if condition == "baseline_repair" else
                           {"quick": 0, "deep": 1, "research": 2}[mode]
                           if condition in {"pipeline", "sequential_review", "adaptive"} else 0)
                    for mode in ("quick", "deep", "research")},
                "provider_call_cap_by_mode": {
                    mode: (2 if condition == "baseline_repair" else
                           {"quick": 1, "deep": 8, "research": 12}[mode])
                    for mode in ("quick", "deep", "research")}}
                for condition in conditions},
            "resource_projection": {"provider_calls_by_condition": projected_calls,
                "wall_seconds_by_condition": projected_wall,
                "provider_calls_worst_case": sum(projected_calls.values()),
                "wall_seconds_worst_case": sum(projected_wall.values()),
                "assumptions": "strict baseline preflight plus one call; repair baseline up to two calls; engine arms at their mode model-call and wall caps"},
            "ordering": order}


def validate_resume(existing: Mapping[str, Any], requested: Mapping[str, Any]) -> None:
    """Reject any changed immutable comparison input before resuming."""
    if canonical_bytes(existing) != canonical_bytes(requested):
        raise ValidationError("manifest", "comparison inputs changed; resume is not allowed")


class EvaluationStore:
    """Incremental local evaluation files; ambiguous trial intents are never replayed."""

    def __init__(self, directory: Path, manifest: Mapping[str, Any]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        with acquire_run_lock(self.directory):
            self._initialize(manifest)

    def _initialize(self, manifest: Mapping[str, Any]) -> None:
        manifest_path = self.directory / "manifest.json"
        if manifest_path.exists():
            prior = _read_json(manifest_path)
            validate_resume(prior, manifest)
        else:
            self.directory.mkdir(parents=True, exist_ok=True)
            write_json(manifest_path, manifest)
        (self.directory / "trials").mkdir(exist_ok=True)
        if not (self.directory / "grades.json").exists():
            write_json(self.directory / "grades.json", [])
        if not (self.directory / "budget.json").exists():
            write_json(self.directory / "budget.json", {"provider_calls_reserved": 0,
                "wall_seconds_observed": 0.0})

    def reserve_budget(self, *, provider_calls: int, setup_wall_seconds: float = 0.0) -> None:
        """Persist call reservations and setup time before work can launch."""
        caps = _read_json(self.directory / "manifest.json")["caps"]
        path = self.directory / "budget.json"
        ledger = _read_json(path)
        if isinstance(provider_calls, bool) or not isinstance(provider_calls, int) or provider_calls < 0:
            raise ValidationError("provider_calls", "reservation must be a nonnegative integer")
        if provider_calls + ledger["provider_calls_reserved"] > caps["max_provider_calls"]:
            raise ValidationError("budget", "provider call cap would be exceeded")
        if setup_wall_seconds < 0 or not math.isfinite(setup_wall_seconds):
            raise ValidationError("wall_seconds", "must be finite and nonnegative")
        if setup_wall_seconds + ledger["wall_seconds_observed"] > caps["max_wall_seconds"]:
            raise ValidationError("budget", "wall time cap is exhausted")
        ledger["provider_calls_reserved"] += provider_calls
        ledger["wall_seconds_observed"] += float(setup_wall_seconds)
        write_json(path, ledger)

    def record_elapsed(self, elapsed_seconds: float) -> None:
        path = self.directory / "budget.json"
        ledger = _read_json(path)
        if elapsed_seconds < 0 or not math.isfinite(elapsed_seconds):
            raise ValidationError("wall_seconds", "must be finite and nonnegative")
        ledger["wall_seconds_observed"] += float(elapsed_seconds)
        write_json(path, ledger)

    def record_usage_check(self, *, observed_remaining_percent: float, case_id: str,
                           replicate: int, condition: str) -> bool:
        """Persist 5-hour quota readings and enforce the allowance from its saved baseline."""
        if (isinstance(observed_remaining_percent, bool) or
                not isinstance(observed_remaining_percent, (int, float)) or
                not math.isfinite(observed_remaining_percent) or
                not 0 <= observed_remaining_percent <= 100):
            raise ValidationError("session_usage", "remaining quota must be a percentage from zero through 100")
        path = self.directory / "usage-checks.json"
        checks = _read_json(path) if path.exists() else []
        if checks:
            baseline = checks[0].get("baseline_remaining_percent",
                                     checks[0].get("observed_remaining_percent"))
            if baseline is None:
                raise ValidationError("session_usage", "existing readings lack a resumable 5-hour quota baseline")
            previous = checks[-1]["observed_remaining_percent"]
            if observed_remaining_percent > previous:
                raise ValidationError("session_usage", "quota increased or reset; the saved allowance cannot be measured reliably")
        else:
            baseline = float(observed_remaining_percent)
        quota_drop = float(baseline) - float(observed_remaining_percent)
        checks.append({"case_id": case_id, "replicate": replicate, "condition": condition,
                       "observed_remaining_percent": float(observed_remaining_percent),
                       "baseline_remaining_percent": float(baseline),
                       "quota_drop_percentage_points": quota_drop,
                       "recorded_at_utc": datetime.now(timezone.utc).isoformat()})
        write_json(path, checks)
        allowance = _read_json(self.directory / "manifest.json")["caps"]["max_session_usage_delta_percent"]
        return observed_remaining_percent > 0 and quota_drop < allowance

    def _trial_path(self, case_id: str, replicate: int, condition: str) -> Path:
        if condition not in VALID_CONDITIONS or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case_id):
            raise ValidationError("trial", "invalid case or condition")
        return self.directory / "trials" / f"{case_id}-{replicate:02d}-{condition}" / "trial.json"

    def record_intent(self, *, case_id: str, replicate: int, condition: str,
                      source_hash: str, reserve_calls: int = 1,
                      setup_wall_seconds: float = 0.0) -> None:
        path = self._trial_path(case_id, replicate, condition)
        if path.exists():
            prior = _read_json(path)
            if prior.get("status") in {"intent", "ambiguous"}:
                raise ValidationError("trial", "ambiguous or in-flight intent will not be relaunched")
            raise ValidationError("trial", "already recorded")
        self.reserve_budget(provider_calls=reserve_calls,
                            setup_wall_seconds=setup_wall_seconds)
        trial = make_trial(case_id=case_id, replicate=replicate, condition=condition,
            status="intent", report=None, provider_calls=0, wall_seconds=0,
            cost_usd=None, source_hash=source_hash)
        trial["reserved_provider_calls"] = reserve_calls
        write_json(path, trial)

    def acquire_pair_inputs(self, case: Mapping[str, Any], replicate: int) -> dict[str, Any]:
        """Persist one deterministic receipt batch shared byte-for-byte by both conditions."""
        case_id = str(case["id"])
        if isinstance(replicate, bool) or not isinstance(replicate, int) or replicate < 1:
            raise ValidationError("replicate", "must be a positive integer")
        pair_dir = self.directory / "receipts"
        pair_path = pair_dir / f"{case_id}-{replicate:02d}.json"
        receipt_items = []
        source_inputs = []
        for source in case["sources"]:
            source_inputs.append({"id": source["id"], "kind": "text",
                "title": f"Evaluation supplied source: {source['id']}", "text": source["text"],
                "url": None, "published_at": None})
        checks = case["checks"] if case.get("evidence_policy", "receipt_assisted") == "receipt_assisted" else []
        for index, check in enumerate(checks, 1):
            request = {"operation": check["operation"], "arguments": check["arguments"]}
            result = perform_math_check(check["operation"], check["arguments"])
            receipt = {"request": request, "result": result, "scope": check["scope"]}
            receipt_items.append(receipt)
            text = ("Evaluator-supplied check transcript. This operation was acquired once for the "
                    "paired comparison and is supplied as text to both conditions; it is not an "
                    "in-run pipeline tool receipt.\n" + canonical_bytes(receipt).decode("utf-8"))
            source_inputs.append({"id": f"eval-check-{index}", "kind": "text",
                "title": f"Evaluation check transcript {index}", "text": text,
                "url": None, "published_at": None})
        record = {"schema_version": 1, "record_type": "evaluation_pair_inputs",
                  "case_id": case_id, "replicate": replicate,
                  "receipts": receipt_items, "source_inputs": source_inputs,
                  "source_hash": sha256(canonical_bytes(source_inputs))}
        if pair_path.is_file():
            prior = _read_json(pair_path)
            if canonical_bytes(prior) != canonical_bytes(record):
                raise ValidationError("receipt", "persisted paired inputs or digest changed")
            return prior
        write_json(pair_path, record)
        return record

    def record_result(self, trial: Mapping[str, Any]) -> None:
        path = self._trial_path(str(trial.get("case_id", "")), trial.get("replicate"),
                                str(trial.get("condition", "")))
        if not path.exists():
            raise ValidationError("trial", "persist intent before recording provider result")
        prior = _read_json(path)
        if prior.get("status") != "intent":
            raise ValidationError("trial", "only a persisted intent may be completed")
        if prior.get("source_hash") != trial.get("source_hash"):
            raise ValidationError("trial", "source hash changed after intent")
        if trial.get("provider_calls", 0) > prior.get("reserved_provider_calls", 0):
            raise ValidationError("trial", "actual provider calls exceed the persisted reservation")
        write_json(path, dict(trial))

    def mark_ambiguous(self, case_id: str, replicate: int, condition: str,
                       *, reason: str, wall_seconds: float) -> None:
        path = self._trial_path(case_id, replicate, condition)
        if not path.exists():
            raise ValidationError("trial", "ambiguous outcome requires a persisted intent")
        prior = _read_json(path)
        if prior.get("status") != "intent":
            raise ValidationError("trial", "only an in-flight intent may become ambiguous")
        prior.update({"status": "ambiguous", "reason": reason[:1000],
                      "wall_seconds": float(wall_seconds)})
        write_json(path, prior)

    def append_grade(self, grade: Mapping[str, Any]) -> None:
        path = self.directory / "grades.json"
        grades = _read_json(path)
        key = (grade.get("case_id"), grade.get("replicate"), grade.get("condition"))
        if any((item.get("case_id"), item.get("replicate"), item.get("condition")) == key for item in grades):
            raise ValidationError("grade", "duplicate grade for this trial")
        grades.append(dict(grade))
        write_json(path, grades)

    def grades(self) -> list[dict[str, Any]]:
        return _read_json(self.directory / "grades.json")

    def trial_records(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted((self.directory / "trials").glob("*/trial.json")):
            records.append(_read_json(path))
        return records

    def recovery_records(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted((self.directory / "recoveries").glob("*/recovery.json")):
            records.append(_read_json(path))
        return records

    def prepare_grading_packets(self, cases: Sequence[Mapping[str, Any]],
                                rubric_text: str) -> dict[str, Any]:
        """Write immutable, condition-blind packets and a separate grading key."""
        cases_by_id = {case["id"]: case for case in cases}
        packet_dir = self.directory / "grading-packets"
        packet_dir.mkdir(exist_ok=True)
        salt_path = self.directory / "grading-key-salt.json"
        salt = (_read_json(salt_path)["salt"] if salt_path.exists()
                else secrets.token_hex(32))
        if not salt_path.exists():
            write_json(salt_path, {"schema_version": 1, "salt": salt})
        packets = []
        key = []
        for trial in self.trial_records():
            case_id, replicate = trial["case_id"], trial["replicate"]
            case = cases_by_id.get(case_id)
            if case is None:
                raise ValidationError("grading_packet", f"case {case_id} is absent from the frozen corpus")
            trial_dir = self._trial_path(case_id, replicate, trial["condition"]).parent
            artifact_hash = trial.get("artifact_sha256") or trial.get("report_sha256")
            if artifact_hash is None:
                continue
            semantic_material, supporting_hashes = _captured_answer_material(trial_dir, trial)
            supporting_hashes = [value for value in supporting_hashes if value != artifact_hash]
            packet_id = "grade-" + sha256(canonical_bytes({"salt": salt,
                "case_id": case_id, "replicate": replicate,
                "condition": trial["condition"], "artifact_sha256": artifact_hash}))[:20]
            packet = {"schema_version": 1, "record_type": "blind_research_grading_packet",
                "packet_id": packet_id, "case_id": case_id, "replicate": replicate,
                "question": case["question"], "objective": case["objective"],
                "fixed_evidence": [{**source, "sha256": sha256(canonical_bytes(source))}
                                   for source in case["sources"]],
                "answer_artifact": {"sha256": artifact_hash,
                                    "supporting_artifact_sha256s": supporting_hashes,
                                    "semantic_content": semantic_material},
                "grading_obligations": case["expected_obligations"],
                "failure_conditions": case["forbidden_claims"], "rubric": rubric_text}
            packet_hash = sha256(canonical_bytes(packet))
            packet_path = packet_dir / f"{packet_id}.json"
            if packet_path.exists() and canonical_bytes(_read_json(packet_path)) != canonical_bytes(packet):
                raise ValidationError("grading_packet", "a frozen packet changed; use a new evaluation directory")
            if not packet_path.exists():
                write_json(packet_path, packet)
            packets.append({"packet_id": packet_id, "packet_sha256": packet_hash,
                            "artifact_sha256": artifact_hash,
                            "supporting_artifact_sha256s": supporting_hashes})
            key.append({"packet_id": packet_id, "condition": trial["condition"],
                "cost_usd": trial.get("cost_usd"), "status": trial.get("status"),
                "failure_class": trial.get("failure_class"), "provider_calls": trial.get("provider_calls"),
                "wall_seconds": trial.get("wall_seconds")})
        manifest = {"schema_version": 1, "record_type": "blind_grading_packet_index",
                    "packets": packets}
        index_path = packet_dir / "index.json"
        if index_path.exists() and canonical_bytes(_read_json(index_path)) != canonical_bytes(manifest):
            raise ValidationError("grading_packet", "packet index is frozen; use a new evaluation directory")
        if not index_path.exists():
            write_json(index_path, manifest)
        key_path = self.directory / "grading-key.json"
        key_value = {"schema_version": 1, "record_type": "blind_grading_key",
                     "entries": key, "salt": salt}
        if key_path.exists() and canonical_bytes(_read_json(key_path)) != canonical_bytes(key_value):
            raise ValidationError("grading_packet", "grading key is frozen; use a new evaluation directory")
        if not key_path.exists():
            write_json(key_path, key_value)
        evaluation_manifest = _read_json(self.directory / "manifest.json")
        evaluation_manifest["grading_packet_index_sha256"] = sha256(canonical_bytes(manifest))
        evaluation_manifest["grading_key_sha256"] = sha256(canonical_bytes(key_value))
        write_json(self.directory / "manifest.json", evaluation_manifest)
        return {"packet_count": len(packets), "index_path": str(index_path.resolve()),
                "grading_key_path": str(key_path.resolve()),
                "grading_packet_index_sha256": evaluation_manifest["grading_packet_index_sha256"],
                "grading_key_sha256": evaluation_manifest["grading_key_sha256"]}

    def append_recovery(self, *, case_id: str, replicate: int, condition: str,
                        source_hash: str, reserve_calls: int = 1) -> dict[str, Any]:
        """Append an independently identified recovery intent linked to an original trial."""
        original_path = self._trial_path(case_id, replicate, condition)
        if not original_path.exists():
            raise ValidationError("recovery", "original trial must exist before a recovery can be appended")
        original = _read_json(original_path)
        if original.get("source_hash") != source_hash:
            raise ValidationError("recovery", "recovery source hash must match the original trial")
        attempts = [item for item in self.recovery_records()
                    if item.get("case_id") == case_id and item.get("replicate") == replicate
                    and item.get("condition") == condition]
        attempt_id = f"{case_id}-{replicate:02d}-{condition}-recovery-{len(attempts) + 1:02d}"
        attempt = make_trial(case_id=case_id, replicate=replicate, condition=condition,
            status="intent", report=None, provider_calls=0, wall_seconds=0,
            cost_usd=None, source_hash=source_hash)
        attempt.update({"record_type": "evaluation_recovery", "recovery_id": attempt_id,
            "parent_trial_id": f"{case_id}/{replicate}/{condition}",
            "parent_status": original.get("status"), "recovery_number": len(attempts) + 1,
            "reserved_provider_calls": reserve_calls})
        path = self.directory / "recoveries" / attempt_id / "recovery.json"
        self.reserve_budget(provider_calls=reserve_calls)
        write_json(path, attempt)
        return attempt

    def record_recovery_result(self, recovery_id: str, trial: Mapping[str, Any]) -> None:
        path = self.directory / "recoveries" / recovery_id / "recovery.json"
        if not path.exists():
            raise ValidationError("recovery", "recovery intent does not exist")
        prior = _read_json(path)
        if prior.get("status") != "intent":
            raise ValidationError("recovery", "only an in-flight recovery can be completed")
        if (prior.get("source_hash") != trial.get("source_hash") or
                any(trial.get(key) != prior.get(key) for key in ("case_id", "replicate", "condition"))):
            raise ValidationError("recovery", "recovery identity or source hash changed")
        if trial.get("provider_calls", 0) > prior.get("reserved_provider_calls", 0):
            raise ValidationError("recovery", "provider calls exceed the recovery reservation")
        result = dict(trial)
        result.update({key: prior[key] for key in
            ("record_type", "recovery_id", "parent_trial_id", "parent_status", "recovery_number",
             "reserved_provider_calls")})
        write_json(path, result)

    def finalize(self, grades: Sequence[Mapping[str, Any]], *, deep_case_ids: set[str],
                 quick_case_ids: set[str] | None = None,
                 required_replicates: int | None = None) -> dict[str, Any]:
        with acquire_run_lock(self.directory):
            return self._finalize_locked(grades, deep_case_ids=deep_case_ids,
                quick_case_ids=quick_case_ids, required_replicates=required_replicates)

    def _finalize_locked(self, grades: Sequence[Mapping[str, Any]], *, deep_case_ids: set[str],
                         quick_case_ids: set[str] | None,
                         required_replicates: int | None) -> dict[str, Any]:
        manifest = _read_json(self.directory / "manifest.json")
        if required_replicates is not None and required_replicates != manifest["replicates"]:
            raise ValidationError("replicates", "finalization must match the immutable manifest")
        budget = _read_json(self.directory / "budget.json")
        trials = self.trial_records()
        artifact_roots = {(item["case_id"], item["replicate"], item["condition"]):
                          self._trial_path(item["case_id"], item["replicate"],
                                           item["condition"]).parent for item in trials}
        packet_bindings: dict[tuple[str, int, str], dict[str, str]] = {}
        if manifest.get("grading_packet_index_sha256"):
            index_path = self.directory / "grading-packets" / "index.json"
            key_path = self.directory / "grading-key.json"
            index = _read_json(index_path)
            if sha256(canonical_bytes(index)) != manifest["grading_packet_index_sha256"]:
                raise ValidationError("grading_packet_index_sha256", "frozen packet index hash differs")
            if not manifest.get("grading_key_sha256") or not key_path.is_file():
                raise ValidationError("grading_key_sha256", "a frozen grading key hash is required")
            key = _read_json(key_path)
            if sha256(canonical_bytes(key)) != manifest["grading_key_sha256"]:
                raise ValidationError("grading_key_sha256", "frozen grading key hash differs")
            indexed = {entry["packet_id"]: entry for entry in index.get("packets", [])}
            key_entries = key.get("entries", [])
            key_ids = [entry.get("packet_id") for entry in key_entries]
            if len(key_ids) != len(set(key_ids)) or set(key_ids) != set(indexed):
                raise ValidationError("grading_key", "must bind each indexed packet exactly once")
            for key_entry in key_entries:
                packet_id = key_entry["packet_id"]
                packet_index = indexed.get(packet_id)
                if packet_index is None:
                    raise ValidationError("grading_packet_index", "grading key references an absent packet")
                packet_path = self.directory / "grading-packets" / f"{packet_id}.json"
                packet = _read_json(packet_path)
                packet_hash = sha256(canonical_bytes(packet))
                if packet_hash != packet_index["packet_sha256"]:
                    raise ValidationError("grading_packet", "packet content differs from the frozen index")
                answer_artifact = packet.get("answer_artifact", {})
                if (answer_artifact.get("sha256") != packet_index.get("artifact_sha256") or
                        answer_artifact.get("supporting_artifact_sha256s", []) !=
                        packet_index.get("supporting_artifact_sha256s", [])):
                    raise ValidationError("grading_packet", "artifact bindings differ from the frozen index")
                identity = (packet["case_id"], packet["replicate"], key_entry["condition"])
                if identity in packet_bindings:
                    raise ValidationError("grading_packet", "duplicate condition binding")
                packet_bindings[identity] = {"packet_id": packet_id,
                    "packet_sha256": packet_hash,
                    "artifact_sha256": packet_index["artifact_sha256"],
                    "supporting_artifact_sha256s": packet_index.get("supporting_artifact_sha256s", [])}
        comparison = compare_trials(self.trial_records(), grades,
            required_replicates=manifest["replicates"], deep_case_ids=deep_case_ids,
            quick_case_ids=quick_case_ids or set(),
            case_ids=set(manifest["case_ids"]), requested_model=manifest["model"],
            requested_effort=manifest["effort"], caps=manifest["caps"],
            budget_wall_seconds=budget["wall_seconds_observed"],
            conditions=manifest.get("conditions", CONDITIONS),
            conditions_by_case=manifest.get("conditions_by_case"),
            comparison_condition=manifest.get("comparison_condition"),
            recoveries=self.recovery_records(), manifest=manifest,
            artifact_roots=artifact_roots, packet_bindings=packet_bindings)
        write_json(self.directory / "comparison.json", comparison)
        (self.directory / "comparison.md").write_text(comparison_markdown_v2(comparison), encoding="utf-8")
        return comparison


def make_trial(*, case_id: str, replicate: int, condition: str, status: str,
               report: str | None, provider_calls: int, wall_seconds: float,
               cost_usd: float | None, source_hash: str, grader: str | None = None,
               tool_calls_used: int | None = None,
               artifact_sha256: str | None = None,
               protocol_validity: str | None = None,
               failure_class: str | None = None,
               final_status: str | None = None,
               observed_session_markers: int | None = None) -> dict[str, Any]:
    if condition not in VALID_CONDITIONS:
        raise ValidationError("condition", "is not a supported evaluation condition")
    if status not in {"intent", "complete", "failed", "ambiguous"}:
        raise ValidationError("status", "is invalid")
    if not isinstance(case_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case_id):
        raise ValidationError("case_id", "must be a lowercase hyphenated identifier")
    if isinstance(replicate, bool) or not isinstance(replicate, int) or replicate < 1:
        raise ValidationError("replicate", "must be a positive integer")
    if report is not None and not isinstance(report, str):
        raise ValidationError("report", "must be text or null")
    if isinstance(provider_calls, bool) or not isinstance(provider_calls, int) or provider_calls < 0:
        raise ValidationError("provider_calls", "must be a nonnegative integer")
    if tool_calls_used is not None and (isinstance(tool_calls_used, bool) or
            not isinstance(tool_calls_used, int) or tool_calls_used < 0):
        raise ValidationError("tool_calls_used", "must be a nonnegative integer or null")
    if isinstance(wall_seconds, bool) or not isinstance(wall_seconds, (float, int)) or wall_seconds < 0 or not math.isfinite(wall_seconds):
        raise ValidationError("wall_seconds", "must be finite and nonnegative")
    if cost_usd is not None and (isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0 or not math.isfinite(cost_usd)):
        raise ValidationError("cost_usd", "must be null or finite and nonnegative")
    report_hash = sha256(report.encode("utf-8")) if report is not None else None
    if artifact_sha256 is not None and (not isinstance(artifact_sha256, str) or
            not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256)):
        raise ValidationError("artifact_sha256", "must be a lowercase SHA-256 digest or null")
    if protocol_validity not in {None, "valid", "invalid", "unavailable"}:
        raise ValidationError("protocol_validity", "is invalid")
    if failure_class not in {None, "schema_rejection", "provider_usage_limit", "provider_failure",
                             "timeout", "permission_failure", "other"}:
        raise ValidationError("failure_class", "is invalid")
    if final_status is not None and not isinstance(final_status, str):
        raise ValidationError("final_status", "must be text or null")
    if observed_session_markers is not None and (isinstance(observed_session_markers, bool) or
            not isinstance(observed_session_markers, int) or observed_session_markers < 0):
        raise ValidationError("observed_session_markers", "must be a nonnegative integer or null")
    return {"schema_version": 2, "record_type": "research_evaluation_trial",
            "case_id": case_id, "replicate": replicate, "condition": condition,
            "status": status, "provider_calls": provider_calls,
            "tool_calls_used": tool_calls_used,
            "wall_seconds": float(wall_seconds), "cost_usd": cost_usd,
            "source_hash": source_hash, "grader": grader,
            "report": report, "report_sha256": report_hash,
            "artifact_sha256": artifact_sha256,
            "protocol_validity": protocol_validity,
            "failure_class": failure_class,
            "final_status": final_status,
            "observed_session_markers": observed_session_markers}


def make_grade(*, case_id: str, replicate: int, condition: str, grader: str,
               dimensions: Mapping[str, int] | None, critical_failures: Sequence[str],
               evidence: Sequence[str], artifact_sha256: str | None = None,
               supporting_artifact_sha256s: Sequence[str] = (),
               packet_id: str | None = None, packet_sha256: str | None = None,
               evidence_refs: Sequence[str] = (),
               dimension_reasons: Mapping[str, str] | None = None,
               assessability: str = "assessable",
               calibration_judgment: str = "not_assessed",
               calibration_evidence: Sequence[str] = (),
               legacy_unbound: bool = False) -> dict[str, Any]:
    if not isinstance(grader, str) or not grader.strip():
        raise ValidationError("grader", "must identify a human or advisory grader")
    if assessability not in {"assessable", "unavailable"}:
        raise ValidationError("assessability", "must be assessable or unavailable")
    if assessability == "assessable":
        if not isinstance(dimensions, Mapping) or set(dimensions) != set(DIMENSIONS):
            raise ValidationError("dimensions", "must grade all five rubric dimensions")
        if any(isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2) for value in dimensions.values()):
            raise ValidationError("dimensions", "scores must be integers from zero to two")
    elif dimensions is not None:
        raise ValidationError("dimensions", "unavailable semantic grades must not contain scores")
    if assessability == "assessable" and not legacy_unbound:
        if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs or any(
                not isinstance(item, str) or not re.fullmatch(
                    r"(?:step|claim|error|passage):[A-Za-z0-9._:-]+", item)
                for item in evidence_refs):
            raise ValidationError("evidence_refs", "assessable grades require references to proof steps, claims, errors, or answer passages")
        if not isinstance(dimension_reasons, Mapping) or set(dimension_reasons) != set(DIMENSIONS) or any(
                not isinstance(value, str) or not value.strip() for value in dimension_reasons.values()):
            raise ValidationError("dimension_reasons", "each scored dimension requires a concrete rationale")
    if not isinstance(evidence, (list, tuple)) or (assessability == "assessable" and not evidence) or any(not isinstance(item, str) or not item.strip() for item in evidence):
        raise ValidationError("evidence", "must contain evidence for assessable grades and be empty for unavailable grades")
    if not isinstance(critical_failures, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in critical_failures):
        raise ValidationError("critical_failures", "entries must be nonempty strings")
    if condition not in VALID_CONDITIONS:
        raise ValidationError("condition", "is not a supported evaluation condition")
    if calibration_judgment not in {"calibrated", "overcautious", "overconfident", "not_assessed"}:
        raise ValidationError("calibration_judgment", "is invalid")
    if not isinstance(calibration_evidence, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in calibration_evidence):
        raise ValidationError("calibration_evidence", "must contain nonempty text entries")
    if calibration_judgment == "not_assessed" and calibration_evidence:
        raise ValidationError("calibration_evidence", "cannot be supplied when calibration is not assessed")
    if calibration_judgment != "not_assessed" and not calibration_evidence:
        raise ValidationError("calibration_evidence", "is required for an assessed calibration judgment")
    if assessability == "unavailable" and calibration_judgment != "not_assessed":
        raise ValidationError("calibration_judgment", "cannot be assessed without an output artifact")
    if artifact_sha256 is not None and (not isinstance(artifact_sha256, str) or
            not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256)):
        raise ValidationError("artifact_sha256", "must be a lowercase SHA-256 digest or null")
    if (not isinstance(supporting_artifact_sha256s, (list, tuple)) or
            any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in supporting_artifact_sha256s) or
            len(set(supporting_artifact_sha256s)) != len(supporting_artifact_sha256s)):
        raise ValidationError("supporting_artifact_sha256s", "must contain unique lowercase SHA-256 digests")
    if ((packet_id is None) != (packet_sha256 is None) or
            (packet_id is not None and (not isinstance(packet_id, str) or
             not re.fullmatch(r"grade-[0-9a-f]{20}", packet_id))) or
            (packet_sha256 is not None and (not isinstance(packet_sha256, str) or
             not re.fullmatch(r"[0-9a-f]{64}", packet_sha256)))):
        raise ValidationError("packet", "packet id and hash must be supplied together and be valid")
    if assessability == "assessable" and artifact_sha256 is None and not legacy_unbound:
        raise ValidationError("artifact_sha256", "new assessable grades must identify the reviewed artifact")
    if assessability == "unavailable" and (evidence or critical_failures):
        raise ValidationError("assessability", "unavailable grades cannot contain scores, failures, or evidence")
    grade_version = 1 if legacy_unbound else 2
    return {"schema_version": grade_version, "record_type": "research_evaluation_grade",
            "case_id": case_id, "replicate": replicate, "condition": condition,
            "grader": grader, "dimensions": dict(dimensions) if dimensions is not None else None,
            "score": sum(dimensions.values()) if dimensions is not None else None,
            "critical_failures": list(critical_failures), "evidence": list(evidence),
            "evidence_refs": list(evidence_refs),
            "dimension_reasons": dict(dimension_reasons or {}),
            "supporting_artifact_sha256s": list(supporting_artifact_sha256s),
            "packet_id": packet_id, "packet_sha256": packet_sha256,
            "artifact_sha256": artifact_sha256, "assessability": assessability,
            "calibration_judgment": calibration_judgment,
            "calibration_evidence": list(calibration_evidence)}


def compare_trials(trials: Sequence[Mapping[str, Any]], grades: Sequence[Mapping[str, Any]],
                   *, required_replicates: int = 3,
                   deep_case_ids: set[str] | None = None,
                   quick_case_ids: set[str] | None = None,
                   case_ids: set[str] | None = None,
                   requested_model: str | None = None,
                   requested_effort: str | None = None,
                   caps: Mapping[str, Any] | None = None,
                   budget_wall_seconds: float | None = None,
                   conditions: Sequence[str] = CONDITIONS,
                   conditions_by_case: Mapping[str, Sequence[str]] | None = None,
                   comparison_condition: str | None = None,
                   recoveries: Sequence[Mapping[str, Any]] = (),
                   manifest: Mapping[str, Any] | None = None,
                   artifact_roots: Mapping[tuple[str, int, str], Path] | None = None,
                   packet_bindings: Mapping[tuple[str, int, str], Mapping[str, str]] | None = None) -> dict[str, Any]:
    """Aggregate only complete, explicitly graded pairs; never infer quality from exit status."""
    trial_map: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    grade_map: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    duplicates: list[str] = []
    for collection, target, label in ((trials, trial_map, "trial"), (grades, grade_map, "grade")):
        for item in collection:
            key = (item.get("case_id"), item.get("replicate"), item.get("condition"))
            if key in target:
                duplicates.append(f"duplicate {label}: {key}")
            target[key] = item
    all_case_ids = sorted(case_ids or ({key[0] for key in trial_map} | {key[0] for key in grade_map}))
    conditions = tuple(conditions)
    if not conditions or len(set(conditions)) != len(conditions) or set(conditions) - set(VALID_CONDITIONS):
        raise ValidationError("conditions", "must list unique supported evaluation conditions")
    scheduled_conditions = {case_id: tuple((conditions_by_case or {}).get(case_id, conditions))
                            for case_id in all_case_ids}
    if any(not values or set(values) - set(conditions) for values in scheduled_conditions.values()):
        raise ValidationError("conditions_by_case", "must map each case to supported scheduled conditions")
    capability_policies = (manifest or {}).get("capability_policy", {})

    def pair_capabilities_match(case_id: str, left_condition: str,
                                right_condition: str) -> bool:
        policy = capability_policies.get(case_id)
        if not isinstance(policy, Mapping):
            return True
        per_condition = policy.get("conditions", {})
        declared = policy.get("declared", {})
        left = per_condition.get(left_condition, declared)
        right = per_condition.get(right_condition, declared)
        return canonical_bytes(left) == canonical_bytes(right)

    expected = {(case_id, replicate, condition) for case_id in all_case_ids
                for replicate in range(1, required_replicates + 1)
                for condition in scheduled_conditions[case_id]}
    unexpected = [f"unexpected trial or grade: {key}"
                  for key in (trial_map.keys() | grade_map.keys()) - expected]
    missing_trials = sorted(expected - trial_map.keys())
    missing_grades = sorted(expected - grade_map.keys())
    bad_trials = [key for key, item in trial_map.items() if item.get("status") != "complete" or
                  (item.get("report") is None and item.get("artifact_sha256") is None)]
    nonterminal_trials = [key for key, item in trial_map.items()
                          if item.get("status") in {"ambiguous", "intent"}]
    missing_artifact_trials = [key for key, item in trial_map.items()
                               if item.get("report") is None and item.get("artifact_sha256") is None]
    mismatched_pairs: list[str] = []
    reference_condition = ("baseline_repair" if "baseline_repair" in conditions else "baseline")
    if comparison_condition is None:
        comparison_condition = next((condition for condition in ("pipeline", "adaptive", "sequential_review")
                                     if condition in conditions), None)
    if comparison_condition not in conditions:
        comparison_condition = None
    all_expected_pair_keys = ({(case_id, replicate) for case_id in all_case_ids
        if comparison_condition is not None and
        {reference_condition, comparison_condition}.issubset(scheduled_conditions[case_id])
        for replicate in range(1, required_replicates + 1)})
    source_mismatch_pair_keys = set()
    for case_id, replicate in all_expected_pair_keys:
        reference = trial_map.get((case_id, replicate, reference_condition))
        comparison = trial_map.get((case_id, replicate, comparison_condition))
        if (reference is not None and comparison is not None and
                reference.get("source_hash") != comparison.get("source_hash")):
            source_mismatch_pair_keys.add((case_id, replicate))
    capability_mismatch_pair_keys = {(case_id, replicate)
        for case_id, replicate in all_expected_pair_keys
        if not pair_capabilities_match(case_id, reference_condition, comparison_condition)}
    expected_pair_keys = (all_expected_pair_keys - capability_mismatch_pair_keys -
                          source_mismatch_pair_keys)
    has_comparison_pair = comparison_condition is not None and any(
        {reference_condition, comparison_condition}.issubset(scheduled_conditions[case_id])
        for case_id in all_case_ids)
    for case_id in all_case_ids:
        for replicate in range(1, required_replicates + 1):
            if (comparison_condition is None or
                    not {reference_condition, comparison_condition}.issubset(scheduled_conditions[case_id])):
                continue
            reference = trial_map.get((case_id, replicate, reference_condition))
            pipeline = trial_map.get((case_id, replicate, comparison_condition))
            if reference and pipeline and reference.get("source_hash") != pipeline.get("source_hash"):
                mismatched_pairs.append(f"source hash mismatch: {case_id}/{replicate}")
    bad_hashes = [f"report hash mismatch: {key}" for key, item in trial_map.items()
                  if item.get("report") is not None and
                  (not isinstance(item.get("report"), str) or
                   item.get("report_sha256") != sha256(item["report"].encode("utf-8")))]
    quick_case_ids = quick_case_ids or set()
    wrong_quick_calls = [f"Quick comparison arm must use exactly one call: {key}"
        for key, item in trial_map.items() if key[0] in quick_case_ids and
        key[2] not in {"baseline", "baseline_repair"} and item.get("provider_calls") != 1]
    wrong_baseline_calls = [f"baseline must use exactly one call: {key}"
        for key, item in trial_map.items() if key[2] == "baseline" and item.get("provider_calls") != 1]
    wrong_repair_baseline_calls = [f"baseline_repair must use one or two calls: {key}"
        for key, item in trial_map.items() if key[2] == "baseline_repair" and
        item.get("provider_calls") not in {1, 2}]
    settings_errors = [f"requested/observed settings mismatch or unknown: {key}"
        for key, item in trial_map.items() if item.get("status") == "complete" and
        requested_model is not None and requested_effort is not None and
        (item.get("requested_model") != requested_model or item.get("requested_effort") != requested_effort or
         item.get("observed_model") != requested_model or item.get("observed_effort") != requested_effort)]
    actual_provider_calls = sum(int(item.get("provider_calls", 0)) for item in trial_map.values())
    actual_wall_seconds = sum(float(item.get("wall_seconds", 0)) for item in trial_map.values())
    cap_errors = []
    if caps and actual_provider_calls > caps["max_provider_calls"]:
        cap_errors.append("actual provider calls exceeded the manifest cap")
    total_wall_seconds = budget_wall_seconds if budget_wall_seconds is not None else actual_wall_seconds
    if caps and total_wall_seconds > caps["max_wall_seconds"]:
        cap_errors.append("actual trial wall time exceeded the manifest cap")
    invalid_grades = []
    for key, grade in list(grade_map.items()):
        try:
            validated = make_grade(case_id=key[0], replicate=key[1], condition=key[2],
                grader=grade.get("grader"), dimensions=grade.get("dimensions"),
                critical_failures=grade.get("critical_failures"), evidence=grade.get("evidence"),
                artifact_sha256=grade.get("artifact_sha256"),
                supporting_artifact_sha256s=grade.get("supporting_artifact_sha256s", ()),
                packet_id=grade.get("packet_id"), packet_sha256=grade.get("packet_sha256"),
                evidence_refs=grade.get("evidence_refs", ()),
                dimension_reasons=grade.get("dimension_reasons"),
                assessability=grade.get("assessability", "assessable"),
                calibration_judgment=grade.get("calibration_judgment", "not_assessed"),
                calibration_evidence=grade.get("calibration_evidence", ()),
                legacy_unbound=grade.get("schema_version", 1) < 2)
            if grade.get("score") != validated["score"]:
                raise ValidationError("grade", "score disagrees with dimensions")
            trial = trial_map.get(key)
            if trial is not None:
                trial_artifact = trial.get("artifact_sha256") or trial.get("report_sha256")
                grade_artifact = grade.get("artifact_sha256")
                if grade.get("assessability", "assessable") == "assessable" and grade.get("schema_version", 1) >= 2 and grade_artifact is None:
                    raise ValidationError("grade.artifact_sha256", "version-two grades must identify the reviewed artifact")
                if grade_artifact is not None and grade_artifact != trial_artifact:
                    raise ValidationError("grade.artifact_sha256", "does not match the reviewed trial artifact")
                if grade.get("assessability", "assessable") == "assessable" and grade_artifact is None and trial.get("artifact_sha256") is not None:
                    raise ValidationError("grade.artifact_sha256", "is required for a captured payload grade")
            if manifest and manifest.get("grading_packet_index_sha256"):
                binding = (packet_bindings or {}).get(key)
                if binding and grade.get("supporting_artifact_sha256s", []) != binding.get("supporting_artifact_sha256s", []):
                    raise ValidationError("grade.supporting_artifact_sha256s", "does not match the frozen packet index")
            if grade.get("supporting_artifact_sha256s"):
                capture_root = (artifact_roots or {}).get(key)
                captured = _captured_output_hashes(capture_root) if capture_root else set()
                if not set(grade["supporting_artifact_sha256s"]).issubset(captured):
                    raise ValidationError("grade.supporting_artifact_sha256s", "does not match captured provider output")
            if manifest and manifest.get("grading_packet_index_sha256"):
                binding = (packet_bindings or {}).get(key)
                if (binding is None or grade.get("packet_id") != binding.get("packet_id") or
                        grade.get("packet_sha256") != binding.get("packet_sha256") or
                        grade.get("artifact_sha256") != binding.get("artifact_sha256")):
                    raise ValidationError("grade.packet", "does not match the frozen packet index and grading key")
        except ValidationError:
            invalid_grades.append(f"invalid grade: {key}")
            del grade_map[key]
    completion_complete = not (unexpected or duplicates or missing_trials or bad_trials or mismatched_pairs or
                    bad_hashes or wrong_quick_calls or wrong_baseline_calls or wrong_repair_baseline_calls or settings_errors or cap_errors)
    complete = not (unexpected or duplicates or missing_trials or missing_grades or nonterminal_trials or
                    missing_artifact_trials or mismatched_pairs or invalid_grades or bad_hashes or
                    wrong_quick_calls or wrong_baseline_calls or wrong_repair_baseline_calls or
                    settings_errors or cap_errors)
    score_differences: list[float] = []
    paired: list[dict[str, Any]] = []
    def has_assessable_artifact(key: tuple[str, int, str], grade: Mapping[str, Any]) -> bool:
        trial = trial_map.get(key)
        return (grade.get("assessability", "assessable") == "assessable" and
                isinstance(grade.get("score"), int) and trial is not None and
                (trial.get("report") is not None or trial.get("artifact_sha256") is not None))
    assessable_pairs = 0
    for case_id, replicate in sorted(expected_pair_keys):
        base_key = (case_id, replicate, reference_condition)
        pipe_key = (case_id, replicate, comparison_condition)
        base = grade_map.get(base_key)
        pipe = grade_map.get(pipe_key)
        if (base is None or pipe is None or
                not has_assessable_artifact(base_key, base) or
                not has_assessable_artifact(pipe_key, pipe)):
            continue
        assessable_pairs += 1
        delta = int(pipe["score"]) - int(base["score"])
        score_differences.append(delta)
        paired_item = {"case_id": case_id, "replicate": replicate,
                       "reference_condition": reference_condition,
                       "reference_score": base["score"], "comparison_score": pipe["score"],
                       "score_delta": delta}
        if reference_condition == "baseline":
            paired_item["baseline_score"] = base["score"]
        if comparison_condition == "pipeline":
            paired_item["pipeline_score"] = pipe["score"]
        paired.append(paired_item)
    calibration_counts = {condition: {judgment: sum(
        grade.get("calibration_judgment", "not_assessed") == judgment
        for key, grade in grade_map.items() if key[2] == condition)
        for judgment in ("calibrated", "overcautious", "overconfident", "not_assessed")}
        for condition in conditions}
    assessable_quality = {condition: {
        "count": sum(grade.get("assessability", "assessable") == "assessable" and
                     has_assessable_artifact(key, grade) for key, grade in grade_map.items()
                     if key[2] == condition),
        "unavailable_count": sum(grade.get("assessability") == "unavailable"
                                 for key, grade in grade_map.items() if key[2] == condition),
        "mean_score": (statistics.mean(grade["score"] for key, grade in grade_map.items()
                       if key[2] == condition and
                       has_assessable_artifact(key, grade))
                       if any(key[2] == condition and grade.get("assessability", "assessable") == "assessable"
                              and has_assessable_artifact(key, grade) for key, grade in grade_map.items())
                       else None)}
        for condition in conditions}
    schema_acceptance = {}
    provider_availability = {}
    resource_use = {}
    for condition in conditions:
        rows = [item for item in trial_map.values() if item.get("condition") == condition]
        protocol_counts = {value: sum(item.get("protocol_validity") == value for item in rows)
                           for value in ("valid", "invalid", "unavailable")}
        protocol_counts["unknown"] = sum(item.get("protocol_validity") is None for item in rows)
        denominator = protocol_counts["valid"] + protocol_counts["invalid"]
        schema_acceptance[condition] = {"attempts": len(rows), **protocol_counts,
            "assessable_protocol_attempts": denominator,
            "acceptance_rate": protocol_counts["valid"] / denominator if denominator else None}
        provider_availability[condition] = {
            "trials": len(rows),
            "complete": sum(item.get("status") == "complete" for item in rows),
            "failed": sum(item.get("status") == "failed" for item in rows),
            "ambiguous": sum(item.get("status") == "ambiguous" for item in rows),
            "in_flight": sum(item.get("status") == "intent" for item in rows),
            "usage_limit": sum(item.get("failure_class") == "provider_usage_limit" for item in rows),
            "trials_with_provider_calls": sum(
                isinstance(item.get("provider_calls"), int) and item.get("provider_calls", 0) > 0
                for item in rows),
            "provider_calls": sum(int(item.get("provider_calls", 0)) for item in rows)}
        def known_values(field: str) -> list[int | float]:
            return [item[field] for item in rows if isinstance(item.get(field), (int, float))
                    and not isinstance(item.get(field), bool)]
        costs = known_values("cost_usd")
        input_tokens = known_values("input_tokens")
        output_tokens = known_values("output_tokens")
        resource_use[condition] = {
            "trials": len(rows),
            "provider_calls": sum(item.get("provider_calls", 0) for item in rows),
            "tool_calls": sum(item.get("tool_calls_used", 0) for item in rows
                              if isinstance(item.get("tool_calls_used"), int) and
                              not isinstance(item.get("tool_calls_used"), bool)),
            "wall_seconds": sum(item.get("wall_seconds", 0) for item in rows),
            "input_tokens": sum(input_tokens) if input_tokens else None,
            "output_tokens": sum(output_tokens) if output_tokens else None,
            "known_token_trials": sum(isinstance(item.get("input_tokens"), int) and
                not isinstance(item.get("input_tokens"), bool) and
                isinstance(item.get("output_tokens"), int) and
                not isinstance(item.get("output_tokens"), bool) for item in rows),
            "unknown_token_trials": sum(item.get("input_tokens") is None or
                                         item.get("output_tokens") is None for item in rows),
            "cost_usd": sum(costs) if costs else None,
            "known_cost_trials": len(costs),
            "unknown_cost_trials": sum(item.get("cost_usd") is None for item in rows)}
    recovery_summary = {}
    for condition in conditions:
        rows = [item for item in recoveries if item.get("condition") == condition]
        recovery_summary[condition] = {
            "attempts": len(rows),
            "complete": sum(item.get("status") == "complete" for item in rows),
            "failed": sum(item.get("status") == "failed" for item in rows),
            "ambiguous": sum(item.get("status") == "ambiguous" for item in rows),
            "provider_calls": sum(item.get("provider_calls", 0) for item in rows),
            "wall_seconds": sum(item.get("wall_seconds", 0) for item in rows)}
    pair_reconciliation = []
    for case_id, replicate in sorted(all_expected_pair_keys):
        reference = trial_map.get((case_id, replicate, reference_condition))
        pipeline = trial_map.get((case_id, replicate, comparison_condition))
        source_match = bool(reference and pipeline and
                            reference.get("source_hash") == pipeline.get("source_hash"))
        capability_match = pair_capabilities_match(case_id, reference_condition,
                                                   comparison_condition)
        same_inputs = source_match and capability_match
        quota = any(item and item.get("failure_class") == "provider_usage_limit"
                    for item in (reference, pipeline))
        has_recovery = any(item.get("case_id") == case_id and item.get("replicate") == replicate
                           for item in recoveries)
        pair_reconciliation.append({"case_id": case_id, "replicate": replicate,
            "equal_input_match": same_inputs, "source_hash_match": source_match,
            "capability_match": capability_match, "quota_truncated": quota,
            "temporal_recovery_available": has_recovery,
            "classification": ("quota_truncated" if quota else "temporally_recovered_first_attempts_retained"
                if has_recovery else "matched_first_attempts" if same_inputs else
                "capability_mismatch" if source_match and not capability_match else
                "unmatched_or_incomplete")})
    ceiling_pairs = [item for item in paired if item["reference_score"] == sum(
        2 for _ in DIMENSIONS)]
    ceiling_deltas = [item["score_delta"] for item in ceiling_pairs]
    input_comparable = bool(manifest and manifest.get("cases_hash") and manifest.get("rubric_hash") and
        manifest.get("model") and manifest.get("effort") and manifest.get("capability_policy"))
    capability_policy = manifest.get("capability_policy", {}) if manifest else {}
    capability_mismatch_case_ids = [case_id for case_id, policy in capability_policy.items()
        if len({canonical_bytes(policy.get("conditions", {}).get(condition, {}))
                for condition in scheduled_conditions.get(case_id, conditions)}) > 1]
    pairwise_quality = []
    for left_index, left_condition in enumerate(conditions):
        for right_condition in conditions[left_index + 1:]:
            deltas = []
            matched = 0
            for case_id, replicate in sorted((case_id, replicate)
                    for case_id in all_case_ids
                    for replicate in range(1, required_replicates + 1)):
                if left_condition not in scheduled_conditions[case_id] or right_condition not in scheduled_conditions[case_id]:
                    continue
                left_key = (case_id, replicate, left_condition)
                right_key = (case_id, replicate, right_condition)
                left_trial, right_trial = trial_map.get(left_key), trial_map.get(right_key)
                left_grade, right_grade = grade_map.get(left_key), grade_map.get(right_key)
                if (left_trial is None or right_trial is None or
                        left_trial.get("source_hash") != right_trial.get("source_hash") or
                        not pair_capabilities_match(case_id, left_condition, right_condition)):
                    continue
                matched += 1
                if (left_grade is not None and right_grade is not None and
                        has_assessable_artifact(left_key, left_grade) and
                        has_assessable_artifact(right_key, right_grade)):
                    deltas.append(int(right_grade["score"]) - int(left_grade["score"]))
            pairwise_quality.append({"left_condition": left_condition,
                "right_condition": right_condition, "equal_input_pairs": matched,
                "assessable_pairs": len(deltas),
                "mean_score_delta_right_minus_left": statistics.mean(deltas) if deltas else None,
                "left_resource_use": resource_use.get(left_condition),
                "right_resource_use": resource_use.get(right_condition)})
    baseline_times = [float(item["wall_seconds"]) for key, item in trial_map.items() if key[2] == reference_condition and item.get("status") == "complete" and isinstance(item.get("wall_seconds"), (float, int)) and item["wall_seconds"] > 0]
    pipeline_times = [float(item["wall_seconds"]) for key, item in trial_map.items() if comparison_condition is not None and key[2] == comparison_condition and item.get("status") == "complete" and isinstance(item.get("wall_seconds"), (float, int)) and item["wall_seconds"] > 0]
    latency_ratios = []
    for case_id in all_case_ids:
        for replicate in range(1, required_replicates + 1):
            if (comparison_condition is None or
                    not {reference_condition, comparison_condition}.issubset(scheduled_conditions[case_id])):
                continue
            if not pair_capabilities_match(case_id, reference_condition, comparison_condition):
                continue
            if (case_id, replicate) not in expected_pair_keys:
                continue
            b = trial_map.get((case_id, replicate, reference_condition)); p = trial_map.get((case_id, replicate, comparison_condition))
            if b and p and b.get("status") == p.get("status") == "complete" and isinstance(b.get("wall_seconds"), (int, float)) and b["wall_seconds"] > 0 and isinstance(p.get("wall_seconds"), (int, float)):
                latency_ratios.append(float(p["wall_seconds"]) / float(b["wall_seconds"]))
    deep_case_ids = deep_case_ids or set()
    deep_comparable_case_ids = {case_id for case_id in deep_case_ids
        if comparison_condition is not None and
        {reference_condition, comparison_condition}.issubset(scheduled_conditions.get(case_id, ())) and
        pair_capabilities_match(case_id, reference_condition, comparison_condition)}
    comparable_pair_identities = {(case_id, replicate) for case_id, replicate in expected_pair_keys}
    deep_scores = [grade["score"] for key, grade in grade_map.items()
        if key[0] in deep_comparable_case_ids and (key[0], key[1]) in comparable_pair_identities and
        key[2] == comparison_condition and
        isinstance(grade.get("score"), int)]
    improvement = statistics.mean(score_differences) if score_differences else None
    deep_coverage_baseline = [grade["dimensions"]["coverage"] for key, grade in grade_map.items()
        if key[0] in deep_comparable_case_ids and (key[0], key[1]) in comparable_pair_identities and
        key[2] == reference_condition and
        has_assessable_artifact(key, grade)]
    deep_coverage_pipeline = [grade["dimensions"]["coverage"] for key, grade in grade_map.items()
        if key[0] in deep_comparable_case_ids and (key[0], key[1]) in comparable_pair_identities and
        key[2] == comparison_condition and
        has_assessable_artifact(key, grade)]
    baseline_failures = sum(len(grade.get("critical_failures", ()))
        for key, grade in grade_map.items()
        if key[2] == reference_condition and (key[0], key[1]) in comparable_pair_identities)
    comparison_failures = sum(len(grade.get("critical_failures", ()))
        for key, grade in grade_map.items()
        if comparison_condition is not None and key[2] == comparison_condition and
        (key[0], key[1]) in comparable_pair_identities)
    reduced_failures = bool(baseline_failures > 0 and comparison_failures <= baseline_failures * 0.75 and
                            deep_coverage_baseline and deep_coverage_pipeline and
                            statistics.mean(deep_coverage_pipeline) >= statistics.mean(deep_coverage_baseline))
    deep_deltas = [grade_map[(case_id, replicate, comparison_condition)]["score"] -
                   grade_map[(case_id, replicate, reference_condition)]["score"]
                   for case_id in sorted(deep_comparable_case_ids) for replicate in range(1, required_replicates + 1)
                   if (case_id, replicate) in comparable_pair_identities and
                      has_assessable_artifact((case_id, replicate, comparison_condition),
                       grade_map.get((case_id, replicate, comparison_condition), {})) and
                   has_assessable_artifact((case_id, replicate, reference_condition),
                       grade_map.get((case_id, replicate, reference_condition), {}))]
    expected_deep_pair_count = sum(case_id in deep_case_ids
                                   for case_id, _ in expected_pair_keys)
    mean_deep_delta = statistics.mean(deep_deltas) if deep_deltas else None
    quality_gain = bool(mean_deep_delta is not None and mean_deep_delta >= 1.0) or reduced_failures
    deep_pair_coverage_complete = expected_deep_pair_count > 0 and len(deep_deltas) == expected_deep_pair_count
    deep_ratios = [float(trial_map[(case_id, replicate, comparison_condition)]["wall_seconds"]) /
        float(trial_map[(case_id, replicate, reference_condition)]["wall_seconds"])
        for case_id in deep_comparable_case_ids for replicate in range(1, required_replicates + 1)
        if (case_id, replicate) in expected_pair_keys and
        comparison_condition is not None and (case_id, replicate, comparison_condition) in trial_map and (case_id, replicate, reference_condition) in trial_map and
        pair_capabilities_match(case_id, reference_condition, comparison_condition) and
        trial_map[(case_id, replicate, comparison_condition)].get("status") == "complete" and
        trial_map[(case_id, replicate, reference_condition)].get("status") == "complete" and
        trial_map[(case_id, replicate, reference_condition)].get("wall_seconds", 0) > 0]
    quick_ratios = [float(trial_map[(case_id, replicate, comparison_condition)]["wall_seconds"]) /
        float(trial_map[(case_id, replicate, reference_condition)]["wall_seconds"])
        for case_id in quick_case_ids for replicate in range(1, required_replicates + 1)
        if (case_id, replicate) in expected_pair_keys and
        comparison_condition is not None and (case_id, replicate, comparison_condition) in trial_map and (case_id, replicate, reference_condition) in trial_map and
        pair_capabilities_match(case_id, reference_condition, comparison_condition) and
        trial_map[(case_id, replicate, comparison_condition)].get("status") == "complete" and
        trial_map[(case_id, replicate, reference_condition)].get("status") == "complete" and
        trial_map[(case_id, replicate, reference_condition)].get("wall_seconds", 0) > 0]
    efficiency_gate = bool(deep_case_ids and quick_case_ids and
        len(deep_ratios) == len(deep_case_ids) * required_replicates and
        len(quick_ratios) == len(quick_case_ids) * required_replicates and
        statistics.median(deep_ratios) <= 6 and statistics.median(quick_ratios) <= 1.5)
    return {"schema_version": 1, "record_type": "research_evaluation_comparison",
            "comparison_status": "complete" if complete else "incomplete",
            "scheduled_trial_count": len(expected),
            "scheduled_trials_recorded": len(expected) - len(missing_trials),
            "scheduled_trial_coverage_rate": ((len(expected) - len(missing_trials)) / len(expected)
                                               if expected else 0.0),
            "execution_completion_rate": (sum(item.get("status") == "complete" for item in trial_map.values()) /
                                          len(expected) if expected else 0.0),
            "all_expected_trials_complete": bool(completion_complete),
            "execution_outcome_counts": {status: sum(item.get("status") == status
                for item in trial_map.values()) for status in ("complete", "failed", "ambiguous", "intent")},
            "protocol_validity_counts": {validity: sum(item.get("protocol_validity") == validity
                for item in trial_map.values()) for validity in ("valid", "invalid", "unavailable")}
                | {"unknown": sum(item.get("protocol_validity") is None for item in trial_map.values())},
            "assessable_pair_count": assessable_pairs,
            "expected_pair_count": len(expected_pair_keys),
            "scheduled_pair_count": len(all_expected_pair_keys),
            "quality_pair_coverage": assessable_pairs / len(expected_pair_keys) if expected_pair_keys else 0.0,
            "assessable_deep_pair_count": len(deep_deltas),
            "expected_deep_pair_count": expected_deep_pair_count,
            "protocol_failure_counts": {"schema_rejection": sum(item.get("failure_class") == "schema_rejection" for item in trial_map.values()),
                "provider_usage_limit": sum(item.get("failure_class") == "provider_usage_limit" for item in trial_map.values()),
                "tool_argument_or_bounds": sum(
                    item.get("failure_class") == "provider_failure" and
                    re.search(r"arguments?:|bounds|invalid tool", str(item.get("error", "")), re.I) is not None
                    for item in trial_map.values()),
                "other": sum(item.get("failure_class") not in {None, "schema_rejection", "provider_usage_limit"} and
                    not (item.get("failure_class") == "provider_failure" and
                         re.search(r"arguments?:|bounds|invalid tool", str(item.get("error", "")), re.I))
                    for item in trial_map.values())},
            "status_calibration_counts": calibration_counts,
            "assessable_quality_by_condition": assessable_quality,
            "schema_acceptance_by_condition": schema_acceptance,
            "terminal_status_counts_by_condition": {condition: {
                str(status): sum(item.get("final_status") == status for item in trial_map.values()
                                 if item.get("condition") == condition)
                for status in sorted({item.get("final_status") for item in trial_map.values()
                                      if item.get("condition") == condition and
                                      item.get("final_status") is not None})}
                for condition in conditions},
            "provider_availability_by_condition": provider_availability,
            "resource_use_by_condition": resource_use,
            "recovery_attempts_by_condition": recovery_summary,
            "pair_reconciliation": pair_reconciliation,
            "equal_input_matched_pair_count": sum(item["equal_input_match"] for item in pair_reconciliation),
            "unmatched_or_incomplete_pair_count": sum(
                item["classification"] == "unmatched_or_incomplete" for item in pair_reconciliation),
            "capability_mismatch_pair_count": len(capability_mismatch_pair_keys),
            "source_mismatch_pair_count": len(source_mismatch_pair_keys),
            "quota_truncated_pair_count": sum(item["quota_truncated"] for item in pair_reconciliation),
            "temporally_recovered_pair_count": sum(item["temporal_recovery_available"] for item in pair_reconciliation),
            "baseline_ceiling_effect": {"maximum_score": 2 * len(DIMENSIONS),
                "pairs_at_ceiling": len(ceiling_pairs),
                "mean_comparison_delta_at_ceiling": statistics.mean(ceiling_deltas)
                    if ceiling_deltas else None,
                "mean_pipeline_delta_at_ceiling": statistics.mean(ceiling_deltas)
                    if ceiling_deltas and comparison_condition == "pipeline" else None,
                "gain_demonstrated_at_ceiling": bool(ceiling_deltas and
                    statistics.mean(ceiling_deltas) > 0)},
            "small_sample_disclosure": ("Small sample: estimates are descriptive and do not establish a general effect."
                if assessable_pairs < 30 else None),
            "input_comparability": {"manifest_inputs_frozen": input_comparable,
                "equal_input_pairs": sum(item["equal_input_match"] for item in pair_reconciliation),
                "capability_mismatch_case_ids": capability_mismatch_case_ids,
                "capabilities_match_all_cases": not capability_mismatch_case_ids,
                "evidence_policy": capability_policy},
            "quick_wrapper_case_ids": sorted(case_id for case_id in quick_case_ids
                if (manifest or {}).get("capability_policy", {}).get(case_id, {}).get("mode") == "quick"
                and comparison_condition == "pipeline"),
            "pairwise_quality": pairwise_quality,
            "legacy_pilot_policy": {"name": "legacy_pilot_thresholds_v1",
                "deep_mean_score_minimum": 8, "mean_deep_pair_delta_minimum": 1,
                "failure_reduction_fraction": 0.25, "deep_latency_ratio_maximum": 6,
                "quick_latency_ratio_maximum": 1.5},
            "quality_gate_passed": bool(complete and comparison_failures == 0 and
                bool(deep_scores) and statistics.mean(deep_scores) >= 8 and quality_gain and
                deep_pair_coverage_complete),
            "trial_count": len(trial_map), "grade_count": len(grade_map),
            "missing_trials": [list(key) for key in missing_trials],
            "missing_grades": [list(key) for key in missing_grades],
            "missing_grades_by_condition": {condition: sum(key[2] == condition
                for key in missing_grades) for condition in conditions},
            "bad_trials": [list(key) for key in bad_trials],
            "integrity_errors": unexpected + duplicates + mismatched_pairs + invalid_grades + bad_hashes + wrong_quick_calls + wrong_baseline_calls + wrong_repair_baseline_calls + settings_errors + cap_errors,
            "mean_paired_score_delta": improvement, "paired_scores": paired,
            "mean_deep_paired_score_delta": mean_deep_delta,
            "conditions": list(conditions), "reference_condition": reference_condition,
            "comparison_condition": comparison_condition if has_comparison_pair else None,
            "critical_failure_counts": {reference_condition: baseline_failures,
                **({comparison_condition: comparison_failures} if comparison_condition is not None else {})},
            "critical_failure_trial_counts": {
                condition: sum(bool(grade.get("critical_failures")) for key, grade in grade_map.items()
                               if key[2] == condition)
                for condition in conditions},
            "quality_gain_demonstrated": bool(complete and quality_gain and deep_pair_coverage_complete),
            "efficiency_gate_passed": bool(complete and efficiency_gate),
            "median_deep_latency_ratio": statistics.median(deep_ratios) if deep_ratios else None,
            "median_quick_latency_ratio": statistics.median(quick_ratios) if quick_ratios else None,
            "mean_comparison_score": statistics.mean(deep_scores) if deep_scores else None,
            "mean_pipeline_score": statistics.mean(deep_scores) if deep_scores and comparison_condition == "pipeline" else None,
            "median_latency_ratio_comparison_over_reference": statistics.median(latency_ratios) if latency_ratios else None,
            "median_latency_ratio_comparison_over_baseline": statistics.median(latency_ratios)
                if latency_ratios and reference_condition == "baseline" else None,
            "median_latency_ratio_pipeline_over_baseline": statistics.median(latency_ratios)
                if latency_ratios and comparison_condition == "pipeline" else None,
            "reference_p50_seconds": statistics.median(baseline_times) if baseline_times else None,
            "baseline_p50_seconds": statistics.median(baseline_times)
                if baseline_times and reference_condition == "baseline" else None,
            "comparison_p50_seconds": statistics.median(pipeline_times) if pipeline_times else None,
            "pipeline_p50_seconds": statistics.median(pipeline_times)
                if pipeline_times and comparison_condition == "pipeline" else None,
            "unknown_cost_trial_count": sum(item.get("cost_usd") is None for item in trial_map.values()),
            "known_cost_total_usd": (sum(item["cost_usd"] for item in trial_map.values()
                if isinstance(item.get("cost_usd"), (int, float))) if any(
                    isinstance(item.get("cost_usd"), (int, float)) for item in trial_map.values()) else None),
            "known_reference_cost_usd": (sum(item["cost_usd"] for key, item in trial_map.items()
                if key[2] == reference_condition and isinstance(item.get("cost_usd"), (int, float)))
                if any(key[2] == reference_condition and isinstance(item.get("cost_usd"), (int, float))
                       for key, item in trial_map.items()) else None),
            "known_baseline_cost_usd": (sum(item["cost_usd"] for key, item in trial_map.items()
                if key[2] == reference_condition and isinstance(item.get("cost_usd"), (int, float)))
                if reference_condition == "baseline" and any(key[2] == reference_condition and
                    isinstance(item.get("cost_usd"), (int, float)) for key, item in trial_map.items()) else None),
            "known_comparison_cost_usd": (sum(item["cost_usd"] for key, item in trial_map.items()
                if comparison_condition is not None and key[2] == comparison_condition and isinstance(item.get("cost_usd"), (int, float)))
                if any(comparison_condition is not None and key[2] == comparison_condition and isinstance(item.get("cost_usd"), (int, float))
                       for key, item in trial_map.items()) else None),
            "actual_provider_calls": actual_provider_calls,
            "provider_call_count_basis": "durable_provider_attempt_intents; legacy_v3_worker_actions_counted_once",
            "observed_session_marker_count": sum(item["observed_session_markers"] for item in trial_map.values()
                if isinstance(item.get("observed_session_markers"), int) and not isinstance(item.get("observed_session_markers"), bool)),
            "unknown_session_marker_trial_count": sum(item.get("observed_session_markers") is None for item in trial_map.values()),
            "actual_wall_seconds": total_wall_seconds,
            "known_input_tokens": sum(item["input_tokens"] for item in trial_map.values() if isinstance(item.get("input_tokens"), int) and not isinstance(item.get("input_tokens"), bool)),
            "known_output_tokens": sum(item["output_tokens"] for item in trial_map.values() if isinstance(item.get("output_tokens"), int) and not isinstance(item.get("output_tokens"), bool)),
            "unknown_token_trial_count": sum(item.get("input_tokens") is None or item.get("output_tokens") is None for item in trial_map.values()),
            "latency_ratio_unavailable_pairs": len(all_case_ids) * required_replicates - len(latency_ratios)}


def run_paired_trials(cases: Sequence[Mapping[str, Any]], store: EvaluationStore, *,
                      trial_runner: Any, usage_checkpoint: Any | None = None,
                      monotonic: Any = time.monotonic,
                      selected_case_ids: set[str] | None = None,
                      selected_conditions: set[str] | None = None) -> dict[str, Any]:
    """Run paired trials under an exclusive output-directory lock."""
    with acquire_run_lock(store.directory):
        initial_wall = _read_json(store.directory / "budget.json")["wall_seconds_observed"]
        initial_trials = {path.parent.name for path in (store.directory / "trials").glob("*/trial.json")}
        started = monotonic()
        waiting_seconds = 0.0

        def active_clock() -> float:
            return monotonic() - waiting_seconds

        def checkpoint(*args: Any) -> Any:
            nonlocal waiting_seconds
            if usage_checkpoint is None:
                return None
            before = monotonic()
            try:
                return usage_checkpoint(*args)
            finally:
                waiting_seconds += max(0.0, monotonic() - before)

        result = {"stopped_reason": "evaluation_error", "trial_conditions_recorded": []}
        try:
            result = _run_paired_trials_locked(cases, store, trial_runner=trial_runner,
                usage_checkpoint=checkpoint if usage_checkpoint is not None else None,
                monotonic=active_clock, selected_case_ids=selected_case_ids,
                selected_conditions=selected_conditions)
        except KeyboardInterrupt:
            result["stopped_reason"] = "user_cancelled"
        finally:
            spent = _read_json(store.directory / "budget.json")
            unrecorded = max(0.0, active_clock() - started -
                             (spent["wall_seconds_observed"] - initial_wall))
            store.record_elapsed(unrecorded)
            budget = _read_json(store.directory / "budget.json")
            result.update({"provider_calls_reserved": budget["provider_calls_reserved"],
                           "wall_seconds_observed": budget["wall_seconds_observed"]})
            result["trial_conditions_recorded"] = [f"{item['case_id']}/{item['replicate']}/{item['condition']}"
                for path in sorted((store.directory / "trials").glob("*/trial.json"))
                if path.parent.name not in initial_trials
                for item in [_read_json(path)] if item.get("status") != "intent"]
            write_json(store.directory / "execution.json", result)
        return result


def _run_paired_trials_locked(cases: Sequence[Mapping[str, Any]], store: EvaluationStore, *,
                              trial_runner: Any, usage_checkpoint: Any | None,
                              monotonic: Any, selected_case_ids: set[str] | None = None,
                              selected_conditions: set[str] | None = None) -> dict[str, Any]:
    """Run unstarted paired trials with persisted caps and human usage checks.

    Each usage checkpoint runs before each condition. `trial_runner` receives
    `(case, condition, pair_inputs, trial_dir, timeout_seconds)` and must ensure
    all child processes stay inside the provided timeout.
    """
    manifest = _read_json(store.directory / "manifest.json")
    cases_by_id = {case["id"]: case for case in cases}
    wall_cap = manifest["caps"]["max_wall_seconds"]
    started = monotonic()
    initially_recorded = _read_json(store.directory / "budget.json")["wall_seconds_observed"]
    completed: list[str] = []
    stopped_reason = None
    for pair in manifest["ordering"]:
        case_id, replicate = pair["case_id"], pair["replicate"]
        if selected_case_ids is not None and case_id not in selected_case_ids:
            continue
        case = cases_by_id[case_id]
        if wall_cap - initially_recorded - (monotonic() - started) <= 0:
            stopped_reason = "wall_time_cap_reached"
            break
        pair_inputs = store.acquire_pair_inputs(case, replicate)
        for condition in pair["conditions"]:
            if selected_conditions is not None and condition not in selected_conditions:
                continue
            path = store._trial_path(case_id, replicate, condition)
            if path.exists():
                existing = _read_json(path)
                if existing.get("status") == "complete":
                    continue
                if existing.get("status") == "failed" and existing.get("failure_class") == "schema_rejection":
                    continue
                if (existing.get("status") == "failed" and
                        existing.get("failure_class") != "provider_usage_limit" and
                        int(existing.get("provider_calls", 0)) > 0):
                    # A recorded terminal failure is an evaluation outcome.
                    # Skip it on resume and continue collecting the remaining
                    # arms; ambiguous and zero-call failures still stop safely.
                    continue
                stopped_reason = "previous_trial_failed_or_unresolved"
                break
            elapsed_session = monotonic() - started
            remaining = int(wall_cap - initially_recorded - elapsed_session)
            preflight_reserve = BASELINE_PREFLIGHT_WORST_SECONDS if condition in {"baseline", "baseline_repair"} else 0
            if remaining <= preflight_reserve:
                stopped_reason = "wall_time_cap_reached"
                break
            observed = usage_checkpoint(case_id, replicate, condition) if usage_checkpoint is not None else None
            if usage_checkpoint is not None and observed is None:
                stopped_reason = "session_usage_checkpoint_unavailable"
                break
            if usage_checkpoint is not None and not store.record_usage_check(observed_remaining_percent=observed,
                    case_id=case_id, replicate=replicate, condition=condition):
                stopped_reason = "session_usage_cap_reached"
                break
            paired_repair_policy = {"baseline_repair", "pipeline"}.issubset(
                set(manifest.get("conditions", CONDITIONS)))
            reserve_calls = ((2 if condition == "baseline_repair" else 1)
                if condition in {"baseline", "baseline_repair"} else
                {"quick": 1, "deep": 8, "research": 12}[case["mode"]]
                if paired_repair_policy else
                {"quick": 1, "deep": 8, "research": 12}[case["mode"]])
            try:
                store.record_intent(case_id=case_id, replicate=replicate,
                    condition=condition, source_hash=pair_inputs["source_hash"],
                    reserve_calls=reserve_calls)
            except ValidationError as error:
                stopped_reason = str(error)
                break
            trial_dir = path.parent
            if condition == "pipeline":
                (trial_dir / "run").mkdir(parents=True, exist_ok=True)
            before = monotonic()
            timeout = int(wall_cap - initially_recorded - (before - started) - preflight_reserve)
            try:
                if timeout <= 0:
                    raw = {"status": "failed", "provider_calls": 0,
                           "error": "wall_time_cap_reached_before_launch"}
                else:
                    raw = trial_runner(case, condition, pair_inputs, trial_dir, timeout)
                elapsed = max(0.0, monotonic() - before)
                trial = make_trial(case_id=case_id, replicate=replicate,
                    condition=condition, status=raw["status"], report=raw.get("report"),
                    provider_calls=raw["provider_calls"], wall_seconds=elapsed,
                    cost_usd=raw.get("cost_usd"), source_hash=pair_inputs["source_hash"],
                    tool_calls_used=raw.get("tool_calls_used"),
                    artifact_sha256=raw.get("artifact_sha256"),
                    protocol_validity=raw.get("protocol_validity") or (
                        "valid" if raw["status"] == "complete" else
                        "invalid" if classify_trial_failure(raw) == "schema_rejection" else "unavailable"),
                    failure_class=classify_trial_failure(raw),
                    final_status=raw.get("final_status"),
                    observed_session_markers=raw.get("observed_session_markers"))
                trial.update({"reserved_provider_calls": reserve_calls,
                    "requested_model": manifest["model"], "requested_effort": manifest["effort"]})
                for key in ("observed_model", "observed_effort", "input_tokens", "output_tokens",
                            "provider_outcome", "provider_exit_code"):
                    if key in raw:
                        trial[key] = raw[key]
                if raw.get("error") is not None:
                    trial["error"] = str(raw["error"])[:4000]
                store.record_result(trial)
                store.record_elapsed(elapsed)
                completed.append(f"{case_id}/{replicate}/{condition}")
                if trial["status"] != "complete":
                    if trial.get("failure_class") == "schema_rejection":
                        continue
                    if trial.get("failure_class") == "provider_usage_limit":
                        stopped_reason = "provider_usage_limit"
                        break
                    if int(trial.get("provider_calls", 0)) > 0:
                        # The trial outcome is durable and unambiguous. Keep
                        # the paired schedule moving so failures are recorded
                        # without discarding the rest of the development set.
                        continue
                    stopped_reason = "trial_failed"
                    break
            except KeyboardInterrupt:
                elapsed = max(0.0, monotonic() - before)
                if _read_json(path).get("status") == "intent":
                    store.mark_ambiguous(case_id, replicate, condition,
                        reason="user interrupted trial; provider completion is unknown",
                        wall_seconds=elapsed)
                stopped_reason = "user_cancelled"
                break
            except Exception as error:
                elapsed = max(0.0, monotonic() - before)
                if _read_json(path).get("status") == "intent":
                    store.mark_ambiguous(case_id, replicate, condition,
                        reason=f"trial outcome unclear: {type(error).__name__}: {error}",
                        wall_seconds=elapsed)
                stopped_reason = "trial_ambiguous"
                break
        if stopped_reason:
            break
    spent = _read_json(store.directory / "budget.json")
    elapsed_session = max(0.0, monotonic() - started)
    extra_setup = max(0.0, elapsed_session -
        (spent["wall_seconds_observed"] - initially_recorded))
    store.record_elapsed(extra_setup)
    final_budget = _read_json(store.directory / "budget.json")
    if final_budget["wall_seconds_observed"] > wall_cap:
        stopped_reason = "wall_time_cap_reached"
    scheduled_first_counts = {condition: 0 for condition in manifest.get("conditions", [])}
    started_first_counts = {condition: 0 for condition in manifest.get("conditions", [])}
    scheduled_position_counts = {condition: {} for condition in manifest.get("conditions", [])}
    started_position_counts = {condition: {} for condition in manifest.get("conditions", [])}
    for scheduled_pair in manifest["ordering"]:
        scheduled_case = scheduled_pair["case_id"]
        if selected_case_ids is not None and scheduled_case not in selected_case_ids:
            continue
        selected_order = [condition for condition in scheduled_pair["conditions"]
                          if selected_conditions is None or condition in selected_conditions]
        if not selected_order:
            continue
        first_condition = selected_order[0]
        scheduled_first_counts[first_condition] += 1
        if store._trial_path(scheduled_case, scheduled_pair["replicate"], first_condition).exists():
            started_first_counts[first_condition] += 1
        for position, condition in enumerate(selected_order):
            scheduled_position_counts[condition][position] = (
                scheduled_position_counts[condition].get(position, 0) + 1)
            if store._trial_path(scheduled_case, scheduled_pair["replicate"], condition).exists():
                started_position_counts[condition][position] = (
                    started_position_counts[condition].get(position, 0) + 1)
    imbalance_values = list(started_first_counts.values())
    all_positions = sorted({position for counts in scheduled_position_counts.values()
                            for position in counts})
    residual_by_position = {}
    for position in all_positions:
        values = [started_position_counts[condition].get(position, 0)
                  for condition in manifest.get("conditions", [])]
        residual_by_position[str(position)] = max(values) - min(values) if values else 0
    return {"stopped_reason": stopped_reason,
            "trial_conditions_recorded": completed,
            "execution_selection": {"case_ids": sorted(selected_case_ids) if selected_case_ids is not None else None,
                                    "conditions": sorted(selected_conditions) if selected_conditions is not None else None},
            "pending_scheduled_trials": [f"{p['case_id']}/{p['replicate']}/{c}"
                for p in manifest["ordering"]
                if selected_case_ids is None or p["case_id"] in selected_case_ids
                for c in p["conditions"] if selected_conditions is None or c in selected_conditions
                if not store._trial_path(p["case_id"], p["replicate"], c).exists()],
            "ordering_balance": {"scheduled_first_condition_counts": scheduled_first_counts,
                "started_first_condition_counts": started_first_counts,
                "started_residual_imbalance": (max(imbalance_values) - min(imbalance_values))
                    if imbalance_values else 0,
                "scheduled_condition_counts_by_position": scheduled_position_counts,
                "started_condition_counts_by_position": started_position_counts,
                "started_residual_imbalance_by_position": residual_by_position},
            "provider_calls_reserved": final_budget["provider_calls_reserved"],
            "wall_seconds_observed": final_budget["wall_seconds_observed"]}


def write_json(path: Path, value: Any) -> None:
    """Atomically persist evaluator metadata without exposing partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def comparison_markdown(comparison: Mapping[str, Any]) -> str:
    delta = comparison.get("mean_paired_score_delta")
    ratio = comparison.get("median_latency_ratio_comparison_over_reference",
                           comparison.get("median_latency_ratio_pipeline_over_baseline"))
    reference = comparison.get("reference_condition", "baseline")
    comparator = comparison.get("comparison_condition", "pipeline") or "comparison arm"
    return "\n".join(("# Paired research-quality comparison", "",
        f"Status: `{comparison.get('comparison_status')}`", "",
        f"Quality gate passed: `{str(bool(comparison.get('quality_gate_passed'))).lower()}`", "",
        f"Completed trials: {comparison.get('execution_completion_rate', 0.0):.1%} of expected attempts.",
        f"Assessable matched pairs: {comparison.get('assessable_pair_count', 0)} / "
        f"{comparison.get('expected_pair_count', 0)}.", "",
        f"Protocol failures: {comparison.get('protocol_failure_counts', {})}.",
        f"Protocol validity outcomes: {comparison.get('protocol_validity_counts', {})}.",
        f"Status calibration judgments: {comparison.get('status_calibration_counts', {})}.", "",
        f"Mean semantic score among assessable outputs: {comparison.get('assessable_quality_by_condition', {})}.",
        f"Observed local session markers: {comparison.get('observed_session_marker_count', 0)}; "
        f"unknown marker trials: {comparison.get('unknown_session_marker_trial_count', 0)}.",
        "Session markers are supplemental log telemetry, not billing totals.", "",
        f"Mean paired score difference: `{delta if delta is not None else 'unavailable'}` points.",
        f"Median latency ratio ({comparator} / {reference}): `{ratio if ratio is not None else 'unavailable'}`.",
        f"Critical failures: {reference} `{comparison.get('critical_failure_counts', {}).get(reference, 0)}`, "
        f"{comparator} `{comparison.get('critical_failure_counts', {}).get(comparator, 0)}`.", "",
        "Semantic grades require an identified human reviewer and evidence passages. "
        "Process completion alone is not a quality grade.", ""))


def comparison_markdown_v2(comparison: Mapping[str, Any]) -> str:
    """Render separate quality, protocol, calibration, availability, and cost views."""
    conditions = comparison.get("conditions", [])
    lines = ["# Research evaluation comparison", "",
        "Status: " + str(comparison.get("comparison_status")),
        "Primary comparison: " + str(comparison.get("comparison_condition") or "no comparison arm") +
        " versus " + str(comparison.get("reference_condition", "baseline")) + ".",
        "Scheduled trial records: " + str(comparison.get("scheduled_trials_recorded", 0)) +
        " / " + str(comparison.get("scheduled_trial_count", 0)) + ".",
        "Protocol-complete trial rate: " + str(comparison.get("execution_completion_rate", 0.0)) +
        " of scheduled trials.",
        "Quality gate passed: " + str(bool(comparison.get("quality_gate_passed"))),
        "Legacy policy: " + str(comparison.get("legacy_pilot_policy", {}).get("name", "unknown")), "",
        "## Semantic quality", "",
        "| Condition | Assessable outputs | Unavailable | Missing grades | Mean score / 10 | Critical-failure labels |",
        "|---|---:|---:|---:|---:|---:|"]
    quality = comparison.get("assessable_quality_by_condition", {})
    failures = comparison.get("critical_failure_counts", {})
    missing_grades = comparison.get("missing_grades_by_condition", {})
    for condition in conditions:
        entry = quality.get(condition, {})
        score = entry.get("mean_score")
        lines.append("| " + condition + " | " + str(entry.get("count", 0)) + " | " +
            str(entry.get("unavailable_count", 0)) + " | " +
            str(missing_grades.get(condition, 0)) + " | " +
            str(score if score is not None else "unknown") + " | " +
            str(failures.get(condition, 0)) + " |")
    ceiling = comparison.get("baseline_ceiling_effect", {})
    lines.extend(["", "Matched assessable pairs: " + str(comparison.get("assessable_pair_count", 0)) +
        " / " + str(comparison.get("expected_pair_count", 0)) +
        "; mean score difference: " + str(comparison.get("mean_paired_score_delta")) + ".",
        "Reference ceiling effect: " + str(ceiling), "",
        "## Schema acceptance", "",
        "| Condition | Attempts | Valid | Invalid | Unavailable | Assessable | Acceptance (valid/assessable) |",
        "|---|---:|---:|---:|---:|---:|---:|"])
    for condition in conditions:
        entry = comparison.get("schema_acceptance_by_condition", {}).get(condition, {})
        rate = entry.get("acceptance_rate")
        shown = str(round(rate * 100, 1)) + "%" if rate is not None else "unknown"
        lines.append("| " + condition + " | " + str(entry.get("attempts", 0)) + " | " +
            str(entry.get("valid", 0)) + " | " + str(entry.get("invalid", 0)) + " | " +
            str(entry.get("unavailable", 0)) + " | " +
            str(entry.get("assessable_protocol_attempts", 0)) + " | " + shown + " |")
    lines.extend(["", "## Terminal status calibration", "",
        "| Condition | Final statuses | Calibration judgments |", "|---|---|---|"])
    for condition in conditions:
        statuses = comparison.get("terminal_status_counts_by_condition", {}).get(condition, {})
        judgments = comparison.get("status_calibration_counts", {}).get(condition, {})
        lines.append("| " + condition + " | " + str(statuses or "none recorded") +
            " | " + str(judgments) + " |")
    lines.extend(["", "## Provider availability", "",
        "| Condition | Complete | Failed | Ambiguous | Usage limits | Provider calls |",
        "|---|---:|---:|---:|---:|---:|"])
    for condition in conditions:
        entry = comparison.get("provider_availability_by_condition", {}).get(condition, {})
        lines.append("| " + condition + " | " + str(entry.get("complete", 0)) + " | " +
            str(entry.get("failed", 0)) + " | " + str(entry.get("ambiguous", 0)) + " | " +
            str(entry.get("usage_limit", 0)) + " | " +
            str(entry.get("provider_calls", 0)) + " |")
    lines.extend(["", "## Resource use", "",
        "| Condition | Provider calls | Tool calls | Wall seconds | Input tokens | Output tokens | Known cost USD |",
        "|---|---:|---:|---:|---:|---:|---:|"])
    for condition in conditions:
        entry = comparison.get("resource_use_by_condition", {}).get(condition, {})
        fields = ("provider_calls", "tool_calls", "wall_seconds", "input_tokens",
                  "output_tokens", "cost_usd")
        cells = [str(entry.get(field) if entry.get(field) is not None else "unknown")
                 for field in fields]
        lines.append("| " + condition + " | " + " | ".join(cells) + " |")
    reconciliation = ("equal-input=" + str(comparison.get("equal_input_matched_pair_count", 0)) +
        ", capability-mismatch=" + str(comparison.get("capability_mismatch_pair_count", 0)) +
        ", source-mismatch=" + str(comparison.get("source_mismatch_pair_count", 0)) +
        ", unmatched/incomplete=" + str(comparison.get("unmatched_or_incomplete_pair_count", 0)) +
        ", temporally recovered=" + str(comparison.get("temporally_recovered_pair_count", 0)) +
        ", quota-truncated=" + str(comparison.get("quota_truncated_pair_count", 0)))
    mismatch_cases = comparison.get("input_comparability", {}).get("capability_mismatch_case_ids", [])
    quick_wrapper_cases = comparison.get("quick_wrapper_case_ids", [])
    lines.extend(["", "## Paired architecture comparisons", "",
        "The strict baseline uses one call. Quick pipeline trials also have a one-call cap, matching baseline. "
        "Deep and Research review arms can use larger per-trial call and wall caps; actual calls and time are shown below.",
        ("Quick `pipeline` rows use the fixed one-answer Quick engine wrapper; they do not run the multi-stage "
         "Deep/Research pipeline. Treat those rows as product-path protocol controls, not full-pipeline effectiveness evidence. "
         "Affected cases: " + ", ".join(quick_wrapper_cases) + ".") if quick_wrapper_cases else
         "No Quick wrapper rows are included.",
        "Condition-specific tool capabilities differ for: " + (", ".join(mismatch_cases) or "none") + ".",
        "| Left arm | Right arm | Equal-input pairs | Assessable pairs | Mean score delta | Left calls / seconds | Right calls / seconds |",
        "|---|---|---:|---:|---:|---:|---:|"])
    for pair in comparison.get("pairwise_quality", []):
        left_use, right_use = pair.get("left_resource_use") or {}, pair.get("right_resource_use") or {}
        left_resources = f"{left_use.get('provider_calls', 'unknown')} / {left_use.get('wall_seconds', 'unknown')}"
        right_resources = f"{right_use.get('provider_calls', 'unknown')} / {right_use.get('wall_seconds', 'unknown')}"
        delta = pair.get("mean_score_delta_right_minus_left")
        lines.append("| " + str(pair.get("left_condition")) + " | " +
            str(pair.get("right_condition")) + " | " + str(pair.get("equal_input_pairs", 0)) +
            " | " + str(pair.get("assessable_pairs", 0)) + " | " +
            str(delta if delta is not None else "unknown") + " | " + left_resources +
            " | " + right_resources + " |")
    lines.extend(["", "Recoveries are separate and excluded from contemporaneous first-attempt pairs.",
        "Recovery resources by condition: " + str(comparison.get("recovery_attempts_by_condition", {})),
        "Pair reconciliation: " + reconciliation + ".",
        "Small sample disclosure: " + str(comparison.get("small_sample_disclosure") or
            "at least 30 assessable pairs; results remain descriptive."),
        "Session IDs are supplemental telemetry, not billing totals.",
        "Semantic grades distinguish unavailable answers from incorrect answers and retain the reviewed artifact hash. "
        "Alternative valid proofs are acceptable. Process completion is not a semantic grade.", ""])
    return "\n".join(lines)
