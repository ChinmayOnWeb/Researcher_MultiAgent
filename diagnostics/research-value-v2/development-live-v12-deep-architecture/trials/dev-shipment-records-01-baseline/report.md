# Single-call baseline

Requested model: `gpt-5.6-terra`; requested effort: `medium`.
This is one unaudited answer. The paired pipeline received the same question, source text, and evaluator-supplied check transcripts.

## Inputs

### Evaluation supplied source: shipment-count

Source ID: `shipment-count`

> Dispatch record: 12 cartons were shipped.

### Evaluation supplied source: units-per-carton

Source ID: `units-per-carton`

> Packing specification for this shipment: each carton contains 8 units.

### Evaluation supplied source: damage-record

Source ID: `damage-record`

> Receiving record: 3 units were damaged in transit and are not usable.

## Answer

Question status: `answered`

> The dispatch and packing records give 12 × 8 = 96 units originally shipped. If the 3 transit-damaged units are among those 96 and no other units are unusable, 96 − 3 = 93 usable units remain. Limitation: the records do not explicitly state that the damaged units are included in this shipment total or that there were no other losses.

## Structured draft

```json
{
  "answer": "The dispatch and packing records give 12 × 8 = 96 units originally shipped. If the 3 transit-damaged units are among those 96 and no other units are unusable, 96 − 3 = 93 usable units remain. Limitation: the records do not explicitly state that the damaged units are included in this shipment total or that there were no other losses.",
  "question_status": "answered",
  "claims": [
    {
      "id": "shipped-cartons",
      "statement": "The shipment-count record states that 12 cartons were shipped.",
      "critical": true,
      "kind": "source_assertion",
      "citations": [
        {
          "source_id": "shipment-count",
          "start": 0,
          "end": 41,
          "quote": "Dispatch record: 12 cartons were shipped."
        }
      ],
      "step_ids": [],
      "tool_ids": [],
      "depends_on": [],
      "basis": "external_fact",
      "basis_reference": "shipment-count",
      "scope_step_ids": [],
      "discharged_by_step_ids": []
    },
    {
      "id": "units-per-carton-claim",
      "statement": "The packing record states that each carton in this shipment contains 8 units.",
      "critical": true,
      "kind": "source_assertion",
      "citations": [
        {
          "source_id": "units-per-carton",
          "start": 0,
          "end": 70,
          "quote": "Packing specification for this shipment: each carton contains 8 units."
        }
      ],
      "step_ids": [],
      "tool_ids": [],
      "depends_on": [],
      "basis": "external_fact",
      "basis_reference": "units-per-carton",
      "scope_step_ids": [],
      "discharged_by_step_ids": []
    },
    {
      "id": "damaged-units",
      "statement": "The damage record states that 3 units were damaged in transit and are not usable.",
      "critical": true,
      "kind": "source_assertion",
      "citations": [
        {
          "source_id": "damage-record",
          "start": 0,
          "end": 69,
          "quote": "Receiving record: 3 units were damaged in transit and are not usable."
        }
      ],
      "step_ids": [],
      "tool_ids": [],
      "depends_on": [],
      "basis": "external_fact",
      "basis_reference": "damage-record",
      "scope_step_ids": [],
      "discharged_by_step_ids": []
    },
    {
      "id": "original-units",
      "statement": "The records imply that 96 units were originally shipped.",
      "critical": true,
      "kind": "deduction",
      "citations": [],
      "step_ids": [
        "compute-original-units"
      ],
      "tool_ids": [],
      "depends_on": [
        "shipped-cartons",
        "units-per-carton-claim"
      ],
      "basis": "derivation",
      "basis_reference": "Arithmetic from the two shipment records.",
      "scope_step_ids": [],
      "discharged_by_step_ids": []
    },
    {
      "id": "subtraction-condition",
      "statement": "Assume the 3 damaged units are included among the 96 shipped units and every other shipped unit is usable.",
      "critical": true,
      "kind": "assumption",
      "citations": [],
      "step_ids": [],
      "tool_ids": [],
      "depends_on": [],
      "basis": "additional_assumption",
      "basis_reference": "Required to connect the damage record to the computed shipment total and to rule out additional unusability.",
      "scope_step_ids": [],
      "discharged_by_step_ids": []
    },
    {
      "id": "usable-units",
      "statement": "Under the stated assumption, 93 usable units remain.",
      "critical": true,
      "kind": "deduction",
      "citations": [],
      "step_ids": [
        "compute-usable-units"
      ],
      "tool_ids": [],
      "depends_on": [
        "original-units",
        "damaged-units",
        "subtraction-condition"
      ],
      "basis": "derivation",
      "basis_reference": "Conditional subtraction under subtraction-condition.",
      "scope_step_ids": [],
      "discharged_by_step_ids": []
    }
  ],
  "proof_steps": [
    {
      "id": "compute-original-units",
      "statement": "Compute the original shipment quantity as 96 units.",
      "justification": "Using 12 shipped cartons and 8 units per carton, multiplication gives 12 × 8 = 96.",
      "depends_on": [],
      "citations": []
    },
    {
      "id": "compute-usable-units",
      "statement": "Compute the conditional usable quantity as 93 units.",
      "justification": "Under subtraction-condition, the 3 unusable units are part of the 96 units and all remaining units are usable; therefore 96 − 3 = 93.",
      "depends_on": [
        "compute-original-units"
      ],
      "citations": []
    }
  ],
  "approaches": [
    {
      "id": "record-arithmetic",
      "description": "Combine carton count with units per carton, then conditionally subtract recorded damaged units.",
      "outcome": "candidate",
      "reason": "The arithmetic follows from the supplied records, but the subtraction needs an unstated relationship between the damage record and the shipment total."
    }
  ],
  "open_questions": [
    "Do the 3 damaged units belong to the stated 12-carton shipment, and were any other units lost or unusable?"
  ],
  "tool_requests": [],
  "change_log": []
}
```
