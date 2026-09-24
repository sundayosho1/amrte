# Market Regime Detection Engine

Prompt 8 introduces `RegimeEngine`, an offline, advisory classifier that
consumes coherent immutable `MarketDataSnapshot`, `StructureSnapshot`, and
`FeatureSnapshot` inputs. It does not calculate indicators, rediscover market
structure, generate orders, or connect to any external service.

## Classification model

The primary regimes are `TREND`, `RANGE`, `BREAKOUT_EXPANSION`, `TRANSITION`,
`ABNORMAL`, and `UNKNOWN`. Direction is independent: `BULLISH`, `BEARISH`,
`NEUTRAL`, `MIXED`, or `UNKNOWN`.

Each context, strategy, and execution timeframe produces bounded component
scores from Prompt 6 structure evidence and Prompt 7 feature evidence. The
configured timeframe weights produce the composite score. Classification uses
minimum scores, a winner margin, confidence, input-health constraints, and an
abnormal override. Breakout classification requires boundary-break,
volatility-expansion, and displacement evidence rather than a single large
observation.

## Stability and safety

Published state is guarded by entry and exit thresholds, confirmation counts,
minimum persistence, cooldown, and a short unknown grace period. Invalid
lineage is rejected. Invalid, stale, contradictory, or insufficient inputs
degrade to abnormal or unknown states, with restricted or blocked research
eligibility. Eligibility is immutable advisory metadata, never permission to
place a trade.

Snapshots include lineage, per-timeframe scores, supporting/conflicting/missing
evidence, reason codes, confidence decomposition, hysteresis state, health, and
a `NO_ACTION` decision trace. History is bounded and duplicate source snapshots
are suppressed. Recovery state is accepted only when dataset fingerprint,
configuration hash, and engine version match; otherwise callers rebuild from
the supplied offline timeline.

## Known boundary

The current Prompt 7 snapshot contains the latest feature values, not a
multi-observation compression history. Consequently, breakout gating verifies
three contemporaneous evidence dimensions, while explicit prior-compression
proof remains deferred until an upstream temporal feature exposes it.
