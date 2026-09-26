"""Offline contract tests for paired evaluation and explicit semantic grading."""

from __future__ import annotations

import tempfile
import json
import hashlib
from pathlib import Path
import unittest

from mathresearch.contracts.validation import ValidationError
from mathresearch.errors import RunLockedError
from mathresearch.locking import acquire_run_lock
from mathresearch.research.evaluation import (
    EvaluationStore, classify_trial_failure, compare_trials, load_cases, make_grade, make_manifest,
    make_trial, run_paired_trials, validate_resume, worker_case,
)
from mathresearch.research.contracts import validate_result


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES = PROJECT_ROOT / "evals" / "research-quality"


def _perfect_case() -> dict[str, object]:
    return {"id": "perfect-six", "question": "Verify the divisors of 6.",
        "objective": "answer", "mode": "deep", "sources": [],
        "expected_obligations": ["Give the proper divisors and their sum."],
        "forbidden_claims": ["Include 6 as a proper divisor."],
        "checks": [{"operation": "check_integer", "arguments": {"n": 6},
                    "scope": "paired deterministic check"}]}


def _grade(condition: str, *, report: str, circular: bool = False) -> dict[str, object]:
    dimensions = {"correctness": 0 if circular else 2,
                  "provenance": 0 if circular else 2,
                  "coverage": 2, "challenge": 0 if circular else 2,
                  "uncertainty": 2}
    return make_grade(case_id="sample", replicate=1, condition=condition,
        grader="human-fixture-review", dimensions=dimensions,
        critical_failures=["circular support accepted"] if circular else [],
        evidence=["Synthetic fixed output passage used by this offline test."],
        evidence_refs=["step:step-1"],
        dimension_reasons={name: "See step-1 and the quoted answer passage."
                           for name in dimensions},
        artifact_sha256=hashlib.sha256(report.encode("utf-8")).hexdigest())


def _trial(condition: str, *, report: str, seconds: float = 2.0) -> dict[str, object]:
    return make_trial(case_id="sample", replicate=1, condition=condition,
        status="complete", report=report, provider_calls=1, wall_seconds=seconds,
        cost_usd=None, source_hash="same-source-hash")


