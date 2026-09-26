# Research log

Run: `eval-dev-flawed-proof-sqrt2-r1-pipeline`

## Decision 1: `frame_request`

Action: `a0001` (`frame`)
Dependencies: none
Outcome: `succeeded`
Elapsed milliseconds: 8766
Provider attempt: `a0001-a01` (`initial`)
Attempt outcome: `succeeded`; input bytes: 6193; duration: 8750 ms; failure class: `none`; session ID markers: 1

## Decision 2: `initial_approach`

Action: `a0002` (`branch`)
Dependencies: `a0001`
Outcome: `protocol_error`
Elapsed milliseconds: 107968
Error: > structural validation failed: claims[1].basis: additional_assumption requires kind=assumption
Provider attempt: `a0002-a01` (`initial`)
Attempt outcome: `protocol_error`; input bytes: 14267; duration: 69000 ms; failure class: `protocol_error`; session ID markers: 1
Provider attempt: `a0002-a02` (`structural_repair`, retry of `a0002-a01`)
Attempt outcome: `protocol_error`; input bytes: 22099; duration: 38889 ms; failure class: `protocol_error`; session ID markers: 1

## Decision 3: `action_failed`

Decision kind: `finish`

Terminal status: `incomplete`
Reason: `action_failed`
