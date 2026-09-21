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

## RQ-003 — Paired-evaluation reasoning effort control

- **Date:** 2026-09-21
- **Task:** 11 (paired evaluation)
- **Question:** Whether the evaluation locks every comparison to high effort or preserves the user's adjustable effort control.
- **Evidence:** The Section 11 draft required high effort, while the user directed that effort remain an adjustable slider instead of a fixed numeric setting. Fair comparison still requires identical effort in both conditions.
- **Ruling:** Preserve the effort control. The user selects a supported effort before starting; that same explicit value is sent to baseline and pipeline across every case and is frozen in the evaluation manifest. Never compare conditions at different effort values or change effort when resuming. Record the chosen value in all trial metadata.
- **Affected contracts/tests:** Section 11.3, evaluation CLI, manifest and trial records. The selected setting is currently `medium` or `high`, matching the version-three provider contract.
- **Authority:** Astra decision relayed at the user's explicit request.

## RQ-004 — Paired-evaluation live allowance

- **Date:** 2026-09-21
- **Task:** 11 (paired evaluation)
- **Question:** What bounded resources to use for the live paired pilot while no reliable provider dollar telemetry is available.
- **Ruling:** Use at most 240 provider-call reservations, 7,200 seconds of active evaluation wall time including setup/preflight, and at most 10 percentage points of incremental usage from a saved start reading. Track the 5-hour quota remaining meter as the closest dashboard measure of near-term session consumption; at 55% remaining, the evaluation baseline is 55%, and stop before launching another trial once it reaches 45%. Record the baseline and each checkpoint before a trial. Because this reading is operator supplied and can change during a trial, the operator must monitor and interrupt a long trial if needed. Context-window occupancy is not a cumulative usage meter; weekly quota is too broad for this pilot. Never claim the percentage is automatically enforced.
- **Clarification:** The 10% figure is the evaluation's incremental allowance, not an absolute ceiling on total session consumption. The five-hour meter is used as a proxy; the selected starting reading is persisted and later readings are compared to it.
- **Affected contracts/tests:** Section 11.3, evaluation manifest caps, CLI explicit arguments, persisted usage-check records, no-launch-at-allowance test.
- **Authority:** Astra recommendation accepted by the user.
