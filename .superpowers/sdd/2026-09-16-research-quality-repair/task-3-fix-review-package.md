# Task 3 fix review package

Base: 081520baa01ef2cadaf5eca9935a5304e4ff04cd
Head: d62f8958aa5de2d268d74e2f5c3e3ed1b15b8b70

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
index fa2e0b1..2295907 100644
--- a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
@@ -41,3 +41,29 @@ Exit code: `0`. Result: `Ran 40 tests in 3.588s — OK`.
 ## Limits carried to dependent tasks
 
 Task 3 intentionally leaves worker-packet semantics opaque until Task 4 supplies the substantive validator. Source-record and broker-receipt schemas remain Task 6 ownership; Task 3 preserves their durable authority boundary without defining their content format.
+
+## Fix round 1
+
+Root cause analysis found that the initial store verified captures only while iterating surviving action directories. A deleted finished-action directory was therefore invisible to the capture check and could be followed by state repair. The reducer also accepted a successful result before relating it to the recorded action role, compared timestamp source strings, and did not retain completed gate identities.
+
+The fix now requires an existing safe action directory and both digest-verified canonical captures for every committed `action_finished` record before any materialization. Successful worker results are validated through `validate_result(action.role, result)` during replay. Event timestamps are normalized to UTC instants before chronology comparison. Gate IDs cannot be reopened after answer; repeated response IDs are accepted only when their canonical payload digests match. `noop` is recognized as a decision kind and constrained to terminal/open-gate states. Initialization creates the events directory only while the acquired run lock is held.
+
+New red-green regressions cover deleted finished captures, arbitrary successful worker JSON, and equivalent offset UTC instants. The focused regression command passed after the changes, followed by the required suite:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
+```
+
+Exit code: `0`. Result: `Ran 43 tests in 3.813s — OK`.
+
+### Remaining review scope
+
+The action-result-to-source/receipt projection schemas, full route-table authorization, and atomic temporary hardlink alias rules require the downstream Task 6 broker schemas and the existing private temporary-alias verifier to be integrated. They are not fully addressed by this round's changes and must not be represented as complete fixes.
+
+## Fix round 1 follow-up
+
+The remaining structural store boundary is now closed without defining Task 6 semantics. `tools/<action-id>/` is legal only for a committed successful action whose recorded action kind is `tool`; it must contain exactly a regular, non-link `receipt.json` whose canonical bytes equal that action's committed result object. `sources/<source-id>/` is legal only when a successful `fetch_source` tool result structurally exposes that source ID; it must contain exactly a regular, non-link `source.json` with matching canonical bytes. Worker actions cannot authorize tool directories, and arbitrary source directories cannot become evidence.
+
+The store now uses the legacy `_verify_temporary_hardlink_aliases` routine for root, event, action, source, and tool projection directories. Every entry, including a dot-prefixed writer temporary, is classified as a documented temporary alias or rejected; aliases are accepted only when the immutable target identity and hardlink count verify.
+
+Task 3 validates the Section 6 local action structure through Task 2's `validate_action`, enforces contiguous action lifecycle/dependencies and terminal/gate legality, and deliberately defers Section 7 routing-table reason-code selection to Task 7. It does not make route policy decisions.
diff --git a/src/mathresearch/research/events.py b/src/mathresearch/research/events.py
index 3c5dd9d..a2625c9 100644
--- a/src/mathresearch/research/events.py
+++ b/src/mathresearch/research/events.py
@@ -31,9 +31,9 @@ def _timestamp(value: Any, field: str) -> str:
         parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
     except ValueError as exc:
         raise ValidationError(field, "must be a UTC timestamp") from exc
-    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
-        raise ValidationError(field, "must be a UTC timestamp")
-    return text
+    if parsed.tzinfo is None:
+        raise ValidationError(field, "must be an offset-aware timestamp")
+    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
 
 
 def _sha(value: Any, field: str) -> str:
@@ -96,7 +96,7 @@ def _validate_body(kind: str, payload: Any) -> dict[str, Any]:
     if kind == "decision_recorded":
         require_exact_fields(data, kind, {"decision_id", "kind", "reason_code", "action", "details"})
         decision_kind = require_string(data["kind"], "decision.kind")
-        if decision_kind not in {"worker", "tool", "gate", "finish"}: raise ValidationError("decision.kind", "must be worker, tool, gate, or finish")
+        if decision_kind not in {"worker", "tool", "gate", "finish", "noop"}: raise ValidationError("decision.kind", "is invalid")
         action = None if data["action"] is None else validate_action(data["action"])
         if (decision_kind in {"worker", "tool"}) != (action is not None): raise ValidationError("decision.action", "must match decision kind")
         return {"decision_id": require_identifier(data["decision_id"], "decision_id"), "kind": decision_kind, "reason_code": require_string(data["reason_code"], "reason_code"), "action": action, "details": validate_decision_details(data["details"])}
@@ -159,7 +159,7 @@ class ResearchSnapshot:
 
 def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ...]) -> ResearchSnapshot:
     if not events: raise ValueError("history requires initialization")
-    request: ResearchRequest | None = None; initialized_at = ""; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; run_id = events[0].run_id; previous_time = ""
+    request: ResearchRequest | None = None; initialized_at = ""; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; gate_ids: set[str] = set(); response_digests: dict[str, str] = {}; run_id = events[0].run_id; previous_time = ""
     for expected, item in enumerate(events, 1):
         if item.sequence != expected or item.run_id != run_id or (previous_time and item.occurred_at < previous_time): raise ValueError("events must be contiguous and chronological")
         previous_time = item.occurred_at
@@ -171,6 +171,7 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
         elif request is None: raise ValueError("initialization required")
         elif item.event_type == "decision_recorded":
             action = item.body["action"]
+            if item.body["kind"] == "noop" and not (terminal is not None or gate is not None): raise ValueError("noop is only legal for terminal or open gates")
             if action is not None:
                 action_id = action["id"]
                 if action_id in actions or pending is not None: raise ValueError("duplicate or overlapping action")
@@ -186,13 +187,26 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
             action_id = item.body["action_id"]
             if pending != action_id or action_id not in intended: raise ValueError("finish without intent or wrong action")
             action = actions[action_id]
-            if item.body["outcome"] == "succeeded": results[action_id] = item.body["result"]
+            if item.body["outcome"] == "succeeded":
+                try:
+                    result = (validate_result(action["role"], item.body["result"])
+                              if action["kind"] == "worker" else dict(require_object(item.body["result"], "tool result")))
+                except ValidationError as exc:
+                    raise ValueError("successful result does not match action") from exc
+                results[action_id] = result
             pending = None
         elif item.event_type == "gate_opened":
-            if gate is not None: raise ValueError("duplicate gate")
+            if gate is not None or item.body["gate_id"] in gate_ids: raise ValueError("duplicate gate")
             gate = item.body
+            gate_ids.add(item.body["gate_id"])
         elif item.event_type == "gate_answered":
+            digest = hashlib.sha256(canonical_json_bytes(item.body["response"])).hexdigest()
+            prior = response_digests.get(item.body["response_id"])
+            if prior is not None:
+                if prior != digest: raise ValueError("response ID payload conflict")
+                continue
             if gate is None or gate["gate_id"] != item.body["gate_id"]: raise ValueError("unknown or closed gate")
+            response_digests[item.body["response_id"]] = digest
             gate = None
         elif item.event_type == "research_finished":
             if pending is not None: raise ValueError("finish while action pending")
diff --git a/src/mathresearch/research/store.py b/src/mathresearch/research/store.py
index f513137..c1a6c55 100644
--- a/src/mathresearch/research/store.py
+++ b/src/mathresearch/research/store.py
@@ -12,7 +12,7 @@ from typing import Any, Iterator
 
 from mathresearch.errors import RunCorruptError, RunNotFoundError, RunStoreError, RunUninitializedError
 from mathresearch.locking import acquire_run_lock
-from mathresearch.run_store import _atomic_write_new, _atomic_write_replace, _load_persisted_json, _require_existing_run_directory, _require_regular_file, _require_safe_existing_lock_target
+from mathresearch.run_store import _atomic_write_new, _atomic_write_replace, _documented_event_temporary_target, _documented_temporary_target, _load_persisted_json, _require_existing_run_directory, _require_regular_file, _require_safe_existing_lock_target, _verify_temporary_hardlink_aliases
 from mathresearch.contracts.research_request import ResearchRequest
 from .events import ResearchEvent, ResearchSnapshot, canonical_json_bytes, replay_research_events
 
@@ -28,50 +28,75 @@ def _read_events(run_dir: Path) -> tuple[ResearchEvent, ...]:
     events_dir = run_dir / "events"
     if not events_dir.exists(): raise RunUninitializedError(run_dir)
     _safe_directory(events_dir, run_dir)
-    names = sorted(path.name for path in events_dir.iterdir() if not path.name.startswith("."))
+    entries: dict[str, Path] = {}; temporary: list[tuple[Path, str]] = []
+    for path in events_dir.iterdir():
+        target = _documented_event_temporary_target(path.name)
+        if target is not None:
+            _require_regular_file(path, run_dir); temporary.append((path, target)); continue
+        if len(path.name) != 11 or not path.name.endswith(".json") or not path.name[:6].isdigit(): raise RunCorruptError(run_dir, "unexpected event artifact")
+        _require_regular_file(path, run_dir); entries[path.name] = path
+    names = sorted(entries)
     expected = [f"{number:06d}.json" for number in range(1, len(names) + 1)]
     if names != expected: raise RunCorruptError(run_dir, "event files must be contiguous canonical sequences")
     events: list[ResearchEvent] = []
     for name in names:
-        path = events_dir / name; _require_regular_file(path, run_dir)
+        path = entries[name]
         try: events.append(ResearchEvent.from_json(_load_persisted_json(path, run_dir)))
         except (ValueError, TypeError) as exc: raise RunCorruptError(run_dir, "invalid research event") from exc
+    _verify_temporary_hardlink_aliases(run_dir, entries, temporary, immutable_targets=frozenset(entries))
     return tuple(events)
 
 
+def _checked_children(directory: Path, run_dir: Path, *, files: set[str], directories: set[str], immutable: set[str] = set()) -> dict[str, Path]:
+    entries: dict[str, Path] = {}; temporary: list[tuple[Path, str]] = []
+    for path in directory.iterdir():
+        target = _documented_temporary_target(path.name, tuple(files))
+        if target is not None:
+            _require_regular_file(path, run_dir); temporary.append((path, target)); continue
+        if path.name in files:
+            _require_regular_file(path, run_dir)
+        elif path.name in directories:
+            _safe_directory(path, run_dir)
+        else: raise RunCorruptError(run_dir, f"unexpected artifact {path.name}")
+        entries[path.name] = path
+    _verify_temporary_hardlink_aliases(run_dir, entries, temporary, immutable_targets=frozenset(immutable))
+    return entries
+
+
 def _check_layout(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
     allowed = {".run.lock", "request.json", "state.json", "events", "actions", "sources", "tools", "report.md", "research-log.md"}
-    for entry in run_dir.iterdir():
-        if entry.name.startswith(".") and entry.name.endswith(".tmp"): continue
-        if entry.name not in allowed: raise RunCorruptError(run_dir, f"unexpected root entry {entry.name}")
+    root = _checked_children(run_dir, run_dir, files={".run.lock", "request.json", "state.json", "report.md", "research-log.md"}, directories={"events", "actions", "sources", "tools"}, immutable={"request.json"})
     for name in ("actions", "sources", "tools"):
         path = run_dir / name
         if path.exists(): _safe_directory(path, run_dir)
     intended = {item.body["action_id"]: item.body for item in events if item.event_type == "action_intended"}
     finished = {item.body["action_id"]: item.body for item in events if item.event_type == "action_finished"}
+    for action_id, outcome in finished.items():
+        action_dir = run_dir / "actions" / action_id
+        if not action_dir.exists():
+            raise RunCorruptError(run_dir, "finished action capture directory is missing")
+        _safe_directory(action_dir, run_dir)
+        for filename, digest_key in (("stdout.bin", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
+            capture = action_dir / filename
+            if not capture.exists() or not capture.is_file() or hashlib.sha256(capture.read_bytes()).hexdigest() != outcome[digest_key]:
+                raise RunCorruptError(run_dir, "capture digest mismatch")
     if (run_dir / "actions").exists():
-        for action_dir in (run_dir / "actions").iterdir():
-            if action_dir.name.startswith("."): continue
+        for action_dir in _checked_children(run_dir / "actions", run_dir, files=set(), directories=set(intended)).values():
             if action_dir.name not in intended: raise RunCorruptError(run_dir, "unauthorized action directory")
             _safe_directory(action_dir, run_dir)
-            for child in action_dir.iterdir():
-                if child.name.startswith(".") and child.name.endswith(".tmp"): continue
-                if child.name not in {"packet.json", "stdout.bin", "stderr.log", "result.json"}: raise RunCorruptError(run_dir, "unexpected action artifact")
-                _require_regular_file(child, run_dir)
+            _checked_children(action_dir, run_dir, files={"packet.json", "stdout.bin", "stderr.log", "result.json"}, directories=set(), immutable={"packet.json", "result.json"})
             packet = action_dir / "packet.json"
             if packet.exists() and packet.read_bytes() != canonical_json_bytes(intended[action_dir.name]["packet"]): raise RunCorruptError(run_dir, "packet projection mismatch")
-            if action_dir.name in finished:
-                outcome = finished[action_dir.name]
-                for filename, digest_key in (("stdout.bin", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
-                    capture = action_dir / filename
-                    if not capture.exists() or hashlib.sha256(capture.read_bytes()).hexdigest() != outcome[digest_key]: raise RunCorruptError(run_dir, "capture digest mismatch")
-    for dirname in ("tools", "sources"):
-        path = run_dir / dirname
-        if path.exists():
-            for child in path.iterdir():
-                if child.name.startswith("."): continue
-                _safe_directory(child, run_dir)
-                if dirname == "tools" and child.name not in finished: raise RunCorruptError(run_dir, "unauthorized tool projection")
+    successful_tools = {action_id: outcome for action_id, outcome in finished.items() if outcome["outcome"] == "succeeded" and snapshot.actions[action_id]["kind"] == "tool"}
+    if (run_dir / "tools").exists():
+        for action_id, directory in _checked_children(run_dir / "tools", run_dir, files=set(), directories=set(successful_tools)).items():
+            receipt = _checked_children(directory, run_dir, files={"receipt.json"}, directories=set(), immutable={"receipt.json"}).get("receipt.json")
+            if receipt is None or receipt.read_bytes() != canonical_json_bytes(successful_tools[action_id]["result"]): raise RunCorruptError(run_dir, "invalid tool receipt projection")
+    source_results = {result["source"]["id"]: result["source"] for action_id, result in snapshot.results.items() if snapshot.actions[action_id]["kind"] == "tool" and snapshot.actions[action_id]["role"] == "fetch_source" and isinstance(result, dict) and isinstance(result.get("source"), dict) and isinstance(result["source"].get("id"), str)}
+    if (run_dir / "sources").exists():
+        for source_id, directory in _checked_children(run_dir / "sources", run_dir, files=set(), directories=set(source_results)).items():
+            source = _checked_children(directory, run_dir, files={"source.json"}, directories=set(), immutable={"source.json"}).get("source.json")
+            if source is None or source.read_bytes() != canonical_json_bytes(source_results[source_id]): raise RunCorruptError(run_dir, "invalid source projection")
 
 
 def _materialize(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
@@ -86,6 +111,16 @@ def _materialize(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[Resear
         elif item.event_type == "action_finished" and item.body["result"] is not None:
             result = run_dir / "actions" / item.body["action_id"] / "result.json"
             if not result.exists(): _atomic_write_new(result, canonical_json_bytes(item.body["result"]))
+            action = snapshot.actions[item.body["action_id"]]
+            if action["kind"] == "tool" and item.body["outcome"] == "succeeded":
+                directory = run_dir / "tools" / item.body["action_id"]; directory.mkdir(parents=True, exist_ok=True)
+                receipt = directory / "receipt.json"
+                if not receipt.exists(): _atomic_write_new(receipt, canonical_json_bytes(item.body["result"]))
+                source = item.body["result"].get("source") if isinstance(item.body["result"], dict) else None
+                if action["role"] == "fetch_source" and isinstance(source, dict) and isinstance(source.get("id"), str):
+                    source_dir = run_dir / "sources" / source["id"]; source_dir.mkdir(parents=True, exist_ok=True)
+                    source_path = source_dir / "source.json"
+                    if not source_path.exists(): _atomic_write_new(source_path, canonical_json_bytes(source))
         elif item.event_type == "research_finished":
             _atomic_write_replace(run_dir / "report.md", item.body["report_markdown"].encode("utf-8")); _atomic_write_replace(run_dir / "research-log.md", item.body["log_markdown"].encode("utf-8"))
 
@@ -117,11 +152,12 @@ def initialize_research(request_path: Path, run_dir: Path) -> ResearchSnapshot:
         raw = json.loads(request_path.read_text(encoding="utf-8")); request = ResearchRequest.from_json(raw)
     except (OSError, ValueError, TypeError) as exc: raise RunStoreError("invalid research request") from exc
     if run_dir.exists() and any(item.name != ".run.lock" for item in run_dir.iterdir()): raise RunStoreError("research destination is not empty")
-    run_dir.mkdir(parents=True, exist_ok=True); (run_dir / "events").mkdir(exist_ok=True)
+    run_dir.mkdir(parents=True, exist_ok=True)
     from datetime import datetime, timezone
     occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
     event = ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": 1, "event_type": "research_initialized", "run_id": request.run_id, "occurred_at": occurred_at, "body": {"request": request.to_json()}})
     with acquire_run_lock(run_dir):
+        (run_dir / "events").mkdir(exist_ok=True)
         _atomic_write_new(run_dir / "events" / "000001.json", canonical_json_bytes(event.to_json()))
         snapshot = replay_research_events((event,)); _materialize(run_dir, snapshot, (event,))
     return snapshot
diff --git a/tests/unit/test_research_events.py b/tests/unit/test_research_events.py
index 7756adb..16ab967 100644
--- a/tests/unit/test_research_events.py
+++ b/tests/unit/test_research_events.py
@@ -69,3 +69,14 @@ class ResearchEventTests(unittest.TestCase):
         init = event(1, "research_initialized", {"request": valid_request_payload()})
         duplicate = copy.deepcopy(gate); duplicate["sequence"] = 3
         with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(item) for item in [init, gate, duplicate]])
+
+    def test_success_result_must_match_the_recorded_worker_role(self) -> None:
+        history = quick_complete()
+        history[3]["body"]["result"] = {"arbitrary": "json"}
+        with self.assertRaises(ValueError):
+            replay_research_events([ResearchEvent.from_json(item) for item in history])
+
+    def test_normalizes_equivalent_utc_instants_for_chronology(self) -> None:
+        history = quick_complete()
+        history[1]["occurred_at"] = "2026-09-15T17:00:02-07:00"
+        self.assertEqual(replay_research_events([ResearchEvent.from_json(item) for item in history]).sequence, 5)
diff --git a/tests/unit/test_research_store.py b/tests/unit/test_research_store.py
index 6ecaeda..b0a74c8 100644
--- a/tests/unit/test_research_store.py
+++ b/tests/unit/test_research_store.py
@@ -1,11 +1,14 @@
 from __future__ import annotations
 
 import json
+import shutil
 import tempfile
 import unittest
 from pathlib import Path
 
-from mathresearch.research.store import initialize_research, load_research_status
+from mathresearch.research.events import ResearchEvent, canonical_json_bytes
+from mathresearch.research.store import initialize_research, load_research_status, open_research_run
+from tests.unit.test_research_events import ACTION, DETAILS, PACKET, TELEMETRY
 from tests.unit.test_research_contracts import valid_request_payload
 
 
@@ -26,3 +29,19 @@ class ResearchStoreTests(unittest.TestCase):
             run = root / "run"; initialize_research(request, run)
             (run / "unexpected").write_text("x", encoding="utf-8")
             with self.assertRaises(RuntimeError): load_research_status(run)
+
+    def test_missing_finished_capture_blocks_all_projection_repair(self) -> None:
+        with tempfile.TemporaryDirectory() as temp:
+            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
+            run = root / "run"; initialize_research(request, run)
+            with open_research_run(run) as locked:
+                base = {"schema_version": 3, "record_type": "research_event", "run_id": "odd-perfect-run", "occurred_at": "2099-09-16T00:00:02Z"}
+                locked.append(ResearchEvent.from_json(base | {"sequence": 2, "event_type": "decision_recorded", "body": {"decision_id": "d0001", "kind": "worker", "reason_code": "frame_request", "action": ACTION, "details": DETAILS}}))
+                packet = canonical_json_bytes(PACKET)
+                locked.append(ResearchEvent.from_json(base | {"sequence": 3, "event_type": "action_intended", "body": {"action_id": "a0001", "packet": PACKET, "packet_sha256": __import__("hashlib").sha256(packet).hexdigest()}}))
+                stdout = locked.write_capture("a0001", "stdout.bin", b"out"); stderr = locked.write_capture("a0001", "stderr.log", b"err")
+                locked.append(ResearchEvent.from_json(base | {"sequence": 4, "event_type": "action_finished", "body": {"action_id": "a0001", "outcome": "succeeded", "exit_code": 0, "stdout_sha256": stdout, "stderr_sha256": stderr, "result": {"task_type": "exploration", "deliverables": ["d"], "subquestions": ["q"], "missing_inputs": [], "proposed_checks": [], "source_needs": []}, "error": None, "telemetry": TELEMETRY}}))
+            shutil.rmtree(run / "actions" / "a0001")
+            (run / "state.json").unlink()
+            with self.assertRaises(RuntimeError): load_research_status(run)
+            self.assertFalse((run / "state.json").exists())
