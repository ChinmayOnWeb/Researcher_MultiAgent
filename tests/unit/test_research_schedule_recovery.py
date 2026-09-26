"""Task 5 regressions for immutable schedules and append-only recovery."""

import tempfile
from pathlib import Path
import unittest

from mathresearch.contracts.validation import ValidationError
from mathresearch.research.evaluation import (
    EvaluationStore, load_cases, make_manifest, make_trial, run_paired_trials,
)


ROOT = Path(__file__).resolve().parents[2]


class ScheduleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.cases_hash, self.rubric_hash = load_cases(ROOT / "evals/research-quality")
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT.parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "run"

    def manifest(self, *, conditions=("baseline", "pipeline"), calls=240, replicates=1):
        return make_manifest(cases=self.cases, cases_hash=self.cases_hash,
            rubric_hash=self.rubric_hash, model="gpt-5.6-terra", effort="medium",
            git_sha="fixture", max_provider_calls=calls, max_wall_seconds=7200,
            conditions=conditions, replicates=replicates)

    def test_schedule_uses_full_corpus_order_when_selecting_one_case(self):
        full = self.manifest()
        selected = self.cases[1]
        one_case_schedule = [row for row in full["ordering"] if row["case_id"] == selected["id"]]
        self.assertEqual(one_case_schedule[0]["conditions"],
            full["ordering"][len([row for row in full["ordering"]
                                  if row["case_position"] < 1])]["conditions"])
        self.assertEqual(full["case_ids"], [case["id"] for case in self.cases])
        self.assertEqual(full["ordering"][0]["conditions"][0],
            full["ordering"][1]["conditions"][1])

    def test_ten_case_one_replicate_schedule_has_five_starts_per_condition(self):
        cases = [dict(self.cases[index % len(self.cases)], id=f"case-{index:02d}")
                 for index in range(10)]
        manifest = make_manifest(cases=cases, cases_hash="a" * 64, rubric_hash="b" * 64,
            model="gpt-5.6-terra", effort="medium", git_sha="fixture",
            max_provider_calls=20, max_wall_seconds=7200, replicates=1)
        starts = [pair["conditions"][0] for pair in manifest["ordering"]]
        self.assertEqual(starts.count("baseline"), 5)
        self.assertEqual(starts.count("pipeline"), 5)

    def test_selected_single_condition_can_have_one_call_cap(self):
        manifest = self.manifest(conditions=("baseline",), calls=1)
        store = EvaluationStore(self.out, manifest)
        result = run_paired_trials(self.cases, store, selected_case_ids={self.cases[0]["id"]},
            selected_conditions={"baseline"},
            trial_runner=lambda *args: {"status": "complete", "provider_calls": 1, "report": "ok"})
        self.assertIsNone(result["stopped_reason"])
        self.assertEqual(result["provider_calls_reserved"], 1)

    def test_schema_failure_is_recorded_and_partner_still_runs(self):
        manifest = self.manifest(conditions=("baseline", "pipeline"), calls=240)
        store = EvaluationStore(self.out, manifest)
        first_case = self.cases[0]
        calls = []

        def runner(case, condition, *args):
            calls.append(condition)
            if condition == manifest["ordering"][0]["conditions"][0]:
                return {"status": "failed", "provider_calls": 1,
                        "error": "structural validation failed"}
            return {"status": "complete", "provider_calls": 1, "report": "ok"}

        result = run_paired_trials(self.cases, store,
            selected_case_ids={first_case["id"]}, trial_runner=runner)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(store.trial_records()), 2)
        self.assertIsNone(result["stopped_reason"])

    def test_recovery_is_appended_and_does_not_replace_original(self):
        case = self.cases[0]
        store = EvaluationStore(self.out, self.manifest(conditions=("baseline",), calls=10))
        store.record_intent(case_id=case["id"], replicate=1, condition="baseline",
            source_hash="same", reserve_calls=1)
        original = store._trial_path(case["id"], 1, "baseline").read_bytes()
        recovery = store.append_recovery(case_id=case["id"], replicate=1,
            condition="baseline", source_hash="same", reserve_calls=1)
        result = make_trial(case_id=case["id"], replicate=1, condition="baseline",
            status="complete", report="recovered", provider_calls=1, wall_seconds=1,
            cost_usd=None, source_hash="same")
        store.record_recovery_result(recovery["recovery_id"], result)
        self.assertEqual(store._trial_path(case["id"], 1, "baseline").read_bytes(), original)
        self.assertEqual(len(store.recovery_records()), 1)
        self.assertEqual(store.recovery_records()[0]["parent_trial_id"],
            f"{case['id']}/1/baseline")

    def test_recovery_requires_original_trial(self):
        store = EvaluationStore(self.out, self.manifest(conditions=("baseline",), calls=10))
        with self.assertRaisesRegex(ValidationError, "original trial must exist"):
            store.append_recovery(case_id=self.cases[0]["id"], replicate=1,
                condition="baseline", source_hash="same")


if __name__ == "__main__":
    unittest.main()
