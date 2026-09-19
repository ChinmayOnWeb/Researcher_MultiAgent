# Task 5: explicit provider settings and observations

`CodexAdapter` accepts optional keyword-only reasoning effort. Legacy `None` preserves the prior command line; research requests accept only medium or high and place the exact setting in one argv element before `exec`. Preflight records the installed CLI version, checks that native tools remain disabled, and validates the configured help invocation without submitting a prompt.

`research.provider` applies the immutable request model and effort, returns a stable configuration receipt, parses provider metadata only before the first `user` header, and exposes known mismatches while preserving missing observations as unknown. Replay persists `provider_configured` and rejects settings that differ from the request.

Verification: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_codex_adapter tests.unit.test_research_provider tests.unit.test_research_events -q` — exit 0, 25 tests. Combined Task 4/provider focused verification passed 48 tests.
