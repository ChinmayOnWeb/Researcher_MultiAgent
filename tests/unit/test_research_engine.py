from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from mathresearch.adapters.base import LaunchSpec, WorkerInput, WorkerOutput
from mathresearch.contracts.research_request import ResearchRequest
from mathresearch.research.engine import answer_research_gate, initialize, run_research
from mathresearch.research.store import load_research_status
from mathresearch.research.reporting import render_report, render_log
from tests.unit.test_research_contracts import valid_request_payload


def draft(answer: str, approach_id: str) -> dict[str, Any]:
    return {"answer": answer, "question_status": "answered", "claims": [{
        "id": "claim-one", "statement": "The candidate follows from its stated step.",
        "critical": True, "kind": "deduction", "citations": [], "step_ids": ["step-one"],
        "tool_ids": [], "depends_on": [], "basis": "derivation", "basis_reference": "The stated rule",
        "scope_step_ids": [], "discharged_by_step_ids": []}],
        "proof_steps": [{"id": "step-one", "statement": "Apply the stated rule.",
            "justification": "The rule applies on the declared domain.", "depends_on": [], "citations": []}],
        "approaches": [{"id": approach_id, "description": f"Route {approach_id}",
            "outcome": "candidate", "reason": "Direct derivation."}],
        "open_questions": [], "tool_requests": [], "change_log": []}


def scripted_result(stage: str) -> dict[str, Any]:
    role, _, branch = stage.partition(":")
    if role == "frame":
        return {"task_type": "exploration", "deliverables": ["derive a bounded result"],
            "subquestions": ["what follows from the assumptions?"], "missing_inputs": [],
            "proposed_checks": [], "source_needs": []}
    if role == "answer": return draft("Direct candidate proof.", "direct-route")
    if role == "branch": return draft(f"Independent candidate {branch}.", f"approach-{branch}")
    if role == "synthesize": return draft("Combined candidate argument.", "combined-route")
    if role == "revise":
        revised = draft("Revised candidate argument.", "repaired-route")
        revised["change_log"] = ["addressed the audit objection"]
        return revised
    if role == "audit":
        return {"checks": [{"claim_id": "claim-one", "verdict": "supported",
            "reasoning": "The encoded step supports the scoped claim.", "checked_step_ids": ["step-one"],
            "basis_verdict": "applicable", "basis_reasoning": "The stated rule applies."}],
            "challenges": [{"claim_id": "claim-one", "attack": "Try a counterexample.",
                "result": "No counterexample was found within this challenge.",
                "outcome": "survives", "tool_ids": []}], "missing_evidence": [],
            "tool_requests": [], "recommended_action": "finish"}
    raise AssertionError(stage)


