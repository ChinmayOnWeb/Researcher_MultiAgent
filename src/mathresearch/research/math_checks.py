"""Exact, bounded mathematical operations available to the research broker."""

from __future__ import annotations

from math import isqrt
from typing import Any

from mathresearch.contracts.validation import ValidationError, require_exact_fields, require_object


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(field, "must be an integer")
    return value


def check_integer(n: Any) -> dict[str, Any]:
    number = _int(n, "n")
    if not 1 <= number <= 10**8:
        raise ValidationError("n", "must be between 1 and 100000000")
    divisors: set[int] = set()
    for candidate in range(1, isqrt(number) + 1):
        if number % candidate == 0:
            if candidate != number: divisors.add(candidate)
            partner = number // candidate
            if partner != number: divisors.add(partner)
    ordered = sorted(divisors)
    total = sum(ordered)
    return {"n": number, "proper_divisors": ordered, "proper_divisor_sum": total,
            "is_perfect": total == number}


def search_perfect(lo: Any, hi: Any, parity: Any) -> dict[str, Any]:
    lower, upper = _int(lo, "lo"), _int(hi, "hi")
    if not isinstance(parity, str) or parity not in {"odd", "even", "all"}:
        raise ValidationError("parity", "must be odd, even, or all")
    if not 1 <= lower <= upper <= 100000 or upper - lower > 10000:
        raise ValidationError("range", "must satisfy 1<=lo<=hi<=100000 and hi-lo<=10000")
    sums = [0] * (upper + 1)
    for divisor in range(1, upper // 2 + 1):
        for multiple in range(divisor * 2, upper + 1, divisor):
            sums[multiple] += divisor
    candidates = [n for n in range(lower, upper + 1)
                  if parity == "all" or (parity == "odd") == (n % 2 == 1)]
    matches = [n for n in candidates if sums[n] == n]
    return {"lo": lower, "hi": upper, "parity": parity,
            "tested_count": len(candidates), "matches": matches}


def _polynomial_value(coefficients: list[int], n: int) -> int:
    value = 0
    for coefficient in reversed(coefficients):
        value = value * n + coefficient
    return value


def _trim(coefficients: list[int]) -> list[int]:
    while len(coefficients) > 1 and coefficients[-1] == 0:
        coefficients.pop()
    return coefficients


def check_polynomial(lhs: Any, rhs: Any, lo: Any, hi: Any) -> dict[str, Any]:
    if not isinstance(lhs, list) or not 1 <= len(lhs) <= 13:
        raise ValidationError("lhs", "must be an array with 1..13 coefficients")
    if not isinstance(rhs, list) or not 1 <= len(rhs) <= 13:
        raise ValidationError("rhs", "must be an array with 1..13 coefficients")
    left = [_int(value, f"lhs[{index}]") for index, value in enumerate(lhs)]
    right = [_int(value, f"rhs[{index}]") for index, value in enumerate(rhs)]
    if any(abs(value) > 10**6 for value in left + right):
        raise ValidationError("coefficients", "absolute coefficient values must not exceed 1000000")
    lower, upper = _int(lo, "lo"), _int(hi, "hi")
    if not -10000 <= lower <= upper <= 10000 or upper - lower > 10000:
        raise ValidationError("range", "must satisfy -10000<=lo<=hi<=10000 and hi-lo<=10000")
    left, right = _trim(left), _trim(right)
    equal = left == right
    counterexample = None
    checked = 0
    if not equal:
        for n in range(lower, upper + 1):
            checked += 1
            left_value, right_value = _polynomial_value(left, n), _polynomial_value(right, n)
            if left_value != right_value:
                counterexample = {"n": n, "lhs_value": left_value, "rhs_value": right_value}
                break
    return {"coefficient_equal": equal, "counterexample": counterexample,
            "bounded_checked_count": checked}


def perform_math_check(operation: str, arguments: Any) -> dict[str, Any]:
    data = validate_math_arguments(operation, arguments)
    if operation == "check_integer": return check_integer(data["n"])
    if operation == "search_perfect": return search_perfect(data["lo"], data["hi"], data["parity"])
    return check_polynomial(data["lhs"], data["rhs"], data["lo"], data["hi"])


def validate_math_arguments(operation: str, arguments: Any) -> dict[str, Any]:
    """Validate exact arguments and operation caps without performing the requested check."""
    data = require_object(arguments, "arguments")
    shapes = {"check_integer": {"n"}, "search_perfect": {"lo", "hi", "parity"},
              "check_polynomial": {"lhs", "rhs", "lo", "hi"}}
    if operation not in shapes:
        raise ValidationError("operation", "is not a mathematical check")
    require_exact_fields(data, "arguments", shapes[operation])
    if operation == "check_integer":
        n = _int(data["n"], "arguments.n")
        if not 1 <= n <= 10**8: raise ValidationError("arguments.n", "must be between 1 and 100000000")
    elif operation == "search_perfect":
        lo, hi = _int(data["lo"], "arguments.lo"), _int(data["hi"], "arguments.hi")
        if not isinstance(data["parity"], str) or data["parity"] not in {"odd", "even", "all"}:
            raise ValidationError("arguments.parity", "is invalid")
        if not 1 <= lo <= hi <= 100000 or hi - lo > 10000:
            raise ValidationError("arguments", "search range exceeds its bounds")
    else:
        for field in ("lhs", "rhs"):
            value = data[field]
            if not isinstance(value, list) or not 1 <= len(value) <= 13:
                raise ValidationError(f"arguments.{field}", "must contain 1..13 coefficients")
            for index, coefficient in enumerate(value):
                item = _int(coefficient, f"arguments.{field}[{index}]")
                if abs(item) > 10**6: raise ValidationError(f"arguments.{field}[{index}]", "absolute value exceeds 1000000")
        lo, hi = _int(data["lo"], "arguments.lo"), _int(data["hi"], "arguments.hi")
        if not -10000 <= lo <= hi <= 10000 or hi - lo > 10000:
            raise ValidationError("arguments", "polynomial range exceeds its bounds")
    return dict(data)
