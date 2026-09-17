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
from mathresearch.run_store import _atomic_write_new, _atomic_write_replace, _documented_event_temporary_target, _documented_temporary_target, _load_persisted_json, _require_existing_run_directory, _require_regular_file, _require_safe_existing_lock_target, _verify_temporary_hardlink_aliases
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
    entries: dict[str, Path] = {}; temporary: list[tuple[Path, str]] = []
    for path in events_dir.iterdir():
        target = _documented_event_temporary_target(path.name)
        if target is not None:
            _require_regular_file(path, run_dir); temporary.append((path, target)); continue
        if len(path.name) != 11 or not path.name.endswith(".json") or not path.name[:6].isdigit(): raise RunCorruptError(run_dir, "unexpected event artifact")
        _require_regular_file(path, run_dir); entries[path.name] = path
    names = sorted(entries)
    expected = [f"{number:06d}.json" for number in range(1, len(names) + 1)]
    if names != expected: raise RunCorruptError(run_dir, "event files must be contiguous canonical sequences")
    events: list[ResearchEvent] = []
    for name in names:
        path = entries[name]
        try: events.append(ResearchEvent.from_json(_load_persisted_json(path, run_dir)))
        except (ValueError, TypeError) as exc: raise RunCorruptError(run_dir, "invalid research event") from exc
    _verify_temporary_hardlink_aliases(run_dir, entries, temporary, immutable_targets=frozenset(entries))
    return tuple(events)


def _checked_children(directory: Path, run_dir: Path, *, files: set[str], directories: set[str], immutable: set[str] = set()) -> dict[str, Path]:
    entries: dict[str, Path] = {}; temporary: list[tuple[Path, str]] = []
    for path in directory.iterdir():
        target = _documented_temporary_target(path.name, tuple(files))
        if target is not None:
            _require_regular_file(path, run_dir); temporary.append((path, target)); continue
        if path.name in files:
            _require_regular_file(path, run_dir)
        elif path.name in directories:
            _safe_directory(path, run_dir)
        else: raise RunCorruptError(run_dir, f"unexpected artifact {path.name}")
        entries[path.name] = path
    _verify_temporary_hardlink_aliases(run_dir, entries, temporary, immutable_targets=frozenset(immutable))
    return entries


def _check_layout(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
    allowed = {".run.lock", "request.json", "state.json", "events", "actions", "sources", "tools", "report.md", "research-log.md"}
    root = _checked_children(run_dir, run_dir, files={".run.lock", "request.json", "state.json", "report.md", "research-log.md"}, directories={"events", "actions", "sources", "tools"}, immutable={"request.json"})
    for name in ("actions", "sources", "tools"):
        path = run_dir / name
        if path.exists(): _safe_directory(path, run_dir)
    intended = {item.body["action_id"]: item.body for item in events if item.event_type == "action_intended"}
    finished = {item.body["action_id"]: item.body for item in events if item.event_type == "action_finished"}
    for action_id, outcome in finished.items():
        action_dir = run_dir / "actions" / action_id
        if not action_dir.exists():
            raise RunCorruptError(run_dir, "finished action capture directory is missing")
        _safe_directory(action_dir, run_dir)
        for filename, digest_key in (("stdout.bin", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
            capture = action_dir / filename
            if not capture.exists() or not capture.is_file() or hashlib.sha256(capture.read_bytes()).hexdigest() != outcome[digest_key]:
                raise RunCorruptError(run_dir, "capture digest mismatch")
    if (run_dir / "actions").exists():
        for action_dir in _checked_children(run_dir / "actions", run_dir, files=set(), directories=set(intended)).values():
            if action_dir.name not in intended: raise RunCorruptError(run_dir, "unauthorized action directory")
            _safe_directory(action_dir, run_dir)
            _checked_children(action_dir, run_dir, files={"packet.json", "stdout.bin", "stderr.log", "result.json"}, directories=set(), immutable={"packet.json", "stdout.bin", "stderr.log", "result.json"})
            packet = action_dir / "packet.json"
            if packet.exists() and packet.read_bytes() != canonical_json_bytes(intended[action_dir.name]["packet"]): raise RunCorruptError(run_dir, "packet projection mismatch")
    successful_tools = {action_id: outcome for action_id, outcome in finished.items() if outcome["outcome"] == "succeeded" and snapshot.actions[action_id]["kind"] == "tool"}
    if (run_dir / "tools").exists():
        for action_id, directory in _checked_children(run_dir / "tools", run_dir, files=set(), directories=set(successful_tools)).items():
            receipt = _checked_children(directory, run_dir, files={"receipt.json"}, directories=set(), immutable={"receipt.json"}).get("receipt.json")
            if receipt is None or receipt.read_bytes() != canonical_json_bytes(successful_tools[action_id]["result"]): raise RunCorruptError(run_dir, "invalid tool receipt projection")
    source_results = {result["source"]["id"]: result["source"] for action_id, result in snapshot.results.items() if snapshot.actions[action_id]["kind"] == "tool" and snapshot.actions[action_id]["role"] == "fetch_source" and isinstance(result, dict) and isinstance(result.get("source"), dict) and isinstance(result["source"].get("id"), str)}
    if (run_dir / "sources").exists():
        for source_id, directory in _checked_children(run_dir / "sources", run_dir, files=set(), directories=set(source_results)).items():
            source = _checked_children(directory, run_dir, files={"source.json"}, directories=set(), immutable={"source.json"}).get("source.json")
            if source is None or source.read_bytes() != canonical_json_bytes(source_results[source_id]): raise RunCorruptError(run_dir, "invalid source projection")


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
            action = snapshot.actions[item.body["action_id"]]
            if action["kind"] == "tool" and item.body["outcome"] == "succeeded":
                directory = run_dir / "tools" / item.body["action_id"]; directory.mkdir(parents=True, exist_ok=True)
                receipt = directory / "receipt.json"
                if not receipt.exists(): _atomic_write_new(receipt, canonical_json_bytes(item.body["result"]))
                source = item.body["result"].get("source") if isinstance(item.body["result"], dict) else None
                if action["role"] == "fetch_source" and isinstance(source, dict) and isinstance(source.get("id"), str):
                    source_dir = run_dir / "sources" / source["id"]; source_dir.mkdir(parents=True, exist_ok=True)
                    source_path = source_dir / "source.json"
                    if not source_path.exists(): _atomic_write_new(source_path, canonical_json_bytes(source))
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
    run_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    event = ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": 1, "event_type": "research_initialized", "run_id": request.run_id, "occurred_at": occurred_at, "body": {"request": request.to_json()}})
    with acquire_run_lock(run_dir):
        if any(item.name != ".run.lock" for item in run_dir.iterdir()): raise RunStoreError("research destination is not empty")
        (run_dir / "events").mkdir(exist_ok=True)
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
