"""Locked, isolated storage for version-three research runs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from mathresearch.errors import RunCorruptError, RunNotFoundError, RunStoreError, RunUninitializedError
from mathresearch.locking import acquire_run_lock
from mathresearch.run_store import _atomic_write_new, _atomic_write_replace, _load_persisted_json, _require_existing_run_directory, _require_regular_file, _require_safe_existing_lock_target
from mathresearch.contracts.research_request import ResearchRequest
from .events import ResearchEvent, ResearchSnapshot, canonical_json_bytes, replay_research_events


def _safe_directory(path: Path, run_dir: Path) -> None:
    try: metadata = path.lstat()
    except OSError as exc: raise RunCorruptError(run_dir, f"could not inspect {path.name}") from exc
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & reparse) or not stat.S_ISDIR(metadata.st_mode): raise RunCorruptError(run_dir, f"unsafe directory {path.name}")


def _read_events(run_dir: Path) -> tuple[ResearchEvent, ...]:
    events_dir = run_dir / "events"
    if not events_dir.exists(): raise RunUninitializedError(run_dir)
    _safe_directory(events_dir, run_dir)
    names = sorted(path.name for path in events_dir.iterdir() if not path.name.startswith("."))
    expected = [f"{number:06d}.json" for number in range(1, len(names) + 1)]
    if names != expected: raise RunCorruptError(run_dir, "event files must be contiguous canonical sequences")
    events: list[ResearchEvent] = []
    for name in names:
        path = events_dir / name; _require_regular_file(path, run_dir)
        try: events.append(ResearchEvent.from_json(_load_persisted_json(path, run_dir)))
        except (ValueError, TypeError) as exc: raise RunCorruptError(run_dir, "invalid research event") from exc
    return tuple(events)


def _check_layout(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
    allowed = {".run.lock", "request.json", "state.json", "events", "actions", "sources", "tools", "report.md", "research-log.md"}
    for entry in run_dir.iterdir():
        if entry.name.startswith(".") and entry.name.endswith(".tmp"): continue
        if entry.name not in allowed: raise RunCorruptError(run_dir, f"unexpected root entry {entry.name}")
    for name in ("actions", "sources", "tools"):
        path = run_dir / name
        if path.exists(): _safe_directory(path, run_dir)
    intended = {item.body["action_id"]: item.body for item in events if item.event_type == "action_intended"}
    finished = {item.body["action_id"]: item.body for item in events if item.event_type == "action_finished"}
    if (run_dir / "actions").exists():
        for action_dir in (run_dir / "actions").iterdir():
            if action_dir.name.startswith("."): continue
            if action_dir.name not in intended: raise RunCorruptError(run_dir, "unauthorized action directory")
            _safe_directory(action_dir, run_dir)
            for child in action_dir.iterdir():
                if child.name.startswith(".") and child.name.endswith(".tmp"): continue
                if child.name not in {"packet.json", "stdout.bin", "stderr.log", "result.json"}: raise RunCorruptError(run_dir, "unexpected action artifact")
                _require_regular_file(child, run_dir)
            packet = action_dir / "packet.json"
            if packet.exists() and packet.read_bytes() != canonical_json_bytes(intended[action_dir.name]["packet"]): raise RunCorruptError(run_dir, "packet projection mismatch")
            if action_dir.name in finished:
                outcome = finished[action_dir.name]
                for filename, digest_key in (("stdout.bin", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
                    capture = action_dir / filename
                    if not capture.exists() or hashlib.sha256(capture.read_bytes()).hexdigest() != outcome[digest_key]: raise RunCorruptError(run_dir, "capture digest mismatch")
    for dirname in ("tools", "sources"):
        path = run_dir / dirname
        if path.exists():
            for child in path.iterdir():
                if child.name.startswith("."): continue
                _safe_directory(child, run_dir)
                if dirname == "tools" and child.name not in finished: raise RunCorruptError(run_dir, "unauthorized tool projection")


def _materialize(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
    _atomic_write_replace(run_dir / "state.json", canonical_json_bytes(snapshot.state_json()))
    init = events[0].body["request"]; request = run_dir / "request.json"
    if not request.exists(): _atomic_write_replace(request, canonical_json_bytes(init))
    for item in events:
        if item.event_type == "action_intended":
            directory = run_dir / "actions" / item.body["action_id"]; directory.mkdir(parents=True, exist_ok=True)
            packet = directory / "packet.json"
            if not packet.exists(): _atomic_write_new(packet, canonical_json_bytes(item.body["packet"]))
        elif item.event_type == "action_finished" and item.body["result"] is not None:
            result = run_dir / "actions" / item.body["action_id"] / "result.json"
            if not result.exists(): _atomic_write_new(result, canonical_json_bytes(item.body["result"]))
        elif item.event_type == "research_finished":
            _atomic_write_replace(run_dir / "report.md", item.body["report_markdown"].encode("utf-8")); _atomic_write_replace(run_dir / "research-log.md", item.body["log_markdown"].encode("utf-8"))


class LockedResearchRun:
    def __init__(self, run_dir: Path, events: tuple[ResearchEvent, ...], snapshot: ResearchSnapshot) -> None:
        self.run_dir, self._events, self._snapshot = run_dir, events, snapshot
    @property
    def snapshot(self) -> ResearchSnapshot: return self._snapshot
    @property
    def events(self) -> tuple[ResearchEvent, ...]: return self._events
    def append(self, event: ResearchEvent) -> ResearchSnapshot:
        candidate = self._events + (event,)
        try: snapshot = replay_research_events(candidate)
        except ValueError as exc: raise RunStoreError("invalid research event append") from exc
        target = self.run_dir / "events" / f"{event.sequence:06d}.json"
        if target.exists(): raise RunCorruptError(self.run_dir, "immutable event already exists")
        _atomic_write_new(target, canonical_json_bytes(event.to_json()))
        self._events, self._snapshot = candidate, snapshot; _materialize(self.run_dir, snapshot, candidate)
        return snapshot
    def write_capture(self, action_id: str, name: str, data: bytes) -> str:
        if name not in {"stdout.bin", "stderr.log"} or action_id not in self._snapshot.actions: raise RunStoreError("unsafe capture target")
        directory = self.run_dir / "actions" / action_id; directory.mkdir(parents=True, exist_ok=True)
        _atomic_write_new(directory / name, data); return hashlib.sha256(data).hexdigest()


def initialize_research(request_path: Path, run_dir: Path) -> ResearchSnapshot:
    try:
        raw = json.loads(request_path.read_text(encoding="utf-8")); request = ResearchRequest.from_json(raw)
    except (OSError, ValueError, TypeError) as exc: raise RunStoreError("invalid research request") from exc
    if run_dir.exists() and any(item.name != ".run.lock" for item in run_dir.iterdir()): raise RunStoreError("research destination is not empty")
    run_dir.mkdir(parents=True, exist_ok=True); (run_dir / "events").mkdir(exist_ok=True)
    from datetime import datetime, timezone
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    event = ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": 1, "event_type": "research_initialized", "run_id": request.run_id, "occurred_at": occurred_at, "body": {"request": request.to_json()}})
    with acquire_run_lock(run_dir):
        _atomic_write_new(run_dir / "events" / "000001.json", canonical_json_bytes(event.to_json()))
        snapshot = replay_research_events((event,)); _materialize(run_dir, snapshot, (event,))
    return snapshot


@contextmanager
def open_research_run(run_dir: Path) -> Iterator[LockedResearchRun]:
    _require_existing_run_directory(run_dir); _require_safe_existing_lock_target(run_dir)
    with acquire_run_lock(run_dir):
        events = _read_events(run_dir)
        try: snapshot = replay_research_events(events)
        except ValueError as exc: raise RunCorruptError(run_dir, "invalid research event history") from exc
        _check_layout(run_dir, snapshot, events); _materialize(run_dir, snapshot, events)
        yield LockedResearchRun(run_dir, events, snapshot)


def load_research_status(run_dir: Path) -> ResearchSnapshot:
    with open_research_run(run_dir) as run: return run.snapshot
