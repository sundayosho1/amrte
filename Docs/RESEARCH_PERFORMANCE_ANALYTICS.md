# Research Performance Analytics

AMRTE v0.24.7 provides deterministic, offline statistics for immutable, dimensionless research outcomes. The engine is descriptive only: it cannot change allocation, restore permission, clear cooldowns, close safety incidents, or interact with financial systems.

## Analytical contract

`ResearchOutcomeObservation` records a normalized outcome plus strategy/research-method metadata, subject, regime, session, timeframe, lifecycle lineage, Phase VII safety attribution, dataset fingerprint, configuration snapshot, and point-in-time availability. Invalid, duplicate, future, malformed, or incompatible observations are rejected or quarantined.

`ResearchAnalyticsQuery` defines scope, filters, research period, as-of time, optional observation-count rolling window, provenance, and requested metrics. `ResearchAnalyticsSnapshot` is immutable and carries included identities, exclusions, metric versions, data quality, sample adequacy, confidence metadata, DecisionTrace, and source fingerprint.

## Statistics

Implemented neutral metrics include cumulative normalized outcome, positive/negative/flat rates, average and median normalized outcome, normalized expectancy, positive/negative magnitude ratio, distribution moments, linear-interpolated quantiles, tail summaries, median-absolute-deviation outlier identification, cumulative normalized path, peak-to-trough normalized decline, recovery ratio, positive/negative sequences and magnitudes, duration statistics, stability ratios, standard error, analytical confidence interval metadata, sample adequacy, trend classification, comparisons, and top-N contributions.

Undefined denominators return explicit unavailable states rather than zero or infinity. No automatic annualization is performed. Outliers remain in the raw dataset.

## Segmentation and lineage

The same calculation path supports strategy/research-method, version, variant, family, subject, category, regime, session, timeframe, safety-state, dataset, and composite filters. Segments remain isolated unless an explicit aggregate query is made. Dataset, configuration, metric-version, and as-of context are part of deterministic identities and cache keys.

## Phase VIII handoff

`PhaseVIIIAnalyticsSnapshot` aggregates the global summary and immutable references for segment and rolling snapshots. `Prompt32AnalyticsHandoff` exposes dashboard-ready data without implementing pages, controls, charts, optimization, walk-forward analysis, Monte Carlo analysis, or feedback into upstream permissions.

## Safety boundary

The module contains no broker, account, order, position, fill, leverage, margin, live/demo trading, monetary P&L, account-equity, or financial-drawdown capability. Normalized statistics are generic research measurements and never authorize action.
