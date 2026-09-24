# AMRTE — Prompt 3 Delivery Report

**Prompt:** Persistent State, Restart & Recovery Engine  
**Version:** 0.3.0  
**Status:** PASS WITH SAFETY-SCOPE DEFERMENTS

## Upstream verification

- Prompt 1 baseline before Prompt 3: **22 passed**
- Prompt 2 cumulative baseline before Prompt 3: **67 passed**
- Prompt 1 regression after Prompt 3: **22 passed**
- Prompt 2 cumulative regression after Prompt 3: **67 passed**
- Architecture conflicts: **None**

Prompt 3 extends `IStateRepository`, Prompt 1 clocks/IDs/results/audit hooks,
Prompt 2 snapshots/hashes, and the existing health/capability boundaries. It
does not create a second state machine, clock, configuration engine, or logger.

## Files created

- `src/amrte/core/persistence_types.py`
- `src/amrte/core/persistence.py`
- `src/amrte/core/recovery.py`
- `Tests/Unit/test_persistence.py`
- `Tests/Unit/test_recovery.py`
- `Tests/Integration/test_persistence_recovery.py`
- `Tests/Regression/test_prompt3_baseline.py`
- `Docs/RECOVERY.md`
- `DELIVERY_REPORT_PROMPT_3.md`

## Files modified

- `pyproject.toml`
- `README.md`
- `src/amrte/core/constants.py`
- `src/amrte/core/config_schema.py`
- `src/amrte/core/persistence.py`
- `src/amrte/core/recovery.py`
- `src/amrte/infrastructure/local.py`
- `Tests/Unit/test_configuration_engine.py`
- `Tests/Unit/test_persistence.py`
- `Tests/Unit/test_recovery.py`

## Persistence architecture

- **Repository:** `LocalCheckpointRepository`, implementing the existing
  `IStateRepository` contract and checkpoint-specific operations.
- **Storage:** local UTF-8 canonical JSON; no network or external service.
- **Checkpoint:** immutable versioned metadata plus bounded generic payload.
- **Retention:** current and previous validated generations; configurable policy
  prepared with a mandatory minimum of two.
- **Ownership:** one repository owns save, load, enumeration, validation,
  fallback, quarantine, metadata, and storage health.

## Schema and integrity

- State schema: `1.0`
- Persistence format: `1.0`
- Compatibility: current, compatible, migration-required, incompatible,
  corrupted, and unknown classifications.
- Migration: validation/migration interface prepared; no migration currently
  required.
- Serialization: canonical sorted JSON with non-finite numbers rejected.
- Integrity: SHA-256 payload and manifest hashes.
- Corruption: rejected, audited, quarantined, and never activated.

## Crash consistency

The repository writes a temporary checkpoint, flushes and fsyncs it, validates
it by reading it back, preserves the current generation, atomically promotes
the new checkpoint, and fsyncs the directory. Write failure never reports the
candidate as durable and preserves the last valid generation.

## Reconciliation and recovery

- Configuration snapshot/hash: exact verification.
- Fictional dataset ID/fingerprint: exact verification.
- Experiment ID: verified when expected.
- Clock: checkpoint timestamp and deterministic cursor retained; stale state can
  require manual review.
- Randomness: seed and sequence position preserved and tested.
- Events: `NOT_STARTED`, `IN_PROGRESS`, and `COMMITTED` contract.
- Partial event: replays from last committed cursor.
- Duplicate event: deterministic idempotency ledger prevents recommit.
- Orphan/ghost state: detected and routed to manual review.
- Clean/unclean shutdown: distinguished; unclean recovery increments epoch.
- Protection/suspension/cooldown fields: preserved without reset.

## Health and readiness

Storage health supports `HEALTHY`, `DEGRADED`, `READ_ONLY`, `UNAVAILABLE`,
`CORRUPTED`, and `UNKNOWN`. Successful validation sets health to `HEALTHY`.
Unavailable/read-only/corrupted storage fails recovery closed. Recovery reports
do not transition the Prompt 1 engine to `RUNNING`.

## Tests

- Prompt 3 additions: **35 passed**
- Prompt 1–2 cumulative regression: **67 passed**
- Total: **102 passed**
- Failed: **0**
- Skipped: **0**

Tested first start, missing expected state, clean/unclean restart, valid load,
two generations, monotonic sequence, chain continuity, corruption, fallback,
dual corruption, schema compatibility, payload/manifest integrity, interrupted
writes, stale temporary files, size bounds, configuration/dataset/experiment
mismatch, staleness, partial events, duplicate keys, idempotency, orphan/ghost
state, protection continuity, clock/cursor data, random restoration, recovery
epoch, recovery modes, read-only/unavailable storage, quarantine, readiness, and
permanent execution unavailability.

## Failure injection

- Temporary write: last valid checkpoint preserved.
- Flush: last valid checkpoint preserved.
- Atomic promotion: last valid checkpoint preserved.
- Load corruption: rejected and quarantined.
- Persistence unavailable/read-only: structured fail-closed result.
- Oversized state: rejected before promotion.

