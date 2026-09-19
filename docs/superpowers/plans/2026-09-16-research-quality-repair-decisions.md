# Implementation decisions

## RQ-001 — Evidence tool reference identity

- **Date:** 2026-09-19
- **Task:** 6 (provenance and broker)
- **Question:** Whether Claim and Challenge `tool_ids` identify Draft-local proposed ToolRequest IDs or committed successful ToolReceipt coordinator Action IDs.
- **Evidence:** Plan §8.1 says committed successful receipts; the pre-existing Draft contract instead required matching local ToolRequest IDs, preventing references to committed receipts.
- **Ruling:** Claim and Challenge `tool_ids` reference previously committed successful ToolReceipt coordinator Action IDs. They never refer to Draft-local ToolRequest proposal IDs. A later packet may cite receipts visible in that packet; earlier drafts remain immutable. Deduplication uses operation and canonical arguments excluding proposal ID, retaining the original committed receipt ID and request record.
- **Affected contracts/tests:** Draft validation no longer requires receipt IDs to equal proposal IDs; packet/provenance validation requires referenced successful receipts to be visible; regression tests distinguish proposal ID from coordinator receipt ID.
- **Authority:** Astra ruling relayed at the user's explicit request.
