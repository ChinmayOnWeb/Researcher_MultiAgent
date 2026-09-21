# Task 3 round 4 review package

Base: dc42056003aec04df112daa2ff63902050f56815
Head: 71b29f1902b2d218138710b7321418a9de30f7a5

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
index 5ec804e..ed5d00c 100644
--- a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
@@ -125,3 +125,47 @@ $env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit
 ```
 
 Exit code: `0`. Result: `Ran 46 tests in 3.899s — OK`.
+
+## Fix round 4
+
+Replay now binds every successful `fetch_source` result to durable user authorization. The reducer builds the accepted descriptor catalog from the initialized request and from version-three gate responses that include source additions. Gate additions must use the existing `SourceInput` validator, a `supply` decision allowed by the open gate, matching gate/response IDs, unique non-replacing source IDs, the initial fetch capability, and the six-descriptor aggregate limit. A fetch action resolves only its validated `payload.arguments.source_id`; the result's safely validated `source.id` and exact `source.url` must both match that authorized URL descriptor. The rest of the source object remains opaque and byte-bounded, so this round does not define Task 6's `SourceRecord` or retrieval-receipt semantics.
+
+The missing post-commit recovery coverage exposed a store bug rather than only a test omission. After `action_finished` committed, failure while publishing `receipt.json` or `source.json` left an authorized projection directory without its expected file. Layout validation treated that recoverable absence as corruption and never reached replay materialization. Layout checks now accept an absent derived result/receipt/source file while still rejecting any existing projection whose bytes differ from the committed event. Existing `result.json` is also checked against its authorizing finish event.
+
+`test_finished_tool_result_recovers_after_each_post_commit_projection_failure` exercises the real atomic-write seam separately for `actions/a0001/result.json`, `tools/a0001/receipt.json`, and `sources/source-one/source.json`. In each case it asserts that the immutable finish event exists before recovery, all three projections are reconstructed from history, the recovered result is usable, the event filename set is unchanged, and exactly one `action_finished` publication exists. The earlier decision commit, intent projection, first/second capture, finish commit, gate-response commit, and final-report fault points remain covered by the existing matrix.
+
+The initialization-generated v1 compatibility check was replaced with a complete hand-authored v2 Quick fixture: one v1 initialization event followed by fourteen explicit v2 workflow events through all four intended/finished/accepted stages and terminal completion. Its request, final v2 state, packets, captures, accepted results, report, and lock file are written directly by the test. The test snapshots all 35 file paths and byte strings, calls legacy `load_run_status`, verifies the completed sequence-15 state, and requires the entire file-byte map to remain identical.
+
+Red evidence before the fixes:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events.ResearchEventTests.test_fetch_result_must_match_an_authorized_requested_url_descriptor tests.unit.test_research_events.ResearchEventTests.test_fetch_result_accepts_a_url_descriptor_from_an_accepted_gate tests.unit.test_research_store.ResearchStoreTests.test_finished_tool_result_recovers_after_each_post_commit_projection_failure -v
+```
+
+Exit code: `1`. Unauthorized requested IDs, mismatched result IDs, and mismatched URLs were accepted; recovery after receipt/source publication failures stopped with `RunCorruptError`. A separate red run proved that a gate response using `supply` when the open gate did not allow it was incorrectly accepted.
+
+Focused verification:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
+```
+
+Exit code: `0`. Result: `Ran 49 tests in 5.367s — OK`.
+
+Targeted compatibility and contract regressions:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_contracts tests.unit.test_quick_store -v
+```
+
+Exit code: `0`. Result: `Ran 19 tests in 0.700s — OK`.
+
+Broad unit regression:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest discover -s tests\unit
+```
+
+Exit code: `0`. Result: `Ran 174 tests in 35.259s — OK`.
+
+Route-table reason-code selection remains Task 7 ownership. This round changes no routing policy and adds no Task 6 source or receipt schema.
diff --git a/src/mathresearch/research/events.py b/src/mathresearch/research/events.py
index 09d4681..d763922 100644
--- a/src/mathresearch/research/events.py
+++ b/src/mathresearch/research/events.py
@@ -9,7 +9,7 @@ from datetime import datetime, timezone
 from types import MappingProxyType
 from typing import Any, Mapping
 
-from mathresearch.contracts.research_request import ResearchRequest
+from mathresearch.contracts.research_request import ResearchRequest, SourceInput
 from mathresearch.contracts.validation import ValidationError, require_exact_fields, require_identifier, require_nonnegative_integer, require_object, require_string
 from mathresearch.research.contracts import validate_action, validate_decision_details, validate_result
 
@@ -59,7 +59,7 @@ def _telemetry(value: Any) -> dict[str, Any]:
     return checked
 
 
-def validate_tool_result(operation: str, value: Any) -> dict[str, Any]:
+def validate_tool_result(operation: str, value: Any, *, requested_source: Mapping[str, Any] | None = None) -> dict[str, Any]:
     """Accept only the currently durable tool shape; Task 6 owns semantics."""
     data = require_object(value, "tool result")
     if operation != "fetch_source":
@@ -68,13 +68,46 @@ def validate_tool_result(operation: str, value: Any) -> dict[str, Any]:
     source = require_object(data["source"], "tool result.source")
     if "id" not in source:
         raise ValidationError("tool result.source", "missing required field 'id'")
-    require_identifier(source["id"], "tool result.source.id")
+    source_id = require_identifier(source["id"], "tool result.source.id")
+    if requested_source is None or requested_source.get("kind") != "url":
+        raise ValidationError("tool result.source.id", "is not an authorized URL source")
+    if source_id != requested_source["id"]:
+        raise ValidationError("tool result.source.id", "must match the requested source descriptor")
+    source_url = require_string(source.get("url"), "tool result.source.url")
+    if source_url != requested_source["url"]:
+        raise ValidationError("tool result.source.url", "must match the requested source descriptor")
     checked = {key: value for key, value in source.items()}
     if len(canonical_json_bytes({"source": checked})) > 65536:
         raise ValidationError("tool result", "canonical JSON must be at most 65536 bytes")
     return {"source": checked}
 
 
+def _gate_source_inputs(response: Any, *, gate_id: str, response_id: str,
+                        fetch_sources: bool, allowed_response: tuple[str, ...]) -> tuple[SourceInput, ...]:
+    """Validate only the gate fields needed to authorize added source descriptors."""
+    if not isinstance(response, Mapping) or "sources" not in response:
+        return ()
+    data = require_object(response, "gate response")
+    require_exact_fields(data, "gate response", {"schema_version", "record_type", "gate_id",
+                         "response_id", "decision", "text", "sources"})
+    if data["schema_version"] != 3 or data["record_type"] != "research_gate_response":
+        raise ValidationError("gate response", "must be a version-three research gate response")
+    if data["gate_id"] != gate_id or data["response_id"] != response_id:
+        raise ValidationError("gate response", "identifiers must match the answered gate event")
+    if data["decision"] not in allowed_response:
+        raise ValidationError("gate response.decision", "is not accepted by the open gate")
+    sources = data["sources"]
+    if not isinstance(sources, list) or len(sources) > 6:
+        raise ValidationError("gate response.sources", "must be an array with at most 6 entries")
+    if data["decision"] != "supply":
+        if sources:
+            raise ValidationError("gate response.sources", "require a supply decision")
+        return ()
+    return tuple(SourceInput.from_json(item, field=f"gate response.sources[{index}]",
+                                      fetch_sources=fetch_sources)
+                 for index, item in enumerate(sources))
+
+
 @dataclass(frozen=True)
 class ResearchEvent:
     sequence: int
@@ -177,7 +210,7 @@ class ResearchSnapshot:
 
 def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ...]) -> ResearchSnapshot:
     if not events: raise ValueError("history requires initialization")
-    request: ResearchRequest | None = None; initialized_at = ""; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; gate_ids: set[str] = set(); response_digests: dict[str, str] = {}; run_id = events[0].run_id; previous_time = ""
+    request: ResearchRequest | None = None; initialized_at = ""; actions: dict[str, Mapping[str, Any]] = {}; decisions: list[Mapping[str, Any]] = []; intended: dict[str, Mapping[str, Any]] = {}; results: dict[str, Any] = {}; source_descriptors: dict[str, dict[str, Any]] = {}; pending: str | None = None; gate: Mapping[str, Any] | None = None; terminal: Mapping[str, Any] | None = None; gate_ids: set[str] = set(); response_digests: dict[str, str] = {}; run_id = events[0].run_id; previous_time = ""
     for expected, item in enumerate(events, 1):
         if item.sequence != expected or item.run_id != run_id or (previous_time and item.occurred_at < previous_time): raise ValueError("events must be contiguous and chronological")
         previous_time = item.occurred_at
@@ -186,6 +219,7 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
             if request is not None or expected != 1: raise ValueError("initialization must occur once first")
             request = ResearchRequest.from_json(item.body["request"]); initialized_at = item.occurred_at
             if request.run_id != run_id: raise ValueError("request run_id mismatch")
+            source_descriptors = {source.id: source.to_json() for source in request.sources}
         elif request is None: raise ValueError("initialization required")
         elif item.event_type == "decision_recorded":
             action = item.body["action"]
@@ -207,8 +241,13 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
             action = actions[action_id]
             if item.body["outcome"] == "succeeded":
                 try:
-                    result = (validate_result(action["role"], item.body["result"])
-                              if action["kind"] == "worker" else validate_tool_result(action["role"], item.body["result"]))
+                    if action["kind"] == "worker":
+                        result = validate_result(action["role"], item.body["result"])
+                    else:
+                        requested_id = action["payload"]["arguments"].get("source_id")
+                        requested_source = source_descriptors.get(requested_id) if isinstance(requested_id, str) else None
+                        result = validate_tool_result(action["role"], item.body["result"],
+                                                      requested_source=requested_source)
                 except ValidationError as exc:
                     raise ValueError("successful result does not match action") from exc
                 results[action_id] = result
@@ -225,6 +264,19 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
                 if prior != digest: raise ValueError("response ID payload conflict")
                 continue
             if gate is None or gate["gate_id"] != item.body["gate_id"]: raise ValueError("unknown or closed gate")
+            try:
+                additions = _gate_source_inputs(item.body["response"], gate_id=item.body["gate_id"],
+                                                response_id=item.body["response_id"],
+                                                fetch_sources=request.capabilities["fetch_sources"],
+                                                allowed_response=tuple(gate["allowed_response"]))
+            except ValidationError as exc:
+                raise ValueError("invalid gate source authorization") from exc
+            if len(source_descriptors) + len(additions) > 6:
+                raise ValueError("source descriptor limit exceeded")
+            for source in additions:
+                if source.id in source_descriptors:
+                    raise ValueError("gate source ID replaces an accepted descriptor")
+                source_descriptors[source.id] = source.to_json()
             response_digests[response_key] = digest
             gate = None
         elif item.event_type == "research_finished":
diff --git a/src/mathresearch/research/store.py b/src/mathresearch/research/store.py
index e3834eb..894ac4e 100644
--- a/src/mathresearch/research/store.py
+++ b/src/mathresearch/research/store.py
@@ -87,16 +87,20 @@ def _check_layout(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[Resea
             _checked_children(action_dir, run_dir, files={"packet.json", "stdout.bin", "stderr.log", "result.json"}, directories=set(), immutable={"packet.json", "stdout.bin", "stderr.log", "result.json"})
             packet = action_dir / "packet.json"
             if packet.exists() and packet.read_bytes() != canonical_json_bytes(intended[action_dir.name]["packet"]): raise RunCorruptError(run_dir, "packet projection mismatch")
+            result = action_dir / "result.json"
+            committed = finished.get(action_dir.name)
+            if result.exists() and (committed is None or committed["result"] is None or result.read_bytes() != canonical_json_bytes(committed["result"])):
+                raise RunCorruptError(run_dir, "result projection mismatch")
     successful_tools = {action_id: outcome for action_id, outcome in finished.items() if outcome["outcome"] == "succeeded" and snapshot.actions[action_id]["kind"] == "tool"}
     if (run_dir / "tools").exists():
         for action_id, directory in _checked_children(run_dir / "tools", run_dir, files=set(), directories=set(successful_tools)).items():
             receipt = _checked_children(directory, run_dir, files={"receipt.json"}, directories=set(), immutable={"receipt.json"}).get("receipt.json")
-            if receipt is None or receipt.read_bytes() != canonical_json_bytes(successful_tools[action_id]["result"]): raise RunCorruptError(run_dir, "invalid tool receipt projection")
+            if receipt is not None and receipt.read_bytes() != canonical_json_bytes(successful_tools[action_id]["result"]): raise RunCorruptError(run_dir, "invalid tool receipt projection")
     source_results = {result["source"]["id"]: result["source"] for action_id, result in snapshot.results.items() if snapshot.actions[action_id]["kind"] == "tool" and snapshot.actions[action_id]["role"] == "fetch_source" and isinstance(result, dict) and isinstance(result.get("source"), dict) and isinstance(result["source"].get("id"), str)}
     if (run_dir / "sources").exists():
         for source_id, directory in _checked_children(run_dir / "sources", run_dir, files=set(), directories=set(source_results)).items():
             source = _checked_children(directory, run_dir, files={"source.json"}, directories=set(), immutable={"source.json"}).get("source.json")
-            if source is None or source.read_bytes() != canonical_json_bytes(source_results[source_id]): raise RunCorruptError(run_dir, "invalid source projection")
+            if source is not None and source.read_bytes() != canonical_json_bytes(source_results[source_id]): raise RunCorruptError(run_dir, "invalid source projection")
 
 
 def _materialize(run_dir: Path, snapshot: ResearchSnapshot, events: tuple[ResearchEvent, ...]) -> None:
diff --git a/tests/unit/test_research_events.py b/tests/unit/test_research_events.py
index a83be3a..5117a21 100644
--- a/tests/unit/test_research_events.py
+++ b/tests/unit/test_research_events.py
@@ -27,6 +27,29 @@ TELEMETRY = {"duration_ms": 1, "input_bytes": 1, "output_bytes": 1, "model_obser
              "reasoning_tokens": None, "cost_usd": None}
 
 
+def fetch_history(*, requested_id: str = "source-one", result_id: str = "source-one",
+                  descriptor_url: str = "https://example.test/source",
+                  result_url: str = "https://example.test/source") -> list[dict[str, object]]:
+    request = valid_request_payload()
+    request["capabilities"]["fetch_sources"] = True
+    request["sources"] = [{"id": "source-one", "kind": "url", "title": "Source one",
+                           "text": None, "url": descriptor_url, "published_at": None}]
+    action = {"id": "a0001", "kind": "tool", "role": "fetch_source", "branch": None,
+              "round": 0, "dependencies": [], "payload": {"id": "fetch-one",
+              "operation": "fetch_source", "arguments": {"source_id": requested_id}}}
+    return [
+        event(1, "research_initialized", {"request": request}),
+        event(2, "decision_recorded", {"decision_id": "d0001", "kind": "tool",
+              "reason_code": "acquire_source", "action": action, "details": DETAILS}),
+        event(3, "action_intended", {"action_id": "a0001", "packet": PACKET,
+              "packet_sha256": SHA}),
+        event(4, "action_finished", {"action_id": "a0001", "outcome": "succeeded",
+              "exit_code": 0, "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64,
+              "result": {"source": {"id": result_id, "url": result_url}}, "error": None,
+              "telemetry": TELEMETRY}),
+    ]
+
+
 def quick_complete() -> list[dict[str, object]]:
     return [
         event(1, "research_initialized", {"request": valid_request_payload()}),
@@ -87,3 +110,50 @@ class ResearchEventTests(unittest.TestCase):
         gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
         finish = event(3, "research_finished", {"status": "incomplete", "assessment": {}, "reason": "x", "report_markdown": "", "log_markdown": ""})
         with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(x) for x in [event(1, "research_initialized", {"request": valid_request_payload()}), gate, finish]])
+
+    def test_fetch_result_must_match_an_authorized_requested_url_descriptor(self) -> None:
+        snapshot = replay_research_events([ResearchEvent.from_json(item) for item in fetch_history()])
+        self.assertEqual(snapshot.results["a0001"]["source"]["id"], "source-one")
+
+        for history in (
+            fetch_history(requested_id="not-authorized", result_id="not-authorized"),
+            fetch_history(result_id="different-source"),
+            fetch_history(result_id="../unsafe"),
+            fetch_history(result_url="https://example.test/different"),
+        ):
+            with self.subTest(result=history[-1]["body"]):
+                with self.assertRaises(ValueError):
+                    replay_research_events([ResearchEvent.from_json(item) for item in history])
+
+    def test_fetch_result_accepts_a_url_descriptor_from_an_accepted_gate(self) -> None:
+        request = valid_request_payload()
+        request["capabilities"]["fetch_sources"] = True
+        gate_source = {"id": "gate-source", "kind": "url", "title": "Gate source",
+                       "text": None, "url": "https://example.test/gate", "published_at": None}
+        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "request_evidence",
+                     "questions": ["Provide a source."], "allowed_response": ["supply"],
+                     "resume_token": "0" * 64})
+        answer = event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001",
+                       "response": {"schema_version": 3, "record_type": "research_gate_response",
+                       "gate_id": "g0001", "response_id": "r0001", "decision": "supply",
+                       "text": None, "sources": [gate_source]}})
+        action = {"id": "a0001", "kind": "tool", "role": "fetch_source", "branch": None,
+                  "round": 0, "dependencies": [], "payload": {"id": "fetch-gate",
+                  "operation": "fetch_source", "arguments": {"source_id": "gate-source"}}}
+        history = [event(1, "research_initialized", {"request": request}), gate, answer,
+                   event(4, "decision_recorded", {"decision_id": "d0001", "kind": "tool",
+                         "reason_code": "acquire_source", "action": action, "details": DETAILS}),
+                   event(5, "action_intended", {"action_id": "a0001", "packet": PACKET,
+                         "packet_sha256": SHA}),
+                   event(6, "action_finished", {"action_id": "a0001", "outcome": "succeeded",
+                         "exit_code": 0, "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64,
+                         "result": {"source": {"id": "gate-source", "url": gate_source["url"]}},
+                         "error": None, "telemetry": TELEMETRY})]
+
+        snapshot = replay_research_events([ResearchEvent.from_json(item) for item in history])
+
+        self.assertEqual(snapshot.results["a0001"]["source"]["id"], "gate-source")
+        rejected = copy.deepcopy(history)
+        rejected[1]["body"]["allowed_response"] = ["continue_limited"]
+        with self.assertRaises(ValueError):
+            replay_research_events([ResearchEvent.from_json(item) for item in rejected])
diff --git a/tests/unit/test_research_store.py b/tests/unit/test_research_store.py
index 51b7fe0..05b2ce0 100644
--- a/tests/unit/test_research_store.py
+++ b/tests/unit/test_research_store.py
@@ -9,16 +9,15 @@ from unittest.mock import patch
 
 from mathresearch.research.events import ResearchEvent, canonical_json_bytes
 from mathresearch.research.store import initialize_research, load_research_status, open_research_run
-from mathresearch.run_store import initialize_run, load_run_status
+from mathresearch.run_store import load_run_status
 from tests.unit.test_research_events import ACTION, DETAILS, PACKET, TELEMETRY
 from tests.unit.test_research_contracts import valid_request_payload
-from tests.helpers import valid_run_request_payload
 
 
 class ResearchStoreTests(unittest.TestCase):
-    def _new_run(self, root: Path) -> Path:
+    def _new_run(self, root: Path, payload: dict[str, object] | None = None) -> Path:
         root.mkdir(parents=True, exist_ok=True)
-        request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
+        request = root / "request.json"; request.write_text(json.dumps(payload or valid_request_payload()), encoding="utf-8")
         run = root / "run"; initialize_research(request, run); return run
 
     def _event(self, sequence: int, event_type: str, body: dict[str, object]) -> ResearchEvent:
@@ -94,6 +93,69 @@ class ResearchStoreTests(unittest.TestCase):
                     with open_research_run(run) as locked: locked.append(final)
             self.assertTrue((run / "events" / "000002.json").exists()); load_research_status(run)
             self.assertEqual((run / "report.md").read_text(encoding="utf-8"), "report")
+
+    def test_finished_tool_result_recovers_after_each_post_commit_projection_failure(self) -> None:
+        """A committed finish repairs result, receipt, and source without republishing the action."""
+        from mathresearch.research import store as store_module
+
+        for failed_name in ("result.json", "receipt.json", "source.json"):
+            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as temp:
+                request_payload = valid_request_payload()
+                request_payload["capabilities"]["fetch_sources"] = True
+                source_url = "https://example.test/source"
+                request_payload["sources"] = [{"id": "source-one", "kind": "url",
+                                               "title": "Source one", "text": None,
+                                               "url": source_url, "published_at": None}]
+                run = self._new_run(Path(temp), request_payload)
+                action = {"id": "a0001", "kind": "tool", "role": "fetch_source",
+                          "branch": None, "round": 0, "dependencies": [],
+                          "payload": {"id": "fetch-one", "operation": "fetch_source",
+                                      "arguments": {"source_id": "source-one"}}}
+                decision = self._event(2, "decision_recorded", {"decision_id": "d0001",
+                                      "kind": "tool", "reason_code": "acquire_source",
+                                      "action": action, "details": DETAILS})
+                intent = self._event(3, "action_intended", {"action_id": "a0001",
+                                    "packet": PACKET, "packet_sha256":
+                                    __import__("hashlib").sha256(canonical_json_bytes(PACKET)).hexdigest()})
+                with open_research_run(run) as locked:
+                    locked.append(decision)
+                    locked.append(intent)
+                    stdout = locked.write_capture("a0001", "stdout.bin", b"out")
+                    stderr = locked.write_capture("a0001", "stderr.log", b"err")
+                source = {"id": "source-one", "url": source_url}
+                finish = self._event(4, "action_finished", {"action_id": "a0001",
+                                     "outcome": "succeeded", "exit_code": 0,
+                                     "stdout_sha256": stdout, "stderr_sha256": stderr,
+                                     "result": {"source": source}, "error": None,
+                                     "telemetry": TELEMETRY})
+                original_new = store_module._atomic_write_new
+
+                def fail_selected_projection(target: Path, data: bytes) -> None:
+                    if target.name == failed_name:
+                        raise OSError(f"simulated {failed_name} publication failure")
+                    original_new(target, data)
+
+                with patch("mathresearch.research.store._atomic_write_new",
+                           side_effect=fail_selected_projection):
+                    with self.assertRaises(OSError):
+                        with open_research_run(run) as locked:
+                            locked.append(finish)
+
+                event_paths_before = sorted((run / "events").glob("*.json"))
+                self.assertEqual([path.name for path in event_paths_before],
+                                 ["000001.json", "000002.json", "000003.json", "000004.json"])
+                recovered = load_research_status(run)
+
+                self.assertEqual(recovered.results["a0001"], {"source": source})
+                self.assertEqual(json.loads((run / "actions" / "a0001" / "result.json").read_text(encoding="utf-8")), {"source": source})
+                self.assertEqual(json.loads((run / "tools" / "a0001" / "receipt.json").read_text(encoding="utf-8")), {"source": source})
+                self.assertEqual(json.loads((run / "sources" / "source-one" / "source.json").read_text(encoding="utf-8")), source)
+                event_paths_after = sorted((run / "events").glob("*.json"))
+                self.assertEqual(event_paths_after, event_paths_before)
+                finished_events = [json.loads(path.read_text(encoding="utf-8"))
+                                   for path in event_paths_after
+                                   if json.loads(path.read_text(encoding="utf-8"))["event_type"] == "action_finished"]
+                self.assertEqual(len(finished_events), 1)
     def test_initializes_and_repairs_state_from_immutable_event(self) -> None:
         with tempfile.TemporaryDirectory() as temp:
             root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
@@ -127,12 +189,124 @@ class ResearchStoreTests(unittest.TestCase):
             with self.assertRaises(RuntimeError): load_research_status(run)
             self.assertFalse((run / "state.json").exists())
 
-    def test_legacy_run_status_preserves_all_committed_bytes(self) -> None:
+    def test_complete_hand_authored_v2_status_preserves_every_file_byte(self) -> None:
         with tempfile.TemporaryDirectory() as temp:
-            root = Path(temp); request = root / "legacy-request.json"
-            request.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
-            run = root / "legacy-run"; initialize_run(request, run)
+            run = Path(temp) / "v2-run"
+            events_dir = run / "events"
+            events_dir.mkdir(parents=True)
+            (run / ".run.lock").write_bytes(b"\0")
+            occurred_at = "2099-01-01T00:00:00.000000Z"
+            request = {"schema_version": 1, "record_type": "run_request",
+                       "run_id": "quick-v2-fixture", "question": "q", "actual_goal": None,
+                       "context": None, "constraints": [], "audience_level": "general",
+                       "mode": "quick", "stakes": "ordinary", "learning_mode": False,
+                       "capabilities": {}, "budgets": {"max_accepted_submissions": 4,
+                       "max_revision_cycles": 0, "elapsed_time_seconds": None}}
+            frame = {"framed_question": "q", "success_criteria": ["answer"], "terms": [],
+                     "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"}
+            investigate = {"answer": "a", "claims": [{"id": "claim-one", "statement": "s",
+                           "basis": "derived", "support": "calculation"}], "alternatives": [],
+                           "limitations": []}
+            verify = {"checks": [{"claim_id": "claim-one", "verdict": "supported",
+                      "reasoning": "checked"}], "disposition": "pass", "limitations": []}
+            explain = {"summary": "summary", "explanation": "explanation",
+                       "conclusion": "supported", "limitations": []}
+            packets = {
+                "frame": {"stage": "frame", "request": request, "inputs": {},
+                          "output_schema": {}, "capabilities": {}},
+                "investigate": {"stage": "investigate", "request": request,
+                                "inputs": {"frame": frame}, "output_schema": {},
+                                "capabilities": {}},
+                "verify": {"stage": "verify", "request": request,
+                           "inputs": {"frame": frame, "investigate": investigate},
+                           "output_schema": {}, "capabilities": {}},
+                "explain": {"stage": "explain", "request": request,
+                            "inputs": {"frame": frame, "investigate": investigate,
+                                       "verify": verify}, "output_schema": {},
+                            "capabilities": {}},
+            }
+            stdout = {stage: f"stdout-{stage}".encode("ascii")
+                      for stage in ("frame", "investigate", "verify", "explain")}
+            stderr = {stage: f"stderr-{stage}".encode("ascii")
+                      for stage in ("frame", "investigate", "verify", "explain")}
+            digest = __import__("hashlib").sha256
+
+            def workflow(sequence: int, event_type: str,
+                         body: dict[str, object]) -> dict[str, object]:
+                return {"schema_version": 2, "record_type": "workflow_event",
+                        "sequence": sequence, "event_type": event_type,
+                        "run_id": "quick-v2-fixture", "occurred_at": occurred_at,
+                        "body": body}
+
+            events = [
+                {"schema_version": 1, "record_type": "run_event", "sequence": 1,
+                 "event_type": "run_initialized", "run_id": "quick-v2-fixture",
+                 "occurred_at": occurred_at, "request": request},
+                workflow(2, "quick_configured", {"adapter": "codex", "executable": "codex",
+                         "model": None, "protocol_version": "1", "capabilities": {},
+                         "stages": ["frame", "investigate", "verify", "explain"]}),
+                workflow(3, "quick_attempt_intended", {"stage": "frame", "attempt": 1,
+                         "packet": packets["frame"]}),
+                workflow(4, "quick_attempt_finished", {"stage": "frame", "attempt": 1,
+                         "outcome": "succeeded", "exit_code": 0,
+                         "stdout_sha256": digest(stdout["frame"]).hexdigest(),
+                         "stderr_sha256": digest(stderr["frame"]).hexdigest(),
+                         "result": frame, "error": None}),
+                workflow(5, "quick_stage_accepted", {"stage": "frame", "attempt": 1}),
+                workflow(6, "quick_attempt_intended", {"stage": "investigate", "attempt": 1,
+                         "packet": packets["investigate"]}),
+                workflow(7, "quick_attempt_finished", {"stage": "investigate", "attempt": 1,
+                         "outcome": "succeeded", "exit_code": 0,
+                         "stdout_sha256": digest(stdout["investigate"]).hexdigest(),
+                         "stderr_sha256": digest(stderr["investigate"]).hexdigest(),
+                         "result": investigate, "error": None}),
+                workflow(8, "quick_stage_accepted", {"stage": "investigate", "attempt": 1}),
+                workflow(9, "quick_attempt_intended", {"stage": "verify", "attempt": 1,
+                         "packet": packets["verify"]}),
+                workflow(10, "quick_attempt_finished", {"stage": "verify", "attempt": 1,
+                         "outcome": "succeeded", "exit_code": 0,
+                         "stdout_sha256": digest(stdout["verify"]).hexdigest(),
+                         "stderr_sha256": digest(stderr["verify"]).hexdigest(),
+                         "result": verify, "error": None}),
+                workflow(11, "quick_stage_accepted", {"stage": "verify", "attempt": 1}),
+                workflow(12, "quick_attempt_intended", {"stage": "explain", "attempt": 1,
+                         "packet": packets["explain"]}),
+                workflow(13, "quick_attempt_finished", {"stage": "explain", "attempt": 1,
+                         "outcome": "succeeded", "exit_code": 0,
+                         "stdout_sha256": digest(stdout["explain"]).hexdigest(),
+                         "stderr_sha256": digest(stderr["explain"]).hexdigest(),
+                         "result": explain, "error": None}),
+                workflow(14, "quick_stage_accepted", {"stage": "explain", "attempt": 1}),
+                workflow(15, "quick_completed", {"report_markdown": "# Complete v2 report\n"}),
+            ]
+
+            def write_json(path: Path, payload: object) -> None:
+                path.parent.mkdir(parents=True, exist_ok=True)
+                path.write_bytes(json.dumps(payload, ensure_ascii=False,
+                                            separators=(",", ":")).encode("utf-8"))
+
+            write_json(run / "request.json", request)
+            write_json(run / "state.json", {"schema_version": 2,
+                       "record_type": "quick_state", "run_id": "quick-v2-fixture",
+                       "initialized_at": occurred_at, "status": "complete",
+                       "last_event_sequence": 15, "accepted_submission_count": 4,
+                       "current_stage": None, "reason": None, "report_path": "report.md"})
+            for sequence, payload in enumerate(events, 1):
+                write_json(events_dir / f"{sequence:06d}.json", payload)
+            for stage, result in (("frame", frame), ("investigate", investigate),
+                                  ("verify", verify), ("explain", explain)):
+                task_dir = run / "tasks" / f"task-{stage}"
+                attempt_dir = task_dir / "attempts" / f"attempt-{stage}-001"
+                write_json(task_dir / "accepted.json", result)
+                write_json(attempt_dir / "packet.json", packets[stage])
+                (attempt_dir / "stdout.bin").write_bytes(stdout[stage])
+                (attempt_dir / "stderr.log").write_bytes(stderr[stage])
+            (run / "report.md").write_bytes(b"# Complete v2 report\n")
+
             before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
-            load_run_status(run)
+            state = load_run_status(run)
             after = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
+
+            self.assertEqual(state.status, "complete")
+            self.assertEqual(state.last_event_sequence, 15)
             self.assertEqual(after, before)
