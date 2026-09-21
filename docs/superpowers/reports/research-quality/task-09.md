# Task 9 report: public research CLI and human source continuation

Added `mathresearch research init|run|status|respond` while preserving the legacy commands. Init accepts either a strict version-three request file or explicit question-building flags; builder flags require objective, mode, run ID, and model. Builder defaults preserve every supplied string, select explicit reasoning effort and profile budgets, and disable broker capabilities. Human init output shows mode, objective, and capabilities.

Run, status, and respond report the required stable JSON fields with explicit nulls. Human run progress goes to stderr. Awaiting, incomplete/blocked, budget-exhausted, cancelled, locked, storage, and invalid-invocation results map to the specified exits. Status and completed-run resume read durable history without resolving Codex. Research storage compares `request.json` byte-for-byte with the immutable initialization event and reports a missing or changed projection as corruption. Respond persists exact user text as user evidence, keeps the initial request unchanged, resumes after supply/continue responses, and ends cancellation with exit 21.

Added Deep request examples for odd-perfect status and the sum of the first n odd integers. Both specify the high reasoning effort and bounded profile values; neither enables retrieval or mathematical operations by default.

Fresh-process integration tests cover exact question/goal round-trip, required choices, request/flag conflicts, unsupported Quick capabilities, help and example parsing, supplied text and request preservation, cancellation, changed request detection, completed run behavior without Codex on PATH, JSON fields, and legacy CLI behavior.

Verification: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_engine tests.unit.test_research_store tests.integration.test_research_cli tests.integration.test_quick_cli tests.unit.test_cli -q` — exit 0, 47 tests.

No live provider, source fetch, or mathematical broker action was invoked by these tests. A test-only provider override was not added to the production CLI; the completed run and gate setup use the engine's injected test provider, then exercise public commands in fresh processes.
