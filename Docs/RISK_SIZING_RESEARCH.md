# Fictional Risk Budget and Simulated Exposure Sizing

AMRTE v0.17.0 begins Phase IV with an offline, dimensionless research model. `RiskSizingEngine` accepts only the authoritative Phase III `StrategyDecisionSnapshot`, an immutable fictional capital context, an explicit normalized thesis-invalidation context, optional synthetic cost assumptions, and restrictive modifiers.

All critical mathematics uses `Decimal`. Exposure is capped and quantized downward on a configurable fictional grid, after which normalized risk is recalculated and checked against the authorized fictional budget. Missing, non-finite, zero, near-zero, future, or excessive distance produces zero exposure and `NO_ACTION`. Modifiers can only preserve or reduce the base fictional risk fraction.

The module deliberately has no mapping to lots, contracts, ticks, pips, currencies, margin, leverage, accounts, brokers, or executable orders. `SimulatedExposureDecision` is research metadata and cannot authorize activity outside the fictional simulator.

S1–S3 do not yet expose one common authoritative normalized invalidation distance. The engine therefore requires an explicit `InvalidationDistanceContext`; synthetic fixtures validate the architecture, while missing strategy-authoritative evidence fails closed. Prompt 19 or a narrowly approved upstream research extension remains responsible for future thesis-invalidation geometry.

