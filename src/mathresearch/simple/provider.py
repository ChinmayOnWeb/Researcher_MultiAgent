"""One invocation per stage. No application retries or model repair calls."""

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from .models import Settings, schema


@dataclass(frozen=True)
class Reply:
    raw: bytes
    returned: bool = True
    succeeded: bool = True
    calls: int | None = 1
    error: str | None = None
    observed_model: str | None = None
    observed_effort: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class FakeProvider:
    name = "fake"

    def __init__(self, responses: dict[int, bytes] | None = None):
        self.responses = responses or {}
        self.prompts: list[str] = []

    def __call__(self, prompt: str, kind: str, settings: Settings, directory: Path) -> Reply:
        self.prompts.append(prompt)
        index = len(self.prompts)
        value = ({"verdict": "pass", "issues": []} if kind == "critique" else
                 {"answer": f"Deterministic fixture answer {index}.",
                  "assumptions": [], "uncertainties": []})
        raw = self.responses.get(index, json.dumps(value).encode("utf-8"))
        return Reply(raw, observed_model=settings.model, observed_effort=settings.effort)


class CodexProvider:
    name = "codex"

    def __init__(self):
        self.adapter = None

    def __call__(self, prompt: str, kind: str, settings: Settings, directory: Path) -> Reply:
        # Lazy imports keep the offline path completely provider-independent.
        from mathresearch.adapters.codex import CodexAdapter
        from mathresearch.adapters.base import WorkerInput
        from mathresearch.worker_process import execute_worker

        class RawAdapter(CodexAdapter):
            def decode(self, stdout, result_bytes):
                # The launcher needs a mapping; the simple parser below the
                # provider boundary exclusively interprets the final payload.
                return {}

        if self.adapter is None:
            executable = shutil.which("codex")
            if executable is None:
                return Reply(b"", False, False, 0, "Codex executable is unavailable")
            self.adapter = RawAdapter(Path(executable), model=settings.model,
                                      reasoning_effort=settings.effort)
        elif (self.adapter.model, self.adapter.reasoning_effort) != (settings.model, settings.effort):
            raise ValueError("provider settings changed during the experiment")
        scratch = directory / "provider"
        scratch.mkdir()
        output = execute_worker(self.adapter, WorkerInput("response", prompt, schema(kind)),
            scratch=scratch, timeout_seconds=settings.timeout_seconds)
        (directory / "stdout.bin").write_bytes(output.stdout)
        (directory / "stderr.bin").write_bytes(output.stderr)
        raw = output.raw_result
        if raw is None:
            # A timed-out process may still have written a partial final reply.
            from mathresearch.worker_process import _read_result_if_present
            try:
                raw = _read_result_if_present(scratch / "result.json", scratch.resolve())
            except (OSError, ValueError):
                raw = None
        header = output.stderr.decode("utf-8", "replace").splitlines()
        header = header[:header.index("user")] if "user" in header else []
        values = {}
        for key, label in (("model", "model: "), ("effort", "reasoning effort: ")):
            matches = [line[len(label):].strip() for line in header if line.startswith(label)]
            values[key] = matches[0] if len(matches) == 1 else None
        mismatch = ((values["model"] is not None and values["model"] != settings.model) or
                    (values["effort"] is not None and values["effort"] != settings.effort))
        return Reply(raw or b"", output.exit_code is not None,
            output.outcome == "succeeded" and not mismatch,
            0 if output.outcome == "launch_failed" else 1,
            "observed model/effort mismatch" if mismatch else output.error,
            values["model"], values["effort"])
