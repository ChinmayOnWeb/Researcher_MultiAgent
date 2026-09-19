"""Exact-URL, pinned-address HTTPS source acquisition and text normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit
from typing import Any, Callable, Mapping

from mathresearch.contracts.validation import ValidationError
from mathresearch.research.implementation import BROKER_IMPLEMENTATIONS, IMPLEMENTATION_VERSION

NORMALIZER_VERSION = BROKER_IMPLEMENTATIONS[IMPLEMENTATION_VERSION]["html_normalizer"]
BROKER_VERSION = IMPLEMENTATION_VERSION
MAX_RESPONSE_BYTES = 1024 * 1024


class SourceFetchError(ValueError):
    """A bounded, reportable source acquisition failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _HTMLText(HTMLParser):
    _BLOCKS = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
               "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
               "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
               "table", "tbody", "td", "th", "thead", "tr", "ul"}
    _DROP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._DROP:
            self.drop_stack.append(tag)
        elif not self.drop_stack and tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.drop_stack:
            index = len(self.drop_stack) - 1 - self.drop_stack[::-1].index(tag)
            del self.drop_stack[index:]
        elif not self.drop_stack and tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.drop_stack:
            self.parts.append(data)


def normalize_text(text: str, content_type: str) -> str:
    if content_type == "text/html":
        parser = _HTMLText()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:
            raise SourceFetchError("invalid_html") from exc
        text = " ".join("".join(parser.parts).split())
    else:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        raise SourceFetchError("source_text_empty")
    if len(text) > 32768:
        raise SourceFetchError("source_text_too_large")
    return text


