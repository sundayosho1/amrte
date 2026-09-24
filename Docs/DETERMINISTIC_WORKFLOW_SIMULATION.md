# Deterministic Workflow Simulation Engine

Version 0.24.1 adds a neutral, offline workflow simulator. It models authorized units of generic work and deliberately contains no financial order, market-fill, account, position, price, broker, or trading semantics.

## Processing model

`WorkflowRequest` is validated against immutable authorization, configuration, availability, and expiry data. A valid request creates a deterministic `WorkflowIntent` and `WorkflowSubmission`. State changes append immutable `WorkflowCompletionEvent` records to a bounded, sequence-checked ledger. Frozen snapshots provide point-in-time views.

Supported lifecycle states are created, validated, submitted, acknowledged, partially completed, completed, rejected, timed out, cancelled, expired, recovery-restricted, invalid, and unknown. Terminal submissions cannot gain additional completed work.

## Permanent invariants

- Completed work never exceeds authorized work.
- Duplicate requests and completion events cannot increase work.
- Retries and restarts preserve authorization and completion totals.
- Reconciliation observes inconsistencies but never creates or repairs completed work.
- Partial completion followed by cancellation preserves already completed work and cancels only the remainder.
- Events older than the current immutable state are rejected.
- Missing, future, expired, malformed, or incompatible information fails closed.

## Reliability architecture

- IDs derive deterministically from immutable inputs.
- An idempotency key collapses duplicate requests.
- An `RLock` serializes concurrent mutations and permits safe nested transitions.
- Retry count, timeout, request expiry, and storage limits are configuration-driven.
- Recovery validates schema, engine/configuration lineage, event sequences, conservation totals, bounds, and ghost events before admitting state.
- Replay reproduces the same logical identifiers and accounting.
- Reconciliation reports consistent, ghost, missing, completion-mismatch, sequence-mismatch, or invalid status without mutation.
- Audit hooks and a `DecisionTrace` describe each outcome.

## Interval and time semantics

All methods receive an explicit authoritative `as_of` timestamp. The engine does not read the system clock. Requests are rejected before availability or at/after expiry. Events cannot predate the latest admitted state version.

## Portability and boundaries

The implementation uses Python standard-library, OS-neutral synchronization and existing AMRTE infrastructure. It has no GUI, network dependency, shell runtime dependency, hard-coded path, or platform-specific filesystem behavior. Native Windows execution was not performed; static Windows portability passed.

The module is a generic software-engineering simulator only. It cannot place or represent financial orders, access accounts, calculate leverage or margin, consume live feeds, or execute real/demo transactions.
