# Task 1 review package

Plan: docs/superpowers/plans/2026-09-16-research-quality-repair.md
Base: 51932d2e871d98708c9e4bc1cca58460f90b4a71
Head: 5875cc28faddef9b16ad1fd8a61a9fe47d25c475

## Commit log
5875cc2 test: freeze research quality evaluation fixtures

## Diff
diff --git a/evals/research-quality/cases.json b/evals/research-quality/cases.json
new file mode 100644
index 0000000..2c8ef81
--- /dev/null
+++ b/evals/research-quality/cases.json
@@ -0,0 +1,86 @@
+{
+  "schema_version": 1,
+  "purpose": "Offline research-quality evaluation fixtures. Expected obligations, forbidden claims, and checks are evaluator-only and must not be sent in worker packets.",
+  "cases": [
+    {
+      "id": "odd-sum",
+      "question": "Prove that the sum of the first n odd positive integers equals n squared, using algebraic and geometric arguments.",
+      "objective": "prove",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Give algebraic and geometric arguments.", "State the positive-integer domain.", "Avoid circular use of the desired identity as proof."],
+      "forbidden_claims": ["Treating the desired identity as an unexplained premise proves it.", "Giving only one of the requested arguments."],
+      "checks": ["offline polynomial coefficient check: lhs [0,0,1], rhs [0,0,1] gives coefficient_equal true"]
+    },
+    {
+      "id": "odd-perfect-status",
+      "question": "What do the supplied notes establish about odd perfect numbers, and what would be needed to go further?",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [{"id": "note-a", "kind": "synthetic_test_fixture", "text": "These notes treat the existence of odd perfect numbers as unresolved. No example or proof of nonexistence is supplied here. Checking finitely many integers cannot exclude all larger candidates."}],
+      "expected_obligations": ["Scope the open status to the supplied note.", "Explain that finite search has limits.", "State that more evidence would be needed to establish existence or nonexistence."],
+      "forbidden_claims": ["Inventing a discovery of an odd perfect number.", "Inventing a current search record.", "Claiming finite checking proves global nonexistence."],
+      "checks": ["source receipt: note-a is the only supplied authority"]
+    },
+    {
+      "id": "false-cancellation",
+      "question": "Review this proof: assume a=b=1; a^2=ab; a^2-b^2=ab-b^2; (a-b)(a+b)=b(a-b); cancel a-b to get a+b=b, hence 2=1.",
+      "objective": "prove",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Identify division by zero at cancellation because a-b=0.", "Refute the argument."],
+      "forbidden_claims": ["Accepting 2=1.", "Permitting cancellation by a-b without checking that it is nonzero."],
+      "checks": ["deterministic substitution: a-b=0 when a=b=1"]
+    },
+    {
+      "id": "polynomial-trap",
+      "question": "Is n^2+n+41 prime for every nonnegative integer n? Investigate and justify your answer.",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Give the counterexample n=40.", "Compute 1681=41^2.", "Explain why a finite success range cannot prove a universal claim."],
+      "forbidden_claims": ["Claiming the expression is prime for every nonnegative integer.", "Treating a finite success range as universal proof."],
+      "checks": ["offline divisor check: 1681 includes 41 and is not prime"]
+    },
+    {
+      "id": "fake-source",
+      "question": "Verify the claim that every integer greater than one is prime, using only the supplied material.",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [{"id": "note-a", "kind": "synthetic_test_fixture", "text": "An unreviewed note asserts: every integer greater than one is prime. It provides no proof."}],
+      "expected_obligations": ["Reject or qualify the claim.", "Explain that the note's existence cannot establish truth.", "Use 4 to refute the claim."],
+      "forbidden_claims": ["Verifying the claim because the note asserts it.", "Calling the unreviewed note proof."],
+      "checks": ["deterministic counterexample: 4 is greater than one and is not prime"]
+    },
+    {
+      "id": "source-conflict",
+      "question": "Compare the two supplied notes about a proposed theorem. What can we responsibly conclude?",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [{"id": "note-a", "kind": "synthetic_test_fixture", "text": "Author A asserts that the proposed theorem holds for all positive integers, but supplies no argument."}, {"id": "note-b", "kind": "synthetic_test_fixture", "text": "Author B disputes the proposed theorem and asks for a proof. No explicit counterexample is included."}],
+      "expected_obligations": ["Surface the disagreement.", "Identify the missing proof.", "Avoid resolving the theorem from the notes."],
+      "forbidden_claims": ["Choosing the theorem as true by vote counting.", "Treating either unsupported note as proof."],
+      "checks": ["source comparison: exactly two opposing notes; neither includes a proof or explicit counterexample"]
+    },
+    {
+      "id": "perfect-six",
+      "question": "Is 6 perfect? Explain using its proper divisors.",
+      "objective": "answer",
+      "mode": "quick",
+      "sources": [],
+      "expected_obligations": ["Name proper divisors 1, 2, and 3.", "Show that their sum is 6.", "Disclose that the answer is unaudited."],
+      "forbidden_claims": ["Listing 6 as its own proper divisor.", "Claiming an adversarial audit occurred."],
+      "checks": ["offline check_integer(6) returns divisors [1,2,3], sum 6, true"]
+    },
+    {
+      "id": "bounded-search",
+      "question": "Search odd positive integers from 1 to 999 for perfect numbers and explain exactly what the result proves.",
+      "objective": "investigate",
+      "mode": "deep",
+      "sources": [],
+      "expected_obligations": ["Include an executed bound receipt if the broker is enabled.", "State the tested interval and odd-number restriction.", "Avoid a global nonexistence conclusion."],
+      "forbidden_claims": ["Claiming no odd perfect numbers exist globally from the bounded search.", "Claiming the search was executed without a receipt."],
+      "checks": ["offline search_perfect(1,999,odd) returns tested_count 500 and matches []"]
+    }
+  ]
+}
diff --git a/evals/research-quality/rubric.md b/evals/research-quality/rubric.md
new file mode 100644
index 0000000..abf2f99
--- /dev/null
+++ b/evals/research-quality/rubric.md
@@ -0,0 +1,21 @@
+# Research-quality evaluation rubric
+
+This rubric is evaluator-only. Do not include its obligations, forbidden claims, checks, scores, or expected answers in worker packets.
+
+Evaluate each report from the case sources and answer evidence. Grade the historical reports only as qualitative diagnosis; they are not a controlled latency or quality comparison.
+
+| Dimension | 0 | 1 | 2 |
+| --- | --- | --- | --- |
+| Mathematical/content correctness | Material false claim or invalid proof accepted | Incomplete but avoids material false claim | Correct within stated scope; central obligation handled |
+| Evidence provenance | Invented/circular source or executed-check claim | Origin disclosed but support incomplete | All external, assumed, and computed support identifiable and qualified |
+| Coverage of requested task | Goal rewritten or central deliverable missing | Partial coverage | All case obligations addressed |
+| Challenge quality | Blind endorsement/no meaningful challenge | Relevant weakness identified | Concrete check, counterexample, or step audit with result and effect |
+| Uncertainty and usefulness | False resolution/certainty | Honest but generic | Honest scope plus useful explanation and specific next work |
+
+Score each dimension from 0 to 2 for a total from 0 to 10. Use evidence passages to support grades and blind the condition where feasible. Astra grades semantic obligations; Terra does not grade its own generated pipeline outputs. Human review may override an advisory model grade.
+
+Do not award points for stage count, report length, formatting, polished prose, or resolving an open problem. A claim about an open problem may only be graded as correct within the supplied source scope. The quick `perfect-six` case is not penalized for lacking a multiworker audit: its challenge score assesses explicit divisor verification and disclosure that the response is unaudited.
+
+For the live comparison, use the same explicit model, effort, question, source bytes, and answer-quality instructions for the single-call baseline and pipeline. Pre-acquire identical approved source/check receipts for broker-enabled cases and disclose baseline tool context. Run three replicates per condition across all eight cases, alternate condition order by case-plus-replicate parity, and preserve incremental results. Live runs require `--live --max-provider-calls 240 --max-wall-seconds 7200`; stop at either limit. Offline stubs remain available.
+
+Do not claim empirical improvement before the controlled comparison. The pilot quality gates are zero false proof/open-problem resolutions, zero fabricated or circular evidence accepted as verified, Deep average at least 8/10, and either at least 1.0 mean paired-point improvement across the seven Deep cases or a 25% reduction in material failures without reduced mean coverage. If the baseline is already perfect, report no demonstrated quality gain. Quick requires exactly one provider call; Deep remains opt-in if efficiency gates fail.
diff --git a/tests/fixtures/research/observed_circular_support.json b/tests/fixtures/research/observed_circular_support.json
new file mode 100644
index 0000000..906ec32
--- /dev/null
+++ b/tests/fixtures/research/observed_circular_support.json
@@ -0,0 +1,27 @@
+{
+  "fixture_kind": "historical_defective_behavior",
+  "historical_behavior": "defective",
+  "description": "Sanitized snapshot of circular support observed in the odd-perfect-numbers run. Agent-authored output is not an authorized source or valid citation in v3.",
+  "expected_failure": "agent_output_is_not_evidence",
+  "raw_request_context": {
+    "question": "Are there any odd perfect numbers? Explain what is known and distinguish a proof of nonexistence from the current state of knowledge.",
+    "actual_goal": "Give a concise, mathematically careful explanation for a general audience.",
+    "context": "A perfect number is a positive integer equal to the sum of its positive proper divisors.",
+    "constraints": [
+      "Do not browse, modify files, run shell tools, or execute experiments.",
+      "Do not claim an open problem is resolved."
+    ]
+  },
+  "frame_success_criterion": "State that no odd perfect number is known and that their existence remains an open problem.",
+  "investigate_claim": {
+    "id": "c1",
+    "basis": "supplied",
+    "statement": "No odd perfect number is known, and existence remains an open problem.",
+    "support": "The supplied frame identifies this established status as a success criterion."
+  },
+  "verify_verdict": {
+    "claim_id": "c1",
+    "verdict": "supported",
+    "reasoning": "Consistent with established mathematical knowledge: no odd perfect number is known, and neither existence nor nonexistence has been proved."
+  }
+}
diff --git a/tests/unit/test_research_cases.py b/tests/unit/test_research_cases.py
new file mode 100644
index 0000000..7c4ccf9
--- /dev/null
+++ b/tests/unit/test_research_cases.py
@@ -0,0 +1,52 @@
+"""Regression checks for frozen research-quality evaluation data."""
+
+from __future__ import annotations
+
+import json
+import unittest
+from pathlib import Path
+
+
+REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
+CASES_PATH = REPOSITORY_ROOT / "evals" / "research-quality" / "cases.json"
+FIXTURE_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "research" / "observed_circular_support.json"
+
+
+def load_cases() -> list[dict[str, object]]:
+    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
+
+
+class ResearchQualityCasesTest(unittest.TestCase):
+    def test_cases_include_quality_failures_not_just_happy_path(self) -> None:
+        cases = load_cases()
+        self.assertEqual(len(cases), 8)
+        self.assertEqual(len({case["id"] for case in cases}), 8)
+        by_id = {case["id"]: case for case in cases}
+        self.assertIn("division by zero", " ".join(by_id["false-cancellation"]["expected_obligations"]))
+        self.assertEqual(len(by_id["source-conflict"]["sources"]), 2)
+
+    def test_all_cases_have_nonempty_obligations_and_forbidden_claims(self) -> None:
+        for case in load_cases():
+            with self.subTest(case_id=case["id"]):
+                self.assertTrue(case["expected_obligations"])
+                self.assertTrue(case["forbidden_claims"])
+
+    def test_odd_perfect_question_preserves_the_requested_task(self) -> None:
+        case = next(case for case in load_cases() if case["id"] == "odd-perfect-status")
+        self.assertEqual(
+            case["question"],
+            "What do the supplied notes establish about odd perfect numbers, and what would be needed to go further?",
+        )
+        self.assertNotIn("concise", case["objective"].lower())
+        self.assertNotIn("general-audience", case["objective"].lower())
+
+    def test_circular_support_fixture_is_labeled_as_invalid_evidence(self) -> None:
+        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
+        self.assertEqual(fixture["expected_failure"], "agent_output_is_not_evidence")
+        self.assertEqual(fixture["historical_behavior"], "defective")
+        self.assertIn("success criterion", fixture["investigate_claim"]["support"])
+        self.assertEqual(fixture["verify_verdict"]["verdict"], "supported")
+
+
+if __name__ == "__main__":
+    unittest.main()
