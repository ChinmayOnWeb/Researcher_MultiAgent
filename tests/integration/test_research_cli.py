"""Fresh-process tests for the version-three research CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

from mathresearch.contracts.research_request import ResearchRequest
from mathresearch.research.engine import run_research
from tests.unit.test_research_engine import ScriptedAdapter, scripted_result

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"


class ResearchCliIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PROJECT_ROOT / f".research-cli-test-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.run_dir = self.root / "run"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, *arguments: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ | {
            "PYTHONPATH": os.pathsep.join((str(SOURCE_ROOT), str(PROJECT_ROOT))),
        }
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "mathresearch", "research", *arguments],
            cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, check=False,
        )

    def test_flag_init_preserves_exact_question_and_goal(self) -> None:
        question = 'Are there any odd numbers that are "perfect"?\nShow the uncertainty.'
        goal = "Investigate the evidence and useful next work."
        result = self._run(
            "init", "--question", question, "--objective", "investigate", "--mode", "deep",
            "--run-id", "odd-perfect-cli", "--run-dir", str(self.run_dir), "--model", "gpt-test",
            "--goal", goal, "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        request = json.loads((self.run_dir / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["question"], question)
        self.assertEqual(request["goal"], goal)
        self.assertEqual(request["provider"]["reasoning_effort"], "high")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {"run_status", "answer_status", "model_calls_used",
            "tool_calls_used", "report_path", "gate_id", "reason"})

    def test_missing_builder_choices_and_request_flag_conflicts_are_invalid(self) -> None:
        missing = self._run("init", "--question", "q", "--run-dir", str(self.run_dir), "--json")
        self.assertEqual(missing.returncode, 20)
        self.assertEqual(json.loads(missing.stderr)["run_status"], None)

        conflict = self._run("init", "--request", str(PROJECT_ROOT / "examples" / "quick-proof.json"),
            "--question", "q", "--run-dir", str(self.run_dir), "--json")
        self.assertEqual(conflict.returncode, 20)
        self.assertIn("not allowed with argument", json.loads(conflict.stderr)["reason"])

    def test_unauthorized_capability_request_is_rejected(self) -> None:
        request = {
            "schema_version": 3, "record_type": "research_request", "run_id": "bad-capability",
            "question": "q", "goal": None, "context": None, "constraints": [],
            "audience": "unspecified", "objective": "investigate", "mode": "quick",
            "stakes": "ordinary", "learning_mode": False,
            "provider": {"adapter": "codex", "model": "gpt-test", "reasoning_effort": "high"},
            "capabilities": {"fetch_sources": True, "math_checks": False},
            "budgets": {"max_model_calls": 1, "max_tool_calls": 0, "max_repairs": 0,
                "max_branches": 1, "max_wall_seconds": 180, "per_call_seconds": 180,
                "max_input_bytes": 131072}, "sources": [],
        }
        request_path = self.root / "unauthorized.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = self._run("init", "--request", str(request_path), "--run-dir", str(self.run_dir), "--json")
        self.assertEqual(result.returncode, 20)
        self.assertFalse(self.run_dir.exists())

    def _prepare_gate(self, *, objective: str = "investigate") -> tuple[Path, str, str]:
        question = "Keep this original question exactly."
        goal = "Investigate supplied evidence without rewriting the intent."
        created = self._run("init", "--question", question, "--objective", objective, "--mode", "deep",
            "--run-id", "gate-cli", "--run-dir", str(self.run_dir), "--model", "gpt-test",
            "--goal", goal, "--json")
        self.assertEqual(created.returncode, 0, created.stderr)
        payload = scripted_result("frame:")
        if objective == "prove":
            payload["task_type"] = "exploration"
        else:
            payload["missing_inputs"] = ["Supply a useful source excerpt."]
        stages: list[str] = []
        marker = self.root / "child-invocations.txt"

        def factory(request: ResearchRequest, *, recorded_config: dict[str, object] | None) -> ScriptedAdapter:
            return ScriptedAdapter(request, marker, stages, {"frame:": [payload]})

        waiting = run_research(self.run_dir, provider_factory=factory)
        self.assertEqual(waiting.status, "awaiting_human")
        return self.run_dir, question, goal

    def test_cancel_response_exits_21_without_resolving_codex(self) -> None:
        self._prepare_gate(objective="prove")
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        response_path = self.root / "cancel.json"
        response_path.write_text(json.dumps({"schema_version": 3, "record_type": "research_gate_response",
            "gate_id": state["pending_gate_id"], "response_id": "cancel-cli", "decision": "cancel",
            "text": None, "sources": []}), encoding="utf-8")
        empty_path = self.root / "empty-bin"
        empty_path.mkdir()

        result = self._run("respond", "--run-dir", str(self.run_dir), "--response", str(response_path), "--json",
                           extra_env={"PATH": str(empty_path)})

        self.assertEqual(result.returncode, 21, result.stderr)
        self.assertEqual(json.loads(result.stdout)["reason"], "user_cancelled")
        self.assertEqual(json.loads(result.stdout)["run_status"], "incomplete")

    def test_supply_response_preserves_request_and_adds_user_text_source(self) -> None:
        _, question, goal = self._prepare_gate()
        original_request = (self.run_dir / "request.json").read_bytes()
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        response_path = self.root / "supply.json"
        response_path.write_text(json.dumps({"schema_version": 3, "record_type": "research_gate_response",
            "gate_id": state["pending_gate_id"], "response_id": "supply-cli", "decision": "supply",
            "text": "A user supplied excerpt.", "sources": []}), encoding="utf-8")
        empty_path = self.root / "empty-bin"
        empty_path.mkdir()

        result = self._run("respond", "--run-dir", str(self.run_dir), "--response", str(response_path), "--json",
                           extra_env={"PATH": str(empty_path)})

        self.assertEqual(result.returncode, 11)
        self.assertEqual((self.run_dir / "request.json").read_bytes(), original_request)
        report = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn(question, report)
        self.assertIn(goal, report)
        self.assertIn("Origin: `user_text`", report)
        self.assertIn("User response g0001", report)

    def test_completed_run_status_and_run_do_not_need_codex_on_path(self) -> None:
        initialized = self._run("init", "--question", "A research question.", "--objective", "investigate",
            "--mode", "deep", "--run-id", "complete-cli", "--run-dir", str(self.run_dir), "--model", "gpt-test", "--json")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        stages: list[str] = []
        marker = self.root / "child-invocations.txt"
        from tests.unit.test_research_engine import ResearchEngineTests
        harness = ResearchEngineTests()
        factory, calls, _ = harness._factory(self.root, stages)
        final = run_research(self.run_dir, provider_factory=factory)
        self.assertEqual(final.status, "complete")
        self.assertEqual(calls, ["resolve"])
        empty_path = self.root / "empty-bin"
        empty_path.mkdir()

        result = self._run("run", "--run-dir", str(self.run_dir), "--json", extra_env={"PATH": str(empty_path)})
        status = self._run("status", "--run-dir", str(self.run_dir), "--json", extra_env={"PATH": str(empty_path)})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(result.stdout)["run_status"], "complete")
        self.assertEqual(json.loads(status.stdout)["report_path"], str((self.run_dir / "report.md").resolve()))
        self.assertEqual(len(stages), 5)
        self.assertTrue(marker.is_file())

    def test_modified_request_projection_is_reported_as_corrupt(self) -> None:
        initialized = self._run("init", "--question", "Original wording.", "--objective", "investigate",
            "--mode", "deep", "--run-id", "tamper-cli", "--run-dir", str(self.run_dir), "--model", "gpt-test", "--json")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        request_path = self.run_dir / "request.json"
        changed = json.loads(request_path.read_text(encoding="utf-8"))
        changed["question"] = "Changed after initialization."
        request_path.write_text(json.dumps(changed), encoding="utf-8")

        result = self._run("status", "--run-dir", str(self.run_dir), "--json")

        self.assertEqual(result.returncode, 23)
        self.assertIn("run_corrupt", json.loads(result.stderr)["reason"])

    def test_legacy_cli_still_parses(self) -> None:
        result = subprocess.run([sys.executable, "-m", "mathresearch", "--version"], cwd=PROJECT_ROOT,
            env=os.environ | {"PYTHONPATH": str(SOURCE_ROOT)}, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        help_result = self._run("--help")
        self.assertEqual(help_result.returncode, 0)

    def test_research_help_and_example_requests_parse(self) -> None:
        help_result = self._run("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("init", help_result.stdout)
        self.assertIn("respond", help_result.stdout)
        for index, name in enumerate(("research-odd-perfect.json", "research-odd-sums.json")):
            run_dir = self.root / f"example-{index}"
            result = self._run("init", "--request", str(PROJECT_ROOT / "examples" / name),
                "--run-dir", str(run_dir), "--json")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_offline_evaluation_initializes_manifest_without_provider_calls(self) -> None:
        output = self.root / "evaluation"
        result = self._run("evaluate", "--cases", str(PROJECT_ROOT / "evals" / "research-quality"),
            "--out-dir", str(output), "--model", "gpt-test", "--effort", "high", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["comparison_status"], "incomplete")
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["effort"], "high")
        comparison = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(comparison["actual_provider_calls"], 0)

    def test_evaluation_can_prepare_a_bounded_smoke_case_set(self) -> None:
        output = self.root / "smoke-evaluation"
        result = self._run("evaluate", "--cases", str(PROJECT_ROOT / "evals" / "research-quality"),
            "--out-dir", str(output), "--model", "gpt-test", "--effort", "high",
            "--case-id", "odd-sum", "--case-id", "bounded-search", "--case-id", "perfect-six",
            "--replicates", "1", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["case_ids"], ["odd-sum", "perfect-six", "bounded-search"])
        self.assertEqual(manifest["replicates"], 1)
        self.assertEqual(len(manifest["ordering"]), 3)
        comparison = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(len(comparison["missing_trials"]), 6)
        self.assertTrue(all(item[1] == 1 for item in comparison["missing_trials"]))

    def test_evaluation_rejects_unknown_smoke_case_without_creating_output(self) -> None:
        output = self.root / "invalid-smoke-evaluation"
        result = self._run("evaluate", "--cases", str(PROJECT_ROOT / "evals" / "research-quality"),
            "--out-dir", str(output), "--model", "gpt-test", "--effort", "high",
            "--case-id", "not-a-case", "--json")
        self.assertEqual(result.returncode, 20)
        self.assertIn("unknown case IDs", json.loads(result.stderr)["reason"])
        self.assertFalse(output.exists())

    def test_live_evaluation_requires_all_three_explicit_limits(self) -> None:
        result = self._run("evaluate", "--cases", str(PROJECT_ROOT / "evals" / "research-quality"),
            "--out-dir", str(self.root / "evaluation"), "--model", "gpt-test", "--effort", "high", "--live", "--json")
        self.assertEqual(result.returncode, 20)
        self.assertIn("--max-session-usage-percent", json.loads(result.stderr)["reason"])
        self.assertFalse((self.root / "evaluation").exists())


if __name__ == "__main__":
    unittest.main()
