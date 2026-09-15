"""Tests for durable initialization event and state record contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from mathresearch.contracts.records import RunRequest
from mathresearch.contracts.run import RunInitializedEvent, RunState, project_initialization
from mathresearch.contracts.validation import ValidationError
from tests.helpers import valid_run_request_payload


OCCURRED_AT = "2026-09-12T14:30:45.123456Z"
FULL_WIDTH_OCCURRED_AT = "２０２６-０９-１２T１４:３０:４５.１２３４５６Z"


def valid_event_payload() -> dict[str, object]:
    """Return a complete initialization event JSON fixture."""
    return {
        "schema_version": 1,
        "record_type": "run_event",
        "sequence": 1,
        "event_type": "run_initialized",
        "run_id": "run-local-calculation",
        "occurred_at": OCCURRED_AT,
        "request": valid_run_request_payload(),
    }


def valid_state_payload() -> dict[str, object]:
    """Return the state projection hand-derived from the initialization event."""
    return {
        "schema_version": 1,
        "record_type": "run_state",
        "run_id": "run-local-calculation",
        "status": "initialized",
        "initialized_at": OCCURRED_AT,
        "last_event_sequence": 1,
    }


class RunInitializedEventTests(unittest.TestCase):
    def test_round_trips_complete_initialization_event(self) -> None:
        """Changing a persisted initialization field must be visible after reading it."""
        payload = valid_event_payload()

        event = RunInitializedEvent.from_json(payload)

        self.assertEqual(event.to_json(), payload)

    def test_rejects_missing_or_unknown_event_fields(self) -> None:
        """Schema drift must not silently create partially understood event records."""
        missing = valid_event_payload()
        del missing["request"]
        unknown = valid_event_payload()
        unknown["extra"] = "not allowed"

        for payload in (missing, unknown):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValidationError, "run_event"):
                    RunInitializedEvent.from_json(payload)

    def test_rejects_invalid_event_discriminators_and_run_id(self) -> None:
        """Readers must not accept a different event shape under the same schema version."""
        for field, value in (
            ("record_type", "run_state"),
            ("event_type", "run_started"),
            ("run_id", "Run-Local-Calculation"),
        ):
            with self.subTest(field=field, value=value):
                payload = valid_event_payload()
                payload[field] = value
                with self.assertRaisesRegex(ValidationError, field):
                    RunInitializedEvent.from_json(payload)

    def test_rejects_non_integer_version_or_sequence(self) -> None:
        """Permitting booleans or floats would weaken the persisted JSON format."""
        for field, values in (("schema_version", (True, 1.0, 2)), ("sequence", (True, 1.0, 2))):
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = valid_event_payload()
                    payload[field] = value
                    with self.assertRaisesRegex(ValidationError, field):
                        RunInitializedEvent.from_json(payload)

    def test_rejects_mismatched_or_invalid_nested_request(self) -> None:
        """An event cannot claim a run other than the validated request it initializes."""
        mismatched = valid_event_payload()
        mismatched["run_id"] = "run-other-calculation"
        invalid_nested = valid_event_payload()
        invalid_nested_request = deepcopy(invalid_nested["request"])
        invalid_nested_request["mode"] = "unsupported"  # type: ignore[index]
        invalid_nested["request"] = invalid_nested_request

        for payload in (mismatched, invalid_nested):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    RunInitializedEvent.from_json(payload)

    def test_rejects_malformed_impossible_or_non_utc_event_timestamps(self) -> None:
        """Event chronology needs a single strict and parseable UTC wire format."""
        for timestamp in (
            "2026-09-12T14:30:45Z",
            "2026-09-12T14:30:45.12345Z",
            "2026-09-12T14:30:45.123456+00:00",
            "2026-02-29T14:30:45.123456Z",
            "2026-13-12T14:30:45.123456Z",
            "not-a-timestamp",
            FULL_WIDTH_OCCURRED_AT,
        ):
            with self.subTest(timestamp=timestamp):
                payload = valid_event_payload()
                payload["occurred_at"] = timestamp
                with self.assertRaisesRegex(ValidationError, "occurred_at"):
                    RunInitializedEvent.from_json(payload)

    def test_refuses_boolean_sequence_when_serializing_a_constructed_event(self) -> None:
        """Direct construction must not bypass the JSON contract's integer requirement."""
        request = RunRequest.from_json(valid_run_request_payload())
        event = RunInitializedEvent(
            run_id=request.run_id,
            occurred_at=datetime(2026, 9, 12, 14, 30, 45, 123456, tzinfo=timezone.utc),
            request=request,
            sequence=True,
        )

        with self.assertRaisesRegex(ValidationError, "sequence"):
            event.to_json()

    def test_refuses_invalid_constructed_event_identifiers_and_request_ids(self) -> None:
        """Writing must revalidate hand-constructed records before they reach disk."""
        request = RunRequest.from_json(valid_run_request_payload())
        initialized_at = datetime(2026, 9, 12, 14, 30, 45, 123456, tzinfo=timezone.utc)
        cases = (
            RunInitializedEvent("Run-Local-Calculation", initialized_at, request),
            RunInitializedEvent(
                request.run_id,
                initialized_at,
                replace(request, run_id="run-other-calculation"),
            ),
            RunInitializedEvent(
                request.run_id,
                initialized_at,
                replace(request, run_id="Run-Local-Calculation"),
            ),
            RunInitializedEvent(
                "Run-Local-Calculation",
                initialized_at,
                replace(request, run_id="Run-Local-Calculation"),
            ),
        )

        for event in cases:
            with self.subTest(event=event):
                with self.assertRaisesRegex(ValidationError, "run_id"):
                    event.to_json()


