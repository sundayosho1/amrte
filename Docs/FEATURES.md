# AMRTE Technical Indicator and Feature Engine

Version 0.7.0 consumes only trusted Prompt 5 `MarketDataSnapshot` data. Prompt
6 structure may be referenced by ID for lineage, but is never reconstructed.

## Authoritative definitions

- EMA uses an SMA seed over the first N values, then alpha `2/(N+1)`.
- True Range is the maximum of high-low, high-previous-close distance, and
  low-previous-close distance; the first observation uses high-low.
- ATR, directional movement, ADX, and RSI use Wilder smoothing.
- RSI returns 100 for no losses, 0 for no gains, and 50 for a flat series.
- MACD main is fast EMA minus slow EMA; signal is EMA of valid main values;
  histogram is main minus signal.
- Bollinger Bands use rolling population variance. Bandwidth is band width
  divided by absolute middle; percent-B is price position within the bands.
- Realized volatility is non-annualized population standard deviation of the
  configured rolling return window.
- Percentile rank uses `(below + 0.5 × equal) / count`, so ties are deterministic.
- Shift 0 is the latest eligible bar; shift N moves N eligible bars backward.

Every output carries value-or-`None`, health, as-of time, source bar, warm-up
metadata, warnings, and units. Zero is never used as a substitute for missing,
invalid, or numerically unsafe output.

## Temporal and numerical integrity

Closed-bar requests exclude forming bars. Every calculation is bounded by the
source snapshot's as-of timestamp. Rolling features and percentile histories
use no later observations. Non-finite outputs, invalid logs, and zero
denominators yield explicit error health rather than a fabricated number.

## Identity, cache, and recovery

Feature keys include dataset fingerprint, instrument, timeframe, feature,
canonical parameters, price source, bar state, shift, as-of time, engine
version, and configuration hash. The LRU cache is bounded. Recovery state is
minimal and derived state is always rebuildable from Prompt 5 data.

No third-party dependency was introduced. Native Windows Server verification
remains **WINDOWS VERIFICATION PENDING**; static portability passes.

