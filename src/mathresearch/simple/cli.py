"""python -m mathresearch.simple.cli evaluate ... (offline fake by default)."""

import argparse
import json
from pathlib import Path

from .evaluation import evaluate
from .models import Settings
from .provider import CodexProvider, FakeProvider


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("evaluate")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--question")
    source.add_argument("--cases", type=Path, help="JSON list of {id, question, context}")
    run.add_argument("--context", default="", help="fixed context for --question")
    run.add_argument("--out-dir", required=True, type=Path)
    run.add_argument("--provider", choices=("fake", "codex"), default="fake")
    run.add_argument("--live", action="store_true", help="explicitly authorize Codex calls")
    run.add_argument("--model", default="gpt-5.6-terra")
    run.add_argument("--effort", choices=("medium", "high"), default="medium")
    run.add_argument("--timeout-seconds", type=int, default=180)
    run.add_argument("--order-seed", type=int, default=0)
    args = parser.parse_args(argv)
    if (args.provider == "codex") != args.live:
        parser.error("use --provider codex together with --live; fake is offline")
    if args.cases and args.context:
        parser.error("supply each case's context in the cases file")
    try:
        cases = (json.loads(args.cases.read_text(encoding="utf-8")) if args.cases else
                 [{"id": "question", "question": args.question, "context": args.context}])
        if not isinstance(cases, list):
            raise ValueError("cases must be a JSON list")
        settings = Settings(args.model, args.effort, args.timeout_seconds)
        provider = CodexProvider() if args.live else FakeProvider()
        result = evaluate(cases, args.out_dir, provider, settings, seed=args.order_seed)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps({"status": result["status"], "provider": provider.name,
        "provider_calls": result["provider_calls"],
        "comparison": str((args.out_dir / "comparison.json").resolve())}))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
