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
import statistics
import time
from typing import Any

from mathresearch.contracts.validation import ValidationError
from mathresearch.locking import acquire_run_lock
from mathresearch.research.math_checks import perform_math_check, validate_math_arguments


DIMENSIONS = ("correctness", "provenance", "coverage", "challenge", "uncertainty")
CONDITIONS = ("baseline", "pipeline")
BASELINE_PREFLIGHT_WORST_SECONDS = 30
CASE_FIELDS = {"id", "question", "objective", "mode", "sources",
               "expected_obligations", "forbidden_claims", "checks"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(str(path), f"cannot read strict JSON: {error}") from error


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
        if not isinstance(raw, dict) or set(raw) != CASE_FIELDS:
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
    if set(case) != CASE_FIELDS:
        raise ValidationError("case", "has unknown or missing fields")
    sources = source_inputs if source_inputs is not None else case["sources"]
    return {"question": case["question"], "objective": case["objective"],
            "mode": case["mode"], "sources": json.loads(canonical_bytes(list(sources)))}


def make_manifest(*, cases: Sequence[Mapping[str, Any]], cases_hash: str,
                  rubric_hash: str, model: str, effort: str, git_sha: str,
                  max_provider_calls: int, max_wall_seconds: int,
                  max_session_usage_delta_percent: float = 10.0,
                  replicates: int = 3) -> dict[str, Any]:
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
    if len(cases) * replicates * 2 > max_provider_calls:
        raise ValidationError("max_provider_calls", "cannot fit all paired trials")
    order = []
    for case_index, case in enumerate(cases):
        for replicate in range(1, replicates + 1):
            first = "baseline" if (case_index + replicate) % 2 == 0 else "pipeline"
            second = "pipeline" if first == "baseline" else "baseline"
            order.append({"case_id": case["id"], "replicate": replicate,
                          "conditions": [first, second]})
    return {"schema_version": 1, "record_type": "research_evaluation_manifest",
            "cases_hash": cases_hash, "rubric_hash": rubric_hash, "case_ids": [case["id"] for case in cases],
            "model": model, "effort": effort, "git_sha": git_sha,
            "caps": {"max_provider_calls": max_provider_calls, "max_wall_seconds": max_wall_seconds,
                     "max_session_usage_delta_percent": float(max_session_usage_delta_percent)},
            "replicates": replicates, "ordering": order}


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
        if condition not in CONDITIONS or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case_id):
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
        for index, check in enumerate(case["checks"], 1):
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
        comparison = compare_trials(self.trial_records(), grades,
            required_replicates=manifest["replicates"], deep_case_ids=deep_case_ids,
            quick_case_ids=quick_case_ids or set(),
            case_ids=set(manifest["case_ids"]), requested_model=manifest["model"],
            requested_effort=manifest["effort"], caps=manifest["caps"],
            budget_wall_seconds=budget["wall_seconds_observed"])
        write_json(self.directory / "comparison.json", comparison)
        (self.directory / "comparison.md").write_text(comparison_markdown(comparison), encoding="utf-8")
        return comparison


def make_trial(*, case_id: str, replicate: int, condition: str, status: str,
               report: str | None, provider_calls: int, wall_seconds: float,
               cost_usd: float | None, source_hash: str, grader: str | None = None) -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValidationError("condition", "must be baseline or pipeline")
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
    if isinstance(wall_seconds, bool) or not isinstance(wall_seconds, (float, int)) or wall_seconds < 0 or not math.isfinite(wall_seconds):
        raise ValidationError("wall_seconds", "must be finite and nonnegative")
    if cost_usd is not None and (isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0 or not math.isfinite(cost_usd)):
        raise ValidationError("cost_usd", "must be null or finite and nonnegative")
    report_hash = sha256(report.encode("utf-8")) if report is not None else None
    return {"schema_version": 1, "record_type": "research_evaluation_trial",
            "case_id": case_id, "replicate": replicate, "condition": condition,
            "status": status, "provider_calls": provider_calls,
            "wall_seconds": float(wall_seconds), "cost_usd": cost_usd,
            "source_hash": source_hash, "grader": grader,
            "report": report, "report_sha256": report_hash}


