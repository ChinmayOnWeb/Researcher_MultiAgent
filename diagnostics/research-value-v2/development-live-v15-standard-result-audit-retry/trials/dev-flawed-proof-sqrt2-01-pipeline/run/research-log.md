# Research log

Run: `eval-dev-flawed-proof-sqrt2-r1-pipeline`

## Decision 1: `frame_request`

Action: `a0001` (`frame`)
Dependencies: none
Outcome: `succeeded`
Elapsed milliseconds: 10218
Provider attempt: `a0001-a01` (`initial`)
Attempt outcome: `succeeded`; input bytes: 7115; duration: 10186 ms; failure class: `none`; session ID markers: 1

## Decision 2: `initial_approach`

Action: `a0002` (`branch`)
Dependencies: `a0001`
Outcome: `protocol_error`
Elapsed milliseconds: 79468
Error: > structural validation failed: claims[7].basis: only local assumptions may declare scope or discharge steps
Provider attempt: `a0002-a01` (`initial`)
Attempt outcome: `protocol_error`; input bytes: 15020; duration: 42296 ms; failure class: `protocol_error`; session ID markers: 1
Provider attempt: `a0002-a02` (`structural_repair`, retry of `a0002-a01`)
Attempt outcome: `protocol_error`; input bytes: 21911; duration: 37125 ms; failure class: `protocol_error`; session ID markers: 1

## Decision 3: `action_failed`

Decision kind: `finish`

Terminal status: `incomplete`
Reason: `action_failed`
