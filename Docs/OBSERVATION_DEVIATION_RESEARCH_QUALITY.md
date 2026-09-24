# Neutral Observation Deviation & Research Quality Engine

AMRTE v0.24.2 adds a deterministic quality layer for generic scalar observations. It is a safe architectural substitute for Prompt 26 and contains no financial-market, pricing, transaction-cost, order, account, position, or execution model.

## Model

The engine accepts immutable `ScalarObservation` records carrying a subject, channel, scalar value, observed/available timestamps, source, dataset identity/fingerprint, health, and configuration lineage. It builds a robust baseline from point-in-time-admissible observations using the median, median absolute deviation, and interpolated 90th percentile.

`DeviationSnapshot` records absolute deviation, relative ratio when the denominator is valid, bounded percentile rank, robust z-score when MAD is non-zero, and a configured deviation regime. Missing or zero denominators remain explicit and never become fabricated zero deviation.

`ResearchQualitySnapshot` separates raw state from published state. Published recovery requires configured confirmation while deterioration applies immediately. Repeated failures escalate to an untrusted state. Restrictions are non-amplifying: multipliers remain within `[0, 1]`.

## Temporal and lineage rules

- Only observations whose observed and available timestamps are at or before `as_of` enter a baseline.
- Dataset, fingerprint, subject, channel, and configuration lineage must agree.
- Future, stale, malformed, negative, non-finite, mixed-lineage, or insufficient evidence fails closed.
- Deterministic ordering uses observation time, availability time, then observation ID.
- Every published object is immutable and deterministically identified.

## Reliability

- Bounded per-scope histories and global snapshots.
- Process-local synchronization with `RLock`.
- Recovery validates schema, engine/configuration identity, epoch, duplicate IDs, bounds, and restriction multipliers.
- Incompatible or corrupt recovery enters recovery-restricted state.
- Deterministic replay produces the same snapshot IDs.
- Neutral workflow-health evidence is explicit, attributed, and may only preserve or reduce research permission.
- Audit events and AMRTE `DecisionTrace` explain each result.

## Safety boundary

This module evaluates generic data credibility only. It has no instruments, market prices, spreads, transaction costs, trading strategies, broker/API connectivity, orders, fills, accounts, positions, leverage, margin, or live/demo financial execution capability.
