"""Deterministic child-worker protocol for the first Frame task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .contracts.frame import FramePacket, FrameSubmission


def build_fake_frame_submission(packet: FramePacket, *, attempt: int) -> FrameSubmission:
    """Derive one stable, validated submission from a validated Frame packet."""
    packet = FramePacket.from_json(packet.to_json())
    missing_inputs: list[str] = []
    success_criteria: list[str] = []
    assumptions: list[str] = []
    if packet.request.actual_goal is None:
        missing_inputs.append("actual_goal")
    else:
        success_criteria.append(packet.request.actual_goal)
    if packet.request.context is None:
        missing_inputs.append("context")
    else:
        assumptions.append(packet.request.context)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "frame_submission",
        "submission_id": f"submission-frame-{attempt:03d}",
        "run_id": packet.task.run_id,
        "task_id": packet.task.task_id,
        "revision": packet.task.revision,
        "attempt": attempt,
        "submitted_at": "2026-01-01T00:00:00.000000Z",
        "frame": {
            "framed_question": packet.request.question,
            "success_criteria": success_criteria,
            "terms": ["research question"],
            "assumptions": assumptions,
            "missing_inputs": missing_inputs,
            "stakes_assessment": packet.request.stakes,
        },
    }
    return FrameSubmission.from_json(payload)


def _load_packet(path: Path) -> FramePacket:
    with path.open("r", encoding="utf-8") as packet_file:
        payload = json.load(packet_file, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    return FramePacket.from_json(payload)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate key: {key}")
        payload[key] = value
    return payload


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def main(argv: list[str] | None = None) -> int:
    """Run the narrow child protocol; this is not the coordinator CLI."""
    parser = argparse.ArgumentParser(prog="mathresearch.fake_worker")
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--attempt", required=True, type=int)
    arguments = parser.parse_args(argv)
    try:
        submission = build_fake_frame_submission(_load_packet(arguments.packet), attempt=arguments.attempt)
        sys.stdout.buffer.write(
            json.dumps(submission.to_json(), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        )
        return 0
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        sys.stderr.write(f"fake Frame worker failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
