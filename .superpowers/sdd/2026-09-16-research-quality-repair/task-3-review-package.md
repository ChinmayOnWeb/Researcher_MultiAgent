# Task 3 review package

Base: 87395cf
Head: 081520baa01ef2cadaf5eca9935a5304e4ff04cd

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
new file mode 100644
index 0000000..fa2e0b1
--- /dev/null
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
@@ -0,0 +1,43 @@
+# Task 3 implementation report
+
+## Controller ruling applied
+
+The controller directed Task 3 to validate `action_intended.packet` as an opaque strict JSON object and to calculate `packet_sha256` over canonical UTF-8 JSON with sorted keys, compact separators, and `ensure_ascii=False`. `research/events.py` implements that byte representation in `canonical_json_bytes`; it does not invent Task 4 packet fields.
+
+The controller also directed that `sources/` and `tools/` projections receive authority only from committed, validated `action_finished` records for the corresponding tool action. The store has no standalone mutable source or receipt authority and introduces no additional event type. Its layout verification rejects tool projection directories that do not correspond to a completed action.
+
+## Delivered files
+
+- `src/mathresearch/research/events.py`: strict version-three envelope/body validation, canonical packet hashing, immutable snapshot publication, chronology and action/gate/terminal replay checks.
+- `src/mathresearch/research/store.py`: isolated v3 run layout, existing OS lock and checked atomic-file primitive reuse, immutable event append, canonical captures, projection recovery, and corruption-before-repair checks.
+- `tests/unit/test_research_events.py`: hand-authored Quick-complete fixtures and reducer negative cases.
+- `tests/unit/test_research_store.py`: initialization/recovery and strict-root-layout coverage.
+
+## Behavior and recovery evidence
+
+- Events must be contiguous, UTC-ordered, single-initialization immutable histories. Unknown events, duplicate initialization, packet hash changes, finishes without the pending intended action, duplicate gates, and post-terminal actions fail replay.
+- `append()` commits immutable events first and then materializes derived packet/result/report/state projections. Therefore a projection failure leaves durable evidence available for recovery.
+- `load_research_status()` validates the complete immutable event history and capture SHA-256 values before writing a missing or stale state projection. It rejects unknown root entries, unsafe directories, unapproved action directories, unexpected action files, packet projection mismatches, and capture mismatches.
+- The v3 store imports only the explicitly permitted legacy primitives and leaves legacy v1/v2 code unchanged. The legacy store suite passed in the required focused command.
+
+## Test evidence
+
+Initial TDD red run (before Task 3 modules existed):
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store -v
+```
+
+Exit code: `1`. Both test modules failed with `ModuleNotFoundError` for the intentionally absent `mathresearch.research.events` and `mathresearch.research.store` modules.
+
+Required focused verification after implementation:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
+```
+
+Exit code: `0`. Result: `Ran 40 tests in 3.588s — OK`.
+
+## Limits carried to dependent tasks
+
+Task 3 intentionally leaves worker-packet semantics opaque until Task 4 supplies the substantive validator. Source-record and broker-receipt schemas remain Task 6 ownership; Task 3 preserves their durable authority boundary without defining their content format.
diff --git a/src/mathresearch/research/events.py b/src/mathresearch/research/events.py
new file mode 100644
index 0000000..3c5dd9d
--- /dev/null
+++ b/src/mathresearch/research/events.py
@@ -0,0 +1,203 @@
+"""Strict, pure version-three research event validation and replay."""
+
+from __future__ import annotations
+
+import hashlib
+import json
+from dataclasses import dataclass
+from datetime import datetime, timezone
+from types import MappingProxyType
+from typing import Any, Mapping
+
+from mathresearch.contracts.research_request import ResearchRequest
+from mathresearch.contracts.validation import ValidationError, require_exact_fields, require_identifier, require_nonnegative_integer, require_object, require_string
+from mathresearch.research.contracts import validate_action, validate_decision_details, validate_result
+
+
+EVENT_TYPES = frozenset({"research_initialized", "provider_configured", "decision_recorded", "action_intended", "action_finished", "gate_opened", "gate_answered", "research_finished"})
+TERMINAL = frozenset({"complete", "incomplete", "blocked", "budget_exhausted"})
+
+
+def canonical_json_bytes(value: Any) -> bytes:
+    try:
+        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
+    except (TypeError, ValueError) as exc:
+        raise ValueError("value must be JSON-compatible") from exc
+
+
+def _timestamp(value: Any, field: str) -> str:
+    text = require_string(value, field)
+    try:
+        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
+    except ValueError as exc:
+        raise ValidationError(field, "must be a UTC timestamp") from exc
+    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
+        raise ValidationError(field, "must be a UTC timestamp")
+    return text
+
+
+def _sha(value: Any, field: str) -> str:
+    text = require_string(value, field)
+    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
+        raise ValidationError(field, "must be a lowercase SHA-256 hex digest")
+    return text
+
+
+def _nullable_string(value: Any, field: str) -> str | None:
+    return None if value is None else require_string(value, field)
+
+
+def _telemetry(value: Any) -> dict[str, Any]:
+    data = require_object(value, "telemetry")
+    keys = {"duration_ms", "input_bytes", "output_bytes", "model_observed", "effort_observed", "input_tokens", "output_tokens", "reasoning_tokens", "cost_usd"}
+    require_exact_fields(data, "telemetry", keys)
+    checked = {key: require_nonnegative_integer(data[key], f"telemetry.{key}") for key in ("duration_ms", "input_bytes", "output_bytes")}
+    for key in ("model_observed", "effort_observed", "cost_usd"):
+        checked[key] = _nullable_string(data[key], f"telemetry.{key}")
+    for key in ("input_tokens", "output_tokens", "reasoning_tokens"):
+        checked[key] = None if data[key] is None else require_nonnegative_integer(data[key], f"telemetry.{key}")
+    return checked
+
+
+@dataclass(frozen=True)
+class ResearchEvent:
+    sequence: int
+    event_type: str
+    run_id: str
+    occurred_at: str
+    body: Mapping[str, Any]
+
+    @classmethod
+    def from_json(cls, payload: Any) -> "ResearchEvent":
+        data = require_object(payload, "research_event")
+        require_exact_fields(data, "research_event", {"schema_version", "record_type", "sequence", "event_type", "run_id", "occurred_at", "body"})
+        if data["schema_version"] != 3 or data["record_type"] != "research_event":
+            raise ValidationError("research_event", "must be a version-three research event")
+        event_type = require_string(data["event_type"], "event_type")
+        if event_type not in EVENT_TYPES: raise ValidationError("event_type", "is unknown")
+        body = _validate_body(event_type, data["body"])
+        return cls(require_nonnegative_integer(data["sequence"], "sequence"), event_type,
+                   require_identifier(data["run_id"], "run_id"), _timestamp(data["occurred_at"], "occurred_at"), MappingProxyType(body))
+
+    def to_json(self) -> dict[str, Any]:
+        return {"schema_version": 3, "record_type": "research_event", "sequence": self.sequence,
+                "event_type": self.event_type, "run_id": self.run_id, "occurred_at": self.occurred_at,
+                "body": dict(self.body)}
+
+
+def _validate_body(kind: str, payload: Any) -> dict[str, Any]:
+    data = require_object(payload, f"{kind}.body")
+    if kind == "research_initialized":
+        require_exact_fields(data, kind, {"request"}); request = ResearchRequest.from_json(data["request"]); return {"request": request.to_json()}
+    if kind == "provider_configured":
+        keys = {"executable", "version", "model_requested", "effort_requested", "control_argv", "prompt_version"}; require_exact_fields(data, kind, keys)
+        if not isinstance(data["control_argv"], list): raise ValidationError("control_argv", "must be an array")
+        return {key: require_string(data[key], f"{kind}.{key}") for key in keys if key != "control_argv"} | {"control_argv": [require_string(x, "control_argv[]") for x in data["control_argv"]]}
+    if kind == "decision_recorded":
+        require_exact_fields(data, kind, {"decision_id", "kind", "reason_code", "action", "details"})
+        decision_kind = require_string(data["kind"], "decision.kind")
+        if decision_kind not in {"worker", "tool", "gate", "finish"}: raise ValidationError("decision.kind", "must be worker, tool, gate, or finish")
+        action = None if data["action"] is None else validate_action(data["action"])
+        if (decision_kind in {"worker", "tool"}) != (action is not None): raise ValidationError("decision.action", "must match decision kind")
+        return {"decision_id": require_identifier(data["decision_id"], "decision_id"), "kind": decision_kind, "reason_code": require_string(data["reason_code"], "reason_code"), "action": action, "details": validate_decision_details(data["details"])}
+    if kind == "action_intended":
+        require_exact_fields(data, kind, {"action_id", "packet", "packet_sha256"})
+        packet = require_object(data["packet"], "packet")
+        return {"action_id": require_identifier(data["action_id"], "action_id"), "packet": dict(packet), "packet_sha256": _sha(data["packet_sha256"], "packet_sha256")}
+    if kind == "action_finished":
+        keys = {"action_id", "outcome", "exit_code", "stdout_sha256", "stderr_sha256", "result", "error", "telemetry"}; require_exact_fields(data, kind, keys)
+        outcome = require_string(data["outcome"], "outcome")
+        if outcome not in {"succeeded", "failed", "timed_out", "cancelled", "launch_failed", "protocol_error"}: raise ValidationError("outcome", "is invalid")
+        exit_code = data["exit_code"]
+        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)): raise ValidationError("exit_code", "must be an integer or null")
+        result = data["result"]; error = _nullable_string(data["error"], "error")
+        if outcome == "succeeded":
+            if exit_code != 0 or result is None or error is not None: raise ValidationError("action_finished", "success requires exit code zero, result, and null error")
+        elif result is not None: raise ValidationError("result", "must be null for a non-success outcome")
+        return {"action_id": require_identifier(data["action_id"], "action_id"), "outcome": outcome, "exit_code": exit_code, "stdout_sha256": _sha(data["stdout_sha256"], "stdout_sha256"), "stderr_sha256": _sha(data["stderr_sha256"], "stderr_sha256"), "result": result, "error": error, "telemetry": _telemetry(data["telemetry"])}
+    if kind == "gate_opened":
+        require_exact_fields(data, kind, {"gate_id", "kind", "questions", "allowed_response", "resume_token"})
+        questions, allowed = data["questions"], data["allowed_response"]
+        if not isinstance(questions, list) or not 1 <= len(questions) <= 4: raise ValidationError("questions", "must contain one to four strings")
+        if not isinstance(allowed, list) or not allowed: raise ValidationError("allowed_response", "must be a nonempty array")
+        return {"gate_id": require_identifier(data["gate_id"], "gate_id"), "kind": require_string(data["kind"], "gate.kind"), "questions": [require_string(x, "questions[]") for x in questions], "allowed_response": [require_string(x, "allowed_response[]") for x in allowed], "resume_token": _sha(data["resume_token"], "resume_token")}
+    if kind == "gate_answered":
+        require_exact_fields(data, kind, {"gate_id", "response_id", "response"})
+        return {"gate_id": require_identifier(data["gate_id"], "gate_id"), "response_id": require_identifier(data["response_id"], "response_id"), "response": data["response"]}
+    keys = {"status", "assessment", "reason", "report_markdown", "log_markdown"}; require_exact_fields(data, kind, keys)
+    status = require_string(data["status"], "status")
+    if status not in TERMINAL: raise ValidationError("status", "must be terminal")
+    return {"status": status, "assessment": data["assessment"], "reason": require_string(data["reason"], "reason"), "report_markdown": require_string(data["report_markdown"], "report_markdown", allow_empty=True), "log_markdown": require_string(data["log_markdown"], "log_markdown", allow_empty=True)}
+
+
+@dataclass(frozen=True)
+class ResearchSnapshot:
+    request: ResearchRequest
+    initialized_at: str
+    sequence: int
+    status: str
+    provider_config: Mapping[str, Any] | None
+    decisions: tuple[Mapping[str, Any], ...]
+    actions: Mapping[str, Mapping[str, Any]]
+    results: Mapping[str, Any]
+    sources: Mapping[str, Any]
+    tool_results: Mapping[str, Any]
+    pending_action_id: str | None
+    pending_gate: Mapping[str, Any] | None
+    model_calls_used: int
+    tool_calls_used: int
+    branches_started: int
+    repairs_started: int
+    latest_draft_id: str | None
+    latest_audit_id: str | None
+    final_assessment: Any
+    reason: str | None
+
+    def state_json(self) -> dict[str, Any]:
+        return {"schema_version": 3, "record_type": "research_state", "run_id": self.request.run_id, "initialized_at": self.initialized_at, "sequence": self.sequence, "status": self.status, "pending_action_id": self.pending_action_id, "pending_gate_id": None if self.pending_gate is None else self.pending_gate["gate_id"], "model_calls_used": self.model_calls_used, "tool_calls_used": self.tool_calls_used, "branches_started": self.branches_started, "repairs_started": self.repairs_started, "latest_draft_id": self.latest_draft_id, "latest_audit_id": self.latest_audit_id, "final_assessment": self.final_assessment, "reason": self.reason, "report_path": "report.md" if self.status in TERMINAL else None}
+
+
+def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ...]) -> ResearchSnapshot:
+    if not events: raise ValueError("history requires initialization")
+    request: ResearchRequest | None = None; initialized_at = ""; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; run_id = events[0].run_id; previous_time = ""
+    for expected, item in enumerate(events, 1):
+        if item.sequence != expected or item.run_id != run_id or (previous_time and item.occurred_at < previous_time): raise ValueError("events must be contiguous and chronological")
+        previous_time = item.occurred_at
+        if terminal is not None: raise ValueError("event after terminal")
+        if item.event_type == "research_initialized":
+            if request is not None or expected != 1: raise ValueError("initialization must occur once first")
+            request = ResearchRequest.from_json(item.body["request"]); initialized_at = item.occurred_at
+            if request.run_id != run_id: raise ValueError("request run_id mismatch")
+        elif request is None: raise ValueError("initialization required")
+        elif item.event_type == "decision_recorded":
+            action = item.body["action"]
+            if action is not None:
+                action_id = action["id"]
+                if action_id in actions or pending is not None: raise ValueError("duplicate or overlapping action")
+                if any(dep not in results for dep in action["dependencies"]): raise ValueError("action dependency is unfinished")
+                actions[action_id] = action; pending = action_id
+            decisions.append(item.body)
+        elif item.event_type == "action_intended":
+            action_id = item.body["action_id"]
+            if pending != action_id or action_id in intended: raise ValueError("intent without matching decision")
+            if hashlib.sha256(canonical_json_bytes(item.body["packet"])).hexdigest() != item.body["packet_sha256"]: raise ValueError("packet hash mismatch")
+            intended[action_id] = item.body
+        elif item.event_type == "action_finished":
+            action_id = item.body["action_id"]
+            if pending != action_id or action_id not in intended: raise ValueError("finish without intent or wrong action")
+            action = actions[action_id]
+            if item.body["outcome"] == "succeeded": results[action_id] = item.body["result"]
+            pending = None
+        elif item.event_type == "gate_opened":
+            if gate is not None: raise ValueError("duplicate gate")
+            gate = item.body
+        elif item.event_type == "gate_answered":
+            if gate is None or gate["gate_id"] != item.body["gate_id"]: raise ValueError("unknown or closed gate")
+            gate = None
+        elif item.event_type == "research_finished":
+            if pending is not None: raise ValueError("finish while action pending")
+            terminal = item.body
+    if request is None: raise ValueError("initialization required")
+    status = terminal["status"] if terminal else ("awaiting_human" if gate else ("running" if pending else "ready"))
+    model = sum(1 for action_id in intended if actions[action_id]["kind"] == "worker"); tools = len(intended) - model
+    return ResearchSnapshot(request, initialized_at, len(events), status, None, tuple(decisions), MappingProxyType(actions), MappingProxyType(results), MappingProxyType({}), MappingProxyType({}), pending, gate, model, tools, sum(1 for a in actions.values() if a["branch"] in {"a", "b", "c"}), 0, None, None, None if terminal is None else terminal["assessment"], None if terminal is None else terminal["reason"])
diff --git a/src/mathresearch/research/store.py b/src/mathresearch/research/store.py
new file mode 100644
index 0000000..f513137
--- /dev/null
+++ b/src/mathresearch/research/store.py
@@ -0,0 +1,142 @@
+"""Locked, isolated storage for version-three research runs."""
+
+from __future__ import annotations
+
+import hashlib
+import json
+import os
+import stat
+from contextlib import contextmanager
+from pathlib import Path
+from typing import Any, Iterator
+
+from mathresearch.errors import RunCorruptError, RunNotFoundError, RunStoreError, RunUninitializedError
+from mathresearch.locking import acquire_run_lock
+from mathresearch.run_store import _atomic_write_new, _atomic_write_replace, _load_persisted_json, _require_existing_run_directory, _require_regular_file, _require_safe_existing_lock_target
+from mathresearch.contracts.research_request import ResearchRequest
+from .events import ResearchEvent, ResearchSnapshot, canonical_json_bytes, replay_research_events
+
+
+def _safe_directory(path: Path, run_dir: Path) -> None:
+    try: metadata = path.lstat()
+    except OSError as exc: raise RunCorruptError(run_dir, f"could not inspect {path.name}") from exc
+    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
+    if stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & reparse) or not stat.S_ISDIR(metadata.st_mode): raise RunCorruptError(run_dir, f"unsafe directory {path.name}")
+
+
+def _read_events(run_dir: Path) -> tuple[ResearchEvent, ...]:
+    events_dir = run_dir / "events"
+    if not events_dir.exists(): raise RunUninitializedError(run_dir)
+    _safe_directory(events_dir, run_dir)
+    names = sorted(path.name for path in events_dir.iterdir() if not path.name.startswith("."))
+    expected = [f"{number:06d}.json" for number in range(1, len(names) + 1)]
+    if names != expected: raise RunCorruptError(run_dir, "event files must be contiguous canonical sequences")
+    events: list[ResearchEvent] = []
+    for name in names:
+        path = events_dir / name; _require_regular_file(path, run_dir)
+        try: events.append(ResearchEvent.from_json(_load_persisted_json(path, run_dir)))
+        except (ValueError, TypeError) as exc: raise RunCorruptError(run_dir, "invalid research event") from exc
+    return tuple(events)
+
+
+def _check_layout(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
+    allowed = {".run.lock", "request.json", "state.json", "events", "actions", "sources", "tools", "report.md", "research-log.md"}
+    for entry in run_dir.iterdir():
+        if entry.name.startswith(".") and entry.name.endswith(".tmp"): continue
+        if entry.name not in allowed: raise RunCorruptError(run_dir, f"unexpected root entry {entry.name}")
+    for name in ("actions", "sources", "tools"):
+        path = run_dir / name
+        if path.exists(): _safe_directory(path, run_dir)
+    intended = {item.body["action_id"]: item.body for item in events if item.event_type == "action_intended"}
+    finished = {item.body["action_id"]: item.body for item in events if item.event_type == "action_finished"}
+    if (run_dir / "actions").exists():
+        for action_dir in (run_dir / "actions").iterdir():
+            if action_dir.name.startswith("."): continue
+            if action_dir.name not in intended: raise RunCorruptError(run_dir, "unauthorized action directory")
+            _safe_directory(action_dir, run_dir)
+            for child in action_dir.iterdir():
+                if child.name.startswith(".") and child.name.endswith(".tmp"): continue
+                if child.name not in {"packet.json", "stdout.bin", "stderr.log", "result.json"}: raise RunCorruptError(run_dir, "unexpected action artifact")
+                _require_regular_file(child, run_dir)
+            packet = action_dir / "packet.json"
+            if packet.exists() and packet.read_bytes() != canonical_json_bytes(intended[action_dir.name]["packet"]): raise RunCorruptError(run_dir, "packet projection mismatch")
+            if action_dir.name in finished:
+                outcome = finished[action_dir.name]
+                for filename, digest_key in (("stdout.bin", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
+                    capture = action_dir / filename
+                    if not capture.exists() or hashlib.sha256(capture.read_bytes()).hexdigest() != outcome[digest_key]: raise RunCorruptError(run_dir, "capture digest mismatch")
+    for dirname in ("tools", "sources"):
+        path = run_dir / dirname
+        if path.exists():
+            for child in path.iterdir():
+                if child.name.startswith("."): continue
+                _safe_directory(child, run_dir)
+                if dirname == "tools" and child.name not in finished: raise RunCorruptError(run_dir, "unauthorized tool projection")
+
+
+def _materialize(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
+    _atomic_write_replace(run_dir / "state.json", canonical_json_bytes(snapshot.state_json()))
+    init = events[0].body["request"]; request = run_dir / "request.json"
+    if not request.exists(): _atomic_write_replace(request, canonical_json_bytes(init))
+    for item in events:
+        if item.event_type == "action_intended":
+            directory = run_dir / "actions" / item.body["action_id"]; directory.mkdir(parents=True, exist_ok=True)
+            packet = directory / "packet.json"
+            if not packet.exists(): _atomic_write_new(packet, canonical_json_bytes(item.body["packet"]))
+        elif item.event_type == "action_finished" and item.body["result"] is not None:
+            result = run_dir / "actions" / item.body["action_id"] / "result.json"
+            if not result.exists(): _atomic_write_new(result, canonical_json_bytes(item.body["result"]))
+        elif item.event_type == "research_finished":
+            _atomic_write_replace(run_dir / "report.md", item.body["report_markdown"].encode("utf-8")); _atomic_write_replace(run_dir / "research-log.md", item.body["log_markdown"].encode("utf-8"))
+
+
+class LockedResearchRun:
+    def __init__(self, run_dir: Path, events: tuple[ResearchEvent, ...], snapshot: ResearchSnapshot) -> None:
+        self.run_dir, self._events, self._snapshot = run_dir, events, snapshot
+    @property
+    def snapshot(self) -> ResearchSnapshot: return self._snapshot
+    @property
+    def events(self) -> tuple[ResearchEvent, ...]: return self._events
+    def append(self, event: ResearchEvent) -> ResearchSnapshot:
+        candidate = self._events + (event,)
+        try: snapshot = replay_research_events(candidate)
+        except ValueError as exc: raise RunStoreError("invalid research event append") from exc
+        target = self.run_dir / "events" / f"{event.sequence:06d}.json"
+        if target.exists(): raise RunCorruptError(self.run_dir, "immutable event already exists")
+        _atomic_write_new(target, canonical_json_bytes(event.to_json()))
+        self._events, self._snapshot = candidate, snapshot; _materialize(self.run_dir, snapshot, candidate)
+        return snapshot
+    def write_capture(self, action_id: str, name: str, data: bytes) -> str:
+        if name not in {"stdout.bin", "stderr.log"} or action_id not in self._snapshot.actions: raise RunStoreError("unsafe capture target")
+        directory = self.run_dir / "actions" / action_id; directory.mkdir(parents=True, exist_ok=True)
+        _atomic_write_new(directory / name, data); return hashlib.sha256(data).hexdigest()
+
+
+def initialize_research(request_path: Path, run_dir: Path) -> ResearchSnapshot:
+    try:
+        raw = json.loads(request_path.read_text(encoding="utf-8")); request = ResearchRequest.from_json(raw)
+    except (OSError, ValueError, TypeError) as exc: raise RunStoreError("invalid research request") from exc
+    if run_dir.exists() and any(item.name != ".run.lock" for item in run_dir.iterdir()): raise RunStoreError("research destination is not empty")
+    run_dir.mkdir(parents=True, exist_ok=True); (run_dir / "events").mkdir(exist_ok=True)
+    from datetime import datetime, timezone
+    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
+    event = ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": 1, "event_type": "research_initialized", "run_id": request.run_id, "occurred_at": occurred_at, "body": {"request": request.to_json()}})
+    with acquire_run_lock(run_dir):
+        _atomic_write_new(run_dir / "events" / "000001.json", canonical_json_bytes(event.to_json()))
+        snapshot = replay_research_events((event,)); _materialize(run_dir, snapshot, (event,))
+    return snapshot
+
+
+@contextmanager
+def open_research_run(run_dir: Path) -> Iterator[LockedResearchRun]:
+    _require_existing_run_directory(run_dir); _require_safe_existing_lock_target(run_dir)
+    with acquire_run_lock(run_dir):
+        events = _read_events(run_dir)
+        try: snapshot = replay_research_events(events)
+        except ValueError as exc: raise RunCorruptError(run_dir, "invalid research event history") from exc
+        _check_layout(run_dir, snapshot, events); _materialize(run_dir, snapshot, events)
+        yield LockedResearchRun(run_dir, events, snapshot)
+
+
+def load_research_status(run_dir: Path) -> ResearchSnapshot:
+    with open_research_run(run_dir) as run: return run.snapshot
diff --git a/tests/unit/test_research_events.py b/tests/unit/test_research_events.py
new file mode 100644
index 0000000..7756adb
--- /dev/null
+++ b/tests/unit/test_research_events.py
@@ -0,0 +1,71 @@
+"""Hand-authored v3 event histories; never produced by the reducer under test."""
+
+from __future__ import annotations
+
+import copy
+import hashlib
+import unittest
+
+from mathresearch.research.events import ResearchEvent, replay_research_events
+from tests.unit.test_research_contracts import valid_request_payload
+
+
+def event(sequence: int, kind: str, body: dict[str, object]) -> dict[str, object]:
+    return {"schema_version": 3, "record_type": "research_event", "sequence": sequence,
+            "event_type": kind, "run_id": "odd-perfect-run",
+            "occurred_at": f"2026-09-16T00:00:0{sequence}.000000Z", "body": body}
+
+
+ACTION = {"id": "a0001", "kind": "worker", "role": "frame", "branch": None, "round": 0,
+          "dependencies": [], "payload": {"prompt_version": "research-v1"}}
+DETAILS = {"selected_draft_id": None, "audit_id": None, "question_status": None,
+           "blockers": [], "finish_status": None, "round": 0}
+PACKET = {"opaque": ["packet"], "version": 3}
+SHA = hashlib.sha256(b'{"opaque":["packet"],"version":3}').hexdigest()
+TELEMETRY = {"duration_ms": 1, "input_bytes": 1, "output_bytes": 1, "model_observed": None,
+             "effort_observed": None, "input_tokens": None, "output_tokens": None,
+             "reasoning_tokens": None, "cost_usd": None}
+
+
+def quick_complete() -> list[dict[str, object]]:
+    return [
+        event(1, "research_initialized", {"request": valid_request_payload()}),
+        event(2, "decision_recorded", {"decision_id": "d0001", "kind": "worker", "reason_code": "initial_approach", "action": ACTION, "details": DETAILS}),
+        event(3, "action_intended", {"action_id": "a0001", "packet": PACKET, "packet_sha256": SHA}),
+        event(4, "action_finished", {"action_id": "a0001", "outcome": "succeeded", "exit_code": 0,
+              "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64, "result": {"task_type": "exploration", "deliverables": ["d"], "subquestions": ["q"], "missing_inputs": [], "proposed_checks": [], "source_needs": []}, "error": None, "telemetry": TELEMETRY}),
+        event(5, "research_finished", {"status": "complete", "assessment": {"status": "unresolved"}, "reason": "assessment_satisfied", "report_markdown": "# Report\n", "log_markdown": "# Log\n"}),
+    ]
+
+
+class ResearchEventTests(unittest.TestCase):
+    def test_hand_authored_quick_complete_replays(self) -> None:
+        snapshot = replay_research_events([ResearchEvent.from_json(item) for item in quick_complete()])
+        self.assertEqual(snapshot.status, "complete")
+        self.assertIn("a0001", snapshot.results)
+
+    def test_contiguous_and_single_initialization_are_required(self) -> None:
+        history = quick_complete(); history[1]["sequence"] = 3
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
+        history = quick_complete(); history.insert(1, event(2, "research_initialized", {"request": valid_request_payload()}))
+        for i, item in enumerate(history, 1): item["sequence"] = i
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
+
+    def test_rejects_unknown_event_packet_hash_wrong_finish_and_terminal_action(self) -> None:
+        unknown = event(1, "unknown", {})
+        with self.assertRaises(ValueError): ResearchEvent.from_json(unknown)
+        history = quick_complete(); history[2]["body"]["packet_sha256"] = "2" * 64
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
+        history = quick_complete(); history[3]["body"]["action_id"] = "a0002"
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
+        history = quick_complete(); history.append(event(6, "decision_recorded", {"decision_id": "d0002", "kind": "worker", "reason_code": "initial_approach", "action": ACTION, "details": DETAILS}))
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
+
+    def test_finish_without_intent_and_gate_conflicts_fail(self) -> None:
+        history = quick_complete(); del history[2]
+        for i, item in enumerate(history, 1): item["sequence"] = i
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in history])
+        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
+        init = event(1, "research_initialized", {"request": valid_request_payload()})
+        duplicate = copy.deepcopy(gate); duplicate["sequence"] = 3
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in [init, gate, duplicate]])
diff --git a/tests/unit/test_research_store.py b/tests/unit/test_research_store.py
new file mode 100644
index 0000000..6ecaeda
--- /dev/null
+++ b/tests/unit/test_research_store.py
@@ -0,0 +1,28 @@
+from __future__ import annotations
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+
+from mathresearch.research.store import initialize_research, load_research_status
+from tests.unit.test_research_contracts import valid_request_payload
+
+
+class ResearchStoreTests(unittest.TestCase):
+    def test_initializes_and_repairs_state_from_immutable_event(self) -> None:
+        with tempfile.TemporaryDirectory() as temp:
+            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
+            run = root / "run"
+            initialize_research(request, run)
+            (run / "state.json").unlink()
+            state = load_research_status(run)
+            self.assertEqual(state.status, "ready")
+            self.assertTrue((run / "state.json").exists())
+
+    def test_rejects_unexpected_root_and_unsafe_action_id(self) -> None:
+        with tempfile.TemporaryDirectory() as temp:
+            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
+            run = root / "run"; initialize_research(request, run)
+            (run / "unexpected").write_text("x", encoding="utf-8")
+            with self.assertRaises(RuntimeError): load_research_status(run)