class ScriptedAdapter:
    """Provider test double whose payload crosses the real bounded child runner."""

    def __init__(self, request: ResearchRequest, marker_file: Path, invocations: list[str],
                 outputs: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.request = request
        self.marker_file = marker_file
        self.invocations = invocations
        self.outputs = outputs if outputs is not None else {}

    def preflight(self) -> None:
        return None

    def configuration_receipt(self) -> dict[str, Any]:
        return {"executable": sys.executable, "version": "scripted-child-v1",
            "model_requested": self.request.provider["model"],
            "effort_requested": self.request.provider["reasoning_effort"],
            "control_argv": ["test-scripted-child"], "prompt_version": "research-v1"}

    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec:
        self.invocations.append(task.stage)
        queue = self.outputs.get(task.stage, [])
        result = queue.pop(0) if queue else scripted_result(task.stage)
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        marker = repr(str(self.marker_file))
        marker_value = repr(task.stage)
        script = ("import os,sys; "
            f"open({marker},'a',encoding='utf-8').write({marker_value}+' '+str(os.getpid())+'\\n'); "
            "sys.stdin.buffer.read(); "
            "sys.stderr.write('model: gpt-test\\nreasoning effort: high\\nuser\\n'); "
            f"sys.stdout.write({payload!r})")
        return LaunchSpec((sys.executable, "-c", script), task.prompt.encode("utf-8"), scratch, None)

    def decode(self, stdout: bytes, result_bytes: bytes | None) -> Mapping[str, Any]:
        if result_bytes is not None: raise ValueError("unexpected result file")
        return json.loads(stdout.decode("utf-8"))


class ResearchEngineTests(unittest.TestCase):
    def _run(self, root: Path, *, mode: str = "deep", objective: str = "investigate",
             configure: Any = None) -> Path:
        payload = valid_request_payload()
        payload["run_id"] = "engine-run"
        payload["mode"] = mode
        payload["objective"] = objective
        payload["provider"] = {"adapter": "codex", "model": "gpt-test", "reasoning_effort": "high"}
        if configure is not None: configure(payload)
        request_path = root / "request.json"
        request_path.write_text(json.dumps(payload), encoding="utf-8")
        run_dir = root / "run"
        initialize(request_path, run_dir)
        return run_dir

    def _factory(self, root: Path, stages: list[str], calls: list[str] | None = None):
        calls = calls if calls is not None else []
        marker = root / "child-invocations.txt"
        def factory(request: ResearchRequest, *, recorded_config: Mapping[str, Any] | None):
            calls.append("resolve")
            return ScriptedAdapter(request, marker, stages)
        return factory, calls, marker

    def test_full_deep_run_uses_real_child_runner_and_recovers_exact_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            stages: list[str] = []; factory, resolved, marker = self._factory(root, stages)
            final = run_research(run_dir, provider_factory=factory,
                                 scratch_parent=root / "worker-scratch")
            self.assertEqual(final.status, "complete", final.reason)
            self.assertEqual(stages, ["frame:", "branch:a", "branch:b", "synthesize:", "audit:"])
            self.assertEqual(len(set(marker.read_text(encoding="utf-8").splitlines())), 5)
            self.assertEqual(resolved, ["resolve"])
            self.assertEqual(final.model_calls_used, 5)
            self.assertEqual([a["role"] for a in final.actions.values()],
                             ["frame", "branch", "branch", "synthesize", "audit"])
            report = (run_dir / "report.md").read_text(encoding="utf-8")
            log = (run_dir / "research-log.md").read_text(encoding="utf-8")
            self.assertEqual(report, render_report(final))
            self.assertEqual(log, render_log(final))
            reopened = load_research_status(run_dir)
            self.assertEqual(reopened.status, "complete")
            self.assertEqual((run_dir / "report.md").read_bytes(), report.encode("utf-8"))
            again = run_research(run_dir, provider_factory=lambda request: self.fail("terminal resume resolved provider"))
            self.assertEqual(again.sequence, reopened.sequence)
            self.assertEqual(stages, ["frame:", "branch:a", "branch:b", "synthesize:", "audit:"])

    def test_adaptive_policy_uses_only_draft_and_audit_when_obligations_are_met(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            def configure(payload: dict[str, Any]) -> None:
                payload["schema_version"] = 4
                payload["execution_policy"] = "adaptive"
            run_dir = self._run(root, configure=configure)
            stages: list[str] = []
            factory, _, _ = self._factory(root, stages)
            def fake_worker(adapter, task, **kwargs):
                stages.append(task.stage)
                payload = scripted_result(task.stage)
                return WorkerOutput("succeeded", 0,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    b"model: gpt-test\nreasoning effort: high\n", payload, None)
            with patch("mathresearch.research.engine.execute_worker", side_effect=fake_worker):
                final = run_research(run_dir, provider_factory=factory,
                                     scratch_parent=root / "worker-scratch")
            self.assertEqual(final.status, "complete", final.reason)
            self.assertEqual(stages, ["answer:", "audit:"])
            self.assertEqual(final.model_calls_used, 2)
            self.assertEqual(final.final_assessment["answer_status"], "supported_within_scope")

    def test_real_polynomial_receipt_is_in_draft_and_audit_evidence_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def configure(payload: dict[str, Any]) -> None:
                payload["capabilities"]["math_checks"] = True
            run_dir = self._run(root, configure=configure)
            frame = scripted_result("frame:")
            frame["proposed_checks"] = [{"id": "identity-check", "operation": "check_polynomial",
                "arguments": {"lhs": [2, 3, 1], "rhs": [2, 3, 1], "lo": -10, "hi": 10}}]
            def checked_draft(answer: str, approach: str) -> dict[str, Any]:
                result = draft(answer, approach)
                result["claims"][0].update({"statement": "The encoded polynomials are equal.",
                    "tool_ids": ["a0002"]})
                result["proof_steps"][0].update({"statement": "Compare the encoded coefficients.",
                    "justification": "The deterministic receipt confirms equality."})
                return result
            audit = scripted_result("audit:")
            audit["checks"][0].update({"reasoning": "The polynomial identity receipt agrees with the claim."})
            audit["challenges"][0].update({"tool_ids": ["a0002"]})
            outputs = {"frame:": [frame], "branch:a": [checked_draft("Candidate A.", "route-a")],
                "branch:b": [checked_draft("Candidate B.", "route-b")],
                "synthesize:": [checked_draft("Combined identity proof.", "combined")],
                "audit:": [audit]}
            stages: list[str] = []
            marker = root / "child-invocations.txt"
            factory = lambda request, recorded_config=None: ScriptedAdapter(
                request, marker, stages, outputs)
            with patch.dict(os.environ, {"PYTHONPATH": str(Path("src").resolve())}):
                final = run_research(run_dir, provider_factory=factory,
                                     scratch_parent=root / "worker-scratch")
            self.assertEqual(final.status, "complete", final.reason)
            self.assertTrue(any(action.get("kind") == "tool" for action in final.actions.values()))
            draft_action = next(action for action in final.actions.values()
                if action.get("role") == "synthesize")
            audit_action = next(action for action in final.actions.values()
                if action.get("role") == "audit")
            for action_id in (draft_action["id"], audit_action["id"]):
                packet = json.loads(final.intent_packets[action_id])
                receipt = packet["tool_results"]["a0002"]
                self.assertEqual(receipt["request"]["operation"], "check_polynomial")
                self.assertEqual(receipt["status"], "succeeded")

    def test_structural_repair_is_a_separate_budgeted_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def configure(payload: dict[str, Any]) -> None:
                payload["budgets"]["max_model_calls"] = 2
                payload["budgets"]["max_repairs"] = 1
            run_dir = self._run(root, configure=configure)
            invalid = scripted_result("frame:")
            invalid["unrecognized"] = "force repair"
            stages: list[str] = []
            marker = root / "child-invocations.txt"
            outputs = {"frame:": [invalid, scripted_result("frame:")]}
            def factory(request: ResearchRequest, *, recorded_config: Mapping[str, Any] | None):
                return ScriptedAdapter(request, marker, stages, outputs)
            final = run_research(run_dir, provider_factory=factory)
            self.assertEqual(final.model_calls_used, 2)
            self.assertEqual(len(final.attempts), 2)
            attempts = list(final.attempts.values())
            self.assertEqual(attempts[0]["attempt_kind"], "initial")
            self.assertEqual(attempts[1]["attempt_kind"], "structural_repair")
            self.assertEqual(attempts[1]["prompt_version"], "structural-repair-v4")
            self.assertEqual(attempts[1]["parent_attempt_id"], attempts[0]["attempt_id"])
            self.assertGreater(attempts[1]["input_bytes"], attempts[0]["input_bytes"])
            review = attempts[1]["repair_review"]
            self.assertEqual(review["rejected_payload"]["unrecognized"], "force repair")
            self.assertEqual(review["corrected_payload"], scripted_result("frame:"))
            self.assertEqual(review["diff"][0]["path"], "/unrecognized")
            self.assertIn("diff", review["change_explanation"])
            self.assertEqual(stages, ["frame:", "frame:"])
            attempt_dir = run_dir / "actions" / "a0001" / "attempts" / attempts[0]["attempt_id"]
            self.assertTrue((attempt_dir / "stdout.bin").is_file())
            self.assertTrue((attempt_dir / "result.bin").is_file())
            self.assertEqual((attempt_dir / "result.bin").read_bytes(),
                             json.dumps(invalid, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8"))

    def test_failed_structural_repair_is_bounded_and_preserves_semantic_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def configure(payload: dict[str, Any]) -> None:
                payload["budgets"]["max_model_calls"] = 2
                payload["budgets"]["max_repairs"] = 1
            run_dir = self._run(root, configure=configure)
            invalid = scripted_result("frame:")
            invalid["answer"] = "Readable answer, despite a malformed contract."
            invalid["unrecognized"] = "force repair"
            still_invalid = dict(invalid)
            stages: list[str] = []
            marker = root / "child-invocations.txt"
            outputs = {"frame:": [invalid, still_invalid]}
            def factory(request: ResearchRequest, *, recorded_config: Mapping[str, Any] | None):
                return ScriptedAdapter(request, marker, stages, outputs)
            final = run_research(run_dir, provider_factory=factory)
            self.assertEqual(final.model_calls_used, 2)
            self.assertEqual(len(final.attempts), 2)
            self.assertEqual(stages, ["frame:", "frame:"])
            self.assertTrue(any(item.get("semantic_artifact") ==
                "Readable answer, despite a malformed contract."
                for item in final.outcomes.values()))

    def test_structural_repair_does_not_exceed_one_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def configure(payload: dict[str, Any]) -> None:
                payload["budgets"]["max_model_calls"] = 1
            run_dir = self._run(root, configure=configure)
            invalid = scripted_result("frame:")
            invalid["unrecognized"] = "force repair"
            stages: list[str] = []
            outputs = {"frame:": [invalid, scripted_result("frame:")]}
            marker = root / "child-invocations.txt"
            def factory(request: ResearchRequest, *, recorded_config: Mapping[str, Any] | None):
                return ScriptedAdapter(request, marker, stages, outputs)
            final = run_research(run_dir, provider_factory=factory)
            self.assertEqual(final.model_calls_used, 1)
            self.assertEqual(len(final.attempts), 1)
            self.assertEqual(stages, ["frame:"])

    def test_crash_after_provider_attempt_intent_is_ambiguous_without_relaunch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = self._run(root)
            stages: list[str] = []
            factory, _, _ = self._factory(root, stages)
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_provider_attempt_intent":
                    raise RuntimeError("stop after provider intent")
            with self.assertRaisesRegex(RuntimeError, "stop after provider intent"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            final = run_research(run_dir, provider_factory=lambda request: self.fail("ambiguous provider attempt relaunched"))
            self.assertEqual((final.status, final.reason), ("blocked", "ambiguous_execution"))
            self.assertEqual(final.model_calls_used, 1)
            self.assertEqual(stages, [])
            terminal_resume = run_research(run_dir,
                provider_factory=lambda request: self.fail("terminal ambiguous attempt resolved provider"))
            self.assertEqual(terminal_resume.sequence, final.sequence)

    def test_crash_after_finished_branch_resumes_without_second_child_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            stages: list[str] = []; factory, _, _ = self._factory(root, stages)
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_branch_a_finished": raise RuntimeError("simulated interruption")
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            resumed = run_research(run_dir, provider_factory=factory)
            self.assertEqual(resumed.status, "complete", resumed.reason)
            self.assertEqual(stages.count("branch:a"), 1)

    def test_decision_before_intent_replays_same_action_without_duplicate_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            stages: list[str] = []; marker = root / "child-invocations.txt"
            recorded_configs: list[Mapping[str, Any] | None] = []
            def factory(request: ResearchRequest, *, recorded_config: Mapping[str, Any] | None):
                recorded_configs.append(recorded_config)
                return ScriptedAdapter(request, marker, stages)
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_decision": raise RuntimeError("stop before intent")
            with self.assertRaisesRegex(RuntimeError, "stop before intent"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            resumed = run_research(run_dir, provider_factory=factory)
            self.assertEqual(resumed.status, "complete", resumed.reason)
            self.assertEqual(stages.count("frame:"), 1)
            self.assertEqual(sum(1 for d in resumed.decisions if d["reason_code"] == "frame_request"), 1)
            self.assertIsNone(recorded_configs[0])
            self.assertEqual(recorded_configs[1], resumed.provider_config)

    def test_crash_after_intent_blocks_ambiguous_action_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            stages: list[str]; factory, _, _ = self._factory(root, stages := [])
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_intent": raise RuntimeError("stop after intent")
            with self.assertRaisesRegex(RuntimeError, "stop after intent"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            final = run_research(run_dir, provider_factory=lambda request: self.fail("ambiguous resume resolved provider"))
            self.assertEqual(final.status, "blocked")
            self.assertEqual(final.reason, "ambiguous_execution")
            self.assertEqual(stages, [])

    def test_crash_after_first_capture_blocks_without_relaunching_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            stages: list[str] = []; factory, _, _ = self._factory(root, stages)
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_stdout_capture": raise RuntimeError("stop after first capture")
            with self.assertRaisesRegex(RuntimeError, "stop after first capture"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            resumed = run_research(run_dir, provider_factory=lambda request: self.fail("ambiguous resume resolved provider"))
            self.assertEqual((resumed.status, resumed.reason), ("blocked", "ambiguous_execution"))
            self.assertEqual(stages, ["frame:"])

    def test_crash_after_revise_result_resumes_with_one_fresh_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            initial_audit = scripted_result("audit:")
            initial_audit["checks"][0]["verdict"] = "unsupported"
            outputs = {"audit:": [initial_audit, scripted_result("audit:")]}
            stages: list[str] = []; marker = root / "child-invocations.txt"
            def factory(request: ResearchRequest, *, recorded_config: Mapping[str, Any] | None):
                return ScriptedAdapter(request, marker, stages, outputs)
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_revise__finished": raise RuntimeError("stop before re-audit")
            with self.assertRaisesRegex(RuntimeError, "stop before re-audit"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            resumed = run_research(run_dir, provider_factory=factory)

            self.assertEqual(resumed.status, "complete")
            self.assertEqual(stages.count("revise:"), 1)
            self.assertEqual(stages.count("audit:"), 2)

    def test_final_event_before_projection_recovers_terminal_projection_without_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            stages: list[str] = []; factory, _, _ = self._factory(root, stages)
            def crash(phase: str, snapshot: Any) -> None:
                if phase == "after_final_event_persisted_before_projection":
                    self.assertTrue((run_dir / "events" / f"{snapshot.sequence:06d}.json").exists())
                    self.assertFalse((run_dir / "report.md").exists())
                    self.assertFalse((run_dir / "research-log.md").exists())
                    raise RuntimeError("stop after final event persistence")
            with self.assertRaisesRegex(RuntimeError, "stop after final event persistence"):
                run_research(run_dir, provider_factory=factory, fault_hook=crash)
            resumed = run_research(run_dir, provider_factory=lambda request, *, recorded_config: self.fail("terminal resume resolved provider"))

            self.assertEqual(resumed.status, "complete")
            self.assertEqual((run_dir / "report.md").read_text(encoding="utf-8"), render_report(resumed))
            self.assertEqual((run_dir / "research-log.md").read_text(encoding="utf-8"), render_log(resumed))
            self.assertEqual(len(stages), 5)

    def test_deadline_uses_persisted_initialization_without_resolving_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            state = load_research_status(run_dir)
            start = datetime.fromisoformat(state.initialized_at.replace("Z", "+00:00"))
            future = start + timedelta(seconds=state.request.budgets["max_wall_seconds"] + 1)
            result = run_research(run_dir, provider_factory=lambda request: self.fail("deadline resolved provider"),
                                  now=lambda: future)
            self.assertEqual(result.status, "budget_exhausted")
            self.assertEqual(result.reason, "deadline_before_launch")

    def test_deadline_rechecked_after_intent_prevents_child_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir = self._run(root)
            state = load_research_status(run_dir)
            start = datetime.fromisoformat(state.initialized_at.replace("Z", "+00:00"))
            clock = {"value": start + timedelta(seconds=1)}
            stages: list[str] = []; factory, _, _ = self._factory(root, stages)

            def advance_after_intent(phase: str, snapshot: Any) -> None:
                if phase == "after_intent":
                    clock["value"] = start + timedelta(seconds=snapshot.request.budgets["max_wall_seconds"] + 1)

            result = run_research(run_dir, provider_factory=factory,
                                  now=lambda: clock["value"], fault_hook=advance_after_intent)
            self.assertEqual((result.status, result.reason), ("budget_exhausted", "deadline_before_launch"))
            self.assertEqual(stages, [])
            self.assertEqual(result.outcomes["a0001"]["outcome"], "launch_failed")

    def test_gate_answer_is_idempotent_and_conflicting_duplicate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def require_input(payload: dict[str, Any]) -> None:
                payload["objective"] = "prove"
            run_dir = self._run(root, configure=require_input)
            stages: list[str] = []; factory, _, _ = self._factory(root, stages)
            gate_state = run_research(run_dir, provider_factory=factory)
            self.assertEqual(gate_state.status, "awaiting_human")
            gate = gate_state.pending_gate
            response = {"schema_version": 3, "record_type": "research_gate_response",
                "gate_id": gate["gate_id"], "response_id": "response-one", "decision": "continue_limited",
                "text": None, "sources": []}
            answered = answer_research_gate(run_dir, response)
            duplicate = answer_research_gate(run_dir, response)
            self.assertEqual(duplicate.sequence, answered.sequence)
            resumed = run_research(run_dir, provider_factory=factory)
            self.assertEqual(resumed.status, "complete")
            with self.assertRaisesRegex(ValueError, "payload conflict"):
                answer_research_gate(run_dir, response | {"text": "changed"})

    def test_cancelled_gate_finishes_without_resuming_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = self._run(root, objective="prove")
            stages: list[str] = []; factory, _, _ = self._factory(root, stages)
            waiting = run_research(run_dir, provider_factory=factory)
            self.assertEqual(waiting.status, "awaiting_human")
            gate = waiting.pending_gate
            response = {"schema_version": 3, "record_type": "research_gate_response",
                "gate_id": gate["gate_id"], "response_id": "cancel-one", "decision": "cancel",
                "text": None, "sources": []}

            cancelled = answer_research_gate(run_dir, response)
            self.assertEqual((cancelled.status, cancelled.reason), ("incomplete", "user_cancelled"))
            resumed = run_research(run_dir, provider_factory=lambda request, *, recorded_config: self.fail("cancel resumed provider"))
            self.assertEqual((resumed.status, resumed.reason), ("incomplete", "user_cancelled"))
            self.assertEqual(stages, ["frame:"])


if __name__ == "__main__":
    unittest.main()
