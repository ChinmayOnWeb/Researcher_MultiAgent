from __future__ import annotations

import unittest

from mathresearch.contracts.validation import ValidationError
from mathresearch.research.math_checks import check_integer, check_polynomial, perform_math_check, search_perfect


class ResearchMathCheckTests(unittest.TestCase):
    def test_check_integer_handles_perfect_and_unit_values(self) -> None:
        self.assertEqual(check_integer(6), {"n": 6, "proper_divisors": [1, 2, 3],
                         "proper_divisor_sum": 6, "is_perfect": True})
        self.assertEqual(check_integer(1), {"n": 1, "proper_divisors": [],
                         "proper_divisor_sum": 0, "is_perfect": False})
        self.assertIn(41, check_integer(1681)["proper_divisors"])

    def test_search_is_scoped_to_requested_interval_and_parity(self) -> None:
        odd = search_perfect(1, 999, "odd")
        self.assertEqual(odd["tested_count"], 500)
        self.assertEqual(odd["matches"], [])
        all_values = search_perfect(1, 30, "all")
        self.assertEqual(all_values["matches"], [6, 28])

    def test_unhashable_parity_is_a_validation_error(self) -> None:
        from mathresearch.research.math_checks import validate_math_arguments
        with self.assertRaises(ValidationError):
            validate_math_arguments("search_perfect", {"lo": 1, "hi": 10, "parity": []})

    def test_polynomial_comparison_trims_zeros_and_finds_first_counterexample(self) -> None:
        same = check_polynomial([0, 0, 1, 0], [0, 0, 1], -3, 3)
        self.assertEqual(same, {"coefficient_equal": True, "counterexample": None,
                                "bounded_checked_count": 0})
        unequal = check_polynomial([1], [0], 0, 4)
        self.assertEqual(unequal["counterexample"], {"n": 0, "lhs_value": 1, "rhs_value": 0})
        self.assertEqual(unequal["bounded_checked_count"], 1)

    def test_rejects_bool_unknown_fields_and_oversized_inputs(self) -> None:
        for call in (lambda: check_integer(True), lambda: check_integer(10**8 + 1),
                     lambda: search_perfect(1, 10002, "all"),
                     lambda: check_polynomial([True], [0], 0, 1),
                     lambda: check_polynomial([10**6 + 1], [0], 0, 1),
                     lambda: perform_math_check("check_integer", {"n": 6, "hidden": True})):
            with self.subTest(call=call), self.assertRaises(ValidationError):
                call()


if __name__ == "__main__":
    unittest.main()