def make_grade(*, case_id: str, replicate: int, condition: str, grader: str,
               dimensions: Mapping[str, int], critical_failures: Sequence[str],
               evidence: Sequence[str]) -> dict[str, Any]:
    if not isinstance(grader, str) or not grader.strip():
        raise ValidationError("grader", "must identify a human or advisory grader")
    if not isinstance(dimensions, Mapping) or set(dimensions) != set(DIMENSIONS):
        raise ValidationError("dimensions", "must grade all five rubric dimensions")
    if any(isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2) for value in dimensions.values()):
        raise ValidationError("dimensions", "scores must be integers from zero to two")
    if not isinstance(evidence, (list, tuple)) or not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
        raise ValidationError("evidence", "at least one evidence passage is required")
    if not isinstance(critical_failures, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in critical_failures):
        raise ValidationError("critical_failures", "entries must be nonempty strings")
    if condition not in CONDITIONS:
        raise ValidationError("condition", "must be baseline or pipeline")
    return {"case_id": case_id, "replicate": replicate, "condition": condition,
            "grader": grader, "dimensions": dict(dimensions), "score": sum(dimensions.values()),
            "critical_failures": list(critical_failures), "evidence": list(evidence)}


def compare_trials(trials: Sequence[Mapping[str, Any]], grades: Sequence[Mapping[str, Any]],
                   *, required_replicates: int = 3,
                   deep_case_ids: set[str] | None = None,
                   quick_case_ids: set[str] | None = None,
                   case_ids: set[str] | None = None,
                   requested_model: str | None = None,
                   requested_effort: str | None = None,
                   caps: Mapping[str, Any] | None = None,
                   budget_wall_seconds: float | None = None) -> dict[str, Any]:
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
    expected = {(case_id, replicate, condition) for case_id in all_case_ids
                for replicate in range(1, required_replicates + 1) for condition in CONDITIONS}
    unexpected = [f"unexpected trial or grade: {key}"
                  for key in (trial_map.keys() | grade_map.keys()) - expected]
    missing_trials = sorted(expected - trial_map.keys())
    missing_grades = sorted(expected - grade_map.keys())
    bad_trials = [key for key, item in trial_map.items() if item.get("status") != "complete" or item.get("report") is None]
    mismatched_pairs: list[str] = []
    for case_id in all_case_ids:
        for replicate in range(1, required_replicates + 1):
            baseline = trial_map.get((case_id, replicate, "baseline"))
            pipeline = trial_map.get((case_id, replicate, "pipeline"))
            if baseline and pipeline and baseline.get("source_hash") != pipeline.get("source_hash"):
                mismatched_pairs.append(f"source hash mismatch: {case_id}/{replicate}")
    bad_hashes = [f"report hash mismatch: {key}" for key, item in trial_map.items()
                  if item.get("report") is not None and
                  (not isinstance(item.get("report"), str) or
                   item.get("report_sha256") != sha256(item["report"].encode("utf-8")))]
    quick_case_ids = quick_case_ids or set()
    wrong_quick_calls = [f"Quick pipeline must use exactly one call: {key}"
        for key, item in trial_map.items() if key[0] in quick_case_ids and key[2] == "pipeline" and item.get("provider_calls") != 1]
    wrong_baseline_calls = [f"baseline must use exactly one call: {key}"
        for key, item in trial_map.items() if key[2] == "baseline" and item.get("provider_calls") != 1]
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
                critical_failures=grade.get("critical_failures"), evidence=grade.get("evidence"))
            if grade.get("score") != validated["score"]:
                raise ValidationError("grade", "score disagrees with dimensions")
        except ValidationError:
            invalid_grades.append(f"invalid grade: {key}")
            del grade_map[key]
    complete = not (unexpected or duplicates or missing_trials or missing_grades or bad_trials or mismatched_pairs or
                    invalid_grades or bad_hashes or wrong_quick_calls or wrong_baseline_calls or settings_errors or cap_errors)
    score_differences: list[float] = []
    paired: list[dict[str, Any]] = []
    if complete:
        for case_id in all_case_ids:
            for replicate in range(1, required_replicates + 1):
                base = grade_map[(case_id, replicate, "baseline")]
                pipe = grade_map[(case_id, replicate, "pipeline")]
                delta = int(pipe["score"]) - int(base["score"])
                score_differences.append(delta)
                paired.append({"case_id": case_id, "replicate": replicate,
                               "baseline_score": base["score"], "pipeline_score": pipe["score"],
                               "score_delta": delta})
    baseline_failures = sum(len(grade.get("critical_failures", ())) for key, grade in grade_map.items() if key[2] == "baseline")
    pipeline_failures = sum(len(grade.get("critical_failures", ())) for key, grade in grade_map.items() if key[2] == "pipeline")
    baseline_times = [float(item["wall_seconds"]) for key, item in trial_map.items() if key[2] == "baseline" and item.get("status") == "complete" and isinstance(item.get("wall_seconds"), (float, int)) and item["wall_seconds"] > 0]
    pipeline_times = [float(item["wall_seconds"]) for key, item in trial_map.items() if key[2] == "pipeline" and item.get("status") == "complete" and isinstance(item.get("wall_seconds"), (float, int)) and item["wall_seconds"] > 0]
    latency_ratios = []
    for case_id in all_case_ids:
        for replicate in range(1, required_replicates + 1):
            b = trial_map.get((case_id, replicate, "baseline")); p = trial_map.get((case_id, replicate, "pipeline"))
            if b and p and b.get("status") == p.get("status") == "complete" and isinstance(b.get("wall_seconds"), (int, float)) and b["wall_seconds"] > 0 and isinstance(p.get("wall_seconds"), (int, float)):
                latency_ratios.append(float(p["wall_seconds"]) / float(b["wall_seconds"]))
    deep_case_ids = deep_case_ids or set()
    deep_scores = [grade["score"] for key, grade in grade_map.items() if key[0] in deep_case_ids and key[2] == "pipeline" and isinstance(grade.get("score"), int)]
    improvement = statistics.mean(score_differences) if complete and score_differences else None
    deep_coverage_baseline = [grade["dimensions"]["coverage"] for key, grade in grade_map.items() if key[0] in deep_case_ids and key[2] == "baseline"]
    deep_coverage_pipeline = [grade["dimensions"]["coverage"] for key, grade in grade_map.items() if key[0] in deep_case_ids and key[2] == "pipeline"]
    reduced_failures = bool(baseline_failures > 0 and pipeline_failures <= baseline_failures * 0.75 and
                            deep_coverage_baseline and deep_coverage_pipeline and
                            statistics.mean(deep_coverage_pipeline) >= statistics.mean(deep_coverage_baseline))
    deep_deltas = [grade_map[(case_id, replicate, "pipeline")]["score"] - grade_map[(case_id, replicate, "baseline")]["score"]
                   for case_id in sorted(deep_case_ids) for replicate in range(1, required_replicates + 1)
                   if (case_id, replicate, "pipeline") in grade_map and
                   (case_id, replicate, "baseline") in grade_map]
    mean_deep_delta = statistics.mean(deep_deltas) if deep_deltas else None
    quality_gain = bool(mean_deep_delta is not None and mean_deep_delta >= 1.0) or reduced_failures
    deep_ratios = [float(trial_map[(case_id, replicate, "pipeline")]["wall_seconds"]) /
        float(trial_map[(case_id, replicate, "baseline")]["wall_seconds"])
        for case_id in deep_case_ids for replicate in range(1, required_replicates + 1)
        if (case_id, replicate, "pipeline") in trial_map and (case_id, replicate, "baseline") in trial_map and
        trial_map[(case_id, replicate, "pipeline")].get("status") == "complete" and
        trial_map[(case_id, replicate, "baseline")].get("status") == "complete" and
        trial_map[(case_id, replicate, "baseline")].get("wall_seconds", 0) > 0]
    quick_ratios = [float(trial_map[(case_id, replicate, "pipeline")]["wall_seconds"]) /
        float(trial_map[(case_id, replicate, "baseline")]["wall_seconds"])
        for case_id in quick_case_ids for replicate in range(1, required_replicates + 1)
        if (case_id, replicate, "pipeline") in trial_map and (case_id, replicate, "baseline") in trial_map and
        trial_map[(case_id, replicate, "pipeline")].get("status") == "complete" and
        trial_map[(case_id, replicate, "baseline")].get("status") == "complete" and
        trial_map[(case_id, replicate, "baseline")].get("wall_seconds", 0) > 0]
    efficiency_gate = bool(deep_case_ids and quick_case_ids and
        len(deep_ratios) == len(deep_case_ids) * required_replicates and
        len(quick_ratios) == len(quick_case_ids) * required_replicates and
        statistics.median(deep_ratios) <= 6 and statistics.median(quick_ratios) <= 1.5)
    return {"schema_version": 1, "record_type": "research_evaluation_comparison",
            "comparison_status": "complete" if complete else "incomplete",
            "quality_gate_passed": bool(complete and pipeline_failures == 0 and
                bool(deep_scores) and statistics.mean(deep_scores) >= 8 and quality_gain),
            "trial_count": len(trial_map), "grade_count": len(grade_map),
            "missing_trials": [list(key) for key in missing_trials],
            "missing_grades": [list(key) for key in missing_grades],
            "bad_trials": [list(key) for key in bad_trials],
            "integrity_errors": unexpected + duplicates + mismatched_pairs + invalid_grades + bad_hashes + wrong_quick_calls + wrong_baseline_calls + settings_errors + cap_errors,
            "mean_paired_score_delta": improvement, "paired_scores": paired,
            "mean_deep_paired_score_delta": mean_deep_delta,
            "critical_failure_counts": {"baseline": baseline_failures, "pipeline": pipeline_failures},
            "quality_gain_demonstrated": bool(complete and quality_gain),
            "efficiency_gate_passed": bool(complete and efficiency_gate),
            "median_deep_latency_ratio": statistics.median(deep_ratios) if deep_ratios else None,
            "median_quick_latency_ratio": statistics.median(quick_ratios) if quick_ratios else None,
            "mean_pipeline_score": statistics.mean(deep_scores) if deep_scores else None,
            "median_latency_ratio_pipeline_over_baseline": statistics.median(latency_ratios) if latency_ratios else None,
            "baseline_p50_seconds": statistics.median(baseline_times) if baseline_times else None,
            "pipeline_p50_seconds": statistics.median(pipeline_times) if pipeline_times else None,
            "unknown_cost_trial_count": sum(item.get("cost_usd") is None for item in trial_map.values()),
            "known_cost_total_usd": sum(item["cost_usd"] for item in trial_map.values() if isinstance(item.get("cost_usd"), (int, float))),
            "known_baseline_cost_usd": sum(item["cost_usd"] for key, item in trial_map.items() if key[2] == "baseline" and isinstance(item.get("cost_usd"), (int, float))),
            "known_pipeline_cost_usd": sum(item["cost_usd"] for key, item in trial_map.items() if key[2] == "pipeline" and isinstance(item.get("cost_usd"), (int, float))),
            "actual_provider_calls": actual_provider_calls,
            "provider_call_count_basis": "conservative_action_attempts; not confirmed remote requests",
            "actual_wall_seconds": total_wall_seconds,
            "known_input_tokens": sum(item["input_tokens"] for item in trial_map.values() if isinstance(item.get("input_tokens"), int) and not isinstance(item.get("input_tokens"), bool)),
            "known_output_tokens": sum(item["output_tokens"] for item in trial_map.values() if isinstance(item.get("output_tokens"), int) and not isinstance(item.get("output_tokens"), bool)),
            "unknown_token_trial_count": sum(item.get("input_tokens") is None or item.get("output_tokens") is None for item in trial_map.values()),
            "latency_ratio_unavailable_pairs": len(all_case_ids) * required_replicates - len(latency_ratios)}