def validate_captured_source(value: Any, *, requested: Mapping[str, Any],
                             authorized_urls: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
    """Strictly validate a broker-created SourceRecord against its authorized URL descriptor."""
    if not isinstance(value, Mapping): raise ValidationError("source", "must be an object")
    keys = {"id", "origin", "title", "url", "published_at", "captured_at", "text", "sha256", "retrieval_receipt"}
    if set(value) != keys: raise ValidationError("source", "has unknown or missing fields")
    if value["id"] != requested.get("id") or value["origin"] != "retrieved":
        raise ValidationError("source", "must match the authorized retrieved source")
    if value["title"] != requested.get("title") or value["published_at"] != requested.get("published_at"):
        raise ValidationError("source", "must preserve descriptor metadata")
    if not isinstance(value["url"], str): raise ValidationError("source.url", "must be a string")
    validate_https_url(value["url"])
    text = value["text"]
    if not isinstance(text, str) or not text or len(text) > 32768:
        raise ValidationError("source.text", "must be a nonempty string of at most 32768 characters")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if value["sha256"] != digest: raise ValidationError("source.sha256", "must match normalized text")
    try:
        captured = datetime.fromisoformat(value["captured_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None or captured.utcoffset() != timezone.utc.utcoffset(captured): raise ValueError
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError("source.captured_at", "must be a UTC timestamp") from exc
    receipt = value["retrieval_receipt"]
    if not isinstance(receipt, Mapping) or set(receipt) != {"requested_url", "final_url", "http_status", "content_type", "raw_sha256", "text_sha256", "byte_count"}:
        raise ValidationError("source.retrieval_receipt", "has unknown or missing fields")
    if receipt["requested_url"] != requested.get("url") or receipt["final_url"] != value["url"] or receipt["http_status"] != 200:
        raise ValidationError("source.retrieval_receipt", "does not match requested and captured URLs")
    requested_host, _ = validate_https_url(requested.get("url"))
    final_host, _ = validate_https_url(value["url"])
    if final_host != requested_host and value["url"] not in set(authorized_urls or ()):
        raise ValidationError("source.url", "cross-host redirect target is not authorized")
    if receipt["text_sha256"] != digest or isinstance(receipt["http_status"], bool):
        raise ValidationError("source.retrieval_receipt", "text hash or status is invalid")
    for key in ("raw_sha256", "text_sha256"):
        item = receipt[key]
        if not isinstance(item, str) or len(item) != 64 or any(c not in "0123456789abcdef" for c in item):
            raise ValidationError(f"source.retrieval_receipt.{key}", "must be lowercase SHA-256")
    if not isinstance(receipt["byte_count"], int) or isinstance(receipt["byte_count"], bool) or receipt["byte_count"] < 0:
        raise ValidationError("source.retrieval_receipt.byte_count", "must be a nonnegative integer")
    if receipt["content_type"] not in {"text/plain", "text/html"}:
        raise ValidationError("source.retrieval_receipt.content_type", "is unsupported")
    return dict(value)


def validate_https_url(url: str) -> tuple[str, int]:
    if not isinstance(url, str):
        raise SourceFetchError("invalid_url")
    try:
        parsed = urlsplit(url)
        port = 443 if parsed.port is None else parsed.port
    except ValueError as exc:
        raise SourceFetchError("invalid_url") from exc
    if (parsed.scheme != "https" or not parsed.hostname or port != 443 or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise SourceFetchError("invalid_url")
    hostname = parsed.hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise SourceFetchError("ip_literal_denied")
    if any(ord(char) < 33 for char in hostname) or not hostname:
        raise SourceFetchError("invalid_url")
    return hostname, port


def _resolve_public(hostname: str, port: int, resolver: Callable[..., Any]) -> list[str]:
    try:
        records = resolver(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, TimeoutError) as exc:
        raise SourceFetchError("dns_failure") from exc
    addresses: list[str] = []
    for record in records:
        raw = record[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SourceFetchError("invalid_dns_address") from exc
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            raise SourceFetchError("non_global_address_denied")
        if raw not in addresses:
            addresses.append(raw)
    if not addresses:
        raise SourceFetchError("dns_no_addresses")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, timeout: float) -> None:
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _request_once(url: str, hostname: str, address: str, timeout: float) -> tuple[int, Mapping[str, str], bytes]:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    connection = _PinnedHTTPSConnection(hostname, address, timeout)
    try:
        connection.request("GET", path, headers={"Accept-Encoding": "identity", "User-Agent": "mathresearch/1"})
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1)
        headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, headers, body
    finally:
        connection.close()


def _charset(content_type_header: str | None, mime: str) -> str:
    message = Message()
    message["content-type"] = content_type_header or ""
    declared = message.get_param("charset", header="content-type")
    if declared is None:
        raise SourceFetchError("unsupported_charset")
    normalized = str(declared).strip("\"'").lower()
    if normalized not in {"utf-8", "utf8", "us-ascii", "ascii"}:
        raise SourceFetchError("unsupported_charset")
    return "ascii" if normalized in {"us-ascii", "ascii"} else "utf-8"


def fetch_source(source_id: str, descriptors: Mapping[str, Mapping[str, Any]], *,
                 authorized_urls: set[str] | frozenset[str] | None = None,
                 resolver: Callable[..., Any] = socket.getaddrinfo,
                 request_once: Callable[[str, str, str, float], tuple[int, Mapping[str, str], bytes]] = _request_once,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic: Callable[[], float] = time.monotonic,
                 timeout_seconds: float = 15.0) -> dict[str, Any]:
    """Fetch only a previously authorized URL descriptor, pinning validated DNS results."""
    descriptor = descriptors.get(source_id)
    if not isinstance(descriptor, Mapping) or descriptor.get("kind") != "url":
        raise SourceFetchError("source_not_authorized")
    original_url = descriptor.get("url")
    if not isinstance(original_url, str):
        raise SourceFetchError("invalid_url")
    authorized = set(authorized_urls or ())
    authorized.add(original_url)
    url = original_url
    deadline = monotonic() + timeout_seconds
    for redirect_count in range(4):
        hostname, port = validate_https_url(url)
        addresses = _resolve_public(hostname, port, resolver)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise SourceFetchError("fetch_timeout")
        status, headers, body = request_once(url, hostname, addresses[0], remaining)
        if len(body) > MAX_RESPONSE_BYTES:
            raise SourceFetchError("source_response_too_large")
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location or redirect_count == 3:
                raise SourceFetchError("redirect_limit_exceeded")
            destination = urljoin(url, location)
            new_host, _ = validate_https_url(destination)
            if new_host != hostname and destination not in authorized:
                raise SourceFetchError("redirect_not_authorized")
            url = destination
            continue
        if status != 200:
            raise SourceFetchError(f"http_status_{status}")
        if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
            raise SourceFetchError("unsupported_content_encoding")
        content_header = headers.get("content-type", "")
        message = Message(); message["content-type"] = content_header
        mime = message.get_content_type().lower()
        if mime not in {"text/plain", "text/html"}:
            raise SourceFetchError("unsupported_source_type")
        encoding = _charset(content_header, mime)
        try:
            decoded = body.decode(encoding, errors="strict")
        except UnicodeDecodeError as exc:
            raise SourceFetchError("invalid_source_encoding") from exc
        text = normalize_text(decoded, mime)
        existing_text_bytes = sum(len(item.get("text", "").encode("utf-8"))
            for key, item in descriptors.items() if key != source_id and isinstance(item, Mapping)
            and isinstance(item.get("text"), str))
        if existing_text_bytes + len(text.encode("utf-8")) > 65536:
            raise SourceFetchError("combined_source_text_too_large")
        captured = now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source = {"id": source_id, "origin": "retrieved", "title": descriptor["title"],
                  "url": url, "published_at": descriptor.get("published_at"), "captured_at": captured,
                  "text": text, "sha256": text_hash,
                  "retrieval_receipt": {"requested_url": original_url, "final_url": url,
                      "http_status": 200, "content_type": mime, "raw_sha256": hashlib.sha256(body).hexdigest(),
                      "text_sha256": text_hash, "byte_count": len(body)}}
        return {"source": source}
    raise SourceFetchError("redirect_limit_exceeded")
