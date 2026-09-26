# Research log

Run: `eval-dev-shipment-records-r1-pipeline`

## Decision 1: `frame_request`

Action: `a0001` (`frame`)
Dependencies: none
Outcome: `succeeded`
Elapsed milliseconds: 6858
Provider attempt: `a0001-a01` (`initial`)
Attempt outcome: `succeeded`; input bytes: 6445; duration: 6828 ms; failure class: `none`; session ID markers: 1

## Decision 2: `initial_approach`

Action: `a0002` (`branch`)
Dependencies: `a0001`
Outcome: `protocol_error`
Elapsed milliseconds: 57828
Error: > structural validation failed: claims[4].basis: only local assumptions may declare scope or discharge steps
Provider attempt: `a0002-a01` (`initial`)
Attempt outcome: `protocol_error`; input bytes: 14368; duration: 25500 ms; failure class: `protocol_error`; session ID markers: 1
Provider attempt: `a0002-a02` (`structural_repair`, retry of `a0002-a01`)
Attempt outcome: `protocol_error`; input bytes: 21203; duration: 32264 ms; failure class: `protocol_error`; session ID markers: 1

## Decision 3: `action_failed`

Decision kind: `finish`

Terminal status: `incomplete`
Reason: `action_failed`
