"""JSON transport handling; never judges the intellectual answer."""

from dataclasses import dataclass
import json
import re

from .models import envelope_error


@dataclass(frozen=True)
class Parsed:
    value: dict | None
    text: str | None
    parse_error: str | None
    envelope_error: str | None

    @property
    def protocol_valid(self) -> bool:
        return self.parse_error is None and self.envelope_error is None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _finite(value):
    raise ValueError("nonfinite JSON value")


def parse_object(text: str) -> dict:
    candidate = text.removeprefix("\ufeff").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n\s*```", candidate, re.S | re.I)
    if fenced:
        candidate = fenced.group(1).strip()
    decoder = json.JSONDecoder(object_pairs_hook=_unique, parse_constant=_finite)
    roots = []
    position = 0
    # Advance past each whole value; never rescue a nested object from a broken
    # outer object or array. Any competing container makes extraction ambiguous.
    while match := re.search(r"[\[{]", candidate[position:]):
        start = position + match.start()
        value, position = decoder.raw_decode(candidate, start)
        roots.append(value)
    if len(roots) != 1 or not isinstance(roots[0], dict):
        raise ValueError("expected one unambiguous JSON object")
    return roots[0]


def parse_output(raw: bytes, kind: str) -> Parsed:
    text = raw.decode("utf-8", "replace")
    value = None
    error = None
    try:
        value = parse_object(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        error = str(exc)
    envelope = envelope_error(value, kind) if value is not None else None
    semantic = None
    if kind == "answer":
        if value is not None and isinstance(value.get("answer"), str):
            semantic = value["answer"].strip() or None
        if semantic is None and value is None:
            # Only recover an explicit, complete answer string. For competing
            # answers retain all raw text rather than arbitrarily selecting one.
            fields = list(re.finditer(r'"answer"\s*:\s*', text))
            if len(fields) == 1:
                try:
                    answer, _ = json.JSONDecoder().raw_decode(text, fields[0].end())
                    if isinstance(answer, str):
                        semantic = answer.strip() or None
                except ValueError:
                    pass
            if semantic is None and text.strip():
                stripped = text.strip()
                if len(fields) > 1 or not stripped.startswith(("{", "[", "```")):
                    semantic = stripped
    elif value is not None:
        semantic = json.dumps(value, ensure_ascii=False)
    elif text.strip():
        semantic = text.strip()
    return Parsed(value, semantic, error, envelope)
