from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import socket
import unittest

from mathresearch.research.sources import (SourceFetchError, fetch_source, normalize_text,
                                           validate_https_url)
from mathresearch.research.implementation import BROKER_IMPLEMENTATIONS, IMPLEMENTATION_VERSION


def dns(*addresses: str):
    return lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                                         for ip in addresses]


def descriptor(url: str = "https://example.test/note"):
    return {"note-a": {"id": "note-a", "kind": "url", "title": "Note A",
                       "text": None, "url": url, "published_at": None}}


class ResearchSourceTests(unittest.TestCase):
    def test_broker_v1_manifest_pins_html_normalizer(self) -> None:
        self.assertEqual(IMPLEMENTATION_VERSION, "mathresearch-broker-v1")
        self.assertEqual(BROKER_IMPLEMENTATIONS[IMPLEMENTATION_VERSION]["html_normalizer"], "html-normalizer-v1")
        normalized = normalize_text("<p>A &amp; B</p><script>hidden</script>", "text/html")
        self.assertEqual(normalized, "A & B")
        self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), "dff4ec67bd72f843cab6495130699248a946fd5f50433f890d4aa3191beca761")

    def test_https_authorization_rejects_unsafe_url_forms(self) -> None:
        for url in ("http://example.test/x", "https://user@example.test/x",
                    "https://example.test:444/x", "https://127.0.0.1/x",
                    "https://example.test/x#fragment"):
            with self.subTest(url=url), self.assertRaises(SourceFetchError):
                validate_https_url(url)

    def test_text_normalization_and_html_discard_rules(self) -> None:
        self.assertEqual(normalize_text("a\r\nb\rc", "text/plain"), "a\nb\nc")
        self.assertEqual(normalize_text("<p>A &amp; B</p><script>secret</script><div>C</div>",
                                        "text/html"), "A & B C")

    def test_fetch_pins_the_validated_address_and_records_hashes(self) -> None:
        body = b"<p>Captured &amp; normalized</p><style>hidden</style>"
        calls = []
        def request(url, host, address, timeout):
            calls.append((url, host, address, timeout))
            return 200, {"content-type": "text/html; charset=utf-8"}, body
        result = fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34"),
            request_once=request, now=lambda: datetime(2026, 9, 19, tzinfo=timezone.utc))
        source = result["source"]
        self.assertEqual(calls[0][2], "93.184.216.34")
        self.assertEqual(source["text"], "Captured & normalized")
        receipt = source["retrieval_receipt"]
        self.assertEqual(receipt["raw_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt["text_sha256"], hashlib.sha256(source["text"].encode()).hexdigest())
        self.assertEqual(receipt["byte_count"], len(body))

    def test_any_non_global_dns_answer_denies_before_transport(self) -> None:
        reached = []
        with self.assertRaisesRegex(SourceFetchError, "non_global"):
            fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34", "127.0.0.1"),
                         request_once=lambda *args: reached.append(args))
        self.assertEqual(reached, [])

    def test_cross_host_redirect_requires_an_exact_authorized_destination(self) -> None:
        body = b"ok"
        responses = [(302, {"location": "https://other.test/note"}, b"")]
        with self.assertRaisesRegex(SourceFetchError, "redirect_not_authorized"):
            fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34"),
                         request_once=lambda *args: responses.pop(0))
        responses = [(302, {"location": "https://other.test/note"}, b""),
                     (200, {"content-type": "text/plain; charset=ascii"}, body)]
        result = fetch_source("note-a", descriptor(), authorized_urls={"https://other.test/note"},
            resolver=dns("93.184.216.34"), request_once=lambda *args: responses.pop(0))
        self.assertEqual(result["source"]["url"], "https://other.test/note")

    def test_rejects_unsupported_type_encoding_and_oversized_body(self) -> None:
        with self.assertRaisesRegex(SourceFetchError, "unsupported_source_type"):
            fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34"),
                         request_once=lambda *args: (200, {"content-type": "application/pdf"}, b"%PDF"))
        with self.assertRaisesRegex(SourceFetchError, "invalid_source_encoding"):
            fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34"),
                         request_once=lambda *args: (200, {"content-type": "text/plain; charset=utf-8"}, b"\xff"))
        with self.assertRaisesRegex(SourceFetchError, "source_response_too_large"):
            fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34"),
                         request_once=lambda *args: (200, {"content-type": "text/plain; charset=utf-8"}, b"x" * (1024 * 1024 + 1)))

    def test_combined_text_cap_and_expired_deadline_stop_before_publication(self) -> None:
        descriptors = descriptor() | {"old-source": {"id": "old-source", "text": "x" * 32768},
                                      "older-source": {"id": "older-source", "text": "y" * 32768}}
        with self.assertRaisesRegex(SourceFetchError, "combined_source_text_too_large"):
            fetch_source("note-a", descriptors, resolver=dns("93.184.216.34"),
                request_once=lambda *args: (200, {"content-type": "text/plain; charset=utf-8"}, b"new"))
        calls = []
        with self.assertRaisesRegex(SourceFetchError, "fetch_timeout"):
            fetch_source("note-a", descriptor(), resolver=dns("93.184.216.34"),
                request_once=lambda *args: calls.append(args), timeout_seconds=0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
