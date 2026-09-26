# Research log

Run: `eval-dev-flawed-proof-sqrt2-r1-pipeline`

## Decision 1: `frame_request`

Action: `a0001` (`frame`)
Dependencies: none
Outcome: `succeeded`
Elapsed milliseconds: 8000
Provider attempt: `a0001-a01` (`initial`)
Attempt outcome: `succeeded`; input bytes: 5439; duration: 7967 ms; failure class: `none`; session ID markers: 1

## Decision 2: `initial_approach`

Action: `a0002` (`branch`)
Dependencies: `a0001`
Outcome: `protocol_error`
Elapsed milliseconds: 72141
Error: > structural validation failed: claims[0].discharged_by_step_ids: must cover every proof step in scope
Provider attempt: `a0002-a01` (`initial`)
Attempt outcome: `protocol_error`; input bytes: 13482; duration: 42546 ms; failure class: `protocol_error`; session ID markers: 1
Provider attempt: `a0002-a02` (`structural_repair`, retry of `a0002-a01`)
Attempt outcome: `protocol_error`; input bytes: 19681; duration: 29530 ms; failure class: `protocol_error`; session ID markers: 1

## Decision 3: `action_failed`

Decision kind: `finish`

Terminal status: `incomplete`
Reason: `action_failed`
