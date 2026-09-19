from __future__ import annotations

import copy
import unittest

from dataclasses import replace

from mathresearch.research.routing import next_decision
from tests.unit.test_research_prompts import action, draft, snapshot


class ResearchRoutingTests(unittest.TestCase):
    def test_terminal_snapshot_is_noop(self) -> None:
        state = replace(snapshot(), status="complete")
        self.assertEqual(next_decision(state).reason_code, "terminal_noop")

    def test_pending_execution_and_gate_never_start_workers(self) -> None:
        state = replace(snapshot(), pending_action_id="a0009")
        self.assertEqual((next_decision(state).kind, next_decision(state).reason_code), ("finish", "ambiguous_execution"))
        gate = {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"],
                "allowed_response": ["supply"], "resume_token": "0" * 64}
        state = replace(snapshot(), pending_gate=gate, pending_action_id=None)
        self.assertEqual((next_decision(state).kind, next_decision(state).reason_code), ("await", "human_input_needed"))

    def test_quick_is_one_unreviewed_answer_call(self) -> None:
        from types import MappingProxyType
        from mathresearch.contracts.research_request import ResearchRequest
        base = snapshot(); payload = base.request.to_json(); payload["mode"] = "quick"
        payload["budgets"].update({"max_model_calls": 1, "max_tool_calls": 0, "max_repairs": 0,
                                   "max_branches": 1, "max_wall_seconds": 180, "per_call_seconds": 180})
        payload["capabilities"] = {"fetch_sources": False, "math_checks": False}
        request = ResearchRequest.from_json(payload)
        state = replace(base, request=request, actions=MappingProxyType({}), results=MappingProxyType({}),
                        sources=MappingProxyType({}), tool_results=MappingProxyType({}),
                        latest_draft_id=None, latest_audit_id=None, model_calls_used=0)
        first = next_decision(state)
        self.assertEqual((first.action["role"], first.reason_code), ("answer", "quick_answer"))
        answer_action = action("answer-one", "answer")
        state = replace(state, actions=MappingProxyType({"answer-one": answer_action}),
                        results=MappingProxyType({"answer-one": draft("answer")}), model_calls_used=1)
        finish = next_decision(state)
        self.assertEqual((finish.kind, finish.reason_code), ("finish", "quick_unreviewed"))
        self.assertEqual(finish.assessment["answer_status"], "unverified")

    def test_finished_action_without_valid_result_does_not_retry(self) -> None:
        from types import MappingProxyType
        state = snapshot()
        actions = {"a0001": {"id": "a0001", "kind": "worker", "role": "answer", "branch": None,
            "round": 0, "dependencies": [], "payload": {"prompt_version": "research-v1"}}}
        state = replace(state, actions=MappingProxyType(actions), results=MappingProxyType({}),
                        pending_action_id=None)
        decision = next_decision(state)
        self.assertEqual((decision.kind, decision.reason_code), ("finish", "action_failed"))

    def test_deep_starts_with_frame_and_then_blind_initial_branches(self) -> None:
        state = replace(snapshot(), actions={}, results={}, sources={}, tool_results={},
                        latest_draft_id=None, latest_audit_id=None, branches_started=0,
                        model_calls_used=0, tool_calls_used=0)
        frame = next_decision(state)
        self.assertEqual((frame.kind, frame.action["role"]), ("worker", "frame"))
        self.assertEqual(frame.reason_code, "frame_request")
        self.assertEqual(frame.decision_id, "d0001")

    def test_ordered_early_routes_cover_gates_sources_checks_and_branch_setup(self) -> None:
        from types import MappingProxyType
        from mathresearch.contracts.research_request import ResearchRequest
        base = snapshot()
        frame_action = base.actions["frame-one"]
        frame_result = base.results["frame-one"]
        state = replace(base, actions=MappingProxyType({"frame-one": frame_action}),
                        results=MappingProxyType({"frame-one": frame_result}), latest_draft_id=None,
                        latest_audit_id=None, branches_started=0, model_calls_used=1)
        mismatch = dict(frame_result); mismatch["task_type"] = "status"
        request_payload = base.request.to_json(); request_payload["objective"] = "prove"
        state = replace(state, request=ResearchRequest.from_json(request_payload),
                        results=MappingProxyType({"frame-one": mismatch}))
        self.assertEqual(next_decision(state).reason_code, "intent_mismatch")

        missing = dict(frame_result); missing["missing_inputs"] = ["which theorem?"]
        state = replace(state, request=base.request,
                        results=MappingProxyType({"frame-one": missing}))
        self.assertEqual(next_decision(state).reason_code, "missing_inputs")

        source_payload = base.request.to_json(); source_payload["capabilities"]["fetch_sources"] = True
        source_payload["sources"] = [{"id": "url-one", "kind": "url", "title": "URL",
            "text": None, "url": "https://example.test/paper", "published_at": None}]
        state = replace(state, request=ResearchRequest.from_json(source_payload), results=MappingProxyType({"frame-one": frame_result}))
        self.assertEqual(next_decision(state).reason_code, "acquire_source")

        checking = dict(frame_result); checking["proposed_checks"] = [{"id": "check-two", "operation": "check_integer", "arguments": {"n": 28}}]
        state = replace(state, request=base.request, results=MappingProxyType({"frame-one": checking}))
        self.assertEqual(next_decision(state).reason_code, "execute_frame_check")
        state = replace(state, results=MappingProxyType({"frame-one": frame_result,
            "branch-a": base.results["branch-a"]}), actions=MappingProxyType({
            "frame-one": base.actions["frame-one"], "branch-a": base.actions["branch-a"]}))
        self.assertEqual(next_decision(state).reason_code, "independent_approach")
        state = replace(state, results=MappingProxyType({**state.results, "branch-b": base.results["branch-b"]}),
                        actions=MappingProxyType({**state.actions, "branch-b": base.actions["branch-b"]}))
        self.assertEqual(next_decision(state).reason_code, "compare_approaches")

    def test_post_synthesis_audit_tool_and_evidence_routes(self) -> None:
        from types import MappingProxyType
        base = snapshot()
        actions = dict(base.actions); results = dict(base.results)
        actions.pop("audit-one"); results.pop("audit-one")
        state = replace(base, actions=MappingProxyType(actions), results=MappingProxyType(results), latest_audit_id=None)
        self.assertEqual(next_decision(state).reason_code, "challenge_claims")

        review = copy.deepcopy(base.results["audit-one"])
        review["tool_requests"] = [{"id": "new-check", "operation": "check_integer", "arguments": {"n": 28}}]
        state = replace(base, results=MappingProxyType(dict(base.results) | {"audit-one": review}))
        self.assertEqual(next_decision(state).reason_code, "test_audit_objection")

        review["tool_requests"] = []; review["recommended_action"] = "request_sources"
        review["missing_evidence"] = ["the cited theorem text"]
        state = replace(base, results=MappingProxyType(dict(base.results) | {"audit-one": review}))
        self.assertEqual(next_decision(state).reason_code, "request_evidence")

    def test_satisfied_assessment_finishes_within_scope(self) -> None:
        from types import MappingProxyType
        base = snapshot()
        draft = copy.deepcopy(base.results["draft-one"])
        draft["claims"][0]["kind"] = "deduction"
        draft["claims"][0]["tool_ids"] = ["check-one"]
        review = copy.deepcopy(base.results["audit-one"])
        review["checks"][0]["verdict"] = "supported"
        review["challenges"][0]["outcome"] = "survives"
        review["challenges"][0]["tool_ids"] = ["check-one"]
        results = dict(base.results) | {"draft-one": draft, "audit-one": review}
        state = replace(base, results=MappingProxyType(results))
        decision = next_decision(state)
        self.assertEqual((decision.kind, decision.reason_code), ("finish", "assessment_satisfied"))
        self.assertEqual(decision.assessment["answer_status"], "supported_within_scope")

    def test_unsupported_claim_and_finish_recommendation_do_not_finish(self) -> None:
        state = snapshot()
        results = dict(state.results)
        review = copy.deepcopy(results["audit-one"])
        review["checks"][0]["verdict"] = "unsupported"
        review["recommended_action"] = "finish"
        results["audit-one"] = review
        state = replace(state, results=results)
        decision = next_decision(state)
        self.assertEqual(decision.reason_code, "repair_argument")
        self.assertEqual(decision.action["role"], "revise")

    def test_stale_audit_is_never_reused_after_revise(self) -> None:
        from types import MappingProxyType
        state = snapshot()
        actions = dict(state.actions)
        actions["revise-two"] = {"id": "revise-two", "kind": "worker", "role": "revise",
            "branch": None, "round": 1, "dependencies": ["draft-one", "audit-one"],
            "payload": {"prompt_version": "research-v1"}}
        results = dict(state.results); results["revise-two"] = results["draft-one"] | {"change_log": ["fixed"]}
        state = replace(state, actions=MappingProxyType(actions), results=MappingProxyType(results),
                        latest_draft_id="revise-two", repairs_started=1)
        decision = next_decision(state)
        self.assertEqual(decision.action["role"], "audit")
        self.assertEqual(decision.action["dependencies"], ["revise-two"])

    def test_deep_never_launches_targeted_third_branch(self) -> None:
        state = snapshot()
        results = dict(state.results); review = copy.deepcopy(results["audit-one"])
        review["recommended_action"] = "additional_branch"
        review["missing_evidence"] = ["another route"]
        results["audit-one"] = review
        state = replace(state, results=results)
        self.assertNotEqual(next_decision(state).action["branch"], "c")

    def test_repair_reserves_an_audit_call(self) -> None:
        state = snapshot()
        request = state.request.to_json(); request["budgets"]["max_model_calls"] = 7
        from mathresearch.contracts.research_request import ResearchRequest
        state = replace(state, request=ResearchRequest.from_json(request), model_calls_used=6)
        decision = next_decision(state)
        self.assertEqual(decision.kind, "finish")
        self.assertEqual(decision.details["finish_status"], "budget_exhausted")

    def test_user_branch_cap_is_authoritative(self) -> None:
        from types import MappingProxyType
        from mathresearch.contracts.research_request import ResearchRequest
        state = snapshot()
        payload = state.request.to_json(); payload["budgets"]["max_branches"] = 1
        request = ResearchRequest.from_json(payload)
        actions = {key: state.actions[key] for key in ("frame-one", "branch-a")}
        results = {key: state.results[key] for key in actions}
        state = replace(state, request=request, actions=MappingProxyType(actions),
                        results=MappingProxyType(results), branches_started=1, model_calls_used=2)
        decision = next_decision(state)
        self.assertEqual(decision.reason_code, "branch_budget_exhausted")
        self.assertEqual(decision.details["finish_status"], "incomplete")

    def test_third_branch_only_for_research_with_capacity_for_branch_synthesis_audit(self) -> None:
        state = snapshot()
        request = state.request.to_json()
        request["mode"] = "research"
        request["budgets"]["max_model_calls"] = 11
        request["budgets"]["max_branches"] = 3
        request["budgets"]["max_repairs"] = 2
        from mathresearch.contracts.research_request import ResearchRequest
        state = replace(state, request=ResearchRequest.from_json(request))
        results = dict(state.results)
        review = copy.deepcopy(results["audit-one"])
        review["recommended_action"] = "additional_branch"
        review["missing_evidence"] = ["try modular arithmetic"]
        results["audit-one"] = review
        state = replace(state, results=results, model_calls_used=6, repairs_started=0)
        decision = next_decision(state)
        self.assertEqual((decision.reason_code, decision.action["branch"]), ("targeted_extra_branch", "c"))
        state = replace(state, model_calls_used=9)
        self.assertNotEqual(getattr(next_decision(state).action, "branch", None), "c")


if __name__ == "__main__":
    unittest.main()
