"""Only the two provider-facing envelopes and experiment settings."""

from dataclasses import dataclass

CONDITIONS = ("single", "sequential", "pipeline")
CALL_COUNTS = dict(zip(CONDITIONS, (1, 3, 5)))


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-5.6-terra"
    effort: str = "medium"
    timeout_seconds: int = 180

    def __post_init__(self):
        if not self.model.strip() or self.effort not in {"medium", "high"}:
            raise ValueError("a model and medium/high effort are required")
        if type(self.timeout_seconds) is not int or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")


def schema(kind: str) -> dict:
    text_array = {"type": "array", "items": {"type": "string"}}
    if kind == "answer":
        properties = {"answer": {"type": "string"},
                      "assumptions": text_array, "uncertainties": text_array}
    elif kind == "critique":
        properties = {"verdict": {"type": "string", "enum": ["pass", "revise"]},
            "issues": {"type": "array", "items": {"type": "object",
                "properties": {"description": {"type": "string"},
                               "severity": {"type": "string", "enum": ["major", "minor"]}},
                "required": ["description", "severity"], "additionalProperties": False}}}
    else:
        raise ValueError("unknown envelope")
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def envelope_error(value: dict, kind: str) -> str | None:
    if set(value) != set(schema(kind)["required"]):
        return "envelope fields do not match the requested schema"
    if kind == "answer":
        if not isinstance(value["answer"], str) or not value["answer"].strip():
            return "answer must be nonempty text"
        if any(not isinstance(value[key], list) or
               any(not isinstance(item, str) for item in value[key])
               for key in ("assumptions", "uncertainties")):
            return "assumptions and uncertainties must be lists of text"
    else:
        if value["verdict"] not in ("pass", "revise") or not isinstance(value["issues"], list):
            return "critique requires a pass/revise verdict and an issues list"
        for issue in value["issues"]:
            if (not isinstance(issue, dict) or set(issue) != {"description", "severity"}
                    or not isinstance(issue["description"], str) or not issue["description"].strip()
                    or issue["severity"] not in ("major", "minor")):
                return "each issue requires a description and major/minor severity"
    return None
