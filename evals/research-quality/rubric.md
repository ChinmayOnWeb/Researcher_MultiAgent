# Research-quality evaluation rubric

This rubric is evaluator-only. Do not include its obligations, forbidden claims, checks, scores, or expected answers in worker packets.

Evaluate each report from the case sources and answer evidence. Grade the historical reports only as qualitative diagnosis; they are not a controlled latency or quality comparison.

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Mathematical/content correctness | Material false claim or invalid proof accepted | Incomplete but avoids material false claim | Correct within stated scope; central obligation handled |
| Evidence provenance | Invented/circular source or executed-check claim | Origin disclosed but support incomplete | All external, assumed, and computed support identifiable and qualified |
| Coverage of requested task | Goal rewritten or central deliverable missing | Partial coverage | All case obligations addressed |
| Challenge quality | Blind endorsement/no meaningful challenge | Relevant weakness identified | Concrete check, counterexample, or step audit with result and effect |
| Uncertainty and usefulness | False resolution/certainty | Honest but generic | Honest scope plus useful explanation and specific next work |

Score each dimension from 0 to 2 for a total from 0 to 10. Use evidence passages to support grades and blind the condition where feasible. Astra grades semantic obligations; Terra does not grade its own generated pipeline outputs. Human review may override an advisory model grade.

Do not award points for stage count, report length, formatting, polished prose, or resolving an open problem. A claim about an open problem may only be graded as correct within the supplied source scope. The quick `perfect-six` case is not penalized for lacking a multiworker audit: its challenge score assesses explicit divisor verification and disclosure that the response is unaudited.

For the live comparison, use the same explicit model, effort, question, source bytes, and answer-quality instructions for the single-call baseline and pipeline. Pre-acquire identical approved source/check receipts for broker-enabled cases and disclose baseline tool context. Run three replicates per condition across all eight cases, alternate condition order by case-plus-replicate parity, and preserve incremental results. Live runs require `--live --max-provider-calls 240 --max-wall-seconds 7200`; stop at either limit. Offline stubs remain available.

Do not claim empirical improvement before the controlled comparison. The pilot quality gates are zero false proof/open-problem resolutions, zero fabricated or circular evidence accepted as verified, Deep average at least 8/10, and either at least 1.0 mean paired-point improvement across the seven Deep cases or a 25% reduction in material failures without reduced mean coverage. If the baseline is already perfect, report no demonstrated quality gain. Quick requires exactly one provider call; Deep remains opt-in if efficiency gates fail.
