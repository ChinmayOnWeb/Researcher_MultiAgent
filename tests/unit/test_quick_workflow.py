from pathlib import Path
from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch

from mathresearch.adapters.base import WorkerOutput
from mathresearch.quick_workflow import _schema, run_quick
from mathresearch.run_store import initialize_run, load_run_status, open_locked_run


def request_payload():
    return {"schema_version": 1, "record_type": "run_request", "run_id": "quick-flow", "question": "prove it", "actual_goal": None, "context": None, "constraints": [], "audience_level": "general", "mode": "quick", "stakes": "ordinary", "learning_mode": False, "capabilities": {}, "budgets": {"max_accepted_submissions": 4, "max_revision_cycles": 0, "elapsed_time_seconds": None}}


class StubAdapter:
    pass


class UnavailableAdapter:
    def preflight(self):
        raise OSError("provider is no longer installed")


class QuickWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        request = root / "request.json"; request.write_text(json.dumps(request_payload()), encoding="utf-8")
        self.run = root / "run"; initialize_run(request, self.run)
        self.outputs = {
            "frame": {"framed_question": "prove it", "success_criteria": ["proof"], "terms": [], "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"},
            "investigate": {"answer": "answer", "claims": [{"id": "c1", "statement": "claim", "basis": "derived", "support": "derivation"}], "alternatives": ["alt"], "limitations": []},
            "verify": {"checks": [{"claim_id": "c1", "verdict": "supported", "reasoning": "shown"}], "disposition": "pass", "limitations": []},
            "explain": {"summary": "supported", "explanation": "details", "conclusion": "supported", "limitations": []},
        }
    def tearDown(self): self.temp.cleanup()

    def test_provider_schemas_define_items_and_strict_nested_objects(self):
        """An array without items is rejected by Codex before a worker can return a result."""
        expected = {
            "frame": {"framed_question", "success_criteria", "terms", "assumptions", "missing_inputs", "stakes_assessment"},
            "investigate": {"answer", "claims", "alternatives", "limitations"},
            "verify": {"checks", "disposition", "limitations"},
            "explain": {"summary", "explanation", "conclusion", "limitations"},
        }
        for stage, fields in expected.items():
            schema = _schema(stage)
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), fields)
            self.assertEqual(set(schema["properties"]), fields)
            for field in fields:
                property_schema = schema["properties"][field]
                if property_schema.get("type") == "array":
                    self.assertIn("items", property_schema, f"{stage}.{field}")

        claim = _schema("investigate")["properties"]["claims"]["items"]
        self.assertEqual(claim["type"], "object")
        self.assertFalse(claim["additionalProperties"])
        self.assertEqual(set(claim["required"]), {"id", "statement", "basis", "support"})
        self.assertEqual(claim["properties"]["basis"]["enum"], ["supplied", "derived", "inferred", "unknown"])

        check = _schema("verify")["properties"]["checks"]["items"]
        self.assertEqual(check["type"], "object")
        self.assertFalse(check["additionalProperties"])
        self.assertEqual(set(check["required"]), {"claim_id", "verdict", "reasoning"})
        self.assertEqual(check["properties"]["verdict"]["enum"], ["supported", "unsupported", "contradicted"])

    def test_runs_fixed_graph_once_then_noops(self):
        calls=[]
        def worker(adapter, task, **kwargs):
            calls.append(task.stage); return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)
        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)
            self.assertEqual(state.status, "complete")
            self.assertEqual(calls, ["frame", "investigate", "verify", "explain"])
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)
        self.assertEqual(calls, ["frame", "investigate", "verify", "explain"])
        self.assertTrue((self.run / "report.md").is_file())
    def test_successful_unaccepted_stage_recovers_without_relaunch(self):
        calls=[]
        def worker(adapter, task, **kwargs):
            calls.append(task.stage); return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)
        # Simulate crash at Frame acceptance after durable outcome.
        import mathresearch.quick_workflow as flow
        original = flow._apply_stage_disposition
        def crash(locked, stage, result):
            if stage == "frame": raise RuntimeError("crash")
            return original(locked, stage, result)
        with patch("mathresearch.quick_workflow.execute_worker", worker), patch("mathresearch.quick_workflow._apply_stage_disposition", crash):
            with self.assertRaises(RuntimeError): run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)
        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)
        self.assertEqual(state.status, "complete")
        self.assertEqual(calls, ["frame", "investigate", "verify", "explain"])

    def test_accepted_stage_crash_resumes_at_the_next_stage_without_relaunch(self):
        """A crash after durable acceptance must not repeat that accepted stage."""
        calls = []

        def worker(adapter, task, **kwargs):
            calls.append(task.stage)
            return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)

        import mathresearch.quick_workflow as flow
        original = flow._append

        def crash_after_frame_acceptance(locked, kind, body):
            state = original(locked, kind, body)
            if kind == "quick_stage_accepted" and body["stage"] == "frame":
                raise RuntimeError("acceptance crash")
            return state

        with patch("mathresearch.quick_workflow.execute_worker", worker), patch("mathresearch.quick_workflow._append", crash_after_frame_acceptance):
            with self.assertRaisesRegex(RuntimeError, "acceptance crash"):
                run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "complete")
        self.assertEqual(calls, ["frame", "investigate", "verify", "explain"])

    def test_completed_run_returns_state_without_rechecking_provider_availability(self):
        """A durable completion is a no-op even after its provider disappears."""
        def worker(adapter, task, **kwargs):
            return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)

        with patch("mathresearch.quick_workflow.execute_worker", worker):
            run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        state = run_quick(
            self.run,
            UnavailableAdapter(),
            adapter_id="stub",
            executable=Path("stub"),
            model=None,
        )

        self.assertEqual(state.status, "complete")

    def test_intent_without_finished_outcome_blocks_without_relaunch(self):
        """An ambiguous launch intent is terminal and is never replaced automatically."""
        calls = []

        def crash_after_intent(adapter, stage, packet, timeout_seconds):
            calls.append(stage)
            raise RuntimeError("simulated process crash")

        with patch("mathresearch.quick_workflow._run_worker", crash_after_intent):
            with self.assertRaisesRegex(RuntimeError, "simulated process crash"):
                run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "blocked")
        self.assertIn("interrupted frame attempt", state.reason)
        self.assertEqual(calls, ["frame"])

    def test_capture_publication_crash_leaves_an_intent_that_cannot_be_relaunched(self):
        """A crash while saving diagnostics preserves the conservative interrupted state."""
        def worker(adapter, task, **kwargs):
            return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)

        with patch("mathresearch.quick_workflow.execute_worker", worker), patch("mathresearch.quick_workflow.LockedRun.write_capture", side_effect=RuntimeError("capture crash")):
            with self.assertRaisesRegex(RuntimeError, "capture crash"):
                run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "blocked")
        self.assertIn("interrupted frame attempt", state.reason)

    def test_timed_out_worker_blocks_and_keeps_diagnostic_captures(self):
        """A failed worker stops the graph after recording its outcome and captures."""
        def timed_out(adapter, task, **kwargs):
            return WorkerOutput("timed_out", None, b"partial output", b"timeout", None, "timeout")

        with patch("mathresearch.quick_workflow.execute_worker", timed_out):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        attempt = self.run / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"
        self.assertEqual(state.status, "blocked")
        self.assertIn("timed_out", state.reason)
        self.assertEqual((attempt / "stdout.bin").read_bytes(), b"partial output")
        self.assertEqual((attempt / "stderr.log").read_bytes(), b"timeout")

    def test_frame_missing_inputs_stops_before_investigation(self):
        """The coordinator does not let downstream stages bypass Frame's human-input gate."""
        outputs = deepcopy(self.outputs)
        outputs["frame"]["missing_inputs"] = ["domain"]
        calls = []

        def worker(adapter, task, **kwargs):
            calls.append(task.stage)
            return WorkerOutput("succeeded", 0, b"out", b"", outputs[task.stage], None)

        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "blocked")
        self.assertEqual(calls, ["frame"])

    def test_failed_verification_stops_before_explanation(self):
        """A failed verification is not converted into a report by Explain."""
        outputs = deepcopy(self.outputs)
        outputs["verify"]["checks"][0]["verdict"] = "contradicted"
        outputs["verify"]["disposition"] = "fail"
        calls = []

        def worker(adapter, task, **kwargs):
            calls.append(task.stage)
            return WorkerOutput("succeeded", 0, b"out", b"", outputs[task.stage], None)

        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "blocked")
        self.assertEqual(calls, ["frame", "investigate", "verify"])

    def test_inconclusive_verification_allows_only_an_inconclusive_report(self):
        """An eligible inconclusive check reaches Explain and remains visible in its report."""
        outputs = deepcopy(self.outputs)
        outputs["verify"]["disposition"] = "inconclusive"
        outputs["explain"]["conclusion"] = "inconclusive"

        def worker(adapter, task, **kwargs):
            return WorkerOutput("succeeded", 0, b"out", b"", outputs[task.stage], None)

        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "complete")
        self.assertIn("Final conclusion: **inconclusive**", (self.run / "report.md").read_text(encoding="utf-8"))

    def test_accepted_submission_budget_stops_before_the_fourth_stage(self):
        """The fixed graph cannot complete when the durable accepted budget is below four."""
        payload = request_payload()
        payload["budgets"]["max_accepted_submissions"] = 3
        request = self.run.parent / "budget-request.json"
        request.write_text(json.dumps(payload), encoding="utf-8")
        budget_run = self.run.parent / "budget-run"
        initialize_run(request, budget_run)
        calls = []

        def worker(adapter, task, **kwargs):
            calls.append(task.stage)
            return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)

        with patch("mathresearch.quick_workflow.execute_worker", worker):
            state = run_quick(budget_run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "budget_exhausted")
        self.assertEqual(calls, ["frame", "investigate", "verify"])

    def test_elapsed_budget_stops_before_any_worker_launch(self):
        """A zero remaining deadline is recorded before the coordinator creates an intent."""
        with patch("mathresearch.quick_workflow._remaining_seconds", return_value=0), patch("mathresearch.quick_workflow.execute_worker") as worker:
            state = run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        self.assertEqual(state.status, "budget_exhausted")
        worker.assert_not_called()

    def test_completed_event_repairs_report_after_report_projection_crash(self):
        """A committed completion can rebuild the report after a materialization interruption."""
        def worker(adapter, task, **kwargs):
            return WorkerOutput("succeeded", 0, b"out", b"", self.outputs[task.stage], None)

        import mathresearch.run_store as store
        original = store._repair_raw_bytes_projection

        def crash_only_for_report(path, expected, run_dir):
            if path.name == "report.md":
                raise RuntimeError("report projection crash")
            return original(path, expected, run_dir)

        with patch("mathresearch.quick_workflow.execute_worker", worker), patch("mathresearch.run_store._repair_raw_bytes_projection", crash_only_for_report):
            with self.assertRaisesRegex(RuntimeError, "report projection crash"):
                run_quick(self.run, StubAdapter(), adapter_id="stub", executable=Path("stub"), model=None)

        state = load_run_status(self.run)

        self.assertEqual(state.status, "complete")
        self.assertTrue((self.run / "report.md").is_file())
