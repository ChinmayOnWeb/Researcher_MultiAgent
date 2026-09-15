# Durable Run Initialization and Status Implementation Plan

**Goal:** Add durable `mathresearch init` and `status` commands without launching agents.

**Constraints:** Python standard library; events are authoritative; `state.json` is rebuildable; no scheduler, adapter execution, or task dispatch.

### Task 1: Run contracts

Create strict versioned initialization-event and state contracts. Test round trips, UTC timestamps, exact fields, sequence/version validation, and projection.

### Task 2: Run locking

Create a nonblocking, OS-backed per-run lock with real contention tests. The persistent lock file is not an ownership claim.

### Task 3: Atomic initialization

Validate a request before creating the destination, atomically write request/event/state, and refuse to overwrite any existing run artifacts.

### Task 4: Replay and repair

Read the committed initialization event, reject corrupt layouts, and atomically rebuild missing or stale state projections.

### Task 5: CLI and integration tests

Add `init` and `status`, structured domain errors, fresh-process restart/recovery tests, and no-agent-launch assertions.

### Task 6: Documentation

Update the research design to describe coordinator-launched CLI agents as the future execution model and document the initialization durability boundary.
