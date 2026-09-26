# Research log

Run: `eval-dev-rational-domain-2-r1-pipeline`

## Decision 1: `frame_request`

Action: `a0001` (`frame`)
Dependencies: none
Outcome: `succeeded`
Elapsed milliseconds: 14531
Provider attempt: `a0001-a01` (`initial`)
Attempt outcome: `succeeded`; input bytes: 5318; duration: 14500 ms; failure class: `none`; session ID markers: 1

## Decision 2: `execute_frame_check`

Action: `a0002` (`check_integer`)
Dependencies: `a0001`
Outcome: `succeeded`
Elapsed milliseconds: 296

## Decision 3: `execute_frame_check`

Action: `a0003` (`search_perfect`)
Dependencies: `a0001`
Outcome: `protocol_error`
Elapsed milliseconds: 0
Error: > arguments: search range exceeds its bounds

## Decision 4: `action_failed`

Decision kind: `finish`

Terminal status: `incomplete`
Reason: `action_failed`
