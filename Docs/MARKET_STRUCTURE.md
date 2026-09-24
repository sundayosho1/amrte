# AMRTE Multi-Timeframe Market Structure

Version 0.6.0 consumes only trusted immutable Prompt 5 `MarketDataSnapshot`
objects. It never retrieves or normalizes market data independently.

## Temporal semantics

A pivot at bar N is a candidate until all configured right-side closed bars
exist. `candidate_at` records the pivot bar availability; `confirmed_at` and
`confirmation_bar_id` record when the swing became knowable. Consequently,
historical snapshots before confirmation cannot expose it as confirmed.
Structural breaks, zones, tests, and confidence use only bars already present
in the source snapshot.

## Deterministic pipeline

The engine validates Prompt 5 health/synchronization, detects and confirms
swings, classifies compatible highs/lows, derives evidence-based structural
direction, detects policy-controlled breaks, derives strict confirmed shifts,
evaluates consolidation, constructs/merges/prunes zones, analyzes each
configured timeframe independently, and maps the three directions through an
explicit alignment matrix.

`UNKNOWN`, `SIDEWAYS`, and `MIXED` are distinct. Numeric confidence is forced
to zero when mandatory structure health is insufficient or invalid.

## Boundaries

The implementation has no indicators, final regime classification, session or
news logic, strategy signals, financial-risk calculations, portfolio logic,
network providers, platform adapters, or execution behavior.

All histories, zones, and caches are bounded. Recovery stores only engine
schema, last processed IDs, and deduplicated break IDs. Native Windows Server
testing remains **WINDOWS VERIFICATION PENDING**; static portability passes.

