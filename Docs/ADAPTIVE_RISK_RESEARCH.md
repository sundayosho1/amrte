# Adaptive Risk Research (Prompt 18)

AMRTE v0.18.0 restricts an already-authorized Prompt 17 fictional research-risk budget. It is offline, broker-independent, and cannot place or modify an order.

## Authority and invariants

`StrategyDecisionSnapshot → Prompt 17 RiskSizingResult → AdaptiveRiskEngine → AdaptiveRiskDecision`

- `0 <= adaptive risk <= Prompt 17 base risk`
- every standard modifier is in `[0, 1]`; values above 1 are rejected
- any hard block produces zero adaptive risk and zero simulated exposure
- deterioration is immediate; recovery is confirmed, stepped, and cooldown-aware
- future evidence is rejected for historical decisions
- Prompt 17's pure floor-quantization primitive is reused; no second sizing engine exists

## Modifier chain

The default composition is multiplicative and restrictive. Drawdown uses only timestamped fictional research-equity observations. Volatility, strategy health, and data health consume authoritative upstream classifications without recalculating indicators. Dependency groups prevent the same evidence from being penalized twice under the default most-restrictive-only policy.

Portfolio and protection providers are contracts only. Until their authoritative owners exist, availability is recorded as `FUTURE_OWNED`; the configured policy determines neutral-if-not-required, restriction, or blocking. A neutral policy does not claim those future systems are healthy.

## Drawdown and recovery

Peak equity uses observations available at or before the decision timestamp and is persisted by fictional dataset. Configurable monotonic bands map increasing drawdown to non-increasing modifiers. Defensive/protect/blocked states start a distinct adaptive-risk cooldown. Recovery requires confirmations and advances one state at a time, never above the Prompt 17 budget.

## Prompt 19 contract

`COMMON_NORMALIZED_INVALIDATION_DISTANCE` remains deferred to Prompt 19. Prompt 18 consumes Prompt 17's recorded normalized distance only to reduce and requantize fictional exposure. Prompt 19 should provide a versioned, point-in-time, strategy-authoritative invalidation-distance reference; Prompt 18 must not create executable stop logic.

## Safety boundary

No account access, broker equity, margin, leverage, lots, broker volume, executable stops/targets, position modification, live feed, or order submission is present.
