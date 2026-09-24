# S1 Trend Pullback Strategy

AMRTE v0.13.0 adds `S1_TREND_PULLBACK`, a research-only Trend-family strategy.
It consumes the immutable `MarketIntelligenceSnapshot`, participates in the
Prompt 11 lifecycle, and delegates all final scoring to Prompt 12.

## Research sequence

S1 requires a compatible Prompt 8 regime and directionally coherent Prompt 6
context/strategy structure. It then interprets existing Prompt 7 normalized
features to distinguish a counter-directional pullback from noise,
consolidation, excessive depth, or structural reversal. A candidate requires
trend-direction resumption evidence on the configured execution-analysis
timeframe. Directional hypotheses are symmetric.

Default roles are H4 context, H1 strategy, and M15 execution analysis. These
are validated configuration defaults, not embedded constants. Mandatory
confirmation uses authoritative closed-bar feature semantics.

## Pullback intervals and lifecycle

Pullback depth is an ATR-normalized magnitude. The accepted default interval is
`[minimum_depth, maximum_depth]`. Duration is counted in admitted S1 evaluation
observations and accepted on `[minimum_duration, maximum_duration]`. The state
machine distinguishes potential, developing, qualified, resumption pending,
completed, invalidated, expired, rejected, and unknown states.

Logical pullback identity is based on dataset, instrument, direction, knowable
start timestamp, and configuration. Each material snapshot creates a
deterministic immutable version. Histories and orchestrator caches are bounded.

## Ownership boundaries

S1 never recalculates EMA, ATR, ADX, directional movement, momentum,
volatility, pivots, BOS, zones, regime, session, DST, or news windows. It
interprets upstream results with explicit provenance.

`StrategyInvalidationEvidence` describes research-thesis invalidation only.
`StrategyExitContext` describes thesis status only. Neither contains an
executable stop, target, exit, position size, order, broker instruction, or
account operation. R:R remains deferred and correlation remains Phase V-owned.

## Prompt 14 gate

The Prompt 7 bounded temporal feature-series and Prompt 8 historical
pre-breakout compression extensions remain unresolved. They do not block S1,
but must be completed before Prompt 14.