def run_paired_trials(cases: Sequence[Mapping[str, Any]], store: EvaluationStore, *,
                      trial_runner: Any, usage_checkpoint: Any | None = None,
                      monotonic: Any = time.monotonic) -> dict[str, Any]:
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
                usage_checkpoint=checkpoint, monotonic=active_clock)
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
                              trial_runner: Any, usage_checkpoint: Any,
                              monotonic: Any) -> dict[str, Any]:
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
        case = cases_by_id[case_id]
        if wall_cap - initially_recorded - (monotonic() - started) <= 0:
            stopped_reason = "wall_time_cap_reached"
            break
        pair_inputs = store.acquire_pair_inputs(case, replicate)
        for condition in pair["conditions"]:
            path = store._trial_path(case_id, replicate, condition)
            if path.exists():
                existing = _read_json(path)
                if existing.get("status") == "complete":
                    continue
                stopped_reason = "previous_trial_failed_or_unresolved"
                break
            elapsed_session = monotonic() - started
            remaining = int(wall_cap - initially_recorded - elapsed_session)
            preflight_reserve = BASELINE_PREFLIGHT_WORST_SECONDS if condition == "baseline" else 0
            if remaining <= preflight_reserve:
                stopped_reason = "wall_time_cap_reached"
                break
            observed = usage_checkpoint(case_id, replicate, condition)
            if usage_checkpoint is not None and observed is None:
                stopped_reason = "session_usage_checkpoint_unavailable"
                break
            if usage_checkpoint is not None and not store.record_usage_check(observed_remaining_percent=observed,
                    case_id=case_id, replicate=replicate, condition=condition):
                stopped_reason = "session_usage_cap_reached"
                break
            reserve_calls = 1 if condition == "baseline" else {"quick": 1, "deep": 7, "research": 11}[case["mode"]]
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
                    cost_usd=raw.get("cost_usd"), source_hash=pair_inputs["source_hash"])
                trial.update({"reserved_provider_calls": reserve_calls,
                    "requested_model": manifest["model"], "requested_effort": manifest["effort"]})
                for key in ("observed_model", "observed_effort", "input_tokens", "output_tokens",
                            "provider_outcome", "provider_exit_code"):
                    if key in raw:
                        trial[key] = raw[key]
                if "error" in raw:
                    trial["error"] = str(raw["error"])[:4000]
                store.record_result(trial)
                store.record_elapsed(elapsed)
                completed.append(f"{case_id}/{replicate}/{condition}")
                if trial["status"] != "complete":
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
    return {"stopped_reason": stopped_reason,
            "trial_conditions_recorded": completed,
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
    ratio = comparison.get("median_latency_ratio_pipeline_over_baseline")
    return "\n".join(("# Paired research-quality comparison", "",
        f"Status: `{comparison.get('comparison_status')}`", "",
        f"Quality gate passed: `{str(bool(comparison.get('quality_gate_passed'))).lower()}`", "",
        f"Mean paired score difference: `{delta if delta is not None else 'unavailable'}` points.",
        f"Median latency ratio (pipeline / baseline): `{ratio if ratio is not None else 'unavailable'}`.",
        f"Critical failures: baseline `{comparison.get('critical_failure_counts', {}).get('baseline', 0)}`, "
        f"pipeline `{comparison.get('critical_failure_counts', {}).get('pipeline', 0)}`.", "",
        "Semantic grades require an identified human reviewer and evidence passages. "
        "Process completion alone is not a quality grade.", ""))
