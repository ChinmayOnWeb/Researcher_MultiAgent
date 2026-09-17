"""Regression checks for frozen research-quality evaluation data."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = REPOSITORY_ROOT / "evals" / "research-quality" / "cases.json"
FIXTURE_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "research" / "observed_circular_support.json"


def load_cases() -> list[dict[str, object]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


class ResearchQualityCasesTest(unittest.TestCase):
    def test_cases_include_quality_failures_not_just_happy_path(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 8)
        self.assertEqual(len({case["id"] for case in cases}), 8)
        by_id = {case["id"]: case for case in cases}
        self.assertIn("division by zero", " ".join(by_id["false-cancellation"]["expected_obligations"]))
        self.assertEqual(len(by_id["source-conflict"]["sources"]), 2)

    def test_all_cases_have_nonempty_obligations_and_forbidden_claims(self) -> None:
        for case in load_cases():
            with self.subTest(case_id=case["id"]):
                self.assertTrue(case["expected_obligations"])
                self.assertTrue(case["forbidden_claims"])

    def test_odd_perfect_question_preserves_the_requested_task(self) -> None:
        case = next(case for case in load_cases() if case["id"] == "odd-perfect-status")
        self.assertEqual(
            case["question"],
            "What do the supplied notes establish about odd perfect numbers, and what would be needed to go further?",
        )
        self.assertNotIn("concise", case["objective"].lower())
        self.assertNotIn("general-audience", case["objective"].lower())

    def test_circular_support_fixture_is_labeled_as_invalid_evidence(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(fixture["expected_failure"], "agent_output_is_not_evidence")
        self.assertEqual(fixture["historical_behavior"], "defective")
        self.assertIn("success criterion", fixture["investigate_claim"]["support"])
        self.assertEqual(fixture["verify_verdict"]["verdict"], "supported")


if __name__ == "__main__":
    unittest.main()
