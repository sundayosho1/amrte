# Neutral Robustness Validation

AMRTE v0.25.0 adds a domain-neutral, offline robustness layer over Prompt 33's
immutable experiment artifacts. It accepts only timestamped numeric observations
from synthetic or approved offline datasets.

## Implemented methodology

- immutable, deterministic validation plans and handoffs;
- rolling and anchored sequential windows with configurable embargoes;
- frozen parameter-set lineage and point-in-time observation eligibility;
- deterministic holdout seals, contamination detection, and reuse warnings;
- seeded IID, block, and stratified resampling;
- bounded distribution summaries and uncertainty indicators;
- monotonic generic quality-degradation stress;
- parameter-neighborhood cliff, plateau, and isolated-peak indicators;
- negative-evidence preservation, evidence ledger, classification vetoes;
- immutable profiles/results, replay fingerprints, reconciliation, recovery;
- idempotent/concurrency-safe processing, audit, and DecisionTrace.

## Interval semantics

Development and validation intervals are half-open: `[start, end)`. By default,
`development_end == validation_start`; a positive embargo makes the separation
strict. Observations participate only when both their observation time is inside
the relevant interval and their knowledge time is no later than the interval end.

## Safety boundary

The framework does not model markets, trades, orders, fills, positions, monetary
returns, brokerage, leverage, margin, accounts, or financial execution. Scores
are generic, dimensionless software-research measurements. Classification cannot
authorize any real-world action.

## Limitations

The implementation provides descriptive deterministic resampling rather than a
general statistics package. Stratification uses neutral deterministic partitions;
domain-specific strata require a later, separately approved generic contract.
Confidence intervals, advanced streaming quantile sketches, and GUI rendering are
not included. Native Windows execution has not been performed.

