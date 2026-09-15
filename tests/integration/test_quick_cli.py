"""Integration tests for the public quick-workflow command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

from mathresearch.adapters.base import LaunchSpec, WorkerInput
from mathresearch.quick_workflow import _append
from mathresearch.run_store import initialize_run, open_locked_run


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"


def quick_request(*, accepted_budget: int = 4, mode: str = "quick") -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "run_request",
        "run_id": "quick-proof",
        "question": "Prove that the sum of the first n odd positive integers is n squared, using an algebraic argument and a geometric interpretation.",
        "actual_goal": "Provide an elementary proof.",
        "context": "Use only the supplied question.",
        "constraints": ["Do not browse or execute experiments."],
        "audience_level": "undergraduate",
        "mode": mode,
        "stakes": "ordinary",
        "learning_mode": False,
        "capabilities": {"browse": False, "execute_code": False},
        "budgets": {
            "max_accepted_submissions": accepted_budget,
            "max_revision_cycles": 0,
            "elapsed_time_seconds": None,
        },
    }


class StubAdapter:
    """Real argv child used only by the fresh-process CLI tests."""

    def __init__(self, executable: Path, *, mode: str) -> None:
        self.executable = executable
        self.mode = mode

    def prepare(self, task: WorkerInput, scratch: Path) -> LaunchSpec:
        return LaunchSpec(
            (sys.executable, str(self.executable), str(scratch / "result.json"), self.mode),
            task.prompt.encode("utf-8"),
            scratch,
            scratch / "result.json",
        )

    def decode(self, stdout: bytes, result_bytes: bytes | None) -> dict[str, object]:
        if result_bytes is None:
            raise ValueError("stub did not return a result")
        return json.loads(result_bytes)


def resolve_stub_provider(adapter_id: str, model: str | None) -> tuple[StubAdapter, str, Path, str | None]:
    """Resolver shape mirrors the CLI boundary while keeping the test provider local."""
    if adapter_id != "codex":
        raise ValueError("unsupported adapter")
    executable = Path(os.environ["MATHRESEARCH_STUB_EXECUTABLE"])
    return StubAdapter(executable, mode=os.environ.get("MATHRESEARCH_STUB_MODE", "valid")), "codex", executable, model


_STUB_SCRIPT = r'''
import json
import os
import pathlib
import sys

result_path = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
packet = json.loads(sys.stdin.read().split("\n", 1)[1])
stage = packet["stage"]
pathlib.Path(os.environ["MATHRESEARCH_STUB_COUNT"]).open("a", encoding="utf-8").write(stage + "\n")
if mode == "invalid":
    result_path.write_text("not-json", encoding="utf-8")
    raise SystemExit(0)
payloads = {
    "frame": {"framed_question": "Prove the odd-sum identity.", "success_criteria": ["algebraic argument", "geometric interpretation"], "terms": ["odd positive integers"], "assumptions": [], "missing_inputs": [], "stakes_assessment": "ordinary"},
    "investigate": {"answer": "The sum is n squared.", "claims": [{"id": "c1", "statement": "1 + 3 + ... + (2n-1) = n squared.", "basis": "derived", "support": "Adding the next odd number grows n squared to (n+1) squared."}], "alternatives": ["A tiled-square diagram gives the same recurrence."], "limitations": ["This is a model-generated derivation." ]},
    "verify": {"checks": [{"claim_id": "c1", "verdict": "supported", "reasoning": "The difference (n+1)^2 - n^2 equals 2n+1."}], "disposition": "pass", "limitations": ["No external verification was performed."]},
    "explain": {"summary": "Each new odd layer extends an n by n square.", "explanation": "Induction supplies the algebraic proof and concentric square layers supply the geometric interpretation.", "conclusion": "supported", "limitations": ["The provider did not execute code."]},
}
if mode == "verify-fail" and stage == "verify":
    payloads["verify"] = {"checks": [{"claim_id": "c1", "verdict": "contradicted", "reasoning": "Test fixture rejects the claim."}], "disposition": "fail", "limitations": []}
result_path.write_text(json.dumps(payloads[stage]), encoding="utf-8")
'''


class QuickCliIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PROJECT_ROOT / f".quick-cli-test-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.request = self.root / "request.json"
        self.run = self.root / "run"
        self.count = self.root / "launches.txt"
        self.stub = self.root / "provider.py"
        self.stub.write_text(_STUB_SCRIPT, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_request(self, **overrides: object) -> None:
        payload = quick_request(**overrides)
        self.request.write_text(json.dumps(payload), encoding="utf-8")

    def _environment(self, *, mode: str = "valid", unavailable_provider: bool = False) -> dict[str, str]:
        environment = os.environ | {
            "PYTHONPATH": os.pathsep.join((str(SOURCE_ROOT), str(PROJECT_ROOT))),
            "MATHRESEARCH_STUB_EXECUTABLE": str(self.stub),
            "MATHRESEARCH_STUB_COUNT": str(self.count),
            "MATHRESEARCH_STUB_MODE": mode,
        }
        if unavailable_provider:
            environment["PATH"] = ""
        return environment

    def _run(self, *arguments: str, stub: bool = False, mode: str = "valid", unavailable_provider: bool = False) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-m", "mathresearch", *arguments]
        if stub:
            command = [
                sys.executable,
                "-c",
                "import sys; import mathresearch.cli as c; from tests.integration.test_quick_cli import resolve_stub_provider; c.resolve_quick_provider = resolve_stub_provider; raise SystemExit(c.main(sys.argv[1:]))",
                *arguments,
            ]
        return subprocess.run(command, cwd=PROJECT_ROOT, env=self._environment(mode=mode, unavailable_provider=unavailable_provider), capture_output=True, text=True, check=False)

    def _launch_count(self) -> list[str]:
        if not self.count.exists():
            return []
        return self.count.read_text(encoding="utf-8").splitlines()

    def _initialize(self, **overrides: object) -> None:
        self._write_request(**overrides)
        result = self._run("init", "--request", str(self.request), "--run-dir", str(self.run), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_process_lifecycle_writes_report_and_completed_run_is_a_noop(self) -> None:
        """Removing a stage launch must break the observable four-stage report lifecycle."""
        self._initialize()

        run = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--timeout-seconds", "9", "--json", stub=True)

        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["run_status"], "complete")
        self.assertEqual(self._launch_count(), ["frame", "investigate", "verify", "explain"])
        status = self._run("status", "--run-dir", str(self.run), "--json")
        self.assertEqual(json.loads(status.stdout)["status"], "complete")
        report = (self.run / "report.md").read_text(encoding="utf-8")
        self.assertIn("sum of the first n odd positive integers", report)
        self.assertIn("No external retrieval", report)

        repeated = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["run_status"], "complete")
        self.assertEqual(self._launch_count(), ["frame", "investigate", "verify", "explain"])

    def test_unavailable_provider_is_reported_without_launching_a_worker(self) -> None:
        """An absent provider executable must fail before any intent is recorded."""
        self._initialize()
        result = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", unavailable_provider=True)
        self.assertEqual(result.returncode, 11)
        self.assertEqual(json.loads(result.stderr)["code"], "adapter_unavailable")
        self.assertEqual(self._launch_count(), [])

    def test_invalid_provider_json_is_a_protocol_error(self) -> None:
        """Accepting malformed structured output would let a provider bypass the stage schema."""
        self._initialize()
        result = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", stub=True, mode="invalid")
        self.assertEqual(result.returncode, 11)
        self.assertEqual(json.loads(result.stderr)["code"], "adapter_protocol_error")
        self.assertEqual(self._launch_count(), ["frame"])

    def test_conflicting_resume_options_fail_before_a_relaunch(self) -> None:
        """Ignoring a changed model would silently reinterpret persisted configuration."""
        self._initialize()
        complete = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", stub=True)
        self.assertEqual(complete.returncode, 0, complete.stderr)
        result = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--model", "different", "--json", stub=True)
        self.assertEqual(result.returncode, 20)
        self.assertEqual(json.loads(result.stderr)["code"], "unsupported_workflow")
        self.assertEqual(len(self._launch_count()), 4)

    def test_unsupported_mode_and_budget_exhaustion_are_honest(self) -> None:
        """Launching unsupported modes or claiming a four-stage completion under budget is a bug."""
        self._initialize(mode="research")
        unsupported = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", stub=True)
        self.assertEqual(unsupported.returncode, 20)
        self.assertEqual(json.loads(unsupported.stderr)["code"], "unsupported_workflow")
        self.assertEqual(self._launch_count(), [])

        shutil.rmtree(self.run)
        self._initialize(accepted_budget=3)
        exhausted = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", stub=True)
        self.assertEqual(exhausted.returncode, 12)
        self.assertEqual(json.loads(exhausted.stderr)["code"], "budget_exhausted")
        self.assertEqual(self._launch_count(), ["frame", "investigate", "verify"])

    def test_failed_verification_and_interrupted_intent_are_blocked(self) -> None:
        """A bad verification or ambiguous launch cannot be turned into a success by a later run."""
        self._initialize()
        rejected = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", stub=True, mode="verify-fail")
        self.assertEqual(rejected.returncode, 11)
        self.assertEqual(json.loads(rejected.stderr)["code"], "workflow_blocked")
        self.assertEqual(self._launch_count(), ["frame", "investigate", "verify"])

        shutil.rmtree(self.run)
        self._initialize()
        with open_locked_run(self.run) as locked:
            _append(locked, "quick_configured", {"adapter": "codex", "executable": str(self.stub), "model": None, "protocol_version": "1", "capabilities": {"reasoning": True}, "stages": ["frame", "investigate", "verify", "explain"]})
            _append(locked, "quick_attempt_intended", {"stage": "frame", "attempt": 1, "packet": {"stage": "frame", "request": locked.request.to_json(), "inputs": {}, "output_schema": {}, "capabilities": {}}})
        interrupted = self._run("run", "--run-dir", str(self.run), "--adapter", "codex", "--json", stub=True)
        self.assertEqual(interrupted.returncode, 11)
        self.assertEqual(json.loads(interrupted.stderr)["code"], "workflow_blocked")
        self.assertEqual(self._launch_count(), ["frame", "investigate", "verify"])


if __name__ == "__main__":
    unittest.main()
