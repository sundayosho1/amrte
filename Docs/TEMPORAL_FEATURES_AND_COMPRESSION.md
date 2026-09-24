# Temporal Features and Historical Compression

AMRTE v0.14.0 extends the existing Prompt 7 feature engine; it does not add a second feature-calculation path.

`TemporalFeatureSeriesStore` admits immutable Prompt 7 feature snapshots and exposes bounded queries keyed by dataset fingerprint, instrument, timeframe role, timeframe, as-of timestamp, lookback, required feature set, and configuration snapshot. Only observations whose availability time is at or before the query time are eligible. Forming observations are excluded. Missing or invalid required features produce explicit incomplete or invalid health rather than substitute values.

`HistoricalCompressionAnalyzer` consumes that series in Prompt 8. It evaluates only observations strictly before the breakout observation, publishes immutable `HistoricalCompressionEvidence`, and distinguishes `CONFIRMED`, `NOT_CONFIRMED`, `INSUFFICIENT_HISTORY`, `UNAVAILABLE`, and `UNKNOWN`. Compression is based on existing Prompt 7 volatility-expansion and Bollinger-bandwidth evidence; Prompt 8 does not recalculate indicators.

The resulting optional evidence is carried inside `RegimeSnapshot`, so the existing Prompt 10 `MarketIntelligenceSnapshot` lineage remains compatible. Deterministic identities include source-series identity and configuration. Bounded caches and recovery validation prevent cross-dataset or cross-configuration contamination.

