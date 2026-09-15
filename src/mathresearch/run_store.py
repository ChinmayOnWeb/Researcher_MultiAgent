"""Durable, atomic initialization of one local research run."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterator, TypeAlias

from .contracts.frame import FramePacket, FrameSubmission, FrameTask, build_frame_packet
from .contracts.records import RunRequest
from .contracts.run import (
    FrameAttemptIntendedEvent,
    FrameProcessOutcomeEvent,
    FrameSubmissionAcceptedEvent,
    FrameTaskCreatedEvent,
    RunEvent,
    RunInitializedEvent,
    RunState,
    parse_run_event,
    project_initialization,
    replay_run_events,
)
from .contracts.quick import QuickState, WorkflowEvent, replay_quick_events
from .contracts.validation import ValidationError
from .errors import RunCorruptError, RunNotFoundError, RunStoreError, RunUninitializedError
from .locking import LOCK_FILE_NAME, _is_link_or_reparse_point, acquire_run_lock


REQUEST_FILE_NAME = "request.json"
STATE_FILE_NAME = "state.json"
EVENTS_DIRECTORY_NAME = "events"
INITIALIZATION_EVENT_FILE_NAME = "000001.json"
TASKS_DIRECTORY_NAME = "tasks"
FRAME_TASK_DIRECTORY_NAME = "task-frame"
TASK_FILE_NAME = "task.json"
ATTEMPTS_DIRECTORY_NAME = "attempts"
PACKET_FILE_NAME = "packet.json"
ACCEPTED_FILE_NAME = "accepted.json"
STDOUT_FILE_NAME = "stdout.bin"
STDERR_FILE_NAME = "stderr.log"
_EVENT_FILE_PATTERN = re.compile(r"([0-9]{6})\.json\Z")
_EVENT_TEMPORARY_PATTERN = re.compile(r"\.([0-9]{6}\.json)\..+\.tmp\Z")


PersistedState: TypeAlias = RunState | QuickState
PersistedEvent: TypeAlias = RunEvent | WorkflowEvent


def load_run_status(run_dir: Path) -> PersistedState:
    """Replay all committed events and repair only their derived projections."""
    with open_locked_run(run_dir) as locked_run:
        return locked_run.state


@dataclass
class LockedRun:
    """A validated run held under its OS lock for replay and event publication."""

    run_dir: Path
    request: RunRequest
    state: PersistedState
    _events: list[PersistedEvent] = field(repr=False)

    @property
    def events(self) -> tuple[PersistedEvent, ...]:
        """Return the replay-validated immutable history held by this lock."""
        return tuple(self._events)

    def materialize(self) -> PersistedState:
        """Revalidate all immutable evidence and rebuild missing or stale caches."""
        request, state, events = _load_locked_run(self.run_dir)
        self.request = request
        self.state = state
        self._events = events
        return state

    def append(self, candidate: PersistedEvent) -> PersistedState:
        """Commit one next canonical event and then rebuild its derived projections."""
        event = _validated_new_event(candidate)
        if event.sequence != len(self._events) + 1:
            raise ValidationError("sequence", "must be the next committed event sequence")
        try:
            expected_state = _replay_history((*self._events, event))
        except ValidationError:
            raise
        event_path = self.run_dir / EVENTS_DIRECTORY_NAME / f"{event.sequence:06d}.json"
        _atomic_write_new(event_path, _json_bytes(event.to_json()))
        self._events.append(event)
        self.state = _materialize_history(self.run_dir, self.request, self._events, expected_state)
        return self.state

    def write_capture(self, stage: str, attempt: int, name: str, data: bytes) -> str:
        """Atomically publish a diagnostic capture for one committed quick intent."""
        if stage not in ("frame", "investigate", "verify", "explain"):
            raise ValidationError("stage", "must be a supported quick stage")
        if attempt != 1:
            raise ValidationError("attempt", "must equal 1")
        if name not in (STDOUT_FILE_NAME, STDERR_FILE_NAME):
            raise ValidationError("name", "must be stdout.bin or stderr.log")
        if not isinstance(data, bytes):
            raise ValidationError("data", "must be bytes")
        intended = any(isinstance(event, WorkflowEvent) and event.event_type == "quick_attempt_intended" and event.body["stage"] == stage and event.body["attempt"] == attempt for event in self._events)
        if not intended:
            raise ValidationError("attempt", "must reference a committed intended attempt")
        target = self.run_dir / TASKS_DIRECTORY_NAME / f"task-{stage}" / ATTEMPTS_DIRECTORY_NAME / f"attempt-{stage}-{attempt:03d}" / name
        _require_safe_capture_target(target, self.run_dir)
        _atomic_write_new(target, data)
        import hashlib
        return hashlib.sha256(data).hexdigest()


@contextmanager
def open_locked_run(run_dir: Path) -> Iterator[LockedRun]:
    """Yield a run whose event history and materializations are safe under one lock."""
    _require_existing_run_directory(run_dir)
    _require_safe_existing_lock_target(run_dir)
    try:
        with acquire_run_lock(run_dir):
            request, state, events = _load_locked_run(run_dir)
            yield LockedRun(run_dir, request, state, events)
    except (RunNotFoundError, RunUninitializedError, RunCorruptError, RunStoreError):
        raise
    except OSError as exc:
        raise RunStoreError(f"could not open locked run: {run_dir}") from exc


def _require_existing_run_directory(run_dir: Path) -> None:
    """Distinguish a missing run from a non-directory or linked run path."""
    try:
        mode = run_dir.lstat().st_mode
    except FileNotFoundError as exc:
        raise RunNotFoundError(run_dir) from exc
    except OSError as exc:
        raise RunStoreError(f"could not inspect run directory: {run_dir}") from exc
    if _is_link_or_reparse_point(run_dir.lstat()) or not stat.S_ISDIR(mode):
        raise RunCorruptError(run_dir, "run path is not a real directory")


def _require_safe_existing_lock_target(run_dir: Path) -> None:
    """Classify a bad lock entry as corruption before lock acquisition touches it."""
    lock_path = run_dir / LOCK_FILE_NAME
    try:
        metadata = lock_path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RunCorruptError(run_dir, "could not inspect run lock") from exc
    if (
        _is_link_or_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise RunCorruptError(run_dir, "invalid run lock")


def _checked_run_directory_entries(run_dir: Path) -> dict[str, Path]:
    """Return permanent root entries after rejecting undeclared artifacts."""
    allowed = {
        LOCK_FILE_NAME,
        REQUEST_FILE_NAME,
        STATE_FILE_NAME,
        EVENTS_DIRECTORY_NAME,
        TASKS_DIRECTORY_NAME,
        "report.md",
    }
    entries: dict[str, Path] = {}
    temporary_entries: list[tuple[Path, str]] = []
    try:
        directory_entries = list(run_dir.iterdir())
    except OSError as exc:
        raise RunCorruptError(run_dir, "could not inspect run directory") from exc
    for entry in directory_entries:
        temporary_target = _documented_temporary_target(
            entry.name,
            (REQUEST_FILE_NAME, STATE_FILE_NAME, "report.md"),
        )
        if temporary_target is not None:
            _require_regular_file(entry, run_dir)
            temporary_entries.append((entry, temporary_target))
            continue
        if entry.name not in allowed:
            raise RunCorruptError(run_dir, f"unexpected run artifact: {entry.name}")
        _require_expected_kind(
            entry,
            run_dir,
            is_directory=entry.name in {EVENTS_DIRECTORY_NAME, TASKS_DIRECTORY_NAME},
        )
        entries[entry.name] = entry
    _verify_temporary_hardlink_aliases(
        run_dir,
        entries,
        temporary_entries,
        immutable_targets=frozenset((REQUEST_FILE_NAME,)),
    )
    return entries


def _checked_events_directory_entries(run_dir: Path, events_dir: Path) -> list[Path]:
    """Return every canonical committed event, rejecting gaps and aliases."""
    entries: dict[str, Path] = {}
    temporary_entries: list[tuple[Path, str]] = []
    try:
        directory_entries = list(events_dir.iterdir())
    except OSError as exc:
        raise RunCorruptError(run_dir, "could not inspect events directory") from exc
    for entry in directory_entries:
        temporary_target = _documented_event_temporary_target(entry.name)
        if temporary_target is not None:
            _require_regular_file(entry, run_dir)
            temporary_entries.append((entry, temporary_target))
            continue
        event_match = _EVENT_FILE_PATTERN.fullmatch(entry.name)
        if event_match is None or int(event_match.group(1)) < 1:
            raise RunCorruptError(run_dir, f"unexpected event artifact: {entry.name}")
        _require_regular_file(entry, run_dir)
        entries[entry.name] = entry
    expected_names = [f"{sequence:06d}.json" for sequence in range(1, len(entries) + 1)]
    if list(sorted(entries)) != expected_names:
        raise RunCorruptError(run_dir, "event files must be contiguous canonical sequences")
    _verify_temporary_hardlink_aliases(
        run_dir,
        entries,
        temporary_entries,
        immutable_targets=frozenset(entries),
    )
    return [entries[name] for name in expected_names]


def _documented_event_temporary_target(name: str) -> str | None:
    """Recognize temporary names written beside any canonical event filename."""
    match = _EVENT_TEMPORARY_PATTERN.fullmatch(name)
    if match is None or int(match.group(1)[:6]) < 1:
        return None
    return match.group(1)


def _documented_temporary_target(name: str, target_names: tuple[str, ...]) -> str | None:
    """Recognize only the sibling temporary names produced by ``_write_temporary_file``."""
    for target_name in target_names:
        prefix = f".{target_name}."
        if name.startswith(prefix) and name.endswith(".tmp"):
            return target_name if len(name) > len(prefix) + len(".tmp") else None
    return None


def _require_expected_kind(entry: Path, run_dir: Path, *, is_directory: bool) -> None:
    """Reject symlinks, hardlinks, and the wrong filesystem object type."""
    try:
        metadata = entry.lstat()
    except OSError as exc:
        raise RunCorruptError(run_dir, f"could not inspect run artifact: {entry.name}") from exc
    expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
    if (
        _is_link_or_reparse_point(metadata)
        or not expected
    ):
        raise RunCorruptError(run_dir, f"invalid run artifact: {entry.name}")


def _require_regular_file(entry: Path, run_dir: Path) -> None:
    """Reject a non-file or link where immutable JSON bytes are expected."""
    _require_expected_kind(entry, run_dir, is_directory=False)


def _verify_temporary_hardlink_aliases(
    run_dir: Path,
    entries: dict[str, Path],
    temporary_entries: list[tuple[Path, str]],
    *,
    immutable_targets: frozenset[str],
) -> None:
    """Allow only writer-left hardlink aliases whose target identity is verified."""
    aliases_by_target: dict[str, list[Path]] = {}
    for temporary_path, target_name in temporary_entries:
        temporary_metadata = temporary_path.lstat()
        if temporary_metadata.st_nlink == 1:
            continue
        target_path = entries.get(target_name)
        if target_name not in immutable_targets or target_path is None:
            raise RunCorruptError(run_dir, f"unverified temporary hardlink: {temporary_path.name}")
        target_metadata = target_path.lstat()
        if not os.path.samestat(temporary_metadata, target_metadata):
            raise RunCorruptError(run_dir, f"unverified temporary hardlink: {temporary_path.name}")
        aliases_by_target.setdefault(target_name, []).append(temporary_path)

    for entry_name, entry_path in entries.items():
        metadata = entry_path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            continue
        expected_links = 1 + len(aliases_by_target.get(entry_name, ()))
        if metadata.st_nlink != expected_links:
            raise RunCorruptError(run_dir, f"unverified hardlink: {entry_name}")


def _checked_materialization_layout(
    run_dir: Path,
    tasks_dir: Path | None,
    events: list[PersistedEvent],
) -> None:
    """Validate the small fixed Frame cache tree without treating it as evidence."""
    if any(isinstance(event, WorkflowEvent) for event in events):
        _checked_quick_materialization_layout(run_dir, tasks_dir, events)
        return
    if (run_dir / "report.md").exists():
        raise RunCorruptError(run_dir, "report materialization is only valid for quick workflow histories")
    task_created = any(isinstance(event, FrameTaskCreatedEvent) for event in events)
    attempts = {
        event.attempt for event in events if isinstance(event, FrameAttemptIntendedEvent)
    }
    accepted = any(isinstance(event, FrameSubmissionAcceptedEvent) for event in events)
    if not task_created:
        if tasks_dir is not None:
            raise RunCorruptError(run_dir, "tasks materialization exists before task creation")
        return
    if tasks_dir is None:
        return

    task_roots = _checked_projection_directory_entries(
        tasks_dir,
        run_dir,
        allowed_files=frozenset(),
        allowed_directories=frozenset((FRAME_TASK_DIRECTORY_NAME,)),
    )
    task_dir = task_roots.get(FRAME_TASK_DIRECTORY_NAME)
    if task_dir is None:
        return
    task_entries = _checked_projection_directory_entries(
        task_dir,
        run_dir,
        allowed_files=frozenset((TASK_FILE_NAME, ACCEPTED_FILE_NAME)),
        allowed_directories=frozenset((ATTEMPTS_DIRECTORY_NAME,)),
    )
    if not accepted and ACCEPTED_FILE_NAME in task_entries:
        raise RunCorruptError(run_dir, "accepted materialization exists before acceptance")
    attempts_dir = task_entries.get(ATTEMPTS_DIRECTORY_NAME)
    if not attempts:
        if attempts_dir is not None:
            raise RunCorruptError(run_dir, "attempt materialization exists before intent")
        return
    if attempts_dir is None:
        return
    attempt_entries = _checked_projection_directory_entries(
        attempts_dir,
        run_dir,
        allowed_files=frozenset(),
        allowed_directories=frozenset(
            _attempt_directory_name(attempt) for attempt in attempts
        ),
    )
    # Missing expected directories are recoverable, but each directory that is
    # present remains untrusted and must be checked independently.
    for attempt_dir in attempt_entries.values():
        _checked_projection_directory_entries(
            attempt_dir,
            run_dir,
            # Process capture is owned by the later dispatcher, but its fixed
            # filenames must remain legal under this store's strict layout.
            allowed_files=frozenset((PACKET_FILE_NAME, STDOUT_FILE_NAME, STDERR_FILE_NAME)),
            allowed_directories=frozenset(),
        )


def _checked_projection_directory_entries(
    directory: Path,
    run_dir: Path,
    *,
    allowed_files: frozenset[str],
    allowed_directories: frozenset[str],
) -> dict[str, Path]:
    """Check one projection directory, permitting only writer-shaped temp files."""
    entries: dict[str, Path] = {}
    temporary_entries: list[tuple[Path, str]] = []
    try:
        directory_entries = list(directory.iterdir())
    except OSError as exc:
        raise RunCorruptError(run_dir, f"could not inspect materialization directory: {directory.name}") from exc
    for entry in directory_entries:
        temporary_target = _documented_temporary_target(entry.name, tuple(allowed_files))
        if temporary_target is not None:
            _require_regular_file(entry, run_dir)
            temporary_entries.append((entry, temporary_target))
            continue
        if entry.name in allowed_files:
            _require_regular_file(entry, run_dir)
        elif entry.name in allowed_directories:
            _require_expected_kind(entry, run_dir, is_directory=True)
        else:
            raise RunCorruptError(run_dir, f"unexpected materialization artifact: {entry.name}")
        entries[entry.name] = entry
    _verify_temporary_hardlink_aliases(
        run_dir,
        entries,
        temporary_entries,
        immutable_targets=frozenset(),
    )
    return entries


def _checked_quick_materialization_layout(run_dir: Path, tasks_dir: Path | None, events: list[PersistedEvent]) -> None:
    """Validate every present derived quick stage directory independently."""
    intents = {event.body["stage"] for event in events if isinstance(event, WorkflowEvent) and event.event_type == "quick_attempt_intended"}
    accepted = {event.body["stage"] for event in events if isinstance(event, WorkflowEvent) and event.event_type == "quick_stage_accepted"}
    completed = any(isinstance(event, WorkflowEvent) and event.event_type == "quick_completed" for event in events)
    report = run_dir / "report.md"
    if report.exists():
        _require_regular_file(report, run_dir)
        if not completed: raise RunCorruptError(run_dir, "report materialization exists before completion")
    if tasks_dir is not None:
        roots = _checked_projection_directory_entries(tasks_dir, run_dir, allowed_files=frozenset(), allowed_directories=frozenset(f"task-{stage}" for stage in intents))
        for stage, task_dir in roots.items():
            stage_name = stage.removeprefix("task-")
            entries = _checked_projection_directory_entries(task_dir, run_dir, allowed_files=frozenset((ACCEPTED_FILE_NAME,)), allowed_directories=frozenset((ATTEMPTS_DIRECTORY_NAME,)))
            if stage_name not in accepted and ACCEPTED_FILE_NAME in entries: raise RunCorruptError(run_dir, "accepted materialization exists before acceptance")
            attempts = entries.get(ATTEMPTS_DIRECTORY_NAME)
            if attempts is None: continue
            attempt_entries = _checked_projection_directory_entries(attempts, run_dir, allowed_files=frozenset(), allowed_directories=frozenset((f"attempt-{stage_name}-001",)))
            for attempt_dir in attempt_entries.values():
                _checked_projection_directory_entries(attempt_dir, run_dir, allowed_files=frozenset((PACKET_FILE_NAME, STDOUT_FILE_NAME, STDERR_FILE_NAME)), allowed_directories=frozenset())
    _checked_quick_capture_digests(run_dir, events)


def _checked_quick_capture_digests(run_dir: Path, events: list[PersistedEvent]) -> None:
    """Require every finished quick attempt's diagnostic bytes to match its event."""
    for event in events:
        if not isinstance(event, WorkflowEvent) or event.event_type != "quick_attempt_finished":
            continue
        stage = event.body["stage"]
        attempt_dir = run_dir / TASKS_DIRECTORY_NAME / f"task-{stage}" / ATTEMPTS_DIRECTORY_NAME / f"attempt-{stage}-001"
        for name, digest_name in ((STDOUT_FILE_NAME, "stdout_sha256"), (STDERR_FILE_NAME, "stderr_sha256")):
            capture = attempt_dir / name
            try:
                _require_regular_file(capture, run_dir)
                actual = hashlib.sha256(capture.read_bytes()).hexdigest()
            except OSError as exc:
                raise RunCorruptError(run_dir, f"could not read committed {name} capture") from exc
            if actual != event.body[digest_name]:
                raise RunCorruptError(run_dir, f"committed {name} capture digest does not match event")


