# Task 3 final review package

Base: c99d309a3b2f24fb5ae6844b1daf3f60ede3528c
Head: dc42056003aec04df112daa2ff63902050f56815

## Diff
diff --git a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
index 7cfb866..5ec804e 100644
--- a/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
+++ b/.superpowers/sdd/2026-09-16-research-quality-repair/task-3-report.md
@@ -85,3 +85,43 @@ $env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit
 Exit code: `0`. Result: `Ran 43 tests in 3.753s — OK`.
 
 The focused existing tests exercised capture corruption, link/reparse/hardlink and legacy v1/v2 compatibility through `test_run_store`. New dedicated Task 3 fault-injection and v2-byte fixture tests were not added in this round and are not claimed as evidence.
+
+## Fix round 3
+
+`decision_recorded` now requires its decision kind and embedded Action kind to agree, so a worker decision cannot launch a tool Action or vice versa. Replay also rejects `research_finished` while a human gate remains open, independently of Task 7 routing reasons.
+
+Targeted reducer verification:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events -v
+```
+
+Exit code: `0`. Result: `Ran 7 tests in 0.007s — OK`.
+
+The required decision/intent/capture/finish/gate/final-report fault-injection matrix and a dedicated hand-authored v2 byte-preservation fixture remain missing. They are not claimed as implemented in this commit.
+
+## Fix round 3 follow-up
+
+Added a legacy-store byte-preservation regression: it hand-authors a legacy request, initializes the legacy run, snapshots every committed file's relative path and bytes, calls legacy `load_run_status`, and requires exact equality afterward. The targeted test passed with `Ran 4 tests ... OK`; the required combined suite then passed with `Ran 45 tests in 3.495s — OK`.
+
+The requested v3 fault-injection matrix remains incomplete and is not claimed as covered by this follow-up. Existing `test_run_store` continues to exercise projection publication faults, link/reparse/hardlink checks, stale temporary alias validation, and immutable evidence repair for the legacy store.
+
+## Final Task 3 coverage pass
+
+`test_v3_fault_matrix_preserves_committed_boundaries` injects failures through the real v3 atomic store seams at decision event commit, intent packet projection, first capture, second capture, action-finish event commit, gate-response event commit, and final report materialization. It uses hand-authored events and verifies the exact durable boundary in each case: failed commits leave no event; a committed intent survives packet projection failure and recovers without a duplicate event; capture failures retain only the already-published capture; failed finish/gate commits leave their event sequence absent; and a committed final event repairs its report on status replay.
+
+Targeted command:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_store -v
+```
+
+Exit code: `0`. Result: `Ran 5 tests in 0.705s — OK`.
+
+Required command:
+
+```powershell
+$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v
+```
+
+Exit code: `0`. Result: `Ran 46 tests in 3.899s — OK`.
diff --git a/src/mathresearch/research/events.py b/src/mathresearch/research/events.py
index a95bc8c..09d4681 100644
--- a/src/mathresearch/research/events.py
+++ b/src/mathresearch/research/events.py
@@ -115,6 +115,8 @@ def _validate_body(kind: str, payload: Any) -> dict[str, Any]:
         if decision_kind not in {"worker", "tool", "gate", "finish", "noop"}: raise ValidationError("decision.kind", "is invalid")
         action = None if data["action"] is None else validate_action(data["action"])
         if (decision_kind in {"worker", "tool"}) != (action is not None): raise ValidationError("decision.action", "must match decision kind")
+        if action is not None and action["kind"] != decision_kind:
+            raise ValidationError("decision.action.kind", "must match decision kind")
         return {"decision_id": require_identifier(data["decision_id"], "decision_id"), "kind": decision_kind, "reason_code": require_string(data["reason_code"], "reason_code"), "action": action, "details": validate_decision_details(data["details"])}
     if kind == "action_intended":
         require_exact_fields(data, kind, {"action_id", "packet", "packet_sha256"})
