"""Regression checks for frozen research-quality evaluation data."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from mathresearch.research.evaluation import load_cases as load_evaluation_cases, worker_case


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = REPOSITORY_ROOT / "evals" / "research-quality" / "cases.json"
FIXTURE_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "research" / "observed_circular_support.json"


def load_cases() -> list[dict[str, object]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


class ResearchQualityCasesTest(unittest.TestCase):
    def test_cases_include_quality_failures_not_just_happy_path(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 3)
        self.assertEqual(len({case["id"] for case in cases}), 3)
        by_id = {case["id"]: case for case in cases}
        self.assertIn("minimal polynomial", by_id["algebraic-certificate"]["question"])
        self.assertTrue(by_id["domino-tilings"]["sources"])

    def test_all_cases_have_nonempty_obligations_and_forbidden_claims(self) -> None:
        for case in load_cases():
            with self.subTest(case_id=case["id"]):
                self.assertTrue(case["expected_obligations"])
                self.assertTrue(case["forbidden_claims"])

    def test_value_v2_sets_are_separate_and_truth_stays_out_of_worker_packets(self) -> None:
        development_dir = REPOSITORY_ROOT / "evals" / "research-value-v2" / "development"
        heldout_dir = REPOSITORY_ROOT / "evals" / "research-value-v2" / "held-out"
        development, _, _ = load_evaluation_cases(development_dir)
        heldout, _, _ = load_evaluation_cases(heldout_dir)
        self.assertEqual(len(development), 6)
        self.assertEqual(len(heldout), 6)
        self.assertFalse({case["id"] for case in development} & {case["id"] for case in heldout})
        for case in development + heldout:
            packet = worker_case(case)
            self.assertNotIn("expected_obligations", packet)
            self.assertNotIn("forbidden_claims", packet)

    def test_circular_support_fixture_is_labeled_as_invalid_evidence(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(fixture["expected_failure"], "agent_output_is_not_evidence")
        self.assertEqual(fixture["historical_behavior"], "defective")
        self.assertIn("success criterion", fixture["investigate_claim"]["support"])
        self.assertEqual(fixture["verify_verdict"]["verdict"], "supported")


if __name__ == "__main__":
    unittest.main()
