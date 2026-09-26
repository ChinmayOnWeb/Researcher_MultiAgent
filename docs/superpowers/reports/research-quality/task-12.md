# Task 4 report — proof status and audit freshness

Implemented in `codex-research-quality-repair` without provider calls.

## Changes

- Added a v3 claim basis and matching audit basis verdict/reasoning fields. New actions use `research-v3`; direct historical validation and replay retain v1/v2 schemas based on the durable action version.
- Added contract checks for premise, assumption, local-scope, standard-result, external-fact, derivation, conjecture, and unsupported-recollection classifications. Audited application is required for a result to support a derivation; local assumptions require explicit scope and discharge steps.
- Updated worker instructions to ask for basis reasoning and separate source attribution from truth.
- Unified deep routing assessment with packet-visible evidence, and included selected draft/audit IDs and hashes, evidence hash, and objection history. Stale audits are not selected for a revised draft.
- Scoped evidence-reference failures to affected claims and their claim dependencies; transitive proof-step dependencies are traversed as steps and must be covered by the matching proof audit.
- Updated reporting to reject a final assessment whose selected draft identity/hash does not match.

## Verification

- Focused suite: `PYTHONPATH=src python -m unittest tests.unit.test_research_contracts tests.unit.test_research_prompts tests.unit.test_research_assessment tests.unit.test_research_routing tests.unit.test_research_events tests.unit.test_research_provenance tests.unit.test_research_reporting tests.unit.test_research_engine -q` — 107 passed.
- `python -m compileall -q src/mathresearch/research` — passed.
- `git diff --check` — passed (Git emitted line-ending conversion warnings only).
- Full unit suite was attempted: 317 tests, with unrelated legacy evaluation assertions failing because the current diagnostic corpus/manifest contain 3 cases/9 rows while those tests expect 8 cases/24 rows. The first full run also exposed Task 4 integration issues; the focused suite including engine was rerun successfully after fixes.

## Limitations

- No live calls, grading, or architecture comparison were performed.
- Status labels remain model-reviewed; the changes do not provide formal proof verification.
- The new validation path is schema-versioned. Historical records are read under their recorded v1/v2 action schema; new work emits v3.
