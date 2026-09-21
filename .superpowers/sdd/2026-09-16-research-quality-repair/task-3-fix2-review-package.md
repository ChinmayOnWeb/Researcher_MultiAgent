# Task 3 fix2 review package

Base: d62f8958aa5de2d268d74e2f5c3e3ed1b15b8b70
Head: c99d309a3b2f24fb5ae6844b1daf3f60ede3528c

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
index 2295907..7cfb866 100644
--- a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
@@ -67,3 +67,21 @@ The remaining structural store boundary is now closed without defining Task 6 se
 The store now uses the legacy `_verify_temporary_hardlink_aliases` routine for root, event, action, source, and tool projection directories. Every entry, including a dot-prefixed writer temporary, is classified as a documented temporary alias or rejected; aliases are accepted only when the immutable target identity and hardlink count verify.
 
 Task 3 validates the Section 6 local action structure through Task 2's `validate_action`, enforces contiguous action lifecycle/dependencies and terminal/gate legality, and deliberately defers Section 7 routing-table reason-code selection to Task 7. It does not make route policy decisions.
+
+## Fix round 2
+
+Tool result handling is now operation-bound at replay. Until Task 6 supplies each broker operation's semantic schema, only `fetch_source` has a durable structural result shape: an exact result object containing `source`, with an identifier-validated source ID and a bounded canonical JSON encoding. Other tool result shapes are rejected rather than treated as authority. This validation occurs before store materialization, so traversal strings, absolute paths, separators, dot names, invalid identifiers, and oversized payloads cannot reach `sources/<source-id>`.
+
+Gate response idempotence is keyed by the pair of gate ID and response ID. A reused pair requires the identical canonical response digest; a different gate cannot reuse that authorization. Persisted `noop` decisions are rejected: Section 6 permits a no-op return value, not a no-op event. Capture files are included in the immutable-target alias verifier while SHA-256 capture checks remain mandatory.
+
+Initialization now rechecks the destination while holding the run lock before creating `events/` or publishing an event. The unavoidable empty directory creation is only used to obtain that lock target.
+
+Verification run:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
+```
+
+Exit code: `0`. Result: `Ran 43 tests in 3.753s — OK`.
+
+The focused existing tests exercised capture corruption, link/reparse/hardlink and legacy v1/v2 compatibility through `test_run_store`. New dedicated Task 3 fault-injection and v2-byte fixture tests were not added in this round and are not claimed as evidence.
diff --git a/src/mathresearch/research/events.py b/src/mathresearch/research/events.py
index a2625c9..a95bc8c 100644
--- a/src/mathresearch/research/events.py
+++ b/src/mathresearch/research/events.py
@@ -59,6 +59,22 @@ def _telemetry(value: Any) -> dict[str, Any]:
     return checked
 
 
+def validate_tool_result(operation: str, value: Any) -> dict[str, Any]:
+    """Accept only the currently durable tool shape; Task 6 owns semantics."""
+    data = require_object(value, "tool result")
+    if operation != "fetch_source":
+        raise ValidationError("tool result", "operation result schema is not available before Task 6")
+    require_exact_fields(data, "tool result", {"source"})
+    source = require_object(data["source"], "tool result.source")
+    if "id" not in source:
+        raise ValidationError("tool result.source", "missing required field 'id'")
+    require_identifier(source["id"], "tool result.source.id")
+    checked = {key: value for key, value in source.items()}
+    if len(canonical_json_bytes({"source": checked})) > 65536:
+        raise ValidationError("tool result", "canonical JSON must be at most 65536 bytes")
+    return {"source": checked}
+
+
 @dataclass(frozen=True)
 class ResearchEvent:
     sequence: int
@@ -171,7 +187,7 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
         elif request is None: raise ValueError("initialization required")
         elif item.event_type == "decision_recorded":
             action = item.body["action"]
-            if item.body["kind"] == "noop" and not (terminal is not None or gate is not None): raise ValueError("noop is only legal for terminal or open gates")
+            if item.body["kind"] == "noop": raise ValueError("noop decisions are not persisted")
             if action is not None:
                 action_id = action["id"]
                 if action_id in actions or pending is not None: raise ValueError("duplicate or overlapping action")
@@ -190,7 +206,7 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
             if item.body["outcome"] == "succeeded":
                 try:
                     result = (validate_result(action["role"], item.body["result"])
-                              if action["kind"] == "worker" else dict(require_object(item.body["result"], "tool result")))
+                              if action["kind"] == "worker" else validate_tool_result(action["role"], item.body["result"]))
                 except ValidationError as exc:
                     raise ValueError("successful result does not match action") from exc
                 results[action_id] = result
@@ -201,12 +217,13 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
             gate_ids.add(item.body["gate_id"])
         elif item.event_type == "gate_answered":
             digest = hashlib.sha256(canonical_json_bytes(item.body["response"])).hexdigest()
-            prior = response_digests.get(item.body["response_id"])
+            response_key = f"{item.body['gate_id']}\0{item.body['response_id']}"
+            prior = response_digests.get(response_key)
             if prior is not None:
                 if prior != digest: raise ValueError("response ID payload conflict")
                 continue
             if gate is None or gate["gate_id"] != item.body["gate_id"]: raise ValueError("unknown or closed gate")
-            response_digests[item.body["response_id"]] = digest
+            response_digests[response_key] = digest
             gate = None
         elif item.event_type == "research_finished":
             if pending is not None: raise ValueError("finish while action pending")
diff --git a/src/mathresearch/research/store.py b/src/mathresearch/research/store.py
index c1a6c55..e3834eb 100644
--- a/src/mathresearch/research/store.py
+++ b/src/mathresearch/research/store.py
@@ -84,7 +84,7 @@ def _check_layout(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[Resea
         for action_dir in _checked_children(run_dir / "actions", run_dir, files=set(), directories=set(intended)).values():
             if action_dir.name not in intended: raise RunCorruptError(run_dir, "unauthorized action directory")
             _safe_directory(action_dir, run_dir)
-            _checked_children(action_dir, run_dir, files={"packet.json", "stdout.bin", "stderr.log", "result.json"}, directories=set(), immutable={"packet.json", "result.json"})
+            _checked_children(action_dir, run_dir, files={"packet.json", "stdout.bin", "stderr.log", "result.json"}, directories=set(), immutable={"packet.json", "stdout.bin", "stderr.log", "result.json"})
             packet = action_dir / "packet.json"
             if packet.exists() and packet.read_bytes() != canonical_json_bytes(intended[action_dir.name]["packet"]): raise RunCorruptError(run_dir, "packet projection mismatch")
     successful_tools = {action_id: outcome for action_id, outcome in finished.items() if outcome["outcome"] == "succeeded" and snapshot.actions[action_id]["kind"] == "tool"}
@@ -151,12 +151,12 @@ def initialize_research(request_path: Path, run_dir: Path) -> ResearchSnapshot:
     try:
         raw = json.loads(request_path.read_text(encoding="utf-8")); request = ResearchRequest.from_json(raw)
     except (OSError, ValueError, TypeError) as exc: raise RunStoreError("invalid research request") from exc
-    if run_dir.exists() and any(item.name != ".run.lock" for item in run_dir.iterdir()): raise RunStoreError("research destination is not empty")
     run_dir.mkdir(parents=True, exist_ok=True)
     from datetime import datetime, timezone
     occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
     event = ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": 1, "event_type": "research_initialized", "run_id": request.run_id, "occurred_at": occurred_at, "body": {"request": request.to_json()}})
     with acquire_run_lock(run_dir):
+        if any(item.name != ".run.lock" for item in run_dir.iterdir()): raise RunStoreError("research destination is not empty")
         (run_dir / "events").mkdir(exist_ok=True)
         _atomic_write_new(run_dir / "events" / "000001.json", canonical_json_bytes(event.to_json()))
         snapshot = replay_research_events((event,)); _materialize(run_dir, snapshot, (event,))
