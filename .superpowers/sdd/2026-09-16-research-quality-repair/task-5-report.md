# Task 5 report: explicit provider settings and observations

`CodexAdapter` now accepts optional keyword-only reasoning effort. Legacy `None` preserves the prior command line; new research requests accept only medium or high and place the exact configuration value in one argv element before `exec`. Preflight checks the installed version, disabled native features, and the complete configured help invocation without submitting a prompt.

`research.provider` resolves Codex lazily when called, applies the request's model and effort, returns a stable configuration receipt, parses only provider metadata before the first `user` header, and flags observed model/effort mismatches while preserving absent observations as unknown. Replay persists `provider_configured` and rejects settings that differ from the immutable request.

Verification: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_codex_adapter tests.unit.test_research_provider tests.unit.test_research_events -q` — exit 0, 25 tests. Combined Task 4/provider focused suite also passed 48 tests.