@@ -226,7 +228,7 @@ def replay_research_events(events: list[ResearchEvent] | tuple[ResearchEvent, ..
             response_digests[response_key] = digest
             gate = None
         elif item.event_type == "research_finished":
-            if pending is not None: raise ValueError("finish while action pending")
+            if pending is not None or gate is not None: raise ValueError("finish while action or gate pending")
             terminal = item.body
     if request is None: raise ValueError("initialization required")
     status = terminal["status"] if terminal else ("awaiting_human" if gate else ("running" if pending else "ready"))
diff --git a/tests/unit/test_research_events.py b/tests/unit/test_research_events.py
index 16ab967..a83be3a 100644
--- a/tests/unit/test_research_events.py
+++ b/tests/unit/test_research_events.py
@@ -80,3 +80,10 @@ class ResearchEventTests(unittest.TestCase):
         history = quick_complete()
         history[1]["occurred_at"] = "2026-09-15T17:00:02-07:00"
         self.assertEqual(replay_research_events([ResearchEvent.from_json(item) for item in history]).sequence, 5)
+
+    def test_decision_action_kind_and_open_gate_finish_are_illegal(self) -> None:
+        decision = event(2, "decision_recorded", {"decision_id": "d0001", "kind": "worker", "reason_code": "frame_request", "action": {**ACTION, "kind": "tool", "role": "fetch_source", "payload": {"id": "tool-one", "operation": "fetch_source", "arguments": {"source_id": "source-one"}}}, "details": DETAILS})
+        with self.assertRaises(ValueError): ResearchEvent.from_json(decision)
+        gate = event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
+        finish = event(3, "research_finished", {"status": "incomplete", "assessment": {}, "reason": "x", "report_markdown": "", "log_markdown": ""})
+        with self.assertRaises(ValueError): replay_research_events([ResearchEvent.from_json(x) for x in [event(1, "research_initialized", {"request": valid_request_payload()}), gate, finish]])
diff --git a/tests/unit/test_research_store.py b/tests/unit/test_research_store.py
index b0a74c8..51b7fe0 100644
--- a/tests/unit/test_research_store.py
+++ b/tests/unit/test_research_store.py
@@ -5,14 +5,95 @@ import shutil
 import tempfile
 import unittest
 from pathlib import Path
+from unittest.mock import patch
 
 from mathresearch.research.events import ResearchEvent, canonical_json_bytes
 from mathresearch.research.store import initialize_research, load_research_status, open_research_run
+from mathresearch.run_store import initialize_run, load_run_status
 from tests.unit.test_research_events import ACTION, DETAILS, PACKET, TELEMETRY
 from tests.unit.test_research_contracts import valid_request_payload
+from tests.helpers import valid_run_request_payload
 
 
 class ResearchStoreTests(unittest.TestCase):
+    def _new_run(self, root: Path) -> Path:
+        root.mkdir(parents=True, exist_ok=True)
+        request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
+        run = root / "run"; initialize_research(request, run); return run
+
+    def _event(self, sequence: int, event_type: str, body: dict[str, object]) -> ResearchEvent:
+        return ResearchEvent.from_json({"schema_version": 3, "record_type": "research_event", "sequence": sequence, "event_type": event_type, "run_id": "odd-perfect-run", "occurred_at": f"2099-01-01T00:00:{sequence:02d}Z", "body": body})
+
+    def _decision(self) -> ResearchEvent:
+        return self._event(2, "decision_recorded", {"decision_id": "d0001", "kind": "worker", "reason_code": "frame_request", "action": ACTION, "details": DETAILS})
+
+    def _intent(self) -> ResearchEvent:
+        return self._event(3, "action_intended", {"action_id": "a0001", "packet": PACKET, "packet_sha256": __import__("hashlib").sha256(canonical_json_bytes(PACKET)).hexdigest()})
+
+    def test_v3_fault_matrix_preserves_committed_boundaries(self) -> None:
+        """Every injected publication failure leaves only durable evidence recoverable once."""
+        with tempfile.TemporaryDirectory() as temp:
+            root = Path(temp)
+            # Decision commit: no event is published when immutable event creation fails.
+            run = self._new_run(root / "decision")
+            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("decision")):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.append(self._decision())
+            self.assertFalse((run / "events" / "000002.json").exists())
+
+            # Intent projection: event commit survives packet materialization failure and recovers once.
+            run = self._new_run(root / "intent")
+            with open_research_run(run) as locked: locked.append(self._decision())
+            from mathresearch.research import store as store_module
+            original_new = store_module._atomic_write_new
+            def fail_packet(target: Path, data: bytes) -> None:
+                if target.name == "packet.json": raise OSError("packet")
+                original_new(target, data)
+            with patch("mathresearch.research.store._atomic_write_new", side_effect=fail_packet):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.append(self._intent())
+            self.assertTrue((run / "events" / "000003.json").exists()); load_research_status(run)
+            self.assertEqual(len(list((run / "events").glob("*.json"))), 3)
+
+            # First/second capture failures never invent a capture; completed intent remains unique.
+            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("first")):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.write_capture("a0001", "stdout.bin", b"out")
+            self.assertFalse((run / "actions" / "a0001" / "stdout.bin").exists())
+            with open_research_run(run) as locked: locked.write_capture("a0001", "stdout.bin", b"out")
+            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("second")):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.write_capture("a0001", "stderr.log", b"err")
+            self.assertTrue((run / "actions" / "a0001" / "stdout.bin").exists()); self.assertFalse((run / "actions" / "a0001" / "stderr.log").exists())
+
+            # Action-finish commit failure leaves no finish event; gate-response commit failure likewise.
+            stdout = __import__("hashlib").sha256(b"out").hexdigest(); stderr = __import__("hashlib").sha256(b"err").hexdigest()
+            finish = self._event(4, "action_finished", {"action_id": "a0001", "outcome": "succeeded", "exit_code": 0, "stdout_sha256": stdout, "stderr_sha256": stderr, "result": {"task_type": "exploration", "deliverables": ["d"], "subquestions": ["q"], "missing_inputs": [], "proposed_checks": [], "source_needs": []}, "error": None, "telemetry": TELEMETRY})
+            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("finish")):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.append(finish)
+            self.assertFalse((run / "events" / "000004.json").exists())
+
+            run = self._new_run(root / "gate")
+            gate = self._event(2, "gate_opened", {"gate_id": "g0001", "kind": "missing_inputs", "questions": ["q"], "allowed_response": ["supply"], "resume_token": "0" * 64})
+            with open_research_run(run) as locked: locked.append(gate)
+            answer = self._event(3, "gate_answered", {"gate_id": "g0001", "response_id": "r0001", "response": {}})
+            with patch("mathresearch.research.store._atomic_write_new", side_effect=OSError("gate")):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.append(answer)
+            self.assertFalse((run / "events" / "000003.json").exists())
+
+            run = self._new_run(root / "report")
+            final = self._event(2, "research_finished", {"status": "complete", "assessment": {}, "reason": "x", "report_markdown": "report", "log_markdown": "log"})
+            original_replace = store_module._atomic_write_replace
+            def fail_report(target: Path, data: bytes) -> None:
+                if target.name == "report.md": raise OSError("report")
+                original_replace(target, data)
+            with patch("mathresearch.research.store._atomic_write_replace", side_effect=fail_report):
+                with self.assertRaises(Exception):
+                    with open_research_run(run) as locked: locked.append(final)
+            self.assertTrue((run / "events" / "000002.json").exists()); load_research_status(run)
+            self.assertEqual((run / "report.md").read_text(encoding="utf-8"), "report")
     def test_initializes_and_repairs_state_from_immutable_event(self) -> None:
         with tempfile.TemporaryDirectory() as temp:
             root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
@@ -45,3 +126,13 @@ class ResearchStoreTests(unittest.TestCase):
             (run / "state.json").unlink()
             with self.assertRaises(RuntimeError): load_research_status(run)
             self.assertFalse((run / "state.json").exists())
+
+    def test_legacy_run_status_preserves_all_committed_bytes(self) -> None:
+        with tempfile.TemporaryDirectory() as temp:
+            root = Path(temp); request = root / "legacy-request.json"
+            request.write_text(json.dumps(valid_run_request_payload()), encoding="utf-8")
+            run = root / "legacy-run"; initialize_run(request, run)
+            before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
+            load_run_status(run)
+            after = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
+            self.assertEqual(after, before)
