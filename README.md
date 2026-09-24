# AMRTE Research Core

Prompts 1–11 establish the fail-closed, non-broker-connected foundation,
authoritative typed configuration, crash-consistent persistence/recovery, and
structured observability engines for the Adaptive Multi-Regime Trading Engine
research project.

This package contains lifecycle, configuration, health, identity, clock,
capability, numerical-safety, and dependency-inversion foundations. It does
not contain strategies, pricing logic, broker adapters, authentication,
network connectivity, or executable order placement. Test fixtures use only
fictional instrument identifiers.

Prompt 2 adds immutable named profiles, typed setting definitions, validation,
provenance, deterministic hashing, canonical serialization, structured diffs,
schema classification, atomic profile switching, rollback, and readiness
integration. Profiles adjust abstract fictional-research envelopes only.

Prompt 3 adds versioned local checkpoints, canonical integrity hashes, atomic
promotion, two-generation fallback, quarantine, recovery reconciliation,
idempotency, protection-state continuity, recovery epochs, storage health, and
deterministic replay descriptors. Checkpoints reject sensitive and execution-
enabling fields.

Prompt 4 adds immutable structured events, redaction, correlation/causation,
audit hash chains, JSONL/console/test sinks, rotation, retention, storage limits,
backpressure, decision traces, error escalation, bounded retries, notification
contracts, audit queries, incident timelines, and integrated Phase I diagnostics.

Prompt 5 begins Phase II with an authoritative offline market-data layer:
provider capabilities, immutable normalized bars, provenance, deterministic
dataset/bar/snapshot identity, strict timestamp and OHLC integrity, duplicate
and gap detection, as-of/no-look-ahead enforcement, multi-timeframe
synchronization, explicit spread/volume availability, dataset admission,
bounded caching, new-bar state, recovery metadata, and immutable coherent
MarketDataSnapshots. It accepts only historical, synthetic, fictional, or
other approved offline research inputs.

Prompt 6 adds deterministic multi-timeframe market-structure description over
Prompt 5 snapshots: confirmation-time-safe swings, HH/HL/LH/LL/EH/EL,
structural direction, confirmed structural breaks and shifts, consolidation
with hysteresis, bounded support/resistance zones, alignment, explainable
confidence/evidence, immutable lineage snapshots, cache/rebuild behavior, and
compact recovery metadata. It does not generate signals or execution actions.

Prompt 7 adds the centralized mathematical feature layer: canonical price
sources and feature keys, SMA-seeded EMA, Wilder ATR/ADX/RSI, MACD, population
Bollinger bands, candle/return/momentum/volatility/range measurements, explicit
warm-up and unavailable states, dependency-cycle validation, bounded caching,
immutable lineage snapshots, rebuild, recovery, observability, and readiness.
Features measure data only; they do not produce market or trading decisions.

Prompt 8 adds an advisory market-regime layer over coherent Prompt 5–7
snapshots. It classifies trend, range, breakout/expansion, transition,
abnormal, and unknown states across three timeframes; preserves direction as
a separate dimension; records weighted evidence and confidence; applies
confirmation, persistence, cooldown, exit thresholds, and uncertainty grace;
and publishes bounded history and recovery metadata. Its eligibility output is
research metadata only and every decision trace terminates in `NO_ACTION`.

Prompt 9 adds centralized UTC, timezone, DST, session, calendar, trading-day,
trading-week, Friday, weekend, Monday-reopening, and rollover intelligence.
Session intervals use `[open, close)` semantics. Unknown or ambiguous temporal
context cannot produce positive eligibility, and all outputs remain immutable
research metadata with `NO_ACTION` decision traces.

Prompt 10 adds immutable, versioned offline economic-event intelligence with
historical as-of projection, field-level availability timestamps, conservative
severity handling, instrument relevance, coverage gates, event windows,
deterministic clustering, advisory restrictions, and bounded recovery/cache
state. It also completes Phase II with one lineage-validated immutable
`MarketIntelligenceSnapshot` spanning Prompts 5–10. No event or unified
intelligence output authorizes an action.

Prompt 11 begins Phase III with a universal research-strategy framework:
strategy registry and orchestration, explicit requirements and applicability,
standardized evidence, detection and qualification, a Prompt 12 scoring
contract, immutable candidates and research signals, lifecycle/versioning,
bounded state, and unavailable downstream gate contracts. It implements no
production strategy and no order, position, financial sizing, or execution
capability. Every evaluation trace ends in `NO_ACTION` at the system-action
level even when a research signal is emitted for analysis.

Run the regression baseline with:

```bash
python -m pytest
```

The application entry point is `amrte.app:main`; it initializes the core,
reports readiness, and shuts down without starting any position simulation.
