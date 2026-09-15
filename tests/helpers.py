"""Hand-authored JSON fixtures shared by contract tests."""

from __future__ import annotations


def valid_run_request_payload() -> dict[str, object]:
    """Return a complete request fixture independent from production builders."""
    return {
        "schema_version": 1,
        "record_type": "run_request",
        "run_id": "run-local-calculation",
        "question": "Which model explains the observed sequence?",
        "actual_goal": "Compare two candidate models.",
        "context": "The sequence is supplied locally.",
        "constraints": ["Do not browse."],
        "audience_level": "undergraduate",
        "mode": "research",
        "stakes": "ordinary",
        "learning_mode": False,
        "capabilities": {"browse": False, "execute_code": True},
        "budgets": {
            "max_accepted_submissions": 30,
            "max_revision_cycles": 2,
            "elapsed_time_seconds": None,
        },
    }


def valid_frame_submission_payload() -> dict[str, object]:
    """Return a complete Frame submission fixture independent from contract builders."""
    return {
        "schema_version": 1,
        "record_type": "frame_submission",
        "submission_id": "submission-frame-one",
        "run_id": "run-local-calculation",
        "task_id": "frame",
        "revision": 1,
        "attempt": 1,
        "submitted_at": "2026-09-12T14:30:49.123456Z",
        "frame": {
            "framed_question": "Which model explains the observed sequence?",
            "success_criteria": ["Compare two candidate models."],
            "terms": ["observed sequence"],
            "assumptions": ["The supplied sequence is accurate."],
            "missing_inputs": [],
            "stakes_assessment": "ordinary",
        },
    }
