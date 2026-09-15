"""Behavioral tests for atomic durable run initialization."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from mathresearch.contracts.frame import build_frame_packet, build_frame_task
from mathresearch.contracts.records import RunRequest
from mathresearch.contracts.run import (
    FrameAttemptIntendedEvent,
    FrameProcessOutcomeEvent,
    FrameTaskCreatedEvent,
    parse_run_event,
)
from mathresearch.contracts.validation import ValidationError
from mathresearch.errors import (
    RunCorruptError,
    RunNotFoundError,
    RunStoreError,
    RunUninitializedError,
)
from mathresearch.run_store import initialize_run, load_run_status, open_locked_run
from mathresearch.process_runner import run_fake_frame_attempt
from tests.helpers import valid_run_request_payload
from tests.helpers import valid_frame_submission_payload


class RunStoreInitializationTests(unittest.TestCase):
    """Exercise initialization through real temporary directories."""

    def _write_request(self, root: Path, text: str | None = None) -> Path:
        request_path = root / "input-request.json"
        request_path.write_text(
            text if text is not None else json.dumps(valid_run_request_payload()),
            encoding="utf-8",
        )
        return request_path

    def test_real_process_captures_survive_checked_materialization_layout(self) -> None:
        """Canonical worker captures must not make a successful run corrupt on status replay."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"
            initialize_run(request_path, run_dir)
            request = RunRequest.from_json(valid_run_request_payload())
            task = build_frame_task(request)
            at = load_run_status(run_dir).initialized_at + timedelta(seconds=1)
            with open_locked_run(run_dir) as locked:
                locked.append(FrameTaskCreatedEvent(request.run_id, at, task, 2))
                locked.append(FrameAttemptIntendedEvent(request.run_id, at, task.task_id, task.revision, 1, 3))
            attempt_dir = run_dir / "tasks" / "task-frame" / "attempts" / "attempt-frame-001"
            result = run_fake_frame_attempt(
                attempt_dir / "packet.json", attempt=1,
                stdout_path=attempt_dir / "stdout.bin", stderr_path=attempt_dir / "stderr.log",
                run_dir=run_dir,
            )
            with open_locked_run(run_dir) as locked:
                locked.append(result.process_outcome(sequence=4, occurred_at=at))

            state = load_run_status(run_dir)

            self.assertEqual(state.last_event_sequence, 4)
            self.assertEqual((attempt_dir / "stdout.bin").read_bytes(), result.stdout)
            self.assertEqual((attempt_dir / "stderr.log").read_bytes(), result.stderr)

    def test_initializes_request_event_and_state(self) -> None:
        """Skipping any durable record would leave a new run without its checkpoint."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"

            state = initialize_run(request_path, run_dir)

            self.assertEqual(state.run_id, "run-local-calculation")
            self.assertEqual(state.status, "initialized")
            self.assertEqual(json.loads((run_dir / "request.json").read_text(encoding="utf-8")), valid_run_request_payload())
            event = json.loads((run_dir / "events" / "000001.json").read_text(encoding="utf-8"))
            persisted_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(event["event_type"], "run_initialized")
            self.assertEqual(event["sequence"], 1)
            self.assertEqual(event["request"], valid_run_request_payload())
            self.assertEqual(persisted_state, state.to_json())

    def test_rejects_an_invalid_request_without_creating_a_run_directory(self) -> None:
        """Creating a run before validation would leave artifacts for rejected input."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            payload = valid_run_request_payload()
            del payload["question"]
            request_path = self._write_request(root, json.dumps(payload))
            run_dir = root / "run-local-calculation"

            with self.assertRaises(ValidationError):
                initialize_run(request_path, run_dir)

            self.assertFalse(run_dir.exists())

    def test_rejects_duplicate_keys_and_nonfinite_json_without_creating_a_run(self) -> None:
        """Permissive parsing would let ambiguous or nonstandard request data become durable."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            valid_text = json.dumps(valid_run_request_payload(), indent=2)
            invalid_texts = (
                valid_text.replace(
                    '"question": "Which model explains the observed sequence?",',
                    '"question": "Which model explains the observed sequence?",\n  "question": "A duplicate",',
                ),
                valid_text.replace('"max_accepted_submissions": 30', '"max_accepted_submissions": NaN'),
                valid_text.replace('"max_accepted_submissions": 30', '"max_accepted_submissions": Infinity'),
            )

            for index, invalid_text in enumerate(invalid_texts):
                with self.subTest(index=index):
                    request_path = self._write_request(root, invalid_text)
                    run_dir = root / f"run-invalid-{index}"
                    with self.assertRaises(RunStoreError):
                        initialize_run(request_path, run_dir)
                    self.assertFalse(run_dir.exists())

    def test_rejects_a_lone_surrogate_without_creating_a_run_directory(self) -> None:
        """A non-UTF-8 durable record must fail before it can leave a precommit run."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            payload = valid_run_request_payload()
            payload["question"] = "\ud800"
            request_path = self._write_request(root, json.dumps(payload))
            run_dir = root / "run-local-calculation"

            with self.assertRaises(RunStoreError):
                initialize_run(request_path, run_dir)

            self.assertFalse(run_dir.exists())

    def test_synchronizes_a_new_run_directory_parent_before_event_commit(self) -> None:
        """Losing the new directory entry before its event would lose a reported commit."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"

            def fail_parent_synchronization(directory: Path) -> None:
                if directory == root:
                    raise OSError("simulated run-directory parent sync failure")

            with patch(
                "mathresearch.run_store._fsync_directory",
                side_effect=fail_parent_synchronization,
            ):
                with self.assertRaises(RunStoreError):
                    initialize_run(request_path, run_dir)

            self.assertTrue(run_dir.is_dir())
            self.assertFalse((run_dir / "events" / "000001.json").exists())

    def test_does_not_resynchronize_the_parent_of_an_existing_lock_only_directory(self) -> None:
        """The persistent lock sentinel is an accepted existing directory, not a new entry."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"
            run_dir.mkdir()
            (run_dir / ".run.lock").write_bytes(b"\0")

            def fail_only_parent_synchronization(directory: Path) -> None:
                if directory == root:
                    raise OSError("parent must not be synchronized again")

            with patch(
                "mathresearch.run_store._fsync_directory",
                side_effect=fail_only_parent_synchronization,
            ):
                state = initialize_run(request_path, run_dir)

            self.assertEqual(state.status, "initialized")

    def test_refuses_repeated_initialization_without_changing_committed_records(self) -> None:
        """Allowing a second initializer to replace immutable records would destroy run history."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"
            initialize_run(request_path, run_dir)
            paths = (run_dir / "request.json", run_dir / "events" / "000001.json", run_dir / "state.json")
            original_contents = {path: path.read_bytes() for path in paths}

            with self.assertRaises(RunStoreError):
                initialize_run(request_path, run_dir)

            self.assertEqual({path: path.read_bytes() for path in paths}, original_contents)

    def test_refuses_a_prepopulated_run_directory(self) -> None:
        """Treating arbitrary existing content as a new run risks overwriting another owner."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"
            run_dir.mkdir()
            sentinel = run_dir / "unexpected.txt"
            sentinel.write_text("preserve me", encoding="utf-8")

            with self.assertRaises(RunStoreError):
                initialize_run(request_path, run_dir)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me")
            self.assertFalse((run_dir / "request.json").exists())

    def test_refuses_to_resume_a_precommit_directory_after_an_event_write_fault(self) -> None:
        """Retrying a partial initializer would risk overwriting its immutable request record."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"

            original_link = os.link

            def fail_event_publication(source: Path, target: Path) -> None:
                if Path(target).name == "000001.json":
                    raise OSError("simulated event publication failure")
                original_link(source, target)

            with patch(
                "mathresearch.run_store.os.link",
                side_effect=fail_event_publication,
            ):
                with self.assertRaises(RunStoreError):
                    initialize_run(request_path, run_dir)

            self.assertTrue((run_dir / "request.json").is_file())
            self.assertFalse((run_dir / "events" / "000001.json").exists())
            with self.assertRaises(RunStoreError):
                initialize_run(request_path, run_dir)

    def test_keeps_the_committed_event_when_state_projection_write_fails(self) -> None:
        """The event commit point must survive an interrupted rebuildable state update."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"

            original_replace = os.replace

            def fail_state_publication(source: Path, target: Path) -> None:
                if Path(target).name == "state.json":
                    raise OSError("simulated state publication failure")
                original_replace(source, target)

            with patch(
                "mathresearch.run_store.os.replace",
                side_effect=fail_state_publication,
            ):
                with self.assertRaises(RunStoreError):
                    initialize_run(request_path, run_dir)

            self.assertTrue((run_dir / "request.json").is_file())
            self.assertTrue((run_dir / "events" / "000001.json").is_file())
            self.assertFalse((run_dir / "state.json").exists())

    def test_preserves_the_primary_publication_failure_when_temporary_cleanup_fails(self) -> None:
        """A cleanup error must not hide why immutable publication failed."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = self._write_request(root)
            run_dir = root / "run-local-calculation"

            with patch("mathresearch.run_store.os.link", side_effect=OSError("publish failed")):
                with patch("mathresearch.run_store.Path.unlink", side_effect=OSError("cleanup failed")):
                    with self.assertRaisesRegex(RunStoreError, "could not atomically write run artifact"):
                        initialize_run(request_path, run_dir)


class RunStoreStatusTests(unittest.TestCase):
    """Exercise authoritative event replay and disposable state repair."""

    def _initialize_run(self, root: Path) -> Path:
        request_path = root / "input-request.json"
        request_path.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
        run_dir = root / "run-local-calculation"
        initialize_run(request_path, run_dir)
        return run_dir

    def _frame_history(self, run_dir: Path) -> list[dict[str, object]]:
        """Build a valid Frame lifecycle whose times follow this run's init event."""
        initialized = json.loads((run_dir / "events" / "000001.json").read_text(encoding="utf-8"))
        request = initialized["request"]
        task = build_frame_task(RunRequest.from_json(request))
        first_time = datetime.fromisoformat(initialized["occurred_at"].replace("Z", "+00:00"))

        def occurred_after(seconds: int) -> str:
            return (first_time + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        return [
            {
                "schema_version": 1, "record_type": "run_event", "sequence": 2,
                "event_type": "frame_task_created", "run_id": initialized["run_id"],
                "occurred_at": occurred_after(1), "task": task.to_json(),
            },
            {
                "schema_version": 1, "record_type": "run_event", "sequence": 3,
                "event_type": "frame_attempt_intended", "run_id": initialized["run_id"],
                "occurred_at": occurred_after(2), "task_id": "frame", "revision": 1, "attempt": 1,
            },
            {
                "schema_version": 1, "record_type": "run_event", "sequence": 4,
                "event_type": "frame_process_outcome", "run_id": initialized["run_id"],
                "occurred_at": occurred_after(3), "task_id": "frame", "revision": 1, "attempt": 1,
                "exit_code": 0,
            },
            {
                "schema_version": 1, "record_type": "run_event", "sequence": 5,
                "event_type": "frame_submission_accepted", "run_id": initialized["run_id"],
                "occurred_at": occurred_after(4), "submission": valid_frame_submission_payload(),
            },
        ]

    @staticmethod
    def _write_event(run_dir: Path, event: dict[str, object]) -> Path:
        event_path = run_dir / "events" / f"{event['sequence']:06d}.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        return event_path

    def _write_full_frame_history(self, run_dir: Path) -> list[dict[str, object]]:
        events = self._frame_history(run_dir)
        for event in events:
            self._write_event(run_dir, event)
        return events

    def test_replays_canonical_multi_event_history_and_repairs_derived_materializations(self) -> None:
        """All Frame caches must be rebuilt solely from a complete valid event history."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            events = self._write_full_frame_history(run_dir)
            (run_dir / "state.json").unlink()

            state = load_run_status(run_dir)

            request = RunRequest.from_json(
                json.loads((run_dir / "events" / "000001.json").read_text(encoding="utf-8"))["request"]
            )
            task = build_frame_task(request)
            self.assertEqual(state.status, "active")
            self.assertEqual(state.last_event_sequence, 5)
            task_dir = run_dir / "tasks" / "task-frame"
            self.assertEqual(json.loads((task_dir / "task.json").read_text(encoding="utf-8")), task.to_json())
            self.assertEqual(
                json.loads((task_dir / "attempts" / "attempt-frame-001" / "packet.json").read_text(encoding="utf-8")),
                build_frame_packet(task, request).to_json(),
            )
            self.assertEqual(
                json.loads((task_dir / "accepted.json").read_text(encoding="utf-8")),
                events[-1]["submission"],
            )

    def test_repairs_interrupted_task_intent_and_acceptance_materializations(self) -> None:
        """Missing derived files are recoverable once their complete evidence is durable."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name, target in (
                ("task", Path("tasks") / "task-frame" / "task.json"),
                ("intent", Path("tasks") / "task-frame" / "attempts" / "attempt-frame-001" / "packet.json"),
                ("acceptance", Path("tasks") / "task-frame" / "accepted.json"),
            ):
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    run_dir = self._initialize_run(case_root)
                    self._write_full_frame_history(run_dir)
                    load_run_status(run_dir)
                    (run_dir / target).unlink()

                    self.assertEqual(load_run_status(run_dir).last_event_sequence, 5)
                    self.assertTrue((run_dir / target).is_file())

    def test_rejects_event_gaps_names_and_unknown_types_before_repairing_a_valid_prefix(self) -> None:
        """Status must validate every immutable event before it repairs any cache."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name, mutation in (
                ("gap", lambda run_dir, events: self._write_event(run_dir, {**events[1], "sequence": 4})),
                ("name-mismatch", lambda run_dir, events: (run_dir / "events" / "000002.json").write_text(json.dumps(events[1]), encoding="utf-8")),
                ("unknown-event", lambda run_dir, events: self._write_event(run_dir, {
                    "schema_version": 1, "record_type": "run_event", "sequence": 3,
                    "event_type": "frame_task_unknown", "run_id": events[0]["run_id"],
                    "occurred_at": events[1]["occurred_at"],
                })),
            ):
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    run_dir = self._initialize_run(case_root)
                    events = self._frame_history(run_dir)
                    self._write_event(run_dir, events[0])
                    (run_dir / "state.json").unlink()
                    mutation(run_dir, events)

                    with self.assertRaises(RunCorruptError):
                        load_run_status(run_dir)

                    self.assertFalse((run_dir / "state.json").exists())
                    self.assertFalse((run_dir / "tasks" / "task-frame" / "task.json").exists())

    def test_rejects_unsafe_task_materialization_directories(self) -> None:
        """A replayable cache directory still cannot be a linked or unexpected filesystem object."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            self._write_event(run_dir, self._frame_history(run_dir)[0])
            outside = root / "outside-task-frame"
            outside.mkdir()
            (run_dir / "tasks").mkdir()
            (run_dir / "tasks" / "task-frame").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(RunCorruptError):
                load_run_status(run_dir)

            self.assertFalse((outside / "task.json").exists())

    def test_rejects_unsafe_existing_attempt_when_a_sibling_attempt_cache_is_missing(self) -> None:
        """A recoverable missing cache cannot bypass checks for every surviving sibling."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            events = self._frame_history(run_dir)
            events[2]["exit_code"] = 1
            second_intent = {**events[1], "sequence": 5, "attempt": 2, "occurred_at": events[3]["occurred_at"]}
            for event in (*events[:3], second_intent):
                self._write_event(run_dir, event)
            load_run_status(run_dir)
            attempts_dir = run_dir / "tasks" / "task-frame" / "attempts"
            second_attempt_dir = attempts_dir / "attempt-frame-002"
            (second_attempt_dir / "packet.json").unlink()
            second_attempt_dir.rmdir()
            (attempts_dir / "attempt-frame-001" / "unexpected.bin").write_bytes(b"unsafe")

            with self.assertRaises(RunCorruptError):
                load_run_status(run_dir)

    def test_locked_run_appends_canonical_events_and_exposes_current_request_and_state(self) -> None:
        """Dispatch callers need one lock spanning event publication and derived cache repair."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            events = self._frame_history(run_dir)

            with open_locked_run(run_dir) as locked_run:
                self.assertEqual(locked_run.request.run_id, "run-local-calculation")
                self.assertEqual(locked_run.state.last_event_sequence, 1)
                for event in events:
                    locked_run.append(parse_run_event(event))

                self.assertEqual(locked_run.state.last_event_sequence, 5)

            self.assertEqual(load_run_status(run_dir).accepted_submission_count, 1)

    def test_locked_run_refuses_to_append_over_a_corrupt_immutable_event_copy(self) -> None:
        """Appending must never turn an existing corrupt immutable filename into a valid record."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            corrupt = run_dir / "events" / "000002.json"
            corrupt.write_bytes(b"{not-json")
            original = corrupt.read_bytes()

            with self.assertRaises(RunCorruptError):
                with open_locked_run(run_dir) as locked_run:
                    locked_run.append(self._frame_history(run_dir)[0])

            self.assertEqual(corrupt.read_bytes(), original)

    def test_replays_the_initialization_event_and_repairs_a_missing_state(self) -> None:
        """A committed event without its projection must remain observable after interruption."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            expected = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            (run_dir / "state.json").unlink()

            state = load_run_status(run_dir)

            self.assertEqual(state.to_json(), expected)
            self.assertEqual(
                json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
                expected,
            )

    def test_leaves_a_correct_state_projection_untouched(self) -> None:
        """Replacing a correct projection would make status needlessly mutate a healthy run."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            state_path = run_dir / "state.json"
            os.utime(state_path, ns=(1_000_000_000, 1_000_000_000))
            before = state_path.stat().st_mtime_ns

            state = load_run_status(run_dir)

            self.assertEqual(state.status, "initialized")
            self.assertEqual(state_path.stat().st_mtime_ns, before)

    def test_allows_an_absent_request_copy_when_the_event_is_committed(self) -> None:
        """The event embeds the request, so a lost optional copy must not hide a committed run."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            (run_dir / "request.json").unlink()

            state = load_run_status(run_dir)

            self.assertEqual(state.run_id, "run-local-calculation")

    def test_rebuilds_a_malformed_or_stale_state_from_the_event(self) -> None:
        """Trusting a syntactically bad or semantically stale projection would report false status."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name, contents in (
                ("malformed", b"{not json"),
                (
                    "stale",
                    json.dumps(
                        {
                            "schema_version": 1,
                            "record_type": "run_state",
                            "run_id": "run-local-calculation",
                            "status": "initialized",
                            "initialized_at": "2026-01-01T00:00:00.000000Z",
                            "last_event_sequence": 1,
                        }
                    ).encode("utf-8"),
                ),
            ):
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    run_dir = self._initialize_run(case_root)
                    (run_dir / "state.json").write_bytes(contents)

                    state = load_run_status(run_dir)

                    event = json.loads(
                        (run_dir / "events" / "000001.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(state.run_id, event["run_id"])
                    self.assertEqual(state.initialized_at.isoformat(), event["occurred_at"].replace("Z", "+00:00"))
                    self.assertEqual(
                        json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
                        state.to_json(),
                    )

    def test_distinguishes_missing_and_uninitialized_runs(self) -> None:
        """Collapsing absence and precommit state would prevent callers from recovering correctly."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing = root / "missing"
            with self.assertRaises(RunNotFoundError) as missing_error:
                load_run_status(missing)
            self.assertEqual(missing_error.exception.code, "run_not_found")

            uninitialized = root / "uninitialized"
            uninitialized.mkdir()
            with self.assertRaises(RunUninitializedError) as uninitialized_error:
                load_run_status(uninitialized)
            self.assertEqual(uninitialized_error.exception.code, "run_uninitialized")

    def test_rejects_noncanonical_event_layouts(self) -> None:
        """Accepting gaps, extra events, or undeclared files would make replay ambiguous."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name, mutation in (
                ("extra-event", lambda run_dir: (run_dir / "events" / "000002.json").write_text("{}", encoding="utf-8")),
                ("malformed-event-name", lambda run_dir: (run_dir / "events" / "one.json").write_text("{}", encoding="utf-8")),
                ("top-level-extra", lambda run_dir: (run_dir / "unexpected.txt").write_text("x", encoding="utf-8")),
            ):
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    run_dir = self._initialize_run(case_root)
                    mutation(run_dir)
                    with self.assertRaises(RunCorruptError) as error:
                        load_run_status(run_dir)
                    self.assertEqual(error.exception.code, "run_corrupt")

    def test_ignores_only_writer_temporary_files(self) -> None:
        """An interrupted atomic write must not make an otherwise committed run corrupt."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            (run_dir / ".state.json.interrupted.tmp").write_bytes(b"partial")
            (run_dir / "events" / ".000001.json.interrupted.tmp").write_bytes(b"partial")

            state = load_run_status(run_dir)

            self.assertEqual(state.status, "initialized")

    def test_rejects_links_and_preserves_committed_evidence_on_corruption(self) -> None:
        """Following a link or repairing after bad evidence could make an attacker-controlled record authoritative."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            event_path = run_dir / "events" / "000001.json"
            request_path = run_dir / "request.json"
            event_bytes = event_path.read_bytes()
            request_bytes = request_path.read_bytes()
            linked_state = root / "linked-state.json"
            linked_state.write_text("target", encoding="utf-8")
            (run_dir / "state.json").unlink()
            (run_dir / "state.json").symlink_to(linked_state)

            with self.assertRaises(RunCorruptError):
                load_run_status(run_dir)

            self.assertEqual(event_path.read_bytes(), event_bytes)
            self.assertEqual(request_path.read_bytes(), request_bytes)

    def test_rejects_corrupt_event_and_request_copy_mismatch_without_repair(self) -> None:
        """A bad event or divergent request copy must fail before status can publish a new projection."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name, mutation in (
                ("corrupt-event", lambda run_dir: (run_dir / "events" / "000001.json").write_text("{}", encoding="utf-8")),
                (
                    "request-mismatch",
                    lambda run_dir: (run_dir / "request.json").write_text(
                        json.dumps({**valid_run_request_payload(), "question": "different"}),
                        encoding="utf-8",
                    ),
                ),
            ):
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    run_dir = self._initialize_run(case_root)
                    state_path = run_dir / "state.json"
                    state_path.unlink()
                    mutation(run_dir)
                    event_path = run_dir / "events" / "000001.json"
                    event_bytes = event_path.read_bytes()

                    with self.assertRaises(RunCorruptError):
                        load_run_status(run_dir)

                    self.assertEqual(event_path.read_bytes(), event_bytes)
                    self.assertFalse(state_path.exists())

    def test_state_repair_failure_leaves_committed_evidence_unchanged(self) -> None:
        """A failed projection replacement must not mutate the event or request it replays."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            event_path = run_dir / "events" / "000001.json"
            request_path = run_dir / "request.json"
            event_bytes = event_path.read_bytes()
            request_bytes = request_path.read_bytes()
            (run_dir / "state.json").unlink()
            original_replace = os.replace

            def fail_state_publication(source: Path, target: Path) -> None:
                if Path(target).name == "state.json":
                    raise OSError("simulated status repair failure")
                original_replace(source, target)

            with patch("mathresearch.run_store.os.replace", side_effect=fail_state_publication):
                with self.assertRaises(RunStoreError):
                    load_run_status(run_dir)

            self.assertEqual(event_path.read_bytes(), event_bytes)
            self.assertEqual(request_path.read_bytes(), request_bytes)
            self.assertFalse((run_dir / "state.json").exists())

    def test_accepts_verified_temporary_hardlinks_left_after_immutable_publication(self) -> None:
        """A cleanup-interrupted immutable publish leaves a valid hardlink alias, not corrupt evidence."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for target_name, parent_name in (
                ("request.json", "run"),
                ("000001.json", "events"),
            ):
                with self.subTest(target_name=target_name):
                    case_root = root / target_name
                    case_root.mkdir()
                    request_path = case_root / "input-request.json"
                    request_path.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
                    run_dir = case_root / "run-local-calculation"
                    original_unlink = Path.unlink

                    def leave_matching_temporary(path: Path, *args: object, **kwargs: object) -> None:
                        if path.name.startswith(f".{target_name}.") and path.name.endswith(".tmp"):
                            raise OSError("simulated cleanup interruption")
                        original_unlink(path, *args, **kwargs)

                    with patch("mathresearch.run_store.Path.unlink", new=leave_matching_temporary):
                        initialize_run(request_path, run_dir)

                    parent = run_dir if parent_name == "run" else run_dir / "events"
                    target_path = parent / target_name
                    leftovers = list(parent.glob(f".{target_name}.*.tmp"))
                    self.assertEqual(len(leftovers), 1)
                    self.assertTrue(os.path.samestat(target_path.stat(), leftovers[0].stat()))

                    state = load_run_status(run_dir)

                    self.assertEqual(state.status, "initialized")

    def test_rejects_a_temporary_name_hardlinked_to_unrelated_evidence(self) -> None:
        """A matching temporary name alone must not authorize an unrelated hardlink."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            alias = run_dir / "events" / ".000001.json.unrelated.tmp"
            os.link(run_dir / "request.json", alias)

            with self.assertRaises(RunCorruptError):
                load_run_status(run_dir)

    def test_rejects_an_unsafe_lock_target_before_lock_acquisition_mutates_it(self) -> None:
        """Following a lock symlink would let Windows write its lock sentinel outside the run."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            lock_target = root / "outside-lock-target"
            lock_target.write_bytes(b"")
            lock_path = run_dir / ".run.lock"
            lock_path.unlink()
            lock_path.symlink_to(lock_target)

            with self.assertRaises(RunCorruptError):
                load_run_status(run_dir)

            self.assertEqual(lock_target.read_bytes(), b"")

    def test_rejects_a_nonfile_lock_target_as_corruption(self) -> None:
        """Opening a directory lock target would turn a corrupt layout into a generic storage failure."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_dir = self._initialize_run(root)
            lock_path = run_dir / ".run.lock"
            lock_path.unlink()
            lock_path.mkdir()

            with self.assertRaises(RunCorruptError):
                load_run_status(run_dir)

    def test_rejects_reparse_point_run_directories_and_events_directories(self) -> None:
        """Windows junctions are links even when their POSIX mode is a directory."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name in ("run-root", "events-directory"):
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    run_dir = self._initialize_run(case_root)
                    reparse_path = run_dir if name == "run-root" else run_dir / "events"
                    original_lstat = Path.lstat
                    reparse_attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

                    def report_reparse_point(path: Path) -> object:
                        metadata = original_lstat(path)
                        if path == reparse_path:
                            return SimpleNamespace(
                                st_mode=metadata.st_mode,
                                st_file_attributes=reparse_attributes,
                            )
                        return metadata

                    with patch.object(
                        Path,
                        "lstat",
                        autospec=True,
                        side_effect=report_reparse_point,
                    ):
                        with self.assertRaises(RunCorruptError):
                            load_run_status(run_dir)


if __name__ == "__main__":
    unittest.main()
