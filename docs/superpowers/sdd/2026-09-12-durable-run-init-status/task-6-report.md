# Task 6 — Documentation report

Updated `docs/research-pipeline-design.md` only.

- Reframed future execution as a coordinator-launched adapter for an installed agent CLI, rather than host- or skill-driven execution.
- Made the current boundary explicit: public `mathresearch init` and `mathresearch status` cover contracts, locking, initialization, and status replay/repair. `status` authoritatively replays the initialization event and atomically rebuilds missing or stale state; the slice still performs no agent launch, task scheduling, task dispatch, or adapter execution.
- Documented event authority, rebuildable projection state, nonblocking OS-backed locks, and current recovery/refusal behavior. Initialization may reuse a destination containing only `.run.lock`, but refuses any other nonempty or precommit destination without overwriting; recovery guarantees remain intentionally limited.
- Preserved the ten research phases, evidence requirements, human gates, budgets, stopping rules, and full-workflow acceptance criteria as future scope.

No code or tests were modified.
