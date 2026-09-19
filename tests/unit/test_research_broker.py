from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mathresearch.contracts.validation import ValidationError
from mathresearch.adapters.base import WorkerOutput
from mathresearch.research.broker import run_broker, validate_tool_receipt
from mathresearch.research.broker_worker import handle_request


class ResearchBrokerTests(unittest.TestCase):
    def test_actual_trusted_child_returns_recomputed_math_receipt(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            scratch = Path(temp)
            src_path = str(Path("src").resolve())
            env = dict(os.environ, PYTHONPATH=src_path)
            with patch.dict(os.environ, env, clear=True):
                receipt = run_broker(tool_id="a0001",
                    request={"id": "request-one", "operation": "check_integer", "arguments": {"n": 6}},
                    capabilities={"fetch_sources": False, "math_checks": True}, descriptors={},
                    authorized_urls=None, scope="initial check", scratch=scratch)
            self.assertEqual(receipt["status"], "succeeded")
            self.assertEqual(receipt["result"]["proper_divisors"], [1, 2, 3])
            self.assertEqual(receipt["implementation_version"], "mathresearch-broker-v1")

    def test_denied_capability_and_invalid_input_do_not_launch_child(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            with patch("mathresearch.research.broker.execute_worker") as execute:
                receipt = run_broker(tool_id="a0001",
                    request={"id": "request-one", "operation": "check_integer", "arguments": {"n": 6}},
                    capabilities={"fetch_sources": False, "math_checks": False}, descriptors={},
                    authorized_urls=None, scope="denied", scratch=Path(temp))
                self.assertEqual(receipt["status"], "denied")
                with self.assertRaises(ValidationError):
                    run_broker(tool_id="a0002",
                        request={"id": "request-two", "operation": "check_integer", "arguments": {"n": True}},
                        capabilities={"fetch_sources": False, "math_checks": True}, descriptors={},
                        authorized_urls=None, scope="bad input", scratch=Path(temp))
                execute.assert_not_called()

    def test_expired_remaining_budget_does_not_launch_child(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            with patch("mathresearch.research.broker.execute_worker") as execute:
                receipt = run_broker(tool_id="a0001",
                    request={"id": "request-one", "operation": "check_integer", "arguments": {"n": 6}},
                    capabilities={"fetch_sources": False, "math_checks": True}, descriptors={},
                    authorized_urls=None, scope="deadline", scratch=Path(temp), remaining_seconds=0)
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["error"], "operation_deadline_exhausted")
                execute.assert_not_called()

    def test_child_timeout_becomes_a_failed_receipt_without_retry(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            with patch("mathresearch.research.broker.execute_worker", return_value=WorkerOutput(
                "timed_out", None, b"", b"timed out", None, "broker timed out")) as execute:
                receipt = run_broker(tool_id="a0001",
                    request={"id": "request-one", "operation": "check_integer", "arguments": {"n": 6}},
                    capabilities={"fetch_sources": False, "math_checks": True}, descriptors={},
                    authorized_urls=None, scope="timeout", scratch=Path(temp))
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["error"], "broker timed out")
                execute.assert_called_once()

    def test_receipt_rejects_forged_math_output_or_wrong_action_id(self) -> None:
        request = {"id": "req-one", "operation": "check_integer", "arguments": {"n": 6}}
        receipt = {"tool_id": "a0001", "request": request, "status": "succeeded",
                   "result": {"n": 6, "proper_divisors": [1, 2, 3], "proper_divisor_sum": 6,
                              "is_perfect": False}, "error": None, "scope": "scope",
                   "implementation_version": "mathresearch-broker-v1"}
        with self.assertRaises(ValidationError):
            validate_tool_receipt(receipt, tool_id="a0001", request=request)
        with self.assertRaises(ValidationError):
            validate_tool_receipt(receipt, tool_id="a0002", request=request)
        with self.assertRaises(ValidationError):
            validate_tool_receipt(receipt | {"status": []}, tool_id="a0001", request=request)

    def test_fetch_worker_uses_exact_authorized_descriptor(self) -> None:
        body = b"source"
        digest = hashlib.sha256(body).hexdigest()
        normalized_hash = hashlib.sha256(b"source").hexdigest()
        record = {"id": "source-one", "origin": "retrieved", "title": "Source one",
                  "url": "https://example.test/source", "published_at": None,
                  "captured_at": "2026-09-19T00:00:00Z", "text": "source", "sha256": normalized_hash,
                  "retrieval_receipt": {"requested_url": "https://example.test/source",
                      "final_url": "https://example.test/source", "http_status": 200,
                      "content_type": "text/plain", "raw_sha256": digest,
                      "text_sha256": normalized_hash, "byte_count": len(body)}}
        envelope = {"schema_version": 1, "record_type": "broker_request", "tool_id": "a0001",
            "request": {"id": "req-one", "operation": "fetch_source", "arguments": {"source_id": "source-one"}},
            "scope": "source", "capabilities": {"fetch_sources": True, "math_checks": False},
            "descriptors": {"source-one": {"id": "source-one", "kind": "url", "title": "Source one",
                "url": "https://example.test/source", "published_at": None, "text": None}},
            "authorized_urls": ["https://example.test/source"], "timeout_seconds": 15}
        with patch("mathresearch.research.broker_worker.fetch_source",
                   return_value={"source": record}):
            receipt = handle_request(envelope)
        checked = validate_tool_receipt(receipt, tool_id="a0001", request=envelope["request"],
                                        requested_source=envelope["descriptors"]["source-one"],
                                        authorized_urls={"https://example.test/source"})
        self.assertEqual(checked["status"], "succeeded")
        forged = {**receipt, "result": {"source": {**record, "url": "https://evil.test/x"}}}
        with self.assertRaises(ValidationError):
            validate_tool_receipt(forged, tool_id="a0001", request=envelope["request"],
                                  requested_source=envelope["descriptors"]["source-one"],
                                  authorized_urls={"https://example.test/source"})


if __name__ == "__main__":
    unittest.main()
