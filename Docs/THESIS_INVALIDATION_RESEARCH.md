# Thesis Invalidation Research (Prompt 19)

AMRTE v0.19.0 provides a single offline, immutable research representation of when a hypothesis ceases to be valid. It creates no broker order and cannot manage a position.

## Dependency direction

`Prompt 6/7 evidence + Prompt 16 decision → Prompt 19 boundary/distance → Prompt 17 pure sizing → Prompt 18 restriction`

Prompt 19 references upstream structure and ATR artifacts by deterministic identity, dataset, instrument, timeframe, availability time, and health. It does not calculate swings, ranges, breaks, ATR, strategies, or adaptive risk.

## Methods

- `STRUCTURE`: a confirmed upstream structural reference in the adverse thesis direction.
- `ATR_NORMALIZED`: an upstream ATR value multiplied by a configured research multiplier.
- `HYBRID`: explicit structure-plus-volatility or most-conservative-valid-distance policy.
- fallback is disabled unless a profile lists permitted fallback methods.

The reference point is a research artifact, never a broker fill. Distances use the project's normalized research-price representation, not pips or broker ticks. Minimum and maximum policies reject unsafe distances by default. Optional offline friction and volatility allowances can only widen the distance within configured limits; this reduces or preserves fictional exposure and never increases authorized risk.

## Lifecycle and ledger

Boundaries are immutable and may become active, invalidated, expired, or superseded. Invalidation observations record separate observed and confirmed timestamps. The bounded ledger prevents duplicate event creation during replay and retains event identity through recovery. Boundaries do not trail; trailing research remains future-owned.

## S1/S2/S3 integration

S1 thesis evidence is normalized rather than redefined. S2 received the smallest upstream extension: explicit boundary availability plus boundary/value/confirmation lineage on false-break invalidation evidence. S3 already exposes point-in-time lower/upper range boundaries and source snapshot identity. Strategy-specific profiles select compatible methods without embedding strategy rules in the risk engine.

## Prompt 20 handoff

Prompt 19 exposes `THESIS_INTACT`, `THESIS_WEAKENING`, and `THESIS_INVALIDATED`. Prompt 20 may consume these research states, but Prompt 19 does not define profit targets, partial exits, take-profit, break-even, trailing, or position closure.

## Safety boundary

No live spread, broker stop/freeze level, account data, leverage, margin, lots, stop order, position modification, order submission, or real/demo execution exists.
