"""Explicit opt-in real Codex Frame protocol smoke test.

Run only when a Codex account is authenticated::

    py -m mathresearch.adapters.codex_smoke --live
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

from .base import WorkerInput
from .codex import CodexAdapter
from ..worker_process import execute_worker


FRAME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["framed_question", "success_criteria", "terms", "assumptions", "missing_inputs", "stakes_assessment"],
    "properties": {
        "framed_question": {"type": "string"},
        "success_criteria": {"type": "array", "items": {"type": "string"}},
        "terms": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "missing_inputs": {"type": "array", "items": {"type": "string"}},
        "stakes_assessment": {"type": "string"},
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make one opt-in Codex Frame smoke call.")
    parser.add_argument("--live", action="store_true", help="required: actually invoke the authenticated provider")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("refusing provider call without --live")
    executable = shutil.which("codex")
    if executable is None:
        print("Codex smoke failed: executable unavailable")
        return 2
    with tempfile.TemporaryDirectory(prefix="mathresearch-codex-smoke-") as temporary:
        output = execute_worker(
            CodexAdapter(Path(executable)),
            WorkerInput(
                "frame",
                "Return the requested Frame object for: Prove the sum of the first n odd positive integers is n squared.",
                FRAME_SCHEMA,
            ),
            scratch=Path(temporary),
            timeout_seconds=180,
        )
    print(f"Codex smoke outcome={output.outcome} executable={executable} protocol=codex-cli-0.154.0")
    if output.error:
        print(f"error={output.error}")
    return 0 if output.outcome == "succeeded" else 1


if __name__ == "__main__":  # pragma: no cover - this is intentionally live-only.
    raise SystemExit(main())
