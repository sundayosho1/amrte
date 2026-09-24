# AMRTE Market Data and Integrity Engine

Version 0.5.0 establishes the single market-data authority for later Phase II
modules. The layer accepts offline deterministic research data only. It does
not discover instruments from a platform, open network connections, use an
account, or expose execution operations.

## Contracts

- `IMarketDataProvider` exposes metadata, explicit capabilities, bar queries,
  ranges, dataset identity, and deterministic fingerprints.
- `NormalizedBar` is immutable and retains instrument, timeframe, timestamps,
  optional volume/spread fields, bar state, validity, source reference, and a
  deterministic bar ID.
- `DatasetValidationReport` records integrity findings and admission status.
- `MarketDataSnapshot` is an immutable, coherent, as-of decision context with
  provenance, configuration identity, recovery epoch, health, quality, and
  synchronization state.

## Temporal and integrity rules

All internal timestamps are timezone-aware UTC. Naive timestamps are invalid.
Closed bars are visible only when their close timestamp is at or before the
query's `as_of` timestamp. A forming bar cannot satisfy a closed-bar request.
Snapshot publication requires every requested timeframe to be available,
healthy, and synchronized without future information.

Strict mode rejects invalid timestamps, non-finite or non-positive prices,
invalid OHLC relationships, impossible volume, source chronology disorder,
and conflicting duplicates. Identical duplicates are deterministically
deduplicated and reported. Large discontinuities and uncertain gaps remain in
the validation report; they are not silently repaired or deleted. Lenient
import mode is diagnostic only and never reports unresolved data as healthy.

## Cache, recovery, and portability

The in-memory LRU cache is bounded. Keys include dataset fingerprint,
instrument, timeframe, as-of cursor, requested bar state, and normalization
version. Recovery state contains identity/fingerprint and last committed
closed-bar IDs, not full datasets.

Configured paths are relative and portable. There are no hard-coded developer
paths, shell dependencies, GUI requirements, or platform adapters. Static
portability checks pass. Native Windows Server execution remains **WINDOWS
VERIFICATION PENDING**.

Persistent normalized-data caching is intentionally deferred. If added, it
must use the configured directory, schema/version metadata, atomic replacement,
and Windows-compatible locking.

Prompts 6–10 must consume validated services and `MarketDataSnapshot`; they
must not independently ingest, normalize, repair, or bypass Prompt 5 data.