def _load_persisted_json(path: Path, run_dir: Path) -> Any:
    """Read durable JSON using the same strict parser used for request intake."""
    try:
        with path.open("r", encoding="utf-8") as record_file:
            return json.load(
                record_file,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_constant,
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunCorruptError(run_dir, f"invalid JSON record: {path.name}") from exc


def _load_initialization_event(path: Path, run_dir: Path) -> RunInitializedEvent:
    """Load the authoritative event, mapping every invalid form to corruption."""
    try:
        return RunInitializedEvent.from_json(_load_persisted_json(path, run_dir))
    except ValidationError as exc:
        raise RunCorruptError(run_dir, "invalid initialization event") from exc


def _load_run_event(path: Path, run_dir: Path) -> RunEvent:
    """Load one immutable event through the complete public contract parser."""
    try:
        return parse_run_event(_load_persisted_json(path, run_dir))
    except ValidationError as exc:
        raise RunCorruptError(run_dir, f"invalid event: {path.name}") from exc


def _load_persisted_event(path: Path, run_dir: Path) -> PersistedEvent:
    """Dispatch old and new immutable event versions without reinterpreting either."""
    payload = _load_persisted_json(path, run_dir)
    try:
        if isinstance(payload, dict) and payload.get("schema_version") == 2:
            return WorkflowEvent.from_json(payload)
        return parse_run_event(payload)
    except ValidationError as exc:
        raise RunCorruptError(run_dir, f"invalid event: {path.name}") from exc


def _replay_history(events: tuple[PersistedEvent, ...] | list[PersistedEvent]) -> PersistedState:
    """Select the reducer only for a homogeneous legacy or quick history."""
    quick = any(isinstance(event, WorkflowEvent) for event in events)
    legacy_frame = any(not isinstance(event, (RunInitializedEvent, WorkflowEvent)) for event in events)
    if quick:
        if legacy_frame:
            raise ValidationError("event_type", "cannot mix legacy Frame and quick workflow events")
        return replay_quick_events(events)  # type: ignore[arg-type]
    return replay_run_events(events)  # type: ignore[arg-type]


def _load_persisted_request(path: Path, run_dir: Path) -> RunRequest:
    """Load an optional request copy whose value must equal the event request."""
    try:
        return RunRequest.from_json(_load_persisted_json(path, run_dir))
    except ValidationError as exc:
        raise RunCorruptError(run_dir, "invalid request copy") from exc


def _load_locked_run(run_dir: Path) -> tuple[RunRequest, PersistedState, list[PersistedEvent]]:
    """Validate complete immutable history before rebuilding any derived files."""
    entries = _checked_run_directory_entries(run_dir)
    events_dir = entries.get(EVENTS_DIRECTORY_NAME)
    if events_dir is None:
        raise RunUninitializedError(run_dir)
    event_paths = _checked_events_directory_entries(run_dir, events_dir)
    if not event_paths:
        raise RunUninitializedError(run_dir)
    events = [_load_persisted_event(path, run_dir) for path in event_paths]
    try:
        expected_state = _replay_history(events)
    except ValidationError as exc:
        raise RunCorruptError(run_dir, "invalid event history") from exc
    initialized = events[0]
    if not isinstance(initialized, RunInitializedEvent):
        raise RunCorruptError(run_dir, "first event is not initialization")
    request_path = entries.get(REQUEST_FILE_NAME)
    if request_path is not None:
        request = _load_persisted_request(request_path, run_dir)
        if request != initialized.request:
            raise RunCorruptError(run_dir, "request copy does not match initialization event")
    _checked_materialization_layout(run_dir, entries.get(TASKS_DIRECTORY_NAME), events)
    state = _materialize_history(run_dir, initialized.request, events, expected_state)
    return initialized.request, state, events


def _validated_new_event(candidate: PersistedEvent) -> PersistedEvent:
    """Keep a constructed event behind the same strict JSON boundary as disk input."""
    if isinstance(candidate, WorkflowEvent):
        return WorkflowEvent.from_json(candidate.to_json())
    if not isinstance(candidate, (
        RunInitializedEvent,
        FrameTaskCreatedEvent,
        FrameAttemptIntendedEvent,
        FrameProcessOutcomeEvent,
        FrameSubmissionAcceptedEvent,
    )):
        raise ValidationError("run_event", "must be a supported parsed run event")
    return parse_run_event(candidate.to_json())


def _materialize_history(
    run_dir: Path,
    request: RunRequest,
    events: list[PersistedEvent],
    expected_state: PersistedState,
) -> PersistedState:
    """Publish only caches deterministically derivable from already-validated events."""
    task: FrameTask | None = None
    attempts: list[int] = []
    accepted: FrameSubmission | None = None
    for event in events:
        if isinstance(event, FrameTaskCreatedEvent):
            task = event.task
        elif isinstance(event, FrameAttemptIntendedEvent):
            attempts.append(event.attempt)
        elif isinstance(event, FrameSubmissionAcceptedEvent):
            accepted = event.submission

    state_path = run_dir / STATE_FILE_NAME
    if not state_path.exists() or _load_state_if_valid(state_path) != expected_state:
        _atomic_write_replace(state_path, _json_bytes(expected_state.to_json()))
    if any(isinstance(event, WorkflowEvent) for event in events):
        _materialize_quick_history(run_dir, events, expected_state)
        return expected_state
    if task is None:
        return expected_state

    task_dir = run_dir / TASKS_DIRECTORY_NAME / FRAME_TASK_DIRECTORY_NAME
    _ensure_directory(task_dir, run_dir)
    _repair_json_projection(task_dir / TASK_FILE_NAME, task, FrameTask.from_json, run_dir)
    if attempts:
        attempts_dir = task_dir / ATTEMPTS_DIRECTORY_NAME
        _ensure_directory(attempts_dir, run_dir)
        packet = build_frame_packet(task, request)
        for attempt in attempts:
            attempt_dir = attempts_dir / _attempt_directory_name(attempt)
            _ensure_directory(attempt_dir, run_dir)
            _repair_json_projection(attempt_dir / PACKET_FILE_NAME, packet, FramePacket.from_json, run_dir)
    if accepted is not None:
        _repair_json_projection(task_dir / ACCEPTED_FILE_NAME, accepted, FrameSubmission.from_json, run_dir)
    return expected_state


def _materialize_quick_history(run_dir: Path, events: list[PersistedEvent], expected_state: PersistedState) -> None:
    """Rebuild quick caches only from validated workflow event bodies."""
    for event in events:
        if not isinstance(event, WorkflowEvent):
            continue
        if event.event_type == "quick_attempt_intended":
            stage = event.body["stage"]
            attempt_dir = run_dir / TASKS_DIRECTORY_NAME / f"task-{stage}" / ATTEMPTS_DIRECTORY_NAME / f"attempt-{stage}-001"
            _ensure_directory(attempt_dir, run_dir)
            _repair_raw_json_projection(attempt_dir / PACKET_FILE_NAME, event.body["packet"], run_dir)
        elif event.event_type == "quick_stage_accepted":
            stage = event.body["stage"]
            finish = next((prior for prior in events if isinstance(prior, WorkflowEvent) and prior.event_type == "quick_attempt_finished" and prior.body["stage"] == stage), None)
            if finish is not None:
                task_dir = run_dir / TASKS_DIRECTORY_NAME / f"task-{stage}"
                _ensure_directory(task_dir, run_dir)
                _repair_raw_json_projection(task_dir / ACCEPTED_FILE_NAME, finish.body["result"], run_dir)
        elif event.event_type == "quick_completed":
            _repair_raw_bytes_projection(run_dir / "report.md", event.body["report_markdown"].encode("utf-8"), run_dir)


def _repair_raw_json_projection(path: Path, expected: Any, run_dir: Path) -> None:
    current = None
    if path.exists():
        try: current = _load_persisted_json(path, run_dir)
        except RunCorruptError: current = None
    if current != expected: _atomic_write_replace(path, _json_bytes(expected))


def _repair_raw_bytes_projection(path: Path, expected: bytes, run_dir: Path) -> None:
    current = None
    if path.exists():
        try:
            _require_regular_file(path, run_dir)
            current = path.read_bytes()
        except OSError: current = None
    if current != expected: _atomic_write_replace(path, expected)


def _require_safe_capture_target(target: Path, run_dir: Path) -> None:
    """Require the already-materialized, non-linked quick attempt ancestry."""
    try:
        relative = target.relative_to(run_dir)
    except ValueError as exc:
        raise RunCorruptError(run_dir, "capture target escapes run directory") from exc
    parent = run_dir
    for component in relative.parts[:-1]:
        parent = parent / component
        _require_expected_kind(parent, run_dir, is_directory=True)
    if target.exists():
        _require_regular_file(target, run_dir)


def _ensure_directory(directory: Path, run_dir: Path) -> None:
    """Create a missing derived directory without accepting a replacement object."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RunStoreError(f"could not create materialization directory: {directory}") from exc
    _require_expected_kind(directory, run_dir, is_directory=True)


def _repair_json_projection(path: Path, expected: Any, parser: Any, run_dir: Path) -> None:
    """Replace a disposable JSON cache only when it is absent, invalid, or stale."""
    current: Any | None = None
    if path.exists():
        try:
            current = parser(_load_persisted_json(path, run_dir))
        except (RunCorruptError, ValidationError):
            current = None
    if current != expected:
        _atomic_write_replace(path, _json_bytes(expected.to_json()))


def _attempt_directory_name(attempt: int) -> str:
    return f"attempt-frame-{attempt:03d}"


def _load_state_if_valid(path: Path) -> PersistedState | None:
    """Return a valid state projection, or ``None`` when it needs rebuilding."""
    try:
        with path.open("r", encoding="utf-8") as state_file:
            payload = json.load(
                state_file,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_constant,
            )
        if isinstance(payload, dict) and payload.get("schema_version") == 2:
            return QuickState.from_json(payload)
        return RunState.from_json(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError):
        return None


def initialize_run(request_path: Path, run_dir: Path) -> RunState:
    """Validate and durably initialize a previously unused run directory.

    The initialization event is the commit point.  A failure before it leaves a
    precommit directory which is deliberately not resumed by this function;
    a later status/repair operation owns recovery semantics.
    """
    request = _load_run_request(request_path)
    initialized_at = datetime.now(timezone.utc)
    event, state = project_initialization(request, initialized_at)
    request_bytes = _json_bytes(request.to_json())
    event_bytes = _json_bytes(event.to_json())
    state_bytes = _json_bytes(state.to_json())

    _create_run_directory(run_dir)
    try:
        with acquire_run_lock(run_dir):
            _require_empty_run_directory(run_dir)
            events_dir = run_dir / EVENTS_DIRECTORY_NAME
            try:
                events_dir.mkdir()
            except OSError as exc:
                raise RunStoreError(f"could not create events directory: {events_dir}") from exc

            _atomic_write_new(run_dir / REQUEST_FILE_NAME, request_bytes)
            _atomic_write_new(
                events_dir / INITIALIZATION_EVENT_FILE_NAME,
                event_bytes,
            )
            _atomic_write_replace(run_dir / STATE_FILE_NAME, state_bytes)
    except RunStoreError:
        raise
    except OSError as exc:
        raise RunStoreError(f"could not initialize run: {run_dir}") from exc
    return state


def _load_run_request(request_path: Path) -> RunRequest:
    """Read untrusted request JSON without parser-level ambiguity or non-finite values."""
    try:
        with request_path.open("r", encoding="utf-8") as request_file:
            payload = json.load(
                request_file,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_constant,
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunStoreError(f"invalid request JSON: {request_path}") from exc
    return RunRequest.from_json(payload)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object only when every member name occurs once."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    """Reject JSON extensions such as NaN and Infinity rather than normalizing them."""
    raise ValueError(f"non-finite JSON number: {value}")


def _create_run_directory(run_dir: Path) -> None:
    """Create only the run directory, after request validation and before locking it."""
    created = False
    try:
        run_dir.mkdir()
        created = True
    except FileExistsError:
        if not run_dir.is_dir():
            raise RunStoreError(f"run path is not a directory: {run_dir}")
    except OSError as exc:
        raise RunStoreError(f"could not create run directory: {run_dir}") from exc
    if not created:
        return
    try:
        _fsync_directory(run_dir.parent)
    except OSError as exc:
        raise RunStoreError(f"could not synchronize run directory parent: {run_dir.parent}") from exc


def _require_empty_run_directory(run_dir: Path) -> None:
    """Accept a newly-created directory or its durable lock sentinel alone."""
    try:
        contents = [entry.name for entry in run_dir.iterdir() if entry.name != LOCK_FILE_NAME]
    except OSError as exc:
        raise RunStoreError(f"could not inspect run directory: {run_dir}") from exc
    if contents:
        raise RunStoreError(f"refusing to initialize nonempty run directory: {run_dir}")


def _json_bytes(payload: Any) -> bytes:
    """Serialize durable JSON without allowing Python's nonstandard numeric constants."""
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RunStoreError("could not serialize durable JSON") from exc


def _atomic_write_new(target: Path, contents: bytes) -> None:
    """Atomically publish immutable contents only if ``target`` does not exist."""
    temporary_path = _write_temporary_file(target, contents)
    try:
        try:
            os.link(temporary_path, target)
        except FileExistsError as exc:
            raise RunStoreError(f"refusing to replace immutable run artifact: {target}") from exc
        _fsync_directory(target.parent)
    except RunStoreError:
        raise
    except OSError as exc:
        raise RunStoreError(f"could not atomically write run artifact: {target}") from exc
    finally:
        _remove_temporary_file(temporary_path)


def _atomic_write_replace(target: Path, contents: bytes) -> None:
    """Atomically replace a rebuildable projection after its event is committed."""
    temporary_path = _write_temporary_file(target, contents)
    try:
        os.replace(temporary_path, target)
        _fsync_directory(target.parent)
    except OSError as exc:
        raise RunStoreError(f"could not atomically write run artifact: {target}") from exc
    finally:
        _remove_temporary_file(temporary_path)


def _write_temporary_file(target: Path, contents: bytes) -> Path:
    """Write and synchronize a temporary file beside its eventual destination."""
    file_descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            file_descriptor = None
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except OSError as exc:
        if temporary_path is not None:
            _remove_temporary_file(temporary_path)
        raise RunStoreError(f"could not write temporary run artifact: {target}") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)


def _remove_temporary_file(temporary_path: Path) -> None:
    """Remove an unpublished temporary file without hiding the primary failure."""
    try:
        temporary_path.unlink()
    except OSError:
        pass


def _fsync_directory(directory: Path) -> None:
    """Synchronize a metadata change where the platform supports directory handles."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
