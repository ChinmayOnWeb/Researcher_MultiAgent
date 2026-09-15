"""Tests for strict Frame task records and their replayed run lifecycle."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from mathresearch.contracts.frame import (
    FramePacket,
    FrameSubmission,
    build_frame_packet,
    build_frame_task,
)
from mathresearch.contracts.records import RunRequest
from mathresearch.contracts.run import (
    FrameAttemptIntendedEvent,
    FrameProcessOutcomeEvent,
    FrameSubmissionAcceptedEvent,
    FrameTaskCreatedEvent,
    RunInitializedEvent,
    parse_run_event,
    replay_run_events,
)
from mathresearch.contracts.validation import ValidationError
from tests.helpers import valid_frame_submission_payload, valid_run_request_payload
from tests.unit.test_run_records import valid_event_payload


def frame_task_created_payload() -> dict[str, object]:
    request = RunRequest.from_json(valid_run_request_payload())
    return {
        "schema_version": 1,
        "record_type": "run_event",
        "sequence": 2,
        "event_type": "frame_task_created",
        "run_id": request.run_id,
        "occurred_at": "2026-09-12T14:30:46.123456Z",
        "task": build_frame_task(request).to_json(),
    }


def frame_attempt_intended_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "run_event",
        "sequence": 3,
        "event_type": "frame_attempt_intended",
        "run_id": "run-local-calculation",
        "occurred_at": "2026-09-12T14:30:47.123456Z",
        "task_id": "frame",
        "revision": 1,
        "attempt": 1,
    }


def frame_process_outcome_payload(*, exit_code: int = 0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "run_event",
        "sequence": 4,
        "event_type": "frame_process_outcome",
        "run_id": "run-local-calculation",
        "occurred_at": "2026-09-12T14:30:48.123456Z",
        "task_id": "frame",
        "revision": 1,
        "attempt": 1,
        "exit_code": exit_code,
    }


def frame_submission_accepted_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "run_event",
        "sequence": 5,
        "event_type": "frame_submission_accepted",
        "run_id": "run-local-calculation",
        "occurred_at": "2026-09-12T14:30:50.123456Z",
        "submission": valid_frame_submission_payload(),
    }


def successful_frame_events() -> list[dict[str, object]]:
    return [
        valid_event_payload(),
        frame_task_created_payload(),
        frame_attempt_intended_payload(),
        frame_process_outcome_payload(),
        frame_submission_accepted_payload(),
    ]


class FrameRecordTests(unittest.TestCase):
    def test_builders_are_deterministic_and_packet_preserves_validated_request(self) -> None:
        """Changing frame assignment contents must change the packet consumers receive."""
        request = RunRequest.from_json(valid_run_request_payload())

        task = build_frame_task(request)
        packet = build_frame_packet(task, request)

        self.assertEqual(task.to_json()["task_id"], "frame")
        self.assertEqual(task.to_json()["revision"], 1)
        self.assertEqual(packet.to_json()["task"], task.to_json())
        self.assertEqual(packet.to_json()["request"], valid_run_request_payload())
        self.assertEqual(build_frame_task(request), task)
        self.assertEqual(build_frame_packet(task, request), packet)

    def test_frame_records_round_trip_and_reject_schema_drift(self) -> None:
        """Unknown fields would let incompatible worker payloads enter a durable run."""
        request = RunRequest.from_json(valid_run_request_payload())
        packet_payload = build_frame_packet(build_frame_task(request), request).to_json()
        submission_payload = valid_frame_submission_payload()

        self.assertEqual(FramePacket.from_json(packet_payload).to_json(), packet_payload)
        self.assertEqual(FrameSubmission.from_json(submission_payload).to_json(), submission_payload)
        for payload, parser in (
            ({**packet_payload, "extra": "no"}, FramePacket.from_json),
            ({**submission_payload, "extra": "no"}, FrameSubmission.from_json),
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValidationError, "unknown field"):
                    parser(payload)

    def test_frame_records_reject_boolean_numeric_fields_and_non_utc_submissions(self) -> None:
        """Python booleans and offset timestamps must not weaken persisted identities."""
        for field, value in (("revision", True), ("attempt", True)):
            payload = valid_frame_submission_payload()
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValidationError, field):
                    FrameSubmission.from_json(payload)
        payload = valid_frame_submission_payload()
        payload["submitted_at"] = "2026-09-12T14:30:49.123456+00:00"
        with self.assertRaisesRegex(ValidationError, "submitted_at"):
            FrameSubmission.from_json(payload)

    def test_constructed_submission_serialization_rejects_malformed_frame_mappings(self) -> None:
        """Serialization must preserve validation failures instead of repairing worker data."""
        submission = FrameSubmission.from_json(valid_frame_submission_payload())
        unknown = dict(submission.frame)
        unknown["unrecognized"] = "must not be dropped"
        missing = dict(submission.frame)
        del missing["terms"]
        string_terms = dict(submission.frame)
        string_terms["terms"] = "not an array"

        for frame in (unknown, missing, string_terms):
            with self.subTest(frame=frame):
                with self.assertRaises(ValidationError):
                    replace(submission, frame=frame).to_json()


class FrameRunReplayTests(unittest.TestCase):
    def test_replays_a_signed_process_termination_as_a_failed_outcome(self) -> None:
        """A signal return code must remain durable and cannot satisfy successful acceptance."""
        events = successful_frame_events()[:4]
        events[-1]["exit_code"] = -9

        parsed = [parse_run_event(event) for event in events]
        self.assertEqual(parsed[-1].to_json()["exit_code"], -9)
        state = replay_run_events(parsed)

        self.assertEqual(state.last_event_sequence, 4)
        self.assertEqual(state.accepted_submission_count, 0)

    def test_replays_a_successful_frame_submission_without_completing_the_run(self) -> None:
        """A frame result advances the run to active, not a falsely final complete state."""
        state = replay_run_events(parse_run_event(event) for event in successful_frame_events())

        self.assertEqual(state.status, "active")
        self.assertEqual(state.accepted_submission_count, 1)
        self.assertEqual(state.last_event_sequence, 5)

    def test_replay_rejects_identity_revision_and_attempt_mismatches(self) -> None:
        """A result for a different task execution must never be applied to Frame."""
        cases: list[tuple[str, list[dict[str, object]]]] = []
        bad_run = successful_frame_events()
        bad_run[2]["run_id"] = "run-other-calculation"
        cases.append(("run", bad_run))
        bad_revision = successful_frame_events()
        bad_revision[3]["revision"] = 2
        cases.append(("revision", bad_revision))
        bad_attempt = successful_frame_events()
        bad_attempt[4]["submission"] = deepcopy(valid_frame_submission_payload())
        bad_attempt[4]["submission"]["attempt"] = 2  # type: ignore[index]
        cases.append(("attempt", bad_attempt))

        for name, events in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    replay_run_events(parse_run_event(event) for event in events)

    def test_replay_rejects_illegal_ordering_acceptance_without_success_and_duplicates(self) -> None:
        """Acceptance needs its own recorded successful process and can occur only once."""
        missing_outcome = successful_frame_events()
        del missing_outcome[3]
        missing_outcome[3]["sequence"] = 4
        failed_outcome = successful_frame_events()
        failed_outcome[3]["exit_code"] = 1
        duplicate = successful_frame_events()
        second_acceptance = deepcopy(frame_submission_accepted_payload())
        second_acceptance["sequence"] = 6
        second_acceptance["occurred_at"] = "2026-09-12T14:30:51.123456Z"
        duplicate.append(second_acceptance)

        for events in (missing_outcome, failed_outcome, duplicate):
            with self.subTest(events=events):
                with self.assertRaises(ValidationError):
                    replay_run_events(parse_run_event(event) for event in events)

    def test_replay_rejects_acceptance_for_an_old_attempt_when_a_newer_attempt_is_pending(self) -> None:
        """A late earlier result must not be accepted while the task has moved to a newer attempt."""
        events = successful_frame_events()[:4]
        newer_attempt = frame_attempt_intended_payload()
        newer_attempt["sequence"] = 5
        newer_attempt["attempt"] = 2
        newer_attempt["occurred_at"] = "2026-09-12T14:30:49.123456Z"
        acceptance = frame_submission_accepted_payload()
        acceptance["sequence"] = 6
        acceptance["occurred_at"] = "2026-09-12T14:30:50.123456Z"
        events.extend((newer_attempt, acceptance))

        with self.assertRaisesRegex(ValidationError, "attempt"):
            replay_run_events(parse_run_event(event) for event in events)

    def test_replay_revalidates_constructed_events_before_reducing(self) -> None:
        """Frozen dataclass construction cannot bypass event wire-contract invariants."""
        initialized = RunInitializedEvent.from_json(valid_event_payload())
        created = FrameTaskCreatedEvent.from_json(frame_task_created_payload())
        intended = FrameAttemptIntendedEvent.from_json(frame_attempt_intended_payload())
        successful_outcome = FrameProcessOutcomeEvent.from_json(frame_process_outcome_payload())
        accepted = FrameSubmissionAcceptedEvent.from_json(frame_submission_accepted_payload())
        invalid_attempt = FrameAttemptIntendedEvent(
            initialized.run_id,
            datetime(2026, 9, 12, 14, 30, 47, 123456, tzinfo=timezone.utc),
            "frame",
            1,
            True,
            3,
        )
        invalid_exit = FrameProcessOutcomeEvent(
            initialized.run_id,
            datetime(2026, 9, 12, 14, 30, 48, 123456, tzinfo=timezone.utc),
            "frame",
            1,
            1,
            True,
            4,
        )
        naive_created = replace(created, occurred_at=datetime(2026, 9, 12, 14, 30, 46, 123456))
        mismatched_submission = replace(
            accepted,
            submission=replace(accepted.submission, run_id="run-other-calculation"),
        )
        cases = (
            (initialized, created, invalid_attempt),
            (initialized, created, intended, invalid_exit),
            (initialized, naive_created),
            (initialized, created, intended, successful_outcome, mismatched_submission),
        )

        for events in cases:
            with self.subTest(events=events):
                with self.assertRaises(ValidationError):
                    replay_run_events(events)

    def test_event_parser_rejects_unknown_fields_boolean_sequence_and_non_utc_times(self) -> None:
        """The multi-event reader must enforce the same strict wire boundary for every event."""
        for field, value in (
            ("sequence", True),
            ("occurred_at", "2026-09-12T14:30:46.123456+00:00"),
            ("extra", "no"),
            ("event_type", []),
        ):
            payload = frame_task_created_payload()
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    parse_run_event(payload)


if __name__ == "__main__":
    unittest.main()
