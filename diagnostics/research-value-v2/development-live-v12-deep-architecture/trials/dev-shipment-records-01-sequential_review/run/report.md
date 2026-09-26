# Research report

## Original question

```
How many usable units remain, and how many were originally shipped? Show how the records combine and state any limitation.
```

## Explicit goal

```
Not specified
```

## Status

- Investigation status: **complete**
- Answer status: **inconclusive**
- Provenance status: **valid**
- Semantic status: **issues_found**
- Computation status: **not_performed**

## Answer

> Conditionally, 96 units were originally shipped and 93 usable units remain: 12 cartons × 8 units per carton = 96, then 96 − 3 damaged units = 93. This requires the dispatch, packing, and receiving records to concern one shipment and the 3 damaged units to be included among those 96. The supplied records do not independently establish that linkage.

## What was established

### Claim `shipment-cartons`: source_attributed

> The dispatch record states that 12 cartons were shipped.

Citation: `shipment-count`, character offsets 0–41.
Source title: `Evaluation supplied source: shipment-count`.
> Dispatch record: 12 cartons were shipped.

### Claim `carton-capacity`: source_attributed

> The packing specification states that each carton contains 8 units.

Citation: `units-per-carton`, character offsets 0–70.
Source title: `Evaluation supplied source: units-per-carton`.
> Packing specification for this shipment: each carton contains 8 units.

### Claim `damaged-units`: source_attributed

> The receiving record states that 3 units were damaged in transit and are not usable.

Citation: `damage-record`, character offsets 0–69.
Source title: `Evaluation supplied source: damage-record`.
> Receiving record: 3 units were damaged in transit and are not usable.

### Claim `same-shipment`: conditional

> Assume the dispatch, packing, and receiving records concern the same shipment, and that the 3 damaged units are among its shipped units.

Assumption supplied by the Draft:

Reasons: `audit_conditional`.

### Claim `original-units`: conditional

> Under the same-shipment assumption, 96 units were originally shipped.

Checked step `compute-original`: > Compute the original shipped-unit count as 96.

Reasons: `audit_conditional`; `dependency_same-shipment_conditional`.

### Claim `usable-units`: conditional

> Under the same-shipment assumption, 93 usable units remain.

Checked step `compute-usable`: > Compute the remaining usable-unit count as 93.

Reasons: `audit_conditional`; `dependency_original-units_conditional`; `dependency_same-shipment_conditional`.

## Approaches attempted

No branch approach was completed.

## Critique and revisions

- Claim `same-shipment`: outcome **survives**.
> The three records may describe different shipments, so the 12-carton count, 8-unit capacity, and 3 damaged units may not be combinable.
> The claim is expressly an additional assumption, not an asserted record fact. The draft states the missing linkage as a limitation.

- Claim `usable-units`: outcome **survives**.
> Even if the records concern one shipment, the receiving record may count damaged units outside the 96 units.
> The deduction is explicitly conditional on the assumption that the 3 damaged units are among the shipped units; without that assumption, 93 does not follow.

- Claim `original-units`: outcome **survives**.
> The multiplication requires the cited capacity to apply to all 12 dispatched cartons.
> Under the same-shipment assumption, the packing statement applies to the dispatched cartons, and 12 × 8 = 96.

Revision log:
- > Revised the proof steps to cite the supplied record text directly and to state the cross-record linkage assumption in each conditional computation.
- > Retained the conditional conclusion; no unconditional shipment or usable-unit total is claimed.
- > Recorded the two missing linkage facts as unresolved questions rather than treating record attribution as proof that the records concern one shipment.

## Executed checks

No broker check or source-fetch receipt was recorded.

## Evidence

### `Evaluation supplied source: shipment-count`

- ID: `shipment-count`
- Origin: `user_text`
- URL: `none`
- Published: `unknown`
- Captured: `2026-09-25T07:04:11.297032Z`
- SHA-256: `83af98df3283b577fdd058efd16730ab52672c7fc14e590acb790c91c528bded`

### `Evaluation supplied source: units-per-carton`

- ID: `units-per-carton`
- Origin: `user_text`
- URL: `none`
- Published: `unknown`
- Captured: `2026-09-25T07:04:11.297032Z`
- SHA-256: `65df26b176a63b3ec7755882e7c7675dd938d863e25c5c4a4694396ec2b986d2`

### `Evaluation supplied source: damage-record`

- ID: `damage-record`
- Origin: `user_text`
- URL: `none`
- Published: `unknown`
- Captured: `2026-09-25T07:04:11.297032Z`
- SHA-256: `ad47c71ce02ecd9c5d40ff489f909676021b2f037d6e03b8faefa974fe206c4a`

## Remaining uncertainty and useful next work

> What shipment identifier or explicit cross-reference establishes that the dispatch, packing, and receiving records describe the same shipment?
> What evidence establishes that the 3 damaged units are included among the 96 units computed from the dispatch and packing records?
> A shipment identifier or explicit cross-reference linking the dispatch, packing, and receiving records.
> Evidence that the 3 damaged units are included among the 96 units obtained from the dispatch count and packing capacity.
> unmet obligation: A shipment identifier or explicit cross-reference linking the dispatch, packing, and receiving records.
> unmet obligation: Evidence that the 3 damaged units are included among the units counted by the dispatch and packing records.
> Expected new evidence: a revised proof addressing these audit findings.

## Run disclosure

- Requested model: `gpt-5.6-terra`
- Requested reasoning effort: `medium`
- Observed models: `gpt-5.6-terra`
- Observed reasoning effort: `medium`
- Provider attempt intents: 4
- Model calls: 4
- Historical v3 action-based call count: 0
- Tool calls: 0
- Observed local session ID markers: 4
- Session ID markers are supplemental local telemetry, not billing totals.
- Wall time: 113595 ms
- Summed child duration: 112921 ms
- Formal verification: not performed
- Input bytes: 65456
- Output bytes: 86776
- Input tokens: unknown
- Output tokens: unknown
- Reasoning tokens: unknown
- Recorded cost: unknown
