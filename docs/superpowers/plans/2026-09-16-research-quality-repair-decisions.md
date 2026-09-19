# Implementation decisions

## RQ-001 — Evidence tool reference identity

- **Date:** 2026-09-19
- **Task:** 6 (provenance and broker)
- **Question:** Whether Claim and Challenge `tool_ids` identify Draft-local proposed ToolRequest IDs or committed successful ToolReceipt coordinator Action IDs.
- **Evidence:** Plan §8.1 says committed successful receipts; the pre-existing Draft contract instead required matching local ToolRequest IDs, preventing references to committed receipts.
- **Ruling:** Claim and Challenge `tool_ids` reference previously committed successful ToolReceipt coordinator Action IDs. They never refer to Draft-local ToolRequest proposal IDs. A later packet may cite receipts visible in that packet; earlier drafts remain immutable. Deduplication uses operation and canonical arguments excluding proposal ID, retaining the original committed receipt ID and request record.
- **Affected contracts/tests:** Draft validation no longer requires receipt IDs to equal proposal IDs; packet/provenance validation requires referenced successful receipts to be visible; regression tests distinguish proposal ID from coordinator receipt ID.
- **Authority:** Astra ruling relayed at the user's explicit request.

## RQ-002 — Normalizer version in broker receipts

- **Date:** 2026-09-19
- **Task:** 6 (receipt implementation version)
- **Question:** How to satisfy §8.2's requirement to record the normalizer version while preserving §8.1's exact `implementation_version` literal and receipt schema.
- **Ruling:** Keep `ToolReceipt.implementation_version` exactly `mathresearch-broker-v1`. Treat it as the immutable version of the complete broker implementation, with trusted manifest mapping `mathresearch-broker-v1` to `html-normalizer-v1`. Do not add a receipt field or encode the version into scope, error, or source text. Any future normalization behavior change needs a new implementation version plus explicit validator/replay support.
- **Affected code/tests:** `research/implementation.py` is the trusted manifest; `sources.NORMALIZER_VERSION` resolves through it. Existing strict receipt validation continues to reject composite/unknown strings. Tests pin manifest resolution and HTML v1 normalization output/hash.
- **Authority:** Astra controller ruling requested for the §8.1/§8.2 conflict.