class ResearchEvaluationTests(unittest.TestCase):
    def test_captured_schema_rejections_remain_invalid_but_semantically_assessable(self) -> None:
        expected_errors = {
            "induction-weighted-sum": "base-case",
            "calculus-log-integral": "ibp-epsilon",
            "extremal-noncut-vertices": "step-spanning-tree",
            "probability-overlap-hh": "state-def",
        }
        fixture_root = PROJECT_ROOT / "tests" / "fixtures" / "research" / "diagnostic_regressions"
        for case_id, bad_reference in expected_errors.items():
            with self.subTest(case_id=case_id):
                folder = fixture_root / case_id
                payload_path = folder / "response.json"
                metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                payload_bytes = payload_path.read_bytes().rstrip(b"\n")
                payload = json.loads(payload_bytes)
                self.assertEqual(metadata["artifact_sha256"], hashlib.sha256(payload_bytes).hexdigest())
                self.assertEqual(metadata["failure_class"], "schema_rejection")
                with self.assertRaises(ValidationError) as raised:
                    validate_result("answer", payload)
                self.assertEqual(raised.exception.details["bad_reference"], bad_reference)

    def test_repair_enabled_baseline_is_a_separate_nonpaired_condition(self) -> None:
        report = "repaired baseline output"
        trial = make_trial(case_id="sample", replicate=1, condition="baseline_repair",
            status="complete", report=report, provider_calls=2, wall_seconds=3,
            cost_usd=None, source_hash="same-source-hash")
        grade = make_grade(case_id="sample", replicate=1, condition="baseline_repair",
            grader="human-fixture-review",
            dimensions={"correctness": 2, "provenance": 2, "coverage": 2,
                        "challenge": 2, "uncertainty": 2},
            critical_failures=[], evidence=["The corrected structured result is valid."],
            evidence_refs=["claim:claim-1"],
            dimension_reasons={name: "The corrected claim is supported by the response."
                               for name in ("correctness", "provenance", "coverage",
                                            "challenge", "uncertainty")},
            artifact_sha256=hashlib.sha256(report.encode()).hexdigest())
        summary = compare_trials([trial], [grade], conditions=("baseline_repair",),
            required_replicates=1, case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "complete")
        self.assertEqual(summary["actual_provider_calls"], 2)
        self.assertEqual(summary["assessable_pair_count"], 0)

    def test_repair_baseline_can_be_paired_with_pipeline(self) -> None:
        reference = _trial("baseline_repair", report="repaired baseline") | {"provider_calls": 2}
        pipeline = _trial("pipeline", report="pipeline answer")
        grades = [_grade("baseline_repair", report="repaired baseline"),
                  _grade("pipeline", report="pipeline answer")]
        summary = compare_trials([reference, pipeline], grades,
            conditions=("baseline_repair", "pipeline"), required_replicates=1,
            case_ids={"sample"}, deep_case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "complete")
        self.assertEqual(summary["assessable_pair_count"], 1)
        self.assertEqual(summary["reference_condition"], "baseline_repair")

    def test_strict_baseline_call_limit_rejects_a_repaired_result(self) -> None:
        baseline = _trial("baseline", report="two calls") | {"provider_calls": 2}
        pipeline = _trial("pipeline", report="pipeline result")
        result = compare_trials([baseline, pipeline], [], required_replicates=1,
            case_ids={"sample"})
        self.assertTrue(any("baseline must use exactly one call" in error
                            for error in result["integrity_errors"]))

    def test_schema_failure_can_receive_artifact_bound_semantic_grade(self) -> None:
        artifact_hash = "a" * 64
        rejected = make_trial(case_id="sample", replicate=1, condition="baseline",
            status="failed", report=None, provider_calls=1, wall_seconds=2,
            cost_usd=None, source_hash="same", artifact_sha256=artifact_hash,
            protocol_validity="invalid", failure_class="schema_rejection")
        accepted = _trial("pipeline", report="valid structured proof") | {"source_hash": "same"}
        dimensions = {"correctness": 2, "provenance": 2, "coverage": 2,
                      "challenge": 2, "uncertainty": 2}
        grades = [make_grade(case_id="sample", replicate=1, condition="baseline",
            grader="independent-human", dimensions=dimensions, critical_failures=[],
            evidence=["Captured proof derives the identity by induction."],
            evidence_refs=["step:induction-step"],
            dimension_reasons={name: "See the cited induction step."
                               for name in dimensions},
            artifact_sha256=artifact_hash), _grade("pipeline", report="valid structured proof")]
        summary = compare_trials([rejected, accepted], grades, required_replicates=1,
            case_ids={"sample"}, deep_case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "complete")
        self.assertFalse(summary["all_expected_trials_complete"])
        self.assertEqual(summary["protocol_failure_counts"]["schema_rejection"], 1)
        self.assertEqual(summary["assessable_pair_count"], 1)
        self.assertEqual(summary["paired_scores"][0]["baseline_score"], 10)
        self.assertEqual(summary["assessable_quality_by_condition"]["baseline"],
                         {"count": 1, "unavailable_count": 0, "mean_score": 10})
        self.assertEqual(summary["bad_trials"], [["sample", 1, "baseline"]])

    def test_unavailable_answer_has_no_invented_semantic_score(self) -> None:
        grade = make_grade(case_id="sample", replicate=1, condition="baseline",
            grader="independent-human", dimensions=None, critical_failures=[], evidence=[],
            assessability="unavailable")
        self.assertIsNone(grade["score"])
        self.assertIsNone(grade["dimensions"])

    def test_comparison_keeps_protocol_quality_calibration_and_quota_outcomes_separate(self) -> None:
        artifact = "a" * 64
        rejected = make_trial(case_id="sample", replicate=1, condition="baseline",
            status="failed", report=None, provider_calls=1, wall_seconds=2,
            cost_usd=None, source_hash="same", artifact_sha256=artifact,
            protocol_validity="invalid", failure_class="schema_rejection")
        wrong_answer = _trial("pipeline", report="A structurally valid but incorrect answer.") | {
            "protocol_validity": "valid"}
        quota_exit = make_trial(case_id="sample", replicate=1, condition="sequential_review",
            status="failed", report=None, provider_calls=0, wall_seconds=1,
            cost_usd=None, source_hash="same", failure_class="provider_usage_limit")
        overconfident = _trial("adaptive", report="Incorrect answer; certainly proved.") | {
            "final_status": "supported_within_scope", "protocol_validity": "valid"}
        wrong_hash = hashlib.sha256(wrong_answer["report"].encode()).hexdigest()
        overconfident_hash = hashlib.sha256(overconfident["report"].encode()).hexdigest()
        low_dimensions = {name: 0 for name in ("correctness", "provenance", "coverage",
                                               "challenge", "uncertainty")}
        grades = [make_grade(case_id="sample", replicate=1, condition="baseline",
            grader="independent-human", dimensions={name: 2 for name in low_dimensions},
            critical_failures=[], evidence=["The rejected payload contains a correct proof."],
            artifact_sha256=artifact, evidence_refs=["step:proof-1"],
            dimension_reasons={name: "The captured proof supports this dimension."
                               for name in low_dimensions}),
            make_grade(case_id="sample", replicate=1, condition="pipeline",
            grader="independent-human", dimensions=low_dimensions,
            critical_failures=["incorrect central conclusion"],
            evidence=["The answer asserts a false conclusion."],
            artifact_sha256=wrong_hash,
            evidence_refs=["error:incorrect-conclusion"],
            dimension_reasons={name: "The answer fails the stated obligation."
                               for name in low_dimensions}),
            make_grade(case_id="sample", replicate=1, condition="adaptive",
            grader="independent-human", dimensions=low_dimensions,
            critical_failures=["incorrect central conclusion"],
            evidence=["The final status claims support despite a false conclusion."],
            artifact_sha256=overconfident_hash,
            evidence_refs=["error:incorrect-conclusion"],
            dimension_reasons={name: "The answer fails the stated obligation."
                               for name in low_dimensions},
            calibration_judgment="overconfident",
            calibration_evidence=["The answer labels its false conclusion as supported."])]
        summary = compare_trials([rejected, wrong_answer, quota_exit, overconfident], grades,
            conditions=("baseline", "pipeline", "sequential_review", "adaptive"),
            required_replicates=1, case_ids={"sample"})
        self.assertEqual(summary["protocol_failure_counts"]["schema_rejection"], 1)
        self.assertEqual(summary["schema_acceptance_by_condition"]["pipeline"]["valid"], 1)
        self.assertEqual(summary["provider_availability_by_condition"]["sequential_review"]["usage_limit"], 1)
        self.assertEqual(summary["status_calibration_counts"]["adaptive"]["overconfident"], 1)
        self.assertEqual(summary["terminal_status_counts_by_condition"]["adaptive"]["supported_within_scope"], 1)
        self.assertEqual(summary["assessable_quality_by_condition"]["baseline"]["mean_score"], 10)
        self.assertIsNone(summary["resource_use_by_condition"]["pipeline"]["cost_usd"])

    def test_usage_limit_is_not_classified_as_a_reasoning_or_schema_failure(self) -> None:
        self.assertEqual(classify_trial_failure({"error": "provider usage limit reached",
            "provider_outcome": "failed"}), "provider_usage_limit")
        self.assertEqual(classify_trial_failure({"error": "baseline result schema error: invalid field",
            "provider_outcome": "succeeded"}), "schema_rejection")

    def test_captured_status_and_retry_observations_are_provenance_bound(self) -> None:
        fixture_root = PROJECT_ROOT / "tests" / "fixtures" / "research" / "diagnostic_regressions"
        calibration = json.loads((fixture_root / "pipeline-assessment-induction.json").read_text(encoding="utf-8"))
        self.assertFalse(calibration["synthetic"])
        self.assertEqual(calibration["final_assessment"]["answer_status"], "inconclusive")
        findings = {item["claim_id"]: item for item in calibration["final_assessment"]["claim_findings"]}
        self.assertEqual(findings["induction-principle"]["status"], "unverified")
        stale = json.loads((fixture_root / "pipeline-stale-objection-induction.json").read_text(encoding="utf-8"))
        self.assertIn("No audit objection remains unresolved", stale["excerpt"])
        self.assertIn("claim_induction-principle_unverified", stale["excerpt"])
        retry = json.loads((fixture_root / "structural-retry-session-observations.json").read_text(encoding="utf-8"))
        self.assertFalse(retry["synthetic"])
        self.assertEqual(retry["total_session_markers"], 64)
        self.assertEqual(retry["multi_marker_action_count"], 6)

    def test_cases_load_and_worker_projection_holds_out_rubric_data(self) -> None:
        cases, cases_hash, rubric_hash = load_cases(CASES)
        self.assertEqual(len(cases), 3)
        self.assertEqual(len(cases_hash), 64)
        self.assertEqual(len(rubric_hash), 64)
        projected = worker_case(cases[0])
        self.assertNotIn("expected_obligations", projected)
        self.assertNotIn("forbidden_claims", projected)
        self.assertNotIn("checks", projected)

    def test_process_success_and_circular_output_do_not_pass_quality_gate(self) -> None:
        trials = [_trial("baseline", report="complete but circular"),
                  _trial("pipeline", report="complete but circular")]
        grades = [_grade("baseline", report="complete but circular", circular=True),
                  _grade("pipeline", report="complete but circular", circular=True)]
        summary = compare_trials(trials, grades, required_replicates=1,
                                 deep_case_ids={"sample"}, case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "complete")
        self.assertFalse(summary["quality_gate_passed"])
        self.assertEqual(summary["critical_failure_counts"]["pipeline"], 1)

    def test_qualified_output_can_pass_quality_gate_with_explicit_human_grade(self) -> None:
        trials = [_trial("baseline", report="complete but circular", seconds=3),
                  _trial("pipeline", report="qualified, scoped report", seconds=4)]
        grades = [_grade("baseline", report="complete but circular", circular=True),
                  _grade("pipeline", report="qualified, scoped report")]
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
        summary = compare_trials(trials, [_grade("baseline", report="one"), _grade("pipeline", report="two")],
                                 required_replicates=1, case_ids={"sample"})
        self.assertEqual(summary["comparison_status"], "incomplete")
        self.assertIn("source hash mismatch: sample/1", summary["integrity_errors"])

    def test_capability_mismatch_is_excluded_from_paired_quality_and_latency(self) -> None:
        case_ids = ("sample", "sample-with-tools")
        trials = []
        grades = []
        for case_id in case_ids:
            for condition in ("baseline", "pipeline"):
                report = f"{case_id}/{condition}"
                trials.append(make_trial(case_id=case_id, replicate=1, condition=condition,
                    status="complete", report=report, provider_calls=1, wall_seconds=2,
                    cost_usd=None, source_hash=f"source-{case_id}"))
                score = (0 if condition == "baseline" else 2) if case_id == "sample-with-tools" else 2
                dimensions = {"correctness": score, "provenance": 2, "coverage": 2,
                              "challenge": 2, "uncertainty": 2}
                grades.append(make_grade(case_id=case_id, replicate=1, condition=condition,
                    grader="human-fixture-review", dimensions=dimensions, critical_failures=[],
                    evidence=["Synthetic answer passage for capability-comparability coverage."],
                    evidence_refs=["step:step-1"],
                    dimension_reasons={name: "Supported by the synthetic fixed answer." for name in dimensions},
                    artifact_sha256=hashlib.sha256(report.encode()).hexdigest()))
        manifest = {"capability_policy": {
            "sample": {"declared": {"math_checks": False}, "conditions": {
                "baseline": {"math_checks": False}, "pipeline": {"math_checks": False}}},
            "sample-with-tools": {"declared": {"math_checks": True}, "conditions": {
                "baseline": {"math_checks": False}, "pipeline": {"math_checks": True}}}}}
        summary = compare_trials(trials, grades, conditions=("baseline", "pipeline"),
            required_replicates=1, case_ids=set(case_ids), deep_case_ids=set(case_ids),
            comparison_condition="pipeline", manifest=manifest)
        self.assertEqual(summary["scheduled_pair_count"], 2)
        self.assertEqual(summary["expected_pair_count"], 1)
        self.assertEqual(summary["assessable_pair_count"], 1)
        self.assertEqual(summary["capability_mismatch_pair_count"], 1)
        self.assertEqual(summary["equal_input_matched_pair_count"], 1)
        self.assertEqual(summary["mean_paired_score_delta"], 0)
        self.assertEqual(summary["pairwise_quality"][0]["equal_input_pairs"], 1)
        self.assertEqual(summary["median_latency_ratio_pipeline_over_baseline"], 1)

    def test_extra_trials_outside_the_manifest_invalidate_comparison(self) -> None:
        trials = [_trial("baseline", report="one"), _trial("pipeline", report="two"),
                  _trial("pipeline", report="extra") | {"replicate": 2}]
        result = compare_trials(trials, [_grade("baseline", report="one"), _grade("pipeline", report="two")],
            required_replicates=1, case_ids={"sample"}, deep_case_ids={"sample"})
        self.assertEqual(result["comparison_status"], "incomplete")
        self.assertTrue(any("unexpected" in error for error in result["integrity_errors"]))

    def test_malformed_grade_is_incomplete_without_crashing_aggregation(self) -> None:
        trials = [_trial("baseline", report="one"), _trial("pipeline", report="two")]
        grade = _grade("pipeline", report="two") | {"dimensions": None, "critical_failures": None}
        result = compare_trials(trials, [_grade("baseline", report="one"), grade],
            required_replicates=1, case_ids={"sample"}, deep_case_ids={"sample"})
        self.assertEqual(result["comparison_status"], "incomplete")
        self.assertFalse(result["quality_gain_demonstrated"])
        self.assertFalse(result["efficiency_gate_passed"])

    def test_manifest_is_immutable_and_alternates_condition_order(self) -> None:
        cases, cases_hash, rubric_hash = load_cases(CASES)
        manifest = make_manifest(cases=cases, cases_hash=cases_hash,
            rubric_hash=rubric_hash, model="gpt-test", effort="high", git_sha="abc",
            max_provider_calls=240, max_wall_seconds=7200)
        self.assertEqual(len(manifest["ordering"]), 9)
        self.assertNotEqual(manifest["ordering"][0]["conditions"],
                            manifest["ordering"][1]["conditions"])
        validate_resume(manifest, dict(manifest))
        changed = dict(manifest) | {"model": "different"}
        with self.assertRaises(ValidationError):
            validate_resume(manifest, changed)

    def test_pair_check_receipt_is_shared_input_and_not_a_worker_tool_result(self) -> None:
        case = _perfect_case()
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
        case = _perfect_case()
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
        case = _perfect_case()
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
        case = _perfect_case()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = make_manifest(cases=[case], cases_hash="a" * 64,
                rubric_hash="b" * 64, model="gpt-test", effort="medium", git_sha="abc",
                max_provider_calls=27, max_wall_seconds=7200)
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
            self.assertEqual(outcome["provider_calls_reserved"], 27)
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
