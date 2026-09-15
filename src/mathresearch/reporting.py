"""Deterministic, coordinator-owned rendering for quick research reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts.records import RunRequest


def render_quick_report(request: RunRequest, accepted: Mapping[str, Mapping[str, Any]]) -> str:
    """Render only accepted evidence; worker prose never controls report shape."""
    frame = accepted["frame"]
    investigate = accepted["investigate"]
    verify = accepted["verify"]
    explain = accepted["explain"]
    lines = [
        "# Quick research report", "", "## Question", "", request.question, "",
        "## Conclusion", "", f"Final conclusion: **{explain['conclusion']}**", "", explain["summary"], "",
        "## Explanation", "", explain["explanation"], "",
        "## Claims and support", "",
    ]
    for claim in investigate["claims"]:
        lines.extend((f"- **{claim['id']}** ({claim['basis']}): {claim['statement']}", f"  Support: {claim['support']}"))
    lines.extend(("", "## Alternatives", ""))
    if investigate["alternatives"]:
        lines.extend(f"- {item}" for item in investigate["alternatives"])
    else:
        lines.append("- None supplied.")
    lines.extend(("", "## Verification checks", "", f"Verification disposition: **{verify['disposition']}**", ""))
    for check in verify["checks"]:
        lines.append(f"- **{check['claim_id']} — {check['verdict']}**: {check['reasoning']}")
    limitations = list(frame["missing_inputs"]) + list(investigate["limitations"]) + list(verify["limitations"]) + list(explain["limitations"])
    lines.extend(("", "## Missing evidence and limitations", ""))
    if limitations:
        lines.extend(f"- {item}" for item in limitations)
    else:
        lines.append("- No additional limitations supplied by the workers.")
    lines.extend(("", "## Capability and provider disclosures", "", "- No external retrieval or executed experiments were performed.", "- Verification is model reasoning, not external verification or code execution.", "- All stages used the same provider unless a future coordinator configuration records otherwise.", "- Cost and token usage are unknown.", ""))
    return "\n".join(lines)
