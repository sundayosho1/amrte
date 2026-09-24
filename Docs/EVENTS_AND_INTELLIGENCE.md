# Economic Events and Unified Market Intelligence

Prompt 10 completes AMRTE Phase II using two authoritative components:
`NewsRiskEngine` and `MarketIntelligenceAssembler`. Both are offline research
services. Neither predicts event direction, creates signals, sizes financial
risk, connects to a network, or executes actions.

## Historical event knowledge

`DeterministicEventProvider` stores immutable event versions and projects the
latest version knowable at an `as_of` UTC instant. A logical event ID remains
stable across versions; each revision has its own version ID. `FirstKnownAtUTC`
controls when the schedule enters the historical view. `LastUpdatedAtUTC`
controls when a new immutable version becomes visible. Forecast, previous, and
actual values each remain unavailable until their own availability timestamps.
Later rescheduling, cancellation, release, or revision records therefore cannot
rewrite an earlier historical view.

Dataset identity is a canonical SHA-256 fingerprint over provider identity and
event-version content. Coverage, import time, provider version, source
description, schema version, and configuration lineage are explicit.

## Window semantics

For scheduled event instant `E`, configuration supplies `pre`,
`blackout_before`, `blackout_after`, `post`, and `stabilization` durations.
Intervals are:

- Pre-event: `[E - pre, E - blackout_before)`
- Blackout: `[E - blackout_before, E + blackout_after)`
- Post/stabilization: `[E + blackout_after, E + blackout_after + post + stabilization)`
- Clear only outside those intervals and only when provider health and the
  complete search horizon are trustworthy.

Touching or overlapping restriction intervals merge into deterministic event
clusters. Highest severity wins; critical importance cannot be averaged away.
Cancelled and postponed versions do not create active restrictions.

## Relevance and missing data

Instrument relevance uses configured generic dimensions. Both configured sides
of a two-dimension fictional instrument are evaluated. This contract is not
permanently FX-specific.

`VALID_NO_RELEVANT_EVENTS` is distinct from `DATA_UNAVAILABLE`, `DATA_STALE`,
and `INCOMPLETE_COVERAGE`. Unknown importance follows a configured conservative
mapping and never silently becomes low importance.

## Phase II unified snapshot

`MarketIntelligenceAssembler` validates instrument, dataset, fingerprint,
timestamp, configuration, recovery epoch, and source-snapshot lineage across:

1. Market data
2. Structure
3. Features
4. Regime
5. Session/time
6. Scheduled-event risk

It does not recalculate their logic. Critical health states have precedence,
and restrictions can only stay equal or become stricter. The immutable output
separates overall health from research-intelligence availability and terminates
its DecisionTrace with `NO_ACTION`.

## Prompt 8 carry-forward

Historical pre-breakout compression proof remains an upstream Prompt 7 feature-
series limitation. It is not duplicated in Prompt 10. Before Phase III relies
on strict breakout qualification, add the smallest compatible Prompt 7 temporal
feature-series extension and consume it in Prompt 8.
