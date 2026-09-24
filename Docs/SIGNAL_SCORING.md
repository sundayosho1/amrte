# AMRTE Signal Confidence & Quality Scoring

Version 0.12.0 provides one centralized, deterministic research scorer. A score
describes evidence quality under a named model; it is neither a profit
probability nor an authorization.

## Evaluation order

Hard Phase II intelligence gates, Prompt 11 applicability, detection and
qualification run before scoring. `UNAVAILABLE`, `INCOMPLETE`, `INVALID`, or
`UNKNOWN` score health stops the lifecycle at `NO_ACTION`. No score can weaken
an upstream or downstream restriction.

## Numerical policy

Factors are normalized to `[0,100]`, clamped when configured, weighted using
`math.fsum`, and externally rounded to the configured precision (six decimal
places by default). Raw weights are divided by the sum of effective available
weights, so they need not sum to 100. Optional missing factors are handled by
the configured policy; mandatory missing factors make the score unavailable.
Missing values remain `None` and are never converted to zero.

The decomposed score exposes confidence, quality, completeness, agreement,
uncertainty, conflict penalty, factor contributions, group contributions,
reasons, exact model/version, configuration identity and Phase II lineage.

## Interval and dependency safeguards

Models reject negative weights, duplicate IDs, unknown dependencies, dependency
cycles, invalid normalizers, and zero-effective models. Group caps bound related
evidence. Timeframe role weights are configuration-driven. Critical conflicts
may invalidate scoring. The bounded cache key includes evaluation, model,
configuration and MarketIntelligenceSnapshot identities.

## Research defaults

TREND, BREAKOUT, MEAN_REVERSION, and CUSTOM profiles are unoptimized research
defaults. Strategy-specific evidence remains decomposable. Prompt 12 does not
implement strategy detection rules.

`RISK_REWARD` is `NOT_APPLICABLE / DEFERRED_BY_DESIGN` pending its future
authoritative risk-geometry owner. `CORRELATION` is likewise deferred to Phase
V. Breakout historical compression proof still requires the bounded Prompt 7
feature-series and Prompt 8 proof extension before Prompt 14.

## Safety boundary

The module contains no broker, account, authentication, live-feed, order,
position-sizing, leverage, or execution capability. Outputs are immutable
offline research metadata.
