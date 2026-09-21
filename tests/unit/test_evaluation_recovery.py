"""Offline regressions for the interrupted smoke and its budget guardrails."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mathresearch.adapters.base import WorkerOutput
from mathresearch.contracts.validation import ValidationError
from mathresearch.research.cli import _run_evaluation_trial, main
from mathresearch.research.evaluation import EvaluationStore, load_cases, make_manifest, run_paired_trials


class EvaluationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        cases, cases_hash, rubric_hash = load_cases(Path(__file__).resolve().parents[2] / "evals/research-quality")
        self.case = next(case for case in cases if case["id"] == "perfect-six")
        self.manifest = make_manifest(cases=[self.case], cases_hash=cases_hash,
            rubric_hash=rubric_hash, model="gpt-test", effort="high", git_sha="fixture",
            max_provider_calls=10, max_wall_seconds=100, replicates=1)
        self.store = EvaluationStore(self.root, self.manifest)
        self.now = 0.0

    def run_trials(self, runner, checkpoint=lambda *args: 49):
        return run_paired_trials([self.case], self.store, trial_runner=runner,
            usage_checkpoint=checkpoint, monotonic=lambda: self.now)

    def test_first_failure_stops_and_resume_does_not_bypass_it(self):
        runner = Mock(return_value={"status": "failed", "provider_calls": 0, "error": "permission denied"})
        result = self.run_trials(runner)
        self.assertEqual(result["stopped_reason"], "trial_failed")
        self.assertEqual(runner.call_count, 1)
        checkpoint = Mock(return_value=49)
        again = self.run_trials(runner, checkpoint)
        self.assertEqual(again["stopped_reason"], "previous_trial_failed_or_unresolved")
        checkpoint.assert_not_called()
        self.assertEqual(runner.call_count, 1)

    def test_unclear_result_stops_instead_of_spending_on_next_condition(self):
        runner = Mock(side_effect=RuntimeError("connection lost"))
        result = self.run_trials(runner)
        self.assertEqual(result["stopped_reason"], "trial_ambiguous")
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(self.store.trial_records()[0]["status"], "ambiguous")

    def test_interrupt_during_trial_saves_ambiguity_elapsed_and_stop_reason(self):
        def interrupted(*args):
            self.now += 7
            raise KeyboardInterrupt
        result = self.run_trials(interrupted)
        self.assertEqual(result["stopped_reason"], "user_cancelled")
        self.assertEqual(result["wall_seconds_observed"], 7)
        self.assertEqual(self.store.trial_records()[0]["status"], "ambiguous")
        self.assertEqual(json.loads((self.root / "execution.json").read_text())["stopped_reason"], "user_cancelled")

    def test_interrupt_at_usage_prompt_does_not_charge_human_wait_or_launch(self):
        def interrupted(*args):
            self.now += 2000
            raise KeyboardInterrupt
        runner = Mock()
        result = self.run_trials(runner, interrupted)
        self.assertEqual(result["stopped_reason"], "user_cancelled")
        self.assertEqual(result["wall_seconds_observed"], 0)
        runner.assert_not_called()

    def test_human_wait_is_excluded_from_active_wall_cap(self):
        def checkpoint(*args):
            self.now += 2000
            return 49
        def runner(*args):
            self.now += 2
            return {"status": "complete", "provider_calls": 1, "report": "fixture"}
        result = self.run_trials(runner, checkpoint)
        self.assertIsNone(result["stopped_reason"])
        self.assertEqual(len(result["trial_conditions_recorded"]), 2)
        self.assertEqual(result["wall_seconds_observed"], 4)

    def test_deadline_expiring_during_intent_write_prevents_launch(self):
        record = self.store.record_intent
        def slow_intent(**kwargs):
            record(**kwargs)
            self.now += 101
        runner = Mock()
        with patch.object(self.store, "record_intent", side_effect=slow_intent):
            result = self.run_trials(runner)
        runner.assert_not_called()
        self.assertEqual(result["stopped_reason"], "wall_time_cap_reached")
        self.assertEqual(self.store.trial_records()[0]["provider_calls"], 0)

    def test_zero_quota_and_quota_reset_cannot_create_more_allowance(self):
        args = {"case_id": "perfect-six", "replicate": 1, "condition": "pipeline"}
        self.assertFalse(self.store.record_usage_check(observed_remaining_percent=0, **args))
        with self.assertRaisesRegex(ValidationError, "increased or reset"):
            self.store.record_usage_check(observed_remaining_percent=100, **args)

    def test_saved_baseline_survives_reopening_store(self):
        args = {"case_id": "perfect-six", "replicate": 1, "condition": "pipeline"}
        self.assertTrue(self.store.record_usage_check(observed_remaining_percent=49, **args))
        reopened = EvaluationStore(self.root, self.manifest)
        self.assertFalse(reopened.record_usage_check(observed_remaining_percent=39, **args))

    def test_finalization_uses_manifest_and_rejects_conflicting_count(self):
        result = self.store.finalize([], deep_case_ids=set())
        self.assertEqual(len(result["missing_trials"]), 2)
        with self.assertRaisesRegex(ValidationError, "immutable manifest"):
            self.store.finalize([], deep_case_ids=set(), required_replicates=3)

    def test_baseline_failure_preserves_exit_code_and_raw_diagnostics(self):
        output = WorkerOutput("failed", 7, b"stdout detail", b"stderr detail", None, "provider exited unsuccessfully")
        with patch("mathresearch.research.cli.create_research_provider", return_value=object()), \
             patch("mathresearch.research.cli.execute_worker", return_value=output):
            result = _run_evaluation_trial(self.case, "baseline", {"source_inputs": [], "replicate": 1},
                self.root, 90, self.manifest)
        self.assertEqual(result["provider_exit_code"], 7)
        self.assertEqual((self.root / "stderr.log").read_bytes(), b"stderr detail")
        self.assertEqual((self.root / "stdout.bin").read_bytes(), b"stdout detail")
        self.assertEqual(json.loads((self.root / "provider-result.json").read_text())["outcome"], "failed")

    def test_pipeline_failure_exposes_local_error(self):
        snapshot = SimpleNamespace(status="incomplete", reason="action_failed", model_calls_used=1,
            actions={"a1": {"kind": "worker"}}, action_telemetry={"a1": {}},
            outcomes={"a1": {"error": "Access denied before provider launch"}})
        with patch("mathresearch.research.cli.initialize"), \
             patch("mathresearch.research.cli.run_research", return_value=snapshot):
            result = _run_evaluation_trial(self.case, "pipeline", {"source_inputs": [], "replicate": 1},
                self.root, 90, self.manifest)
        self.assertIn("Access denied", result["error"])

    def test_pipeline_trial_uses_trial_local_worker_temp(self):
        snapshot = SimpleNamespace(status="complete", reason=None, model_calls_used=1,
            actions={}, action_telemetry={}, outcomes={})
        with patch("mathresearch.research.cli.initialize"), \
             patch("mathresearch.research.cli.run_research", return_value=snapshot) as run:
            _run_evaluation_trial(self.case, "pipeline", {"source_inputs": [], "replicate": 1},
                self.root, 90, self.manifest)
        self.assertEqual(run.call_args.kwargs["scratch_parent"], self.root / "worker-tmp")

    def test_cli_reports_failed_smoke_with_nonzero_exit(self):
        cases = Path(__file__).resolve().parents[2] / "evals/research-quality"
        with patch("mathresearch.research.cli._prompt_session_usage", return_value=49), \
             patch("mathresearch.research.cli._run_evaluation_trial", return_value={
                 "status": "failed", "provider_calls": 0, "error": "fixture failure"}), \
             patch("mathresearch.research.cli._emit"):
            code = main(["evaluate", "--cases", str(cases), "--out-dir", str(self.root / "cli"),
                "--model", "gpt-test", "--effort", "high", "--case-id", "perfect-six", "--replicates", "1",
                "--live", "--max-provider-calls", "10", "--max-wall-seconds", "100",
                "--max-session-usage-percent", "10", "--json"])
        self.assertEqual(code, 11)
