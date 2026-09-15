from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from mathresearch.adapters.base import WorkerInput
from mathresearch.adapters.codex import CodexAdapter
from mathresearch.adapters.discovery import discover_built_in_adapters


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.scratch = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prepare_uses_verified_noninteractive_flags_and_stdin(self) -> None:
        adapter = CodexAdapter(Path("C:/tools/codex.exe"), model="gpt-test")
        spec = adapter.prepare(WorkerInput("frame", "prompt", {"type": "object"}), self.scratch)
        self.assertEqual(spec.argv[0], "C:\\tools\\codex.exe")
        self.assertEqual(spec.argv[1:], (
            "--ask-for-approval", "never", "--sandbox", "read-only", "exec",
            "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--model", "gpt-test", "--output-schema", str(self.scratch / "output-schema.json"),
            "--output-last-message", str(self.scratch / "result.json"), "-",
        ))
        self.assertEqual(spec.stdin, b"prompt")
        self.assertEqual(json.loads((self.scratch / "output-schema.json").read_text()), {"type": "object"})

    def test_preflight_rejects_codex_when_shell_execution_cannot_be_disabled(self) -> None:
        adapter = CodexAdapter(Path("C:/tools/codex.exe"))
        with self.assertRaisesRegex(ValueError, "shell execution"):
            adapter.preflight()

    def test_discovery_does_not_advertise_codex_as_reasoning_only_capable(self) -> None:
        codex = next(item for item in discover_built_in_adapters() if item.adapter_id == "codex")
        self.assertFalse(codex.available)
        self.assertIn("shell execution", codex.reason or "")

    def test_decode_requires_one_strict_json_value(self) -> None:
        adapter = CodexAdapter(Path("C:/tools/codex.exe"))
        self.assertEqual(adapter.decode(b"ignored", b'{"value": 1}'), {"value": 1})
        with self.assertRaises(ValueError):
            adapter.decode(b"ignored", b'{"value": 1} trailing')
        with self.assertRaises(ValueError):
            adapter.decode(b"ignored", b'{"value": NaN}')
