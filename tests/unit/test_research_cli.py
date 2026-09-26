"""Tests for research command authorization and resume behavior."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
import uuid

from mathresearch.research.cli import _promote_live_authorization

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ResearchCliTests(unittest.TestCase):
    def test_explicit_live_resume_promotes_saved_dry_run_manifest(self) -> None:
        directory = PROJECT_ROOT / f".research-cli-test-{uuid.uuid4().hex}"
        directory.mkdir()
        try:
            path = directory / "manifest.json"
            original = {"execution_authorization": "dry_run_only", "caps": {"max_provider_calls": 9}}
            path.write_text(json.dumps(original), encoding="utf-8")

            promoted = _promote_live_authorization(path, original)

            self.assertEqual(promoted["execution_authorization"], "live_explicit")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), promoted)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_live_authorization_promotion_leaves_other_authorizations_unchanged(self) -> None:
        original = {"execution_authorization": "live_explicit"}
        self.assertIs(_promote_live_authorization(Path("unused.json"), original), original)


if __name__ == "__main__":
    unittest.main()
