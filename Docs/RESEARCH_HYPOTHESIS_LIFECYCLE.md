# Deterministic Research Hypothesis Lifecycle

AMRTE v0.24.3 completes the neutral Phase VI substitute with an immutable, point-in-time-safe lifecycle for abstract research hypotheses. It is not a financial-position lifecycle.

## Canonical lifecycle

The code-defined states are `PROPOSED`, `VALIDATED`, `AUTHORIZED`, `QUEUED`, `ACTIVATED`, `ACTIVE`, `SAFEGUARDED`, `MONITORED`, `RESOLVED`, `ARCHIVED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `INVALIDATED`, and `FAILED`.

Legal transitions are explicit and versioned in code. Terminal states cannot return to active states. `RESOLVED` may transition only to `ARCHIVED`. Optional active states may be skipped only where the transition matrix explicitly permits it.

## Governance properties

- One deterministic lifecycle exists per hypothesis identity.
- Every successful transition increments state version and event sequence exactly once.
- Compare-and-swap `expected_version` prevents lost concurrent updates.
- A process-local `RLock` makes lifecycle, transition, event, and version commits atomic.
- Immutable precondition snapshots preserve upstream authorization, neutral workflow-health, observation-quality, lineage, and availability evidence.
- Future evidence, lineage mismatch, illegal transition, stale expected version, or terminal restriction fails closed.
- Duplicate creation or an already-satisfied transition returns `NO_ACTION` without advancing state.
- Queue expiration uses explicit `as_of` time and configured maximum age.

## History and recovery

Point-in-time snapshots select only versions and events known by the requested timestamp. Reconciliation detects missing lifecycle state, sequence/event mismatch, version mismatch, orphan identity, and lineage mismatch without repairing or creating permission.

Recovery validates schema, engine/configuration identity, recovery epoch, unique lifecycle/hypothesis identity, transition/event sequencing, legal transitions, state/version conservation, temporal validity, and event-to-transition linkage. Incompatible recovery fails closed. A deterministic replay fingerprint attributes the complete committed history.

## Safety boundary

The engine governs neutral research artifacts only. It contains no positions, orders, fills, prices, instruments, accounts, brokers, leverage, margin, live feeds, or real/demo execution capability.