class RunStateTests(unittest.TestCase):
    def test_round_trips_complete_initialized_state(self) -> None:
        """State projection must preserve the committed initialization checkpoint."""
        payload = valid_state_payload()

        state = RunState.from_json(payload)

        self.assertEqual(state.to_json(), payload)

    def test_rejects_missing_unknown_or_noninteger_state_fields(self) -> None:
        """State readers must reject drift and numeric coercion rather than repair it silently."""
        missing = valid_state_payload()
        del missing["status"]
        unknown = valid_state_payload()
        unknown["extra"] = "not allowed"

        for payload in (missing, unknown):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValidationError, "run_state"):
                    RunState.from_json(payload)
        for field, values in (("schema_version", (True, 1.0, 2)), ("last_event_sequence", (True, 1.0, 2))):
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = valid_state_payload()
                    payload[field] = value
                    with self.assertRaisesRegex(ValidationError, field):
                        RunState.from_json(payload)

    def test_rejects_invalid_state_discriminators_and_run_id(self) -> None:
        """Readers must not accept a different state shape under the same schema version."""
        for field, value in (
            ("record_type", "run_event"),
            ("status", "running"),
            ("run_id", "Run-Local-Calculation"),
        ):
            with self.subTest(field=field, value=value):
                payload = valid_state_payload()
                payload[field] = value
                with self.assertRaisesRegex(ValidationError, field):
                    RunState.from_json(payload)

    def test_rejects_malformed_impossible_or_non_utc_state_timestamps(self) -> None:
        """State timestamps must remain strictly comparable with the event timeline."""
        for timestamp in (
            "2026-09-12T14:30:45Z",
            "2026-09-12T14:30:45.12345Z",
            "2026-09-12T14:30:45.123456+00:00",
            "2026-02-29T14:30:45.123456Z",
            "2026-13-12T14:30:45.123456Z",
            "not-a-timestamp",
            FULL_WIDTH_OCCURRED_AT,
        ):
            with self.subTest(timestamp=timestamp):
                payload = valid_state_payload()
                payload["initialized_at"] = timestamp
                with self.assertRaisesRegex(ValidationError, "initialized_at"):
                    RunState.from_json(payload)

    def test_refuses_boolean_last_sequence_when_serializing_a_constructed_state(self) -> None:
        """Direct construction must not bypass the JSON contract's integer requirement."""
        state = RunState(
            run_id="run-local-calculation",
            initialized_at=datetime(2026, 9, 12, 14, 30, 45, 123456, tzinfo=timezone.utc),
            last_event_sequence=True,
        )

        with self.assertRaisesRegex(ValidationError, "last_event_sequence"):
            state.to_json()

    def test_refuses_invalid_constructed_state_identifier(self) -> None:
        """Writer validation prevents an invalid state path from being persisted."""
        state = RunState(
            run_id="Run-Local-Calculation",
            initialized_at=datetime(2026, 9, 12, 14, 30, 45, 123456, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(ValidationError, "run_id"):
            state.to_json()


class InitializationProjectionTests(unittest.TestCase):
    def test_projects_a_request_into_matching_event_and_state(self) -> None:
        """A new run must start with sequence one and a state derived from that event."""
        request = RunRequest.from_json(valid_run_request_payload())
        initialized_at = datetime(2026, 9, 12, 14, 30, 45, 123456, tzinfo=timezone.utc)

        event, state = project_initialization(request, initialized_at)

        self.assertEqual(event.to_json(), valid_event_payload())
        self.assertEqual(state.to_json(), valid_state_payload())

    def test_refuses_a_manually_constructed_invalid_request(self) -> None:
        """Projection must not trust frozen dataclass construction as validation."""
        request = replace(
            RunRequest.from_json(valid_run_request_payload()), run_id="Run-Local-Calculation"
        )
        initialized_at = datetime(2026, 9, 12, 14, 30, 45, 123456, tzinfo=timezone.utc)

        with self.assertRaisesRegex(ValidationError, "run_id"):
            project_initialization(request, initialized_at)


if __name__ == "__main__":
    unittest.main()
