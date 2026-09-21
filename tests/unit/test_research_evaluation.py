"""Offline contract tests for paired evaluation and explicit semantic grading."""

from __future__ import annotations

import tempfile
import json
from pathlib import Path
import unittest

from mathresearch.contracts.validation import ValidationError
from mathresearch.errors import RunLockedError
from mathresearch.locking import acquire_run_lock
from mathresearch.research.evaluation import (
    EvaluationStore, compare_trials, load_cases, make_grade, make_manifest,
    make_trial, run_paired_trials, validate_resume, worker_case,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES = PROJECT_ROOT / "evals" / "research-quality"


def _grade(condition: str, *, circular: bool = False) -> dict[str, object]:
    dimensions = {"correctness": 0 if circular else 2,
                  "provenance": 0 if circular else 2,
                  "coverage": 2, "challenge": 0 if circular else 2,
                  "uncertainty": 2}
    return make_grade(case_id="sample", replicate=1, condition=condition,
        grader="human-fixture-review", dimensions=dimensions,
        critical_failures=["circular support accepted"] if circular else [],
        evidence=["Synthetic fixed output passage used by this offline test."])


def _trial(condition: str, *, report: str, seconds: float = 2.0) -> dict[str, object]:
    return make_trial(case_id="sample", replicate=1, condition=condition,
        status="complete", report=report, provider_calls=1, wall_seconds=seconds,
        cost_usd=None, source_hash="same-source-hash")


class ResearchEvaluationTests(unittest.TestCase):
    def test_cases_load_and_worker_projection_holds_out_rubric_data(self) -> None:
        cases, cases_hash, rubric_hash = load_cases(CASES)
        self.assertEqual(len(cases), 8)
        self.assertEqual(len(cases_hash), 64)
        self.assertEqual(len(rubric_hash), 64)
        projected = worker_case(cases[0])
        self.assertNotIn("expected_obligations", projected)
        self.assertNotIn("forbidden_claims", projected)
        self.assertNotIn("checks", projected)

    def test_process_success_and_circular_output_do_not_pass_quality_gate(self) -> None:
        trials = [_trial("baseline", report="complete but circular"),
                  _trial("pipeline", report="complete but circular")]
        grades = [_grade("baseline", circular=True), _grade("pipeline", circular=True)]
        summary = compare_trials(trials, grades, required_replicates=1,
                                 deep_case_ids={"sample"}, case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "complete")
        self.assertFalse(summary["quality_gate_passed"])
        self.assertEqual(summary["critical_failure_counts"]["pipeline"], 1)

    def test_qualified_output_can_pass_quality_gate_with_explicit_human_grade(self) -> None:
        trials = [_trial("baseline", report="complete but circular", seconds=3),
                  _trial("pipeline", report="qualified, scoped report", seconds=4)]
        grades = [_grade("baseline", circular=True), _grade("pipeline")]
        summary = compare_trials(trials, grades, required_replicates=1,
                                 deep_case_ids={"sample"}, case_ids={"sample"})
        self.assertTrue(summary["quality_gate_passed"])
        self.assertEqual(summary["mean_paired_score_delta"], 6)
        self.assertEqual(summary["median_latency_ratio_pipeline_over_baseline"], 4 / 3)

    def test_ungraded_trials_are_incomplete_and_unknown_cost_is_not_zero(self) -> None:
        summary = compare_trials([_trial("baseline", report="draft")], [],
                                 required_replicates=1, case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "incomplete")
        self.assertFalse(summary["quality_gate_passed"])
        self.assertEqual(summary["missing_grades"], [
            ["sample", 1, "baseline"], ["sample", 1, "pipeline"]])
        self.assertEqual(summary["unknown_cost_trial_count"], 1)

    def test_source_mismatch_invalidates_pair(self) -> None:
        trials = [_trial("baseline", report="one") | {"source_hash": "a"},
                  _trial("pipeline", report="two") | {"source_hash": "b"}]
        summary = compare_trials(trials, [_grade("baseline"), _grade("pipeline")],
                                 required_replicates=1, case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "incomplete")
        self.assertIn("source hash mismatch: sample/1", summary["integrity_errors"])

    def test_extra_trials_outside_the_manifest_invalidate_comparison(self) -> None:
        trials = [_trial("baseline", report="one"), _trial("pipeline", report="two"),
                  _trial("pipeline", report="extra") | {"replicate": 2}]
        result = compare_trials(trials, [_grade("baseline"), _grade("pipeline")],
            required_replicates=1, case_ids={"sample"}, deep_case_ids={"sample"})
        self.assertEqual(result["comparison_status"], "incomplete")
        self.assertTrue(any("unexpected" in error for error in result["integrity_errors"]))

    def test_malformed_grade_is_incomplete_without_crashing_aggregation(self) -> None:
        trials = [_trial("baseline", report="one"), _trial("pipeline", report="two")]
        grade = _grade("pipeline") | {"dimensions": None, "critical_failures": None}
        result = compare_trials(trials, [_grade("baseline"), grade],
            required_replicates=1, case_ids={"sample"}, deep_case_ids={"sample"})
        self.assertEqual(result["comparison_status"], "incomplete")
        self.assertFalse(result["quality_gain_demonstrated"])
        self.assertFalse(result["efficiency_gate_passed"])

    def test_manifest_is_immutable_and_alternates_condition_order(self) -> None:
        cases, cases_hash, rubric_hash = load_cases(CASES)
        manifest = make_manifest(cases=cases, cases_hash=cases_hash,
            rubric_hash=rubric_hash, model="gpt-test", effort="high", git_sha="abc",
            max_provider_calls=240, max_wall_seconds=7200)
        self.assertEqual(len(manifest["ordering"]), 24)
        self.assertNotEqual(manifest["ordering"][0]["conditions"],
                            manifest["ordering"][1]["conditions"])
        validate_resume(manifest, dict(manifest))
        changed = dict(manifest) | {"model": "different"}
        with self.assertRaises(ValidationError):
            validate_resume(manifest, changed)

    def test_pair_check_receipt_is_shared_input_and_not_a_worker_tool_result(self) -> None:
        cases, _, _ = load_cases(CASES)
        case = next(item for item in cases if item["id"] == "perfect-six")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = make_manifest(cases=[case], cases_hash="a" * 64,
                rubric_hash="b" * 64, model="gpt-test", effort="high", git_sha="abc",
                max_provider_calls=6, max_wall_seconds=7200)
            store = EvaluationStore(root, manifest)
            first = store.acquire_pair_inputs(case, 1)
            second = store.acquire_pair_inputs(case, 1)
            self.assertEqual(first, second)
            transcript = first["source_inputs"][0]["text"]
            self.assertIn('"proper_divisors":[1,2,3]', transcript)
            self.assertEqual(first["receipts"][0]["request"]["operation"], "check_integer")
            self.assertNotIn("expected_obligations", transcript)
            receipt_path = root / "receipts" / "perfect-six-01.json"
            corrupted = json.loads(receipt_path.read_text(encoding="utf-8"))
            corrupted["source_inputs"][0]["text"] = "changed after initialization"
            receipt_path.write_text(json.dumps(corrupted), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "paired inputs or digest changed"):
                store.acquire_pair_inputs(case, 1)

    def test_session_usage_ceiling_stops_before_provider_trial(self) -> None:
        cases, _, _ = load_cases(CASES)
        case = next(item for item in cases if item["id"] == "perfect-six")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = make_manifest(cases=[case], cases_hash="a" * 64,
                rubric_hash="b" * 64, model="gpt-test", effort="high", git_sha="abc",
                max_provider_calls=6, max_wall_seconds=7200)
            store = EvaluationStore(root, manifest)
            usage_readings = iter((55.0, 45.0))
            launched: list[str] = []
            result = run_paired_trials([case], store,
                trial_runner=lambda *args: launched.append("launched") or {
                    "status": "complete", "provider_calls": 1, "report": "fixture"},
                usage_checkpoint=lambda *args: next(usage_readings))
            self.assertEqual(result["stopped_reason"], "session_usage_cap_reached")
            self.assertEqual(launched, ["launched"])
            self.assertEqual(len(store.trial_records()), 1)
            checks = json.loads((root / "usage-checks.json").read_text(encoding="utf-8"))
            self.assertEqual(checks[0]["baseline_remaining_percent"], 55.0)
            self.assertEqual(checks[1]["quota_drop_percentage_points"], 10.0)

    def test_concurrent_paired_runner_is_rejected_before_provider_trial(self) -> None:
        cases, _, _ = load_cases(CASES)
        case = next(item for item in cases if item["id"] == "perfect-six")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = make_manifest(cases=[case], cases_hash="a" * 64,
                rubric_hash="b" * 64, model="gpt-test", effort="high", git_sha="abc",
                max_provider_calls=6, max_wall_seconds=7200)
            store = EvaluationStore(root, manifest)
            launched: list[str] = []
            with acquire_run_lock(root):
                with self.assertRaises(RunLockedError):
                    run_paired_trials([case], store,
                        trial_runner=lambda *args: launched.append("launched"),
                        usage_checkpoint=lambda *args: 0.0)
            self.assertEqual(launched, [])
            self.assertEqual(json.loads((root / "budget.json").read_text(encoding="utf-8"))[
                "provider_calls_reserved"], 0)

    def test_concurrent_store_initialization_is_rejected_before_budget_write(self) -> None:
        cases, cases_hash, rubric_hash = load_cases(CASES)
        manifest = make_manifest(cases=cases, cases_hash=cases_hash,
            rubric_hash=rubric_hash, model="gpt-test", effort="high", git_sha="abc",
            max_provider_calls=240, max_wall_seconds=7200)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with acquire_run_lock(root):
                with self.assertRaises(RunLockedError):
                    EvaluationStore(root, manifest)
            self.assertFalse((root / "budget.json").exists())
            store = EvaluationStore(root, manifest)
            self.assertEqual(json.loads((root / "budget.json").read_text(encoding="utf-8"))[
                "provider_calls_reserved"], 0)

    def test_offline_fixed_outputs_run_as_paired_trials_without_semantic_autogrades(self) -> None:
        cases, _, _ = load_cases(CASES)
        case = next(item for item in cases if item["id"] == "perfect-six")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = make_manifest(cases=[case], cases_hash="a" * 64,
                rubric_hash="b" * 64, model="gpt-test", effort="medium", git_sha="abc",
                max_provider_calls=6, max_wall_seconds=7200)
            store = EvaluationStore(root, manifest)
            observed_hashes: list[str] = []

            def fixed_trial(case_arg, condition, pair_inputs, trial_dir, timeout):
                observed_hashes.append(pair_inputs["source_hash"])
                answer = ("The proper divisors are 1, 2, and 3. They sum to 6. "
                          "This single response is unaudited.")
                return {"status": "complete", "provider_calls": 1,
                        "report": answer, "cost_usd": None}

            outcome = run_paired_trials([case], store, trial_runner=fixed_trial,
                usage_checkpoint=lambda *args: 49.0)
            self.assertEqual(len(outcome["trial_conditions_recorded"]), 6)
            self.assertEqual(outcome["provider_calls_reserved"], 6)
            self.assertEqual(len(store.trial_records()), 6)
            self.assertEqual(len(set(observed_hashes)), 1)
            summary = store.finalize([], deep_case_ids=set(), quick_case_ids={"perfect-six"})
            self.assertEqual(summary["comparison_status"], "incomplete")
            self.assertFalse(summary["quality_gate_passed"])

    def test_ambiguous_intent_is_persisted_and_cannot_be_relaunched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases, cases_hash, rubric_hash = load_cases(CASES)
            manifest = make_manifest(cases=cases, cases_hash=cases_hash,
                rubric_hash=rubric_hash, model="gpt-test", effort="high", git_sha="abc",
                max_provider_calls=240, max_wall_seconds=7200)
            store = EvaluationStore(root, manifest)
            store.record_intent(case_id="sample", replicate=1, condition="baseline",
                                source_hash="hash")
            store.mark_ambiguous("sample", 1, "baseline", reason="connection lost", wall_seconds=5)
            with self.assertRaisesRegex(ValidationError, "will not be relaunched"):
                store.record_intent(case_id="sample", replicate=1, condition="baseline",
                                    source_hash="hash")


if __name__ == "__main__":
    unittest.main()
