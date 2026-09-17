from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mathresearch.research.store import initialize_research, load_research_status
from tests.unit.test_research_contracts import valid_request_payload


class ResearchStoreTests(unittest.TestCase):
    def test_initializes_and_repairs_state_from_immutable_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
            run = root / "run"
            initialize_research(request, run)
            (run / "state.json").unlink()
            state = load_research_status(run)
            self.assertEqual(state.status, "ready")
            self.assertTrue((run / "state.json").exists())

    def test_rejects_unexpected_root_and_unsafe_action_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request = root / "request.json"; request.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
            run = root / "run"; initialize_research(request, run)
            (run / "unexpected").write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError): load_research_status(run)
