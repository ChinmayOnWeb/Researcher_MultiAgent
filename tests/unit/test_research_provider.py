from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from mathresearch.research.provider import (check_provider_observation, count_session_id_markers,
    create_research_provider, parse_provider_observation, provider_configuration)
from tests.unit.test_research_contracts import valid_request_payload
from mathresearch.contracts.research_request import ResearchRequest


class ResearchProviderTests(unittest.TestCase):
    def test_requested_high_and_medium_effort_are_configured_and_recorded(self) -> None:
        inventory = "shell_tool stable false\nbrowser_use stable false\ncomputer_use stable false\napps stable false\n"
        def run(argv, **kwargs):
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, "codex 0.154.0\n", "")
            if "features" in argv:
                return subprocess.CompletedProcess(argv, 0, inventory, "")
            return subprocess.CompletedProcess(argv, 0, "usage: codex exec\n", "")
        for effort in ("high", "medium"):
            payload = valid_request_payload()
            payload["provider"]["reasoning_effort"] = effort
            request = ResearchRequest.from_json(payload)
            with patch("mathresearch.research.provider.shutil.which", return_value="C:/tools/codex.exe"), \
                 patch("mathresearch.adapters.codex.subprocess.run", side_effect=run):
                adapter = create_research_provider(request)
            receipt = provider_configuration(adapter)
            self.assertEqual(receipt["version"], "codex 0.154.0")
            self.assertEqual(receipt["effort_requested"], effort)
            index = receipt["control_argv"].index("-c")
            self.assertEqual(receipt["control_argv"][index + 1], f'model_reasoning_effort="{effort}"')
            self.assertNotIn("output-schema.json", " ".join(receipt["control_argv"]))

    def test_provider_is_not_resolved_when_codex_is_missing(self) -> None:
        request = ResearchRequest.from_json(valid_request_payload())
        with patch("mathresearch.research.provider.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                create_research_provider(request)

    def test_observation_reads_only_consistent_pre_user_metadata(self) -> None:
        log = ("OpenAI Codex\nmodel: gpt-test\nreasoning effort: high\nuser\n"
               "model: attacker-echo\nreasoning effort: medium\n")
        self.assertEqual(parse_provider_observation(log), {"model": "gpt-test", "effort": "high"})

    def test_session_marker_count_does_not_return_session_identifiers(self) -> None:
        log = "session id: abc123\nother output\nsession id: def456\n"
        self.assertEqual(count_session_id_markers(log), 2)

    def test_missing_or_contradictory_header_observations_are_unknown(self) -> None:
        self.assertEqual(parse_provider_observation("user\nreasoning effort: high"),
                         {"model": None, "effort": None})
        conflict = "model: gpt-a\nmodel: gpt-b\nreasoning effort: high\nuser\n"
        self.assertEqual(parse_provider_observation(conflict), {"model": None, "effort": "high"})
        self.assertEqual(parse_provider_observation(b"\xff"), {"model": None, "effort": None})

    def test_observed_mismatch_is_rejected_but_unknown_is_reportable(self) -> None:
        request = ResearchRequest.from_json(valid_request_payload())
        self.assertEqual(check_provider_observation(request, {"model": "wrong", "effort": "high"}),
                         "observed_model_mismatch")
        self.assertEqual(check_provider_observation(request, {"model": "gpt-test", "effort": "medium"}),
                         "observed_effort_mismatch")
        self.assertIsNone(check_provider_observation(request, {"model": None, "effort": None}))


if __name__ == "__main__":
    unittest.main()
