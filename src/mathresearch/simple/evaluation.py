"""Write-once directories and a descriptive comparison, without event replay."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
import re
import time

from .models import CALL_COUNTS, CONDITIONS, Settings
from .parsing import parse_output
from .pipeline import run_single, run_sequential, run_pipeline
from .provider import Reply


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def known_total(rows: list[dict], key: str):
    values = [row[key] for row in rows]
    return sum(values) if values and all(value is not None for value in values) else None


@dataclass
class Stage:
    name: str
    text: str | None
    content: dict | str | None
    usable: bool


def evaluate(cases: list[dict], out_dir: Path, provider, settings: Settings = Settings(),
             *, seed: int = 0) -> dict:
    if not cases:
        raise ValueError("at least one case is required")
    normalized = []
    for case in cases:
        if not isinstance(case, dict) or set(case) - {"id", "question", "context"}:
            raise ValueError("cases contain only id, question, and optional context")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(case.get("id", ""))):
            raise ValueError("case id must contain lowercase words separated by hyphens")
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError("each case needs a question")
        if not isinstance(case.get("context", ""), str):
            raise ValueError("context must be text")
        normalized.append({"id": case["id"], "question": case["question"], "context": case.get("context", "")})
    if len({case["id"] for case in normalized}) != len(normalized):
        raise ValueError("duplicate case id")
    schedule = [{"case_id": case["id"], "condition": condition}
                for case in normalized for condition in CONDITIONS]
    random.Random(seed).shuffle(schedule)  # Generated once across the full experiment.
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    write_json(out_dir / "manifest.json", {"version": "simple-v1", "provider": provider.name,
        "settings": asdict(settings), "cases": normalized, "order_seed": seed,
        "condition_order": schedule, "expected_calls_per_condition": CALL_COUNTS,
        "max_provider_invocations": 9 * len(normalized), "resumable": False})
    all_metadata = []
    results = []
    started = time.monotonic()
    for scheduled in schedule:
        case = next(case for case in normalized if case["id"] == scheduled["case_id"])
        condition = scheduled["condition"]
        directory = out_dir / case["id"] / condition
        directory.mkdir(parents=True)
        rows = []
        stage_started = time.monotonic()

        def call(stage: str, kind: str, prompt: str) -> Stage:
            call_dir = directory / stage
            call_dir.mkdir()
            (call_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            before = time.monotonic()
            try:
                reply = provider(prompt, kind, settings, call_dir)
            except Exception as exc:
                reply = Reply(b"", False, False, None, f"{type(exc).__name__}: {exc}")
            elapsed = time.monotonic() - before
            # raw.txt contains exact original bytes, including invalid UTF-8.
            (call_dir / "raw.txt").write_bytes(reply.raw)
            parsed = parse_output(reply.raw, kind)
            if parsed.value is not None:
                write_json(call_dir / "parsed.json", parsed.value)
            if parsed.text:
                (call_dir / "semantic.txt").write_text(parsed.text, encoding="utf-8")
            metadata = {"model": settings.model, "effort": settings.effort,
                "condition": condition, "stage": stage,
                "provider_call_index": len(all_metadata) + 1, "wall_seconds": elapsed,
                "protocol_valid": parsed.protocol_valid,
                "semantic_output_available": bool(parsed.text),
                "parse_error": parsed.parse_error, "envelope_error": parsed.envelope_error,
                "provider_returned": reply.returned, "provider_succeeded": reply.succeeded,
                "provider_calls": reply.calls, "provider_error": reply.error,
                "observed_model": reply.observed_model, "observed_effort": reply.observed_effort,
                "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
                "cost_usd": reply.cost_usd}
            write_json(call_dir / "metadata.json", metadata)
            rows.append(metadata)
            all_metadata.append(metadata)
            content = parsed.value if parsed.protocol_valid else parsed.text
            return Stage(stage, parsed.text, content, reply.succeeded and bool(parsed.text))

        if condition == "single":
            final = run_single(case["question"], case["context"], call)
        elif condition == "sequential":
            final = run_sequential(case["question"], case["context"], call)
        else:
            final = run_pipeline(case["question"], case["context"], call)
        complete = len(rows) == CALL_COUNTS[condition] and final.usable and all(row["provider_succeeded"] for row in rows)
        result = {"case_id": case["id"], "condition": condition,
            "status": "complete" if complete else "incomplete",
            "answer": final.text, "answer_stage": final.name,
            "semantic_output_available": bool(final.text),
            "semantic_quality": {"status": "ungraded", "score": None},
            "protocol_valid": all(row["protocol_valid"] for row in rows),
            "final_answer_protocol_valid": next(row["protocol_valid"] for row in rows if row["stage"] == final.name),
            "provider_reliability": {"returned": sum(row["provider_returned"] for row in rows),
                                     "succeeded": sum(row["provider_succeeded"] for row in rows)},
            "provider_invocations": len(rows), "provider_calls": known_total(rows, "provider_calls"),
            "expected_provider_calls": CALL_COUNTS[condition],
            "wall_seconds": time.monotonic() - stage_started,
            "input_tokens": known_total(rows, "input_tokens"),
            "output_tokens": known_total(rows, "output_tokens"), "cost_usd": known_total(rows, "cost_usd")}
        write_json(directory / "result.json", result)
        results.append(result)
    comparison = {"version": "simple-v1", "provider": provider.name,
        "status": "complete" if all(row["status"] == "complete" for row in results) else "incomplete",
        "semantic_quality": {"status": "ungraded", "quality_gain_demonstrated": None},
        "condition_order": schedule, "conditions": results,
        "provider_invocations": len(all_metadata),
        "provider_calls": known_total(all_metadata, "provider_calls"),
        "wall_seconds": time.monotonic() - started,
        "input_tokens": known_total(all_metadata, "input_tokens"),
        "output_tokens": known_total(all_metadata, "output_tokens"),
        "cost_usd": known_total(all_metadata, "cost_usd")}
    write_json(out_dir / "comparison.json", comparison)
    return comparison
