# Systemic Research Safety

AMRTE v0.24.6 adds a neutral, offline systemic-safety gate for deterministic research workflows. It does not contain broker, order, account, position, financial execution, live-data, or demo-trading capabilities.

## State model

The engine publishes `NORMAL`, `CAUTION`, `RESTRICTED`, `CIRCUIT_OPEN`, `EMERGENCY_STOP`, `RECOVERY_PENDING`, or `PROBATION`. Repeated medium/high signals can escalate the state. Circuit-open and emergency states latch until explicit evidence-backed recovery succeeds.

The final permission multiplier is always:

```text
min(upstream_multiplier, system_safety_multiplier)
```

Consequently, Prompt 30 cannot restore or amplify a restriction produced by Prompt 28, Prompt 29, or another upstream authority.

## Evidence and temporal rules

Every accepted signal carries deterministic identity, scope, domain, severity, trigger, evidence IDs, observation time, availability time, dataset fingerprint, configuration lineage, and recovery epoch. Future, out-of-order, unprovenanced, unknown, or lineage-incompatible signals fail closed without mutating accepted state.

Supported neutral safety domains are data integrity, observation quality, workflow, state integrity, calculation, temporal integrity, recovery, reconciliation, replay, persistence, configuration, and bounded resources.

## Incidents and recovery

Circuit-open or emergency signals create a deterministic incident. Additional severe signals aggregate into that incident. Recovery requires confirmed evidence, actor, reason, and a bounded probation sequence. Failed probation returns to emergency state. Restart recovery validates schema, engine version, configuration, epoch, event sequence, signal count, and permission invariants.

## Persistence and replay

Statuses, immutable versions, signals, incidents, and events form a bounded append-oriented record. Duplicate signals are idempotent. Point-in-time snapshots exclude later evidence. Reconciliation detects inconsistencies and never manufactures repairs. Replay fingerprints permit deterministic equivalence checks after restart.

## Safety boundary

The module controls only neutral research-workflow permission metadata. It cannot initiate transactions, connect to external financial systems, submit requests to brokers, or manipulate financial exposure. Prompt 31 was not started.
