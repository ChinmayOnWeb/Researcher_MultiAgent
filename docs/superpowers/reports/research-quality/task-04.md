# Task 4 report: substantive prompts and blind packets

Implemented strict packet construction and substantive role prompts. Packets are built only from the supplied request, snapshot, and validated action; exact canonical byte size is checked before worker intent, with no truncation. Branch b is blind to Frame and branch a, while branch c receives only targeted missing-evidence obligations. Synthesis, audit, and revise receive only their declared dependencies.

Replay now preserves exact supplied gate text as immutable snapshot data. Packet validation recursively checks sources, receipts, role inputs, supplied responses, and dependency Draft/Audit records. Audit selection after revision follows the repaired Draft and its matching Audit.

Verification: `$env:PYTHONPATH='src'; py -m unittest tests.unit.test_research_prompts tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_research_contracts -q` — exit 0, 47 tests. The implementation was committed as `68a3471` after completing the interrupted validation pass.
