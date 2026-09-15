"""Tests for versioned, untrusted coordinator contracts."""

from __future__ import annotations

import unittest

from mathresearch.contracts.records import RunRequest
from mathresearch.contracts.validation import ValidationError
from tests.helpers import valid_run_request_payload


class RunRequestTests(unittest.TestCase):
    def test_parses_and_round_trips_a_complete_request(self) -> None:
        """Losing declared constraints or budgets would change the investigation."""
        payload = valid_run_request_payload()

        request = RunRequest.from_json(payload)

        self.assertEqual(request.to_json(), payload)

    def test_rejects_non_integer_schema_versions(self) -> None:
        """Boolean and float versions must not be silently normalized to version one."""
        for invalid_version in (True, 1.0, "1", 2):
            with self.subTest(invalid_version=invalid_version):
                payload = valid_run_request_payload()
                payload["schema_version"] = invalid_version

                with self.assertRaisesRegex(ValidationError, "schema_version"):
                    RunRequest.from_json(payload)

    def test_capabilities_cannot_mutate_after_validation(self) -> None:
        """Changing an accepted capability must require a new coordinator record."""
        payload = valid_run_request_payload()
        request = RunRequest.from_json(payload)

        with self.assertRaises(TypeError):
            request.capabilities["browse"] = True  # type: ignore[index]
        payload["capabilities"]["browse"] = True  # type: ignore[index]

        self.assertFalse(request.capabilities["browse"])


if __name__ == "__main__":
    unittest.main()
