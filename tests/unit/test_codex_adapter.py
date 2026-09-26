from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mathresearch.adapters.base import WorkerInput
from mathresearch.adapters.codex import CodexAdapter
from mathresearch.adapters.discovery import discover_built_in_adapters
from mathresearch.quick_workflow import _schema


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.scratch = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prepare_uses_verified_noninteractive_flags_and_stdin(self) -> None:
        adapter = CodexAdapter(Path("C:/tools/codex.exe"), model="gpt-test")
        schema = _schema("investigate")
        spec = adapter.prepare(WorkerInput("investigate", "prompt", schema), self.scratch)
        self.assertEqual(spec.argv[0], "C:\\tools\\codex.exe")
        self.assertEqual(spec.argv[1:], (
            "--strict-config", "--disable", "shell_tool", "--disable", "browser_use",
            "--disable", "computer_use", "--disable", "apps", "--ask-for-approval",
            "never", "--sandbox", "read-only", "exec",
            "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--model", "gpt-test", "--output-schema", str(self.scratch / "output-schema.json"),
            "--output-last-message", str(self.scratch / "result.json"), "-",
        ))
        self.assertEqual(spec.stdin, b"prompt")
        persisted_schema = json.loads((self.scratch / "output-schema.json").read_text())
        self.assertEqual(persisted_schema, schema)
        self.assertIn("items", persisted_schema["properties"]["claims"])

    def test_reasoning_effort_is_one_literal_config_argument_before_exec(self) -> None:
        for effort in ("high", "medium"):
            with self.subTest(effort=effort):
                scratch = self.scratch / effort
                scratch.mkdir()
                spec = CodexAdapter(Path("codex"), model="gpt-test", reasoning_effort=effort).prepare(
                    WorkerInput("research", "prompt", _schema("investigate")), scratch)
                index = spec.argv.index("-c")
                self.assertEqual(spec.argv[index + 1], f'model_reasoning_effort="{effort}"')
                self.assertLess(index, spec.argv.index("exec"))

    def test_reasoning_effort_rejects_unsupported_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "reasoning_effort"):
            CodexAdapter(Path("codex"), reasoning_effort="none")

    @unittest.skipUnless(shutil.which("codex"), "requires the locally installed Codex CLI")
    def test_preflight_accepts_the_installed_disabled_tool_inventory(self) -> None:
        """Removing a required native disable switch must reject the provider before a worker starts."""
        CodexAdapter(Path(shutil.which("codex") or "codex")).preflight()

    def test_preflight_rejects_a_feature_inventory_that_leaves_shell_enabled(self) -> None:
        """Merely recognizing shell_tool is insufficient if its effective state remains true."""
        inventory = "shell_tool stable true\nbrowser_use stable false\ncomputer_use stable false\napps stable false\n"
        with patch(
            "mathresearch.adapters.codex.subprocess.run",
            return_value=subprocess.CompletedProcess(("codex",), 0, inventory, ""),
        ):
            with self.assertRaisesRegex(ValueError, "must be disabled"):
                CodexAdapter(Path("codex")).preflight()

    def test_discovery_advertises_codex_after_native_tools_are_disabled(self) -> None:
        codex = next(item for item in discover_built_in_adapters() if item.adapter_id == "codex")
        self.assertTrue(codex.available)
        self.assertIsNone(codex.reason)

    def test_decode_uses_shared_conservative_json_object_parser(self) -> None:
        adapter = CodexAdapter(Path("C:/tools/codex.exe"))
        self.assertEqual(adapter.decode(b"ignored", b'{"value": 1}'), {"value": 1})
        self.assertEqual(adapter.decode(b"ignored", b'\xef\xbb\xbf```json\n{"value": 1}\n```'), {"value": 1})
        self.assertEqual(adapter.decode(b"ignored", b'Answer:\n{"value": 1}\nDone'), {"value": 1})
        with self.assertRaises(ValueError):
            adapter.decode(b"ignored", b'{"value": 1} and {"value": 2}')
        with self.assertRaises(ValueError):
            adapter.decode(b"ignored", b'{"value": NaN}')
