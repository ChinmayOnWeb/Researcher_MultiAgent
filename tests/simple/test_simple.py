"""Focused product-contract tests; all providers are offline fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mathresearch.simple.evaluation import evaluate
from mathresearch.simple.models import Settings
from mathresearch.simple.parsing import parse_output
from mathresearch.simple.provider import CodexProvider, FakeProvider, Reply

ANSWER = b'{"answer":"A useful answer.","assumptions":[],"uncertainties":[]}'
CASE = {"id": "fixture", "question": "Find and justify the result.", "context": "Fixed evidence."}


class ParsingTests(unittest.TestCase):
    def test_valid_json(self):
        self.assertTrue(parse_output(ANSWER, "answer").protocol_valid)

    def test_fenced_json(self):
        self.assertTrue(parse_output(b'```json\n' + ANSWER + b'\n```', "answer").protocol_valid)

    def test_prose_around_one_object(self):
        self.assertTrue(parse_output(b'Here it is:\n' + ANSWER + b'\nDone.', "answer").protocol_valid)

    def test_multiple_competing_objects_are_rejected(self):
        result = parse_output(ANSWER + b'\n' + ANSWER, "answer")
        self.assertFalse(result.protocol_valid)
        self.assertIsNone(result.value)
        self.assertIn('A useful answer.', result.text)

    def test_malformed_outer_object_does_not_rescue_nested_object(self):
        result = parse_output(b'{"nested":' + ANSWER + b', broken', "answer")
        self.assertIsNotNone(result.parse_error)
        self.assertIsNone(result.value)

    def test_recoverable_answer_is_retained(self):
        result = parse_output(b'{"answer":"Keep this answer.","assumptions": [}', "answer")
        self.assertEqual(result.text, "Keep this answer.")
        self.assertFalse(result.protocol_valid)

    def test_schema_validity_is_not_mathematical_correctness(self):
        result = parse_output(ANSWER.replace(b'A useful answer.', b'1 + 1 = 3.'), "answer")
        self.assertTrue(result.protocol_valid)
        self.assertEqual(result.text, "1 + 1 = 3.")

    def test_envelope_failure_keeps_parsed_object_and_answer(self):
        result = parse_output(b'{"answer":"Readable."}', "answer")
        self.assertEqual(result.value, {"answer": "Readable."})
        self.assertIsNone(result.parse_error)
        self.assertIsNotNone(result.envelope_error)
        self.assertEqual(result.text, "Readable.")

    def test_ambiguous_transport_forms_are_not_silently_rewritten(self):
        for raw in (b'[' + ANSWER + b']', b'{"answer":"a","answer":"b"}',
                    b'{"answer":"a","score":NaN}'):
            with self.subTest(raw=raw):
                self.assertFalse(parse_output(raw, "answer").protocol_valid)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "experiment"
        self.provider = FakeProvider()
        self.comparison = evaluate([CASE], self.out, self.provider)

    def read(self, condition, stage=None, name="result.json"):
        path = self.out / "fixture" / condition
        if stage:
            path /= stage
        return json.loads((path / name).read_text(encoding="utf-8"))

    def inputs(self, condition, stage):
        text = (self.out / "fixture" / condition / stage / "prompt.txt").read_text(encoding="utf-8")
        return json.loads(text.split("\nInputs:\n", 1)[1])

    def test_single_completes(self):
        self.assertEqual(self.read("single")["status"], "complete")
        self.assertTrue(self.read("single")["answer"])

    def test_sequential_completes(self):
        result = self.read("sequential")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer_stage"], "revision")

    def test_pipeline_completes(self):
        result = self.read("pipeline")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer_stage"], "revision")

    def test_branch_a_sees_only_original_inputs(self):
        self.assertEqual(self.inputs("pipeline", "branch-a"),
                         {"question": CASE["question"], "context": CASE["context"]})

    def test_branch_b_sees_only_original_inputs(self):
        self.assertEqual(self.inputs("pipeline", "branch-b"),
                         {"question": CASE["question"], "context": CASE["context"]})

    def test_synthesis_sees_both(self):
        inputs = self.inputs("pipeline", "synthesis")
        self.assertEqual(inputs["attempt_a"], self.read("pipeline", "branch-a", "parsed.json"))
        self.assertEqual(inputs["attempt_b"], self.read("pipeline", "branch-b", "parsed.json"))

    def test_critique_sees_candidate(self):
        for condition, stage in (("sequential", "draft"), ("pipeline", "synthesis")):
            self.assertEqual(self.inputs(condition, "critique")["candidate"],
                             self.read(condition, stage, "parsed.json"))

    def test_revision_sees_candidate_and_critique(self):
        for condition, stage in (("sequential", "draft"), ("pipeline", "synthesis")):
            inputs = self.inputs(condition, "revision")
            self.assertEqual(inputs["critique"], self.read(condition, "critique", "parsed.json"))
            self.assertEqual(inputs["candidate"], self.read(condition, stage, "parsed.json"))

    def test_exact_call_counts_and_no_extra_stages(self):
        expected = {"single": ["answer"], "sequential": ["draft", "critique", "revision"],
                    "pipeline": ["branch-a", "branch-b", "synthesis", "critique", "revision"]}
        for condition, stages in expected.items():
            self.assertEqual(self.read(condition)["provider_calls"], len(stages))
            directory = self.out / "fixture" / condition
            self.assertEqual(sorted(path.name for path in directory.iterdir() if path.is_dir()), sorted(stages))
            metadata = [self.read(condition, stage, "metadata.json") for stage in stages]
            indices = [row["provider_call_index"] for row in metadata]
            self.assertEqual(indices, sorted(indices))
        self.assertEqual(len(self.provider.prompts), 9)

    def test_comparison_records_all_conditions_without_inventing_grades(self):
        saved = json.loads((self.out / "comparison.json").read_text())
        self.assertEqual(saved, self.comparison)
        self.assertEqual({row["condition"] for row in saved["conditions"]}, {"single", "sequential", "pipeline"})
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(saved["semantic_quality"]["status"], "ungraded")

    def test_full_experiment_order_is_persisted(self):
        cases = [CASE, {**CASE, "id": "second"}]
        out = self.root / "two-cases"
        result = evaluate(cases, out, FakeProvider(), seed=23)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["condition_order"], result["condition_order"])
        self.assertEqual(manifest["condition_order"],
                         [{"case_id": row["case_id"], "condition": row["condition"]} for row in result["conditions"]])
        self.assertEqual(len(manifest["condition_order"]), 6)

    def test_malformed_json_keeps_exact_raw_and_semantics_through_comparison(self):
        raw = b'{"answer":"Still useful.","assumptions": [}'
        # Every answer stage is malformed; critique remains a normal fixture.
        class BrokenAnswers(FakeProvider):
            def __call__(self, prompt, kind, settings, directory):
                normal = super().__call__(prompt, kind, settings, directory)
                return Reply(raw) if kind == "answer" else normal
        out = self.root / "malformed"
        result = evaluate([CASE], out, BrokenAnswers())
        self.assertEqual(result["provider_calls"], 9)
        self.assertEqual(result["status"], "complete")
        for condition in result["conditions"]:
            self.assertFalse(condition["protocol_valid"])
            self.assertTrue(condition["semantic_output_available"])
            self.assertEqual(condition["answer"], "Still useful.")
        stage = out / "fixture" / "pipeline" / "branch-a"
        self.assertEqual((stage / "raw.txt").read_bytes(), raw)
        self.assertFalse((stage / "parsed.json").exists())
        self.assertTrue(json.loads((stage / "metadata.json").read_text())["parse_error"])

    def test_provider_failure_is_separate_from_format_and_semantics(self):
        class FailedProvider:
            name = "failed-fixture"
            def __call__(self, *args):
                return Reply(ANSWER, returned=True, succeeded=False, error="provider failed")
        result = evaluate([CASE], self.root / "failure", FailedProvider())
        self.assertEqual(result["status"], "incomplete")
        for row in result["conditions"]:
            self.assertTrue(row["protocol_valid"])
            self.assertTrue(row["semantic_output_available"])
            self.assertEqual(row["provider_reliability"]["succeeded"], 0)

    def test_existing_directory_is_never_resumed_or_overwritten(self):
        original = (self.out / "comparison.json").read_bytes()
        with self.assertRaises(FileExistsError):
            evaluate([CASE], self.out, FakeProvider())
        self.assertEqual((self.out / "comparison.json").read_bytes(), original)

    def test_offline_cli_uses_no_old_engine_or_provider_launcher(self):
        code = '''
import importlib.abc, sys, runpy
class BlockOld(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("mathresearch.research", "mathresearch.contracts", "mathresearch.worker_process", "mathresearch.adapters", "mathresearch.structured_output")):
            raise AssertionError("forbidden dependency: " + fullname)
sys.meta_path.insert(0, BlockOld())
sys.argv = ["simple", "evaluate", "--question", "Offline question", "--out-dir", sys.argv[1]]
runpy.run_module("mathresearch.simple.cli", run_name="__main__")
'''
        out = self.root / "cli"
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
        completed = subprocess.run([sys.executable, "-c", code, str(out)], env=env,
                                   capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["provider_calls"], 9)
        self.assertTrue((out / "comparison.json").is_file())


class ProviderBridgeTests(unittest.TestCase):
    def test_bridge_preserves_raw_payload_and_does_not_use_adapter_json_parser(self):
        from mathresearch.adapters.base import WorkerOutput
        raw = b'{"answer":"Useful but broken",}'
        def worker(adapter, task, **kwargs):
            self.assertEqual(adapter.decode(b"diagnostics", raw), {})
            self.assertEqual(set(task.output_schema["properties"]), {"answer", "assumptions", "uncertainties"})
            self.assertEqual((adapter.model, adapter.reasoning_effort), ("gpt-5.6-terra", "medium"))
            return WorkerOutput("succeeded", 0, b"diagnostics", b"model: gpt-5.6-terra\r\nreasoning effort: medium\r\nuser\r\nmodel: injected\r\n", {}, None, raw_result=raw)
        with tempfile.TemporaryDirectory() as temp, patch("mathresearch.simple.provider.shutil.which", return_value="codex"), patch("mathresearch.worker_process.execute_worker", side_effect=worker):
            reply = CodexProvider()("prompt", "answer", Settings(), Path(temp))
        self.assertEqual(reply.raw, raw)
        self.assertTrue(reply.succeeded)
        self.assertEqual(reply.calls, 1)

    def test_bridge_records_model_mismatch_as_provider_failure(self):
        from mathresearch.adapters.base import WorkerOutput
        output = WorkerOutput("succeeded", 0, b"", b"model: different\nreasoning effort: medium\nuser\n", {}, None, raw_result=ANSWER)
        with tempfile.TemporaryDirectory() as temp, patch("mathresearch.simple.provider.shutil.which", return_value="codex"), patch("mathresearch.worker_process.execute_worker", return_value=output):
            reply = CodexProvider()("prompt", "answer", Settings(), Path(temp))
        self.assertTrue(reply.returned)
        self.assertFalse(reply.succeeded)
        self.assertTrue(parse_output(reply.raw, "answer").protocol_valid)


if __name__ == "__main__":
    unittest.main()
