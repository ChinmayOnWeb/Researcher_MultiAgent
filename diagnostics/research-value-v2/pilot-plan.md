# Research value v2 pilot handoff

## Frozen arms and settings

All arms use GPT-5.6 Terra at medium effort. The strict baseline gets one provider call. Sequential review and the full pipeline share the same mode call and wall limits, tool policy, evidence policy, and structural repair allowance. The full pipeline retains isolated branches. Development and held-out corpora each contain six fixed cases across six task families. Held-out truth is stored outside worker-facing case files.

The paired families are finite subset enumeration (`dev/holdout-subset-sum`), symbolic domain identity (`dev/holdout-rational-domain`), boundary counterexample (`dev/holdout-euler-boundary`), conflicting records (`dev-schedule-amendment` / `holdout-policy-revision`), flawed proof verification (`dev-flawed-proof-sqrt2` / `holdout-square-root-proof`), and multi-record inference (`dev-shipment-records` / `holdout-inventory-ledger`).

## Offline schedules

`diagnostics/research-value-v2/prepare-pilots.ps1` creates the schedules without provider calls:

- Development calibration: 6 cases × 1 replicate × 3 arms = 18 scheduled attempts; worst case 102 provider calls and 12,060 wall seconds.
- Held-out evaluation: 6 cases × 3 replicates × 3 arms = 54 scheduled attempts; worst case 306 provider calls and 36,180 wall seconds.

These are scheduler maxima derived from arm caps, not estimates of actual usage or cost. Token and USD projections are unknown. The held-out schedule is prepared for review; execute it only after the development set's calibration gate and an explicit live resource envelope are recorded.

## Decision gates

1. Inspect development outputs and blinded grades. Confirm the grading rubric, execution reliability, and whether tool receipts are used correctly.
2. Freeze any protocol correction as a new code revision and new manifest; do not edit existing runs.
3. Before live execution, supply explicit maximum provider calls, wall seconds, and spending limit. The call and wall caps must cover the selected schedule; capture the spend ceiling in the run record. No session quota prompt is used.
4. Run the held-out schedule once at the frozen Terra-medium setting. Stop on provider usage-limit errors or any configured cap.
5. Report semantic grades, schema acceptance, status calibration, provider availability, resource use, equal-input pairs, and all exclusions separately. Treat the six-case sample as descriptive, not an architecture-wide conclusion.

No live results are included in this handoff. Preparing either manifest does not authorize provider calls.