Serialization, hashing, migration, reconciliation, and shutdown errors use the
same structured exception boundary; dedicated stage-specific injection hooks
for those paths remain technical debt.

## Property and invariant status

**PASS.** Tests verify corrupted state never activates, sequences increase,
configuration/dataset mismatches cannot resume automatically, invalid candidates
cannot replace valid state, duplicate commits are prevented, restrictions
survive restart, deterministic random continuation is reproducible, and
execution capabilities remain unavailable.

## Safety verification

- No broker connectivity, authentication, or reconciliation.
- No real or demo leveraged execution.
- No realistic leveraged-market simulation.
- No network dependency.
- Recovered state cannot enable prohibited execution.
- Sensitive/broker/execution-enabling checkpoint fields are rejected.
- Hard-safety configuration remains authoritative after restart.
- Invalid, ambiguous, incompatible, or corrupted state fails closed.

## Requirement gap scan

| Requirement | Classification | Notes |
|---|---|---|
| 3.1–3.5 upstream architecture, safety, authority | IMPLEMENTED | Existing core reused; one repository owner. |
| 3.6–3.8 persistence boundary/categories/checkpoint | IMPLEMENTED | Versioned generic checkpoint and bounded payload. |
| 3.9–3.11 schema compatibility/migration | IMPLEMENTED | Classifier and migration contract; no migration needed. |
| 3.12–3.16 atomic writes/generations/sequence/chain/integrity | IMPLEMENTED | Atomic promotion, two generations, SHA-256. |
| 3.17–3.20 corruption/missing/cleanliness/startup | IMPLEMENTED | Quarantine, first-run distinction, recovery pipeline. |
| 3.21–3.24 configuration/dataset/cursor | IMPLEMENTED | Exact fingerprints and committed cursor. |
| 3.25–3.28 idempotency/commit/partial/duplicate | IMPLEMENTED | Ledger and event commit contract. |
| 3.29 ownership metadata | IMPLEMENTED | Generic owner/experiment/object IDs supported. |
| 3.30–3.31 orphan/ghost | IMPLEMENTED | Deterministic detection and manual-review result. |
| 3.32 protection continuity | IMPLEMENTED | Restrictive state persists and blocks readiness. |
| 3.33 high-water/reference values | DEFERRED BY DESIGN | Persistence accepts generic future-owned references; financial meaning/calculation excluded. |
| 3.34–3.37 cooldown/clock/random/epoch | IMPLEMENTED | Payload continuity, replay descriptor, tested RNG restoration. |
| 3.38–3.39 safe checkpoints/frequency | IMPLEMENTED | Safe write boundary and bounded configuration contract; scheduling belongs to later orchestration. |
| 3.40–3.44 failures/health/edge cases/size/quarantine | IMPLEMENTED | Structured OSError handling, health states, bounds, quarantine. |
| 3.45–3.48 modes/results/confidence/readiness | IMPLEMENTED | All requested classifications represented. |
| 3.49–3.52 fail-safe/manual/audit/replay | IMPLEMENTED | No implicit reset; structured events and replay descriptor. |
| 3.53 fixture export | IMPLEMENTED | Isolated temporary-path checkpoint tests. |
| 3.54–3.57 tests/failure/property/regression | IMPLEMENTED | 102 tests pass; three write-stage injections. |
| 3.58 non-goals | IMPLEMENTED | Excluded from source. |
| 3.59 definition of done | IMPLEMENTED | Mandatory persistence/recovery foundation complete. |
| 3.60–3.62 scan/report/final instruction | IMPLEMENTED | This report; development stops after Prompt 3. |

### Partially implemented

- Dedicated failure-injection switches exist for temporary write, flush, and
  promotion. Other exception paths are handled and tested indirectly but do not
  each have a named injection switch.
- Retention configuration supports future values above two, while the current
  repository physically retains current and previous only.

These do not block Prompt 3 acceptance because the mandatory current/previous
fallback and structured failure boundary are implemented and verified.

### Safety-scope deferments

- Realistic position/order ownership and reconciliation.
- Financial high-water, drawdown, loss, margin, or exposure semantics.
- Market dataset, price, bar, strategy, and financial-event domain logic.
- Broker or account recovery of any kind.

Generic persistence contracts remain available for later safe, fictional domain
objects without implementing those prohibited mechanics.

## Known issues and technical debt

- Physical retention is two generations even when a higher future retention
  value is configured.
- No concrete state migration exists because only schema 1.0 exists.
- Audit events remain in Prompt 1's in-memory sink pending Prompt 4.
- Filesystem integrity hashes detect accidental corruption; they are not digital
  signatures or hostile-tamper authentication.
- No known critical recovery defect remains unresolved.

## Overall acceptance

**ACCEPTED**

## Ready for Prompt 4

**YES**, within the same non-broker-connected, non-realistic-simulation boundary.

