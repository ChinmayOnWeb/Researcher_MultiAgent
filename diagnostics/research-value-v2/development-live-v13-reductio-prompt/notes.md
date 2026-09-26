# Focused reductio diagnosis v13

## Setup

- One Deep case: `dev-flawed-proof-sqrt2`; one replicate; strict baseline, sequential review, and full pipeline.
- GPT-5.6 Terra, medium effort; frozen 17-call / 2,010-second maximum. Actual use: 14 provider attempts and 630.78 seconds.
- The three outputs were equal-input and semantically assessable. Astra blind-graded the frozen packets; token and cost data are unknown.

## Results

| Condition | Score / 10 | Schema | Calls | Seconds |
|---|---:|---|---:|---:|
| Baseline | 10 | valid | 1 | 29.72 |
| Sequential review | 10 | valid | 5 | 204.70 |
| Full pipeline | 7 | valid | 8 | 396.09 |

The pipeline draft reached the correct irrationality conclusion, but justified parity through a division-algorithm consequence while labeling the dependency as the Well-Ordering Principle. Its audit treated that bridge as unsupported. Astra judged the gap real as written, while also advising that an audit should not demand a fresh proof of a correctly named standard theorem; it should check the theorem's hypotheses and application.

The pipeline was 3 points below both other arms and used more calls and time. This is one case and does not establish an architecture-wide effect.

## Follow-up

Updated worker instructions in prompt version 4 to name every invoked standard theorem and its application, and told audits not to require a proof of a standard theorem. The v14 launch under the default Windows sandbox was preserved as a permission failure. See the v15 retry notes for the elevated run and remaining protocol failures.
